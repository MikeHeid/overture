#!/usr/bin/env python3
"""Onboard one project onto the owner console: validate its answers, write its
non-secret config, and print the commands the OWNER runs.

    python3 onboard.py write  --project DIR --name acme --team-domain acme.cloudflareaccess.com \
                              --aud <64 hex> --hostname acme-console.example.com [--port 4793] ...
    python3 onboard.py tunnel --project DIR --id <tunnel uuid>
    python3 onboard.py write  --project DIR --name acme --auth link [--listen ADDR] [--origin URL]   (1.47.0)
    python3 onboard.py detect [--json]      this machine's ZeroTier and Tailscale addresses (1.47.0)

1.47.0 (OPEN-DECISIONS.md "Without Cloudflare", L7): `--auth link` onboards a
console that signs browsers in by link (no Access application, no tunnel); its
console.env carries CONSOLE_AUTH=link, CONSOLE_ORIGIN and, with --listen,
CONSOLE_LISTEN, and `verify` checks the door itself instead of Cloudflare.

`write` creates, inside the project:

    .overture/console.env     the server's settings (none of them a secret)
    .overture.json            fold paths, the adapter, the audit seat, the next-step skills
                                 (merged, never clobbered)
    .overture/adapter.py      a starter adapter, only when the project has none
    .overture/page.html       a starter page, only when the project has none

`tunnel` renders ~/.cloudflared/config-<tunnel>.yml once `cloudflared tunnel
create` has given the tunnel its id.

What it never does, on purpose:
- it never opens a Cloudflare credentials file or cert.pem. It checks only that
  the credentials file EXISTS, by path, so the config it writes points at a real
  file;
- it never creates a tunnel, writes DNS, starts a service or registers the
  project. Those make the console reachable, or tell your Claude sessions to
  trust this project's doorbell, so they are commands printed for you to run;
- it never overwrites a file it did not write before, unless --force is passed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent

NAME = re.compile(r"^[a-z][a-z0-9-]{0,30}[a-z0-9]\Z")
TEAM = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com\Z")
AUD = re.compile(r"^[0-9a-f]{64}\Z")
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOST = re.compile(rf"^(?:{LABEL}\.)+[a-z]{{2,63}}\Z")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
REL = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]{0,200}\Z")
MARK = "# written by overture onboard.py"
# The skills the plugin ships for the two next-step forks (resolved as an installed plugin's
# `<plugin>:<name>`, never from the repository: overture/projectcfg.py `resolve_skill`).
DEFAULT_NEXT_STEP = {"refine": "overture:refine", "drill": "overture:drill"}


class OnboardError(ValueError):
    pass


AUTHS = ("cloudflare", "link")
CLOUDFLARE_ONLY = ("team_domain", "aud", "hostname", "tunnel")
# 1.47.0 (L7): the keys of a console.env for sign-in links, in the order written; CONSOLE_LISTEN only when set.
LINK_KEYS = {"name": "CONSOLE_NAME", "auth": "CONSOLE_AUTH", "listen": "CONSOLE_LISTEN", "origin": "CONSOLE_ORIGIN",
             "port": "CONSOLE_PORT", "page": "CONSOLE_PAGE", "adapter": "CONSOLE_ADAPTER"}


def _kit_modules():
    """overture.devices and overture.netif, from this kit (onboard.py runs before any install)."""
    if str(KIT) not in sys.path:
        sys.path.insert(0, str(KIT))
    from overture import devices as DV
    from overture import netif as NI
    return DV, NI


def check(answers: dict) -> dict:
    """Every answer, validated and normalised; the first bad one is refused by name."""
    a = {k: (v.strip() if isinstance(v, str) else v) for k, v in answers.items()}
    auth = a.get("auth") or "cloudflare"
    if auth not in AUTHS:
        raise OnboardError(f"auth: {auth!r} is not valid: expected cloudflare or link")
    a["auth"] = auth
    if auth == "link":
        return _check_link(a)
    for key in ("listen", "origin"):   # 1.47.0: sign-in links only; behind Cloudflare it is https://HOSTNAME
        if a.get(key) is not None:
            raise OnboardError(f"{key}: is for --auth link; behind Cloudflare the console is on 127.0.0.1 and "
                               f"https://HOSTNAME")
    for key in ("name", "team_domain", "hostname", "tunnel", "aud"):
        if isinstance(a.get(key), str):
            a[key] = a[key].lower()
    if not a.get("tunnel") and isinstance(a.get("name"), str):
        a["tunnel"] = f"{a['name']}-console"
    rules = [
        ("name", NAME, "2-32 lowercase letters, digits and hyphens, starting with a letter (e.g. acme)"),
        ("team_domain", TEAM, "your Zero Trust team domain, <team>.cloudflareaccess.com"),
        ("aud", AUD, "the Access application's AUD tag: 64 hex characters"),
        ("hostname", HOST, "a public hostname in a zone on your Cloudflare account, e.g. acme-console.example.com"),
        ("tunnel", NAME, "a tunnel name made like the project name (default <name>-console)"),
    ]
    for key, rx, want in rules:
        if not isinstance(a.get(key), str) or not rx.match(a[key]):
            raise OnboardError(f"{key}: {a.get(key)!r} is not valid: expected {want}")
    if a["hostname"].endswith(".cloudflareaccess.com"):
        raise OnboardError("hostname: that is the team domain; give the console's own hostname")
    return _check_common(a)


def _check_link(a: dict) -> dict:
    """1.47.0 (L7): `--auth link`: no Access values (each refused by name, so none is written and forgotten),
    an optional --listen (netif's contract 1, by name: whether an interface holds it is said, not required),
    and the origin (default http://LISTEN:PORT, else http://127.0.0.1:PORT; L15)."""
    for key in CLOUDFLARE_ONLY:
        if a.get(key) is not None:
            raise OnboardError(f"{key}: is for --auth cloudflare; a console with sign-in links needs no Cloudflare")
    if isinstance(a.get("name"), str):
        a["name"] = a["name"].lower()
    if not isinstance(a.get("name"), str) or not NAME.match(a["name"]):
        raise OnboardError(f"name: {a.get('name')!r} is not valid: expected 2-32 lowercase letters, digits and "
                           f"hyphens, starting with a letter (e.g. acme)")
    DV, NI = _kit_modules()
    listen = a.get("listen") or None
    if listen is not None:
        why = NI.NOT_LINUX if not sys.platform.startswith("linux") else NI.static_problem(listen)
        if why:
            raise OnboardError(f"listen: {why}")
    a["listen"] = listen
    a = _check_common(a)
    origin = DV.clean_origin(a.get("origin") or f"http://{listen or '127.0.0.1'}:{a['port']}")
    why = DV.origin_problem(origin, listen) or (listen and DV.listen_origin_problem(origin, listen))
    if why:
        raise OnboardError(f"origin: {why}")
    a["origin"] = origin
    return a


def _check_common(a: dict) -> dict:
    # The master agent (steward): only checked and printed into the `register` step below. It is never
    # written into the project's files: a repository must not be able to name the steward (0.8.3).
    if a.get("steward"):
        sys.path.insert(0, str(KIT))
        from overture import names as N
        why = N.problem(a["steward"])
        if why:
            raise OnboardError(f"steward: {why}")
    port = a.get("port", 4793)
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise OnboardError(f"port: {port!r} is not a number") from None
    if not 1024 <= port <= 65535:
        raise OnboardError(f"port: {port} is outside 1024-65535")
    a["port"] = port
    for key, default in (("page", ".overture/page.html"), ("adapter", ".overture/adapter.py")):
        v = a.get(key) or default
        if not isinstance(v, str) or not REL.match(v) or ".." in Path(v).parts:
            raise OnboardError(f"{key}: {v!r} must be a plain relative path inside the project")
        a[key] = v
    return a


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _target(base: Path, rel: str) -> Path:
    """`base/rel`, refused when it or any directory on the way is a symbolic link, or it lands outside `base`.

    A cloned repository can ship a DANGLING link at a path onboarding writes
    (`.overture/adapter.py -> ~/.bashrc`): `exists()` follows it, says no,
    and a plain write would create the link's target wherever it points. So
    every component is checked with lstat, never followed, and `--force`
    does not override this.
    """
    p = base
    for part in Path(rel).parts:
        p = p / part
        if p.is_symlink():
            raise OnboardError(f"{p} is a symbolic link; onboarding writes only real files inside {base}")
    if not p.resolve().is_relative_to(base.resolve()):
        raise OnboardError(f"{p} resolves outside {base}")
    return p


def _write(path: Path, text: str, force: bool) -> str:
    if path.is_symlink():  # the last line of defence; _target refuses these first
        raise OnboardError(f"{path} is a symbolic link; refusing to write through it")
    if path.exists():
        old = path.read_text(encoding="utf-8", errors="replace")
        if old == text:
            return f"unchanged {path}"
        if MARK not in old and not force:
            raise OnboardError(f"{path} exists and was not written by onboard.py; pass --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return f"wrote     {path}"


def env_text(a: dict) -> str:
    if a.get("auth") == "link":   # 1.47.0 (L7); a Cloudflare console's file is byte for byte 1.46's
        return "\n".join([
            MARK,
            "# The owner console's settings for this project, signing browsers in by link (no Cloudflare). None",
            "# of these is a secret: a sign-in link is made in your terminal (agent.py invite) and never kept here.",
            *(f"{v}={a[k]}" for k, v in LINK_KEYS.items() if a.get(k) is not None),
            "",
        ])
    return "\n".join([
        MARK,
        "# The owner console's settings for this project. None of these is a secret: the AUD",
        "# tag and team domain are what the server CHECKS a token against; a token cannot be",
        "# made from them. The tunnel's credentials file is never named or read here.",
        f"CONSOLE_NAME={a['name']}",
        f"CONSOLE_TEAM_DOMAIN={a['team_domain']}",
        f"CONSOLE_AUD={a['aud']}",
        f"CONSOLE_HOSTNAME={a['hostname']}",
        f"CONSOLE_PORT={a['port']}",
        f"CONSOLE_TUNNEL={a['tunnel']}",
        f"CONSOLE_PAGE={a['page']}",
        f"CONSOLE_ADAPTER={a['adapter']}",
        "",
    ])


def config_json(project: Path, a: dict) -> str:
    path = project / ".overture.json"
    cfg = {}
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise OnboardError(f"{path} is not valid JSON ({e}); fix or remove it first") from None
        if not isinstance(cfg, dict):
            raise OnboardError(f"{path} must hold a JSON object")
    fold = cfg.setdefault("fold", {})
    if not isinstance(fold, dict):
        raise OnboardError(f"{path}: \"fold\" must be an object")
    fold.setdefault("locked", ".overture/locked")
    fold.setdefault("ledger", ".overture/folded.txt")
    fold["adapter"] = a["adapter"]
    # Refine and drill run a skill the plugin itself ships, so a fresh install has them. A kind
    # already named is kept as it is: a project that installed its own skill keeps using it.
    steps = cfg.setdefault("next_step", {})
    if not isinstance(steps, dict):
        raise OnboardError(f"{path}: \"next_step\" must be an object")
    for kind, skill in DEFAULT_NEXT_STEP.items():
        steps.setdefault(kind, skill)
    if a.get("audit_seat"):
        cfg["audit"] = {"seat": a["audit_seat"], "brief": a.get("audit_brief") or ""}
    return json.dumps(cfg, indent=2) + "\n"


def state_dir(name: str) -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return base / "overture" / name


def write(project: Path, answers: dict, force: bool = False, check_port: bool = True) -> list[str]:
    project = project.resolve()
    if not project.is_dir():
        raise OnboardError(f"project: {project} is not a directory")
    a = check(answers)
    if check_port and not port_free(a["port"]):
        raise OnboardError(f"port: {a['port']} is already in use on 127.0.0.1; pick another with --port")
    notes = listen_notes(a["listen"]) if a.get("listen") else []   # refuses a non-overlay interface first
    # Every target is checked BEFORE anything is written, so a refusal leaves the project untouched.
    env, cfg = _target(project, ".overture/console.env"), _target(project, ".overture.json")
    starters = [(_target(project, a[k]), t) for k, t in (("adapter", "adapter_template.py"), ("page", "demo/index.html"))]
    new_cfg = config_json(project, a)  # parse the old config BEFORE writing anything
    out = [_write(env, env_text(a), force)]
    if not cfg.exists() or cfg.read_text(encoding="utf-8") != new_cfg:
        cfg.write_text(new_cfg, encoding="utf-8")  # a merge: every key already there is kept
        out.append(f"wrote     {cfg}")
    for target, template in starters:
        if not target.exists():
            out.append(_write(target, (KIT / template).read_text(encoding="utf-8"), force))
        else:
            # The server imports the adapter and runs it as Python, and serves the page with the
            # console in it. One already here may have come with a checkout, and no marker in it
            # can prove otherwise (a hostile file would carry the marker too): always say so.
            out.append(f"REVIEW    {target}: already here, so it was left as it is. The server runs it: "
                       "know what it holds before you run install.sh.")
    # 1.6.1: ensure `.overture/console.env` is gitignored. The file holds the AUD tag + team domain —
    # not secret by the kit's account, but shaped like credentials and Claude Code's safety check
    # treats them that way, so a commit mid-onboarding gets blocked. Adding one line to .gitignore
    # resolves that cleanly for the owner.
    gi_line = ".overture/console.env"
    out.append(_ensure_gitignore(project, gi_line))
    return out + notes


def listen_notes(listen: str) -> list[str]:
    """1.47.0: what a --listen address looks like on this machine now. On a ZeroTier or Tailscale interface:
    the L17 overlap warnings, if any. On no interface yet: a note (the server waits for it, L16). On any
    other interface: refused (OnboardError), as the server would refuse it at once."""
    _DV, NI = _kit_modules()
    try:
        got = NI.check(listen)
    except NI.ListenError as e:
        raise OnboardError(f"listen: {e}") from None
    if got is None:
        return [f"NOTE      no ZeroTier or Tailscale interface holds {listen} now; the server waits up to 2 "
                f"minutes for it when it starts (is ZeroTier joined? `onboard.py detect` lists what is here)"]
    return NI.overlap_warnings(listen, got)


def _ensure_gitignore(project: Path, line: str) -> str:
    """Append `line` to the project's root .gitignore if it is not already there. Idempotent.

    Creates .gitignore when absent. Reports what happened as one output line. Any read/write OSError
    is swallowed into a REVIEW line, so a missing or unwritable .gitignore does not fail onboarding.
    """
    path = project / ".gitignore"
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as e:
        return f"REVIEW    {path}: could not read ({e}); add `{line}` yourself if you track {line} content"
    needle = line.strip()
    for existing in current.splitlines():
        if existing.strip() == needle:
            return f"kept      {path}: already lists {line}"
    sep = "" if (current == "" or current.endswith("\n")) else "\n"
    try:
        path.write_text(current + sep + line + "\n", encoding="utf-8")
    except OSError as e:
        return f"REVIEW    {path}: could not write ({e}); add `{line}` yourself"
    return f"wrote     {path}: appended `{line}`"


def reach(a: dict) -> tuple[str, str]:
    """1.47.0 (L7): (how the console is reached, its owner door's address) for a link-mode answer set:
    "zerotier" / "tailscale" with --listen (by the address: 100.64/10 is Tailscale's), "tailscale-serve" for an
    https origin (`tailscale serve` in front of 127.0.0.1), else "local"."""
    _DV, NI = _kit_modules()
    listen = a.get("listen")
    if a["origin"].startswith("https://"):
        # 1.47 (S1): never with --listen (check refuses an https origin there), so `tailscale serve` targets loopback.
        return "tailscale-serve", "127.0.0.1"
    if listen:
        import ipaddress
        return ("tailscale" if ipaddress.IPv4Address(listen) in NI.TAILSCALE_NET else "zerotier"), listen
    return "local", "127.0.0.1"


def _link_next_steps(project: Path, a: dict) -> str:
    """1.47.0 (L7): the owner's commands for a console with sign-in links: no Access application, no tunnel."""
    how, host = reach(a)
    state = state_dir(a["name"])
    steward = a.get("steward")
    steward_flag = f" --steward {steward}" if steward else ""
    steward_note = (f"    Then, in the Claude session that should process your answers (the master agent), type:\n"
                    f"      /overture:as {steward}\n") if steward else ""
    open_it = {
        "zerotier": f"open {a['origin']} on any device joined to this ZeroTier network. Plain http is right\n"
                    f"    here: ZeroTier encrypts every packet end to end, and only its members reach {host}",
        "tailscale": f"open {a['origin']} on any device on your tailnet (Tailscale encrypts it end to end)",
        "tailscale-serve": f"put it on your tailnet over HTTPS, once:\n"
                           f"      tailscale serve --bg http://{host}:{a['port']}\n"
                           f"    then open {a['origin']}",
        "local": f"open {a['origin']} on this machine (nothing else can reach it)",
    }[how]
    return f"""
Next, run these yourself, in order. Each one is yours to approve. This console signs browsers in by link:
no Cloudflare, no tunnel.

 1. Install the server (a venv, the kit, a systemd user unit) and start it:
      bash "{KIT}/deploy/install.sh" --project "{project}" --start
 2. Let your Claude sessions trust this project's console. It is a trust decision, so a
    session never runs it for you:
      python3 ~/.local/share/overture/kit/agent.py --state "{state}" register --project "{project}"{steward_flag}
{steward_note} 3. Reach it: {open_it}.
 4. Make your sign-in link, in your own terminal (a Claude session is refused):
      python3 ~/.local/share/overture/kit/agent.py --state "{state}" invite YOU@EXAMPLE.COM --origin {a['origin']}
    It prints a link that works once, within 24 hours. Open it in the browser you will use and
    press "Sign this browser in"; that browser stays signed in until you revoke it (People).
    Sign in once per address you use (a browser keeps a sign-in per address).
 5. Check it:
      python3 "{KIT}/onboard.py" verify --project "{project}"
 6. Make yourself the administrator. Until you do, everyone you invite can do everything. In the
    console open People (under More) and press "Make me the administrator": it takes the login
    you signed in as. Or, in your own terminal:
      python3 ~/.local/share/overture/kit/agent.py --state "{state}" access YOU@EXAMPLE.COM owner
    Then invite each other person (step 4 with their email) and give them a role there.
 7. Push the project's items so an agent can `ask` on anything but the starter PROJECT item.
    The server never runs your adapter (CONSOLE-kit/Q24); run this now and whenever the item
    list or the adapter changes:
      python3 ~/.local/share/overture/kit/agent.py --state "{state}" items-push --adapter "{a['adapter']}"
 8. (Optional, for the dashboard page) Send the page from a merged commit, then press
    "Use this page" in the console. Reads the default branch from origin/HEAD (0.9.1):
      python3 ~/.local/share/overture/kit/agent.py --state "{state}" page-snapshot --path "{a['page']}"
"""


WINDOWS_NEXT = """
Next: this is native Windows, where the console cannot run, and the commands onboarding
prints would name Windows paths that a WSL shell cannot use. Run onboarding again inside
WSL: start the Claude Code CLI there and type /overture:console-onboard in the project.
See docs/features/hosting.md#windows.
"""


def next_steps(project: Path, a: dict) -> str:
    if os.name != "posix":   # 1.53.2: say where to go once, instead of commands with C:\ paths
        return WINDOWS_NEXT
    if a.get("auth") == "link":   # 1.47.0 (L7); the Cloudflare steps below are 1.46's, unchanged
        return _link_next_steps(project.resolve(), a)
    project = project.resolve()
    cfg = Path.home() / ".cloudflared" / f"config-{a['tunnel']}.yml"
    cert = Path.home() / ".cloudflared" / "cert.pem"
    login = "" if cert.exists() else "      cloudflared tunnel login        # once per machine; writes cert.pem\n"
    steward = a.get("steward")
    steward_flag = f" --steward {steward}" if steward else ""
    steward_note = (f"    Then, in the Claude session that should process your answers (the master agent), type:\n"
                    f"      /overture:as {steward}\n") if steward else ""
    return f"""
Next, run these yourself, in order. Each one is yours to approve:

 1. Install the server (a venv, the kit, systemd user units; starts only the loopback server):
      bash "{KIT}/deploy/install.sh" --project "{project}" --start
 2. Let your Claude sessions trust this project's console. It is a trust decision, so a
    session never runs it for you:
      python3 ~/.local/share/overture/kit/agent.py --state "{state_dir(a['name'])}" register --project "{project}"{steward_flag}
{steward_note} 3. Create the Access application in Cloudflare Zero Trust for https://{a['hostname']}
    (docs/CLOUDFLARE.md, "Access application"). Its AUD tag is the one you gave.
 4. Create the tunnel, and route DNS WITH --config, or the record can land on another tunnel:
{login}      cloudflared tunnel create {a['tunnel']}
      python3 "{KIT}/onboard.py" tunnel --project "{project}" --id <the tunnel id it printed>
      cloudflared tunnel --config "{cfg}" route dns --overwrite-dns <tunnel id> {a['hostname']}
      systemctl --user enable --now {a['name']}-console-tunnel
 5. Check it:
      curl -s -o /dev/null -w '%{{http_code}}\\n' http://127.0.0.1:{a['port']}/api/view   # 403: no token, refused
      then open https://{a['hostname']}: an Access login, then the page
 6. Make yourself the administrator. Until you do, everyone your Access policy lets in can do
    everything. In the console open People (under More) and press "Make me the administrator":
    it takes the login you are signed in with, so you type no email and no session sees one.
    Or, in your own terminal (a Claude session is refused), with your Access login:
      python3 ~/.local/share/overture/kit/agent.py --state "{state_dir(a['name'])}" access YOU@EXAMPLE.COM owner
    Then add each other person there, as a member of their areas or a viewer.
 7. Push the project's items so an agent can `ask` on anything but the starter PROJECT item.
    The server never runs your adapter (CONSOLE-kit/Q24); run this now and whenever the item
    list or the adapter changes:
      python3 ~/.local/share/overture/kit/agent.py --state "{state_dir(a['name'])}" items-push --adapter "{a['adapter']}"
 8. (Optional, for the dashboard page) Send the page from a merged commit, then press
    "Use this page" in the console. Reads the default branch from origin/HEAD (0.9.1):
      python3 ~/.local/share/overture/kit/agent.py --state "{state_dir(a['name'])}" page-snapshot --path "{a['page']}"
"""


def read_env(path: Path) -> dict:
    if not path.exists():
        raise OnboardError(f"{path} is missing: run `onboard.py write` first")
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    keys = {"name": "CONSOLE_NAME", "team_domain": "CONSOLE_TEAM_DOMAIN", "aud": "CONSOLE_AUD",
            "hostname": "CONSOLE_HOSTNAME", "port": "CONSOLE_PORT", "tunnel": "CONSOLE_TUNNEL",
            "page": "CONSOLE_PAGE", "adapter": "CONSOLE_ADAPTER"}
    if env.get("CONSOLE_AUTH", "cloudflare") != "cloudflare":
        # 1.47.0 (L7): a link-mode file. check() refuses any other CONSOLE_AUTH by name, and the Access keys
        # if any were left in; only its own keys come back (install.sh renders the link unit from them).
        a = check({k: env.get(v) for k, v in {**LINK_KEYS, **{k: keys[k] for k in CLOUDFLARE_ONLY}}.items()})
        return {v: str(a[k]) for k, v in LINK_KEYS.items() if a.get(k) is not None}
    a = check({k: env.get(v) for k, v in keys.items()})
    # Only what was validated leaves this function, in its normalised form: an
    # unknown key in the file is ignored, never passed on to a unit file.
    return {v: str(a[k]) for k, v in keys.items()}


def verify(project: Path) -> list[tuple[str, str, str]]:
    """1.24.0: end-to-end reachability check for a configured project.

    Returns a list of (step, status, detail) tuples where status is "ok", "warn" or
    "fail". The caller prints and decides the exit code. The checks are:

    1. The project has a `.overture/console.env` file (`onboard.py write` already ran).
    2. Required binaries are on PATH: cloudflared, curl.
    3. The user service exists (systemctl --user show overture.service) and is active.
    4. The agent socket (`$XDG_RUNTIME_DIR/overture.sock`) exists and answers /health.
    5. The owner HTTPS endpoint returns an Access challenge (302) — i.e. the tunnel is
       up and Access is enforcing. A 200 would mean the gate is open to the public.

    Nothing reads or writes project state. Nothing holds a secret. On failure every
    step says *what to do next* in one line.
    """
    import shutil
    import subprocess
    results: list[tuple[str, str, str]] = []
    env_path = project.resolve() / ".overture/console.env"
    if not env_path.exists():
        results.append(("config", "fail",
                        f"no .overture/console.env — run `python3 onboard.py write ...` first"))
        return results
    try:
        env = read_env(env_path)
    except OnboardError as e:
        results.append(("config", "fail", f"{e}"))
        return results
    results.append(("config", "ok", f"{env_path} parses as {env['CONSOLE_NAME']} on port {env['CONSOLE_PORT']}"))
    if env.get("CONSOLE_AUTH") == "link":   # 1.47.0 (L7): no Cloudflare to check; the door itself is checked
        return results + _verify_link(env)

    for binary in ("cloudflared", "curl"):
        if shutil.which(binary) is None:
            results.append((f"bin:{binary}", "warn", f"{binary} not on PATH — some checks skipped"))
        else:
            results.append((f"bin:{binary}", "ok", shutil.which(binary) or ""))

    service = "overture.service"
    try:
        proc = subprocess.run(["systemctl", "--user", "is-active", service],
                              capture_output=True, text=True, timeout=5)
        state = (proc.stdout or proc.stderr or "").strip() or "unknown"
        if state == "active":
            results.append(("service", "ok", f"{service} is active"))
        else:
            results.append(("service", "fail",
                            f"{service} is {state} — run `systemctl --user start {service}`"))
    except (OSError, subprocess.TimeoutExpired) as e:
        results.append(("service", "warn", f"could not query systemctl: {e}"))

    uid = getattr(os, "getuid", None)   # 1.53.2: native Windows has none, and no console socket
    sock = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid()}") / "overture.sock" if uid else None
    if sock is None:
        results.append(("agent socket", "fail",
                        "native Windows has no console socket: run verify inside WSL (docs/features/hosting.md#windows)"))
    elif not sock.exists():
        results.append(("agent socket", "fail",
                        f"{sock} missing — the service is not running or has not written its socket"))
    else:
        results.append(("agent socket", "ok", str(sock)))

    hostname = env["CONSOLE_HOSTNAME"]
    curl = shutil.which("curl")
    if curl is None:
        results.append(("tunnel", "warn",
                        f"curl missing; test manually: open https://{hostname} in a browser (expect Access challenge)"))
    else:
        try:
            proc = subprocess.run([curl, "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                                   "--max-time", "8", f"https://{hostname}/"],
                                  capture_output=True, text=True, timeout=10)
            code = (proc.stdout or "").strip() or "000"
            if code in ("302", "401", "403"):
                results.append(("tunnel", "ok",
                                f"https://{hostname} returns HTTP {code} (Access is enforcing)"))
            elif code == "200":
                results.append(("tunnel", "warn",
                                f"https://{hostname} returned 200 — Access may not be gating this hostname"))
            elif code == "000":
                results.append(("tunnel", "fail",
                                f"https://{hostname} did not answer: {(proc.stderr or '').strip() or 'no route'}"))
            else:
                results.append(("tunnel", "warn",
                                f"https://{hostname} returned HTTP {code} — unexpected but not clearly broken"))
        except (OSError, subprocess.TimeoutExpired) as e:
            results.append(("tunnel", "warn", f"curl failed: {e}"))
    return results


BOGUS_TOKEN = "ovi_" + "A" * 43   # the shape of an invite, made by nobody: GET /signin answers 410 for it


def door_answer(host: str, port: int, path: str, timeout: float = 5.0) -> int | str:
    """The HTTP status the owner door at host:port gives a bare GET of `path`, or why nothing answered. Its
    Host header names host:port, as a browser's would (the --listen door checks it)."""
    import http.client
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path)
        r = conn.getresponse()
        r.read(1 << 16)
        return r.status
    except (OSError, http.client.HTTPException) as e:
        return f"{type(e).__name__}: {e}"
    finally:
        conn.close()


def _verify_link(env: dict) -> list[tuple[str, str, str]]:
    """1.47.0 (L7): `verify` for a console with sign-in links. Cloudflare and the tunnel are "not used". The
    door must answer on each address it is bound to (127.0.0.1, and CONSOLE_LISTEN when set) with the gate's
    403, and GET /signin with a token nobody made must be 410 there: link mode is on, and nothing was spent
    to learn it."""
    port = int(env["CONSOLE_PORT"])
    out = [("cloudflare", "skip", "not used: this console signs browsers in by link"),
           ("tunnel", "skip", "not used: no Cloudflare tunnel in link mode")]
    for host in ("127.0.0.1", *([env["CONSOLE_LISTEN"]] if env.get("CONSOLE_LISTEN") else [])):
        step = "door" if host == "127.0.0.1" else f"door {host}"
        got = door_answer(host, port, "/api/view")
        if got == 403:
            out.append((step, "ok", f"http://{host}:{port} answers, and refuses a request with no sign-in (403)"))
        elif isinstance(got, int):
            out.append((step, "fail", f"http://{host}:{port}/api/view answered {got}, not 403: is this the console?"))
            continue
        else:
            out.append((step, "fail", f"nothing answers on http://{host}:{port} ({got}); start it: "
                                      f"systemctl --user start {env['CONSOLE_NAME']}-console"
                                      + ("" if host == "127.0.0.1" else " (is ZeroTier/Tailscale up?)")))
            continue
        got = door_answer(host, port, f"/signin?t={BOGUS_TOKEN}")
        if got == 410:
            out.append((f"sign-in links{'' if host == '127.0.0.1' else ' ' + host}", "ok",
                        "on: a link nobody made is refused as used or expired (410)"))
        else:
            out.append((f"sign-in links{'' if host == '127.0.0.1' else ' ' + host}", "fail",
                        f"GET /signin answered {got}, not 410: the server is not running with --auth link "
                        f"(re-run install.sh --start)"))
    return out


def detect() -> dict:
    """1.47.0 (L7): the ZeroTier and Tailscale addresses netif finds here, and each one's L17 overlap
    warnings: what `onboard.py detect` prints and the console-onboard skill recommends from."""
    _DV, NI = _kit_modules()
    found = NI.overlays()
    warnings = [w for _k, n, addr, p, u in found for w in NI.overlap_warnings(addr, (n, p, u))]
    return {"overlays": [{"kind": k, "name": n, "address": a, "prefix": p, "up": u} for k, n, a, p, u in found],
            "warnings": warnings, "linux": sys.platform.startswith("linux")}


def tunnel(project: Path, tunnel_id: str, force: bool = False) -> str:
    env = read_env(project.resolve() / ".overture/console.env")
    if env.get("CONSOLE_AUTH") == "link":   # 1.47.0
        raise OnboardError("tunnel: this console signs browsers in by link (CONSOLE_AUTH=link): it has no tunnel")
    tid = tunnel_id.strip().lower()
    if not UUID.match(tid):
        raise OnboardError(f"id: {tunnel_id!r} is not a tunnel id (a UUID, as `cloudflared tunnel create` prints)")
    creds = Path.home() / ".cloudflared" / f"{tid}.json"
    if not creds.exists():  # existence only: the file is a secret and is never opened
        raise OnboardError(f"no credentials file at {creds}: run `cloudflared tunnel create` on THIS machine first")
    text = (KIT / "deploy/cloudflared.yml.in").read_text(encoding="utf-8")
    for key, value in {"@TUNNEL_ID@": tid, "@CREDENTIALS@": str(creds), "@HOSTNAME@": env["CONSOLE_HOSTNAME"],
                       "@PORT@": env["CONSOLE_PORT"], "@NAME@": env["CONSOLE_NAME"]}.items():
        text = text.replace(key, value)
    return _write(_target(Path.home() / ".cloudflared", f"config-{env['CONSOLE_TUNNEL']}.yml"), MARK + "\n" + text, force)


def prereqs(as_json: bool) -> int:
    """1.53.2: print every prerequisite, route tools included; 1 when a required one is missing."""
    if str(KIT) not in sys.path:
        sys.path.insert(0, str(KIT))
    from overture import prereqs as PQ   # import-safe on native Windows, unlike the rest of the kit
    items = PQ.scan(routes=True)
    if as_json:
        print(json.dumps(items))
    else:
        for it in items:
            print("\n".join(PQ.item_lines(it)) if not it["ok"] else f"  ok: {it['name']}")
    return 1 if any(it["required"] and not it["ok"] for it in items) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Onboard a project onto the owner console.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="validate the answers and write the project's config")
    w.add_argument("--project", type=Path, default=Path.cwd())
    w.add_argument("--name", required=True)
    # 1.47.0 (L7): the three Access values are required with --auth cloudflare (the default; checked below, in
    # argparse's own words) and refused with --auth link, which takes --listen and --origin instead.
    w.add_argument("--auth", choices=AUTHS, default=None,
                   help="cloudflare (Access, the default) or link (sign-in links: no Cloudflare)")
    w.add_argument("--team-domain")
    w.add_argument("--aud")
    w.add_argument("--hostname")
    w.add_argument("--listen", help="--auth link: the ZeroTier or Tailscale address the console listens on "
                                    "beside 127.0.0.1 (`onboard.py detect` lists them)")
    w.add_argument("--origin", help="--auth link: the console's address as the browser sees it (default "
                                    "http://LISTEN:PORT, else http://127.0.0.1:PORT; https://NAME behind "
                                    "`tailscale serve`)")
    w.add_argument("--tunnel")
    w.add_argument("--port", type=int, default=4793)
    w.add_argument("--page")
    w.add_argument("--adapter")
    w.add_argument("--audit-seat")
    w.add_argument("--audit-brief")
    w.add_argument("--steward", help="the master agent's name: printed into the register step, never written "
                                     "into the project (default: the plugin's `steward` setting)")
    w.add_argument("--force", action="store_true")
    w.add_argument("--no-port-check", action="store_true", help="skip the free-port check (re-running on a live port)")
    s = sub.add_parser("show", help="print the project's settings, re-validated (install.sh reads this)")
    s.add_argument("--project", type=Path, default=Path.cwd())
    t = sub.add_parser("tunnel", help="render the cloudflared config once the tunnel exists")
    t.add_argument("--project", type=Path, default=Path.cwd())
    t.add_argument("--id", required=True)
    t.add_argument("--force", action="store_true")
    v = sub.add_parser("verify", help="check that this project's Overture is reachable end-to-end")
    v.add_argument("--project", type=Path, default=Path.cwd())
    d = sub.add_parser("detect", help="list this machine's ZeroTier and Tailscale addresses (1.47), and any "
                                      "network overlapping one")
    d.add_argument("--json", action="store_true")
    q = sub.add_parser("prereqs", help="what this machine still needs, with the fix for each (1.53.2); "
                                       "exit 1 when a required one is missing. Works on native Windows too")
    q.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "write" and (a.auth or "cloudflare") == "cloudflare":
        missing = [f for f, v in (("--team-domain", a.team_domain), ("--aud", a.aud), ("--hostname", a.hostname))
                   if v is None]
        if missing:
            w.error(f"the following arguments are required: {', '.join(missing)}")
    try:
        if a.cmd == "prereqs":
            return prereqs(a.json)
        if a.cmd == "detect":
            got = detect()
            if a.json:
                print(json.dumps(got))
                return 0
            for o in got["overlays"]:
                print(f"{o['kind']} {o['name']} {o['address']}/{o['prefix']}" + ("" if o["up"] else " (down)"))
            if not got["overlays"]:
                print("no ZeroTier or Tailscale interface here" + ("" if got["linux"] else
                      " (--listen comes with 1.48 on this system)"), file=sys.stderr)
            for line in got["warnings"]:
                print(line)
            return 0
        if a.cmd == "write":
            answers = {k: v for k, v in vars(a).items()
                       if k not in ("cmd", "project", "force", "no_port_check", "json") and v is not None}
            for line in write(a.project, answers, a.force, not a.no_port_check):
                print(line)
            print(next_steps(a.project, check(answers)))
        elif a.cmd == "show":
            for k, v in sorted(read_env(a.project.resolve() / ".overture/console.env").items()):
                print(f"{k}={v}")
        elif a.cmd == "verify":
            results = verify(a.project)
            glyph = {"ok": "✓", "warn": "!", "fail": "✗", "skip": "-"}   # 1.47.0: "skip", a check not used
            width = max((len(step) for step, _, _ in results), default=0)
            for step, status, detail in results:
                print(f"  {glyph[status]} {step.ljust(width)}  {detail}")
            if any(status == "fail" for _, status, _ in results):
                print("\nOverture is NOT reachable end-to-end. Fix the ✗ steps above.", file=sys.stderr)
                return 1
            if any(status == "warn" for _, status, _ in results):
                print("\nOverture looks reachable but some checks could not run (see ! above).")
            else:
                env = read_env(a.project.resolve() / ".overture/console.env")
                print(f"\nOverture is reachable at {env.get('CONSOLE_ORIGIN') or 'https://' + env['CONSOLE_HOSTNAME']}")
        else:
            print(tunnel(a.project, a.id, a.force))
    except OnboardError as e:
        print(f"onboard: {e}", file=sys.stderr)
        return 2
    except OSError as e:  # a read-only mount, a full disk, a permission: named, never a traceback
        print(f"onboard: {e.filename or ''}: {e.strerror or e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
