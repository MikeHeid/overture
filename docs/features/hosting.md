# Hosting and upgrades

[← Back to README](../../README.md)

Run the one server, upgrade it, see how the parts fit, and the traps on Windows with WSL2.

## Upgrade the agent server on each onboarded project

Updating the plugin only refreshes the files on disk; the running Python
server does not pick them up until it restarts. For every project that was
onboarded, run the installer with `--start` to copy the fresh kit to
`~/.local/share/overture/kit/` and restart the systemd user units:

    bash ~/overture/plugins/overture/kit/deploy/install.sh \
      --project <path to project> --start

(When using route A, the path is the plugin cache instead; the install
script's path is printed by `onboard.py show` on the project.)

After the restart, verify from the project's machine. The owner's door
never answers `/health`, or any other path, without sign-in, so a bare
`curl` there gets a 403; that 403 is the check `install.sh` itself makes
("want 403"). To ask the server how it is, use the agent's door, a Unix
socket in the console's state directory that only you can open:

    python3 <kit>/agent.py --state <state dir> health
    # → {"agent": "...", "agent_listening": ..., "ok": true, "register": "ok",
    #    "store_seq": N, "version": "<the version you just installed>"}

For the one server, `server.py health` does the same for every project.

The first Claude session in each project after the upgrade prints a short
banner naming the new version and the commands most useful at that moment
(`items-push`, `items-watch`, `scaffold-dashboard`, `sync-dashboard`,
`page-snapshot`, `prs-push`, `inbox`).

## Hosting

One server, `server.py --all`, hosts every project on the machine. Run it
however suits the host (1.32):

    <py> <kit>/server.py daemon start|stop         # detached, with a pid file and a log
    <py> <kit>/server.py service install --start   # a systemd user unit (Linux, WSL)
    <py> <kit>/server.py status                    # which mode, pid, each project's port
    <py> <kit>/server.py health                    # agent door, version skew, linger; clears stale files

`status` and `health` only read; a daemon and a service refuse to run
together, each naming the other. `server.py --all` in the foreground is
unchanged. macOS launchd support is on the roadmap.

`/health` is always answered on the agent's door. A plain HTTP health
port exists only when the server is started with `--health-port PORT`,
which is off by default and which no unit `install.sh` renders passes. That
port listens on 127.0.0.1 only, needs no sign-in, and refuses anything that
came through a proxy or a tunnel or names another Host. It answers
`GET /health` (200 while the process is up, with its version) and
`GET /ready` (200 only while the item register is loaded, 503 otherwise,
with the same body), so a supervisor or a load check can tell "running"
from "ready" (1.23):

    curl -s http://127.0.0.1:PORT/health     # only with --health-port PORT

**Machine role (1.32).** A plugin setting named **Machine role** (`steward`
or `worker`), and the CLI `agent.py role worker|steward|clear`, mark a
machine where no session may be the steward — useful when the steward runs
on a home server and laptops only *work*. On a `worker` the fold refuses,
`watch`/`synced` refuse, and `/overture:as <steward>` is refused by name.
If the plugin setting and the registry disagree, `worker` wins. See
[docs/JOIN.md](../JOIN.md).

## The link-mode unit and the wait for ZeroTier (1.47)

A console with sign-in links installs as its own systemd user unit,
`NAME-console.service` (NAME is the project's name), which `install.sh`
renders from the template `deploy/console-link.service.in` when
`console.env` says `CONSOLE_AUTH=link`: no Cloudflare and no tunnel unit. It carries the
`--listen` and `--origin` that onboarding wrote (`CONSOLE_LISTEN`,
`CONSOLE_ORIGIN`). `onboard.py show` re-validates them, and `install.sh`
passes them through.

With `--listen`, the server binds nothing until its ZeroTier or Tailscale
address is up. An address not on any interface yet is polled every 2
seconds for up to 2 minutes, with one line in the log:

    overture: waiting for ADDR on a ZeroTier or Tailscale interface (up to 2 minutes)

Then the server binds, or exits 1, naming the address, for
`Restart=on-failure` to try again. Such starts are at least 125 seconds
apart, so a slow boot never reaches the unit's start limit (5 starts within
120 seconds). A server that fails at once (a bad flag, or `--listen` given
an `eth0` address) stops retrying at that limit instead of looping forever;
`systemctl --user status NAME-console.service` says why. An address on a
disallowed interface is refused at once, without the wait. Right after
`install.sh --start`, its loopback check may get no answer yet: it says the
server may still be waiting for ZeroTier, and to check the unit's status.

If ZeroTier comes up after the wait, start the unit again
(`systemctl --user restart NAME-console.service`). The one server's unit
works the same way with `server.json`'s `listen`.

## How it fits together

```
 browser ──Access login or sign-in link──▶ 127.0.0.1:PORT (and --listen ADDR:PORT)  server.py
                                                     │ checks the Access JWT, or the device cookie
                                                     ▼
                                              state dir: store + doorbell
                                                     ▲
 Claude session ── SessionStart hook reads the doorbell (registered projects only)
                └─ skills: console-process / console-fork / console-fold / console-ask / console-visual / console-ux ── agent.py
```

- **`server.py`** serves the console inside your published dashboard
  page. Every request without a valid Access token (or, in link mode, a
  signed-in browser's cookie) is refused, loopback included. **It runs no
  project code and no git.** Your work items arrive by `agent.py
  items-push`, git history by `agent.py history-push`, pull requests by
  `agent.py prs-push` (`gh` runs in the steward, never in the server), and
  the page by `agent.py page-snapshot`. The steward runs all four in its
  own process, and each sends data the server checks against a closed
  schema.
- **`agent.py`** is the agent's side. Its commands:

  | Purpose | Commands |
  |---|---|
  | Reading | `inbox`, `todo`, `view`, `answers` (capped at 64 KiB, with a narrower command named when a read is too big), `health` |
  | Asking and answering | `ask`, `reply`, `working`, `synced`, `watch` |
  | Deliberation | `fork-context`, `transcript`, `visual`, `visual-export`, `next-step`, `costs` |
  | Stale answers | `check`, `reanchor`, `propose-anchor`, `advise` |
  | Pushing data | `items-push`, `items-watch`, `history-push`, `prs-push`, `issues-push`, `page-snapshot`, `asset`, `component-source`, `design-inventory` |
  | Owner only | `register`, `steward`, `role`, `access`, `operator-name`, `notify-url`, `invite`, `devices`, `server add`, `server auth`, `server listen`, `server token rotate`, `item-move`, `pr-merge`, `trigger-token`, `portfolio-token` |

  `--as NAME` names the session.
- **`fold.py`** writes locked answers, and what became of them, into
  your project through its adapter, in the steward's process.
- **`plugin/`** holds the Claude Code plugin: the hooks, the skills, and
  the committee agents. Skills include `roar`, `refine`, `drill`,
  `deliberate`, `grill-me`, `console-ux` and the console-* workflow
  skills. **`/overture:add-skill NAME [category]`** (1.5) scaffolds a new
  skill (`agent-review`, `visualizer`, `documentation` or `other`) under
  `.claude/skills/NAME/SKILL.md`, and refuses to overwrite one.
- **`onboard.py`** and **`deploy/`** onboard a project and install the
  services. `onboard.py verify` does an end-to-end reachability check, and
  `onboard.py detect` (1.47) lists the ZeroTier and Tailscale addresses a
  link-mode console could listen on.

## The cost sidecar (`agent.py costs`)

How many tokens a deliberation really spent is recorded beside the store,
never in it (0.8.9). The steward runs

    python3 <kit>/agent.py --state <state dir> costs collect

in its own session. It reads Claude Code's subagent transcripts for this
project only (the transcript folders of the roots registered on this state
directory), and keeps from each line only the message id and its four token
counts, plus each subagent's type and the `ck-fork:<id>` tag that
console-fork puts at the start of every seat's description. Message content
is dropped as each line is read. It writes one line per subagent to
`STATE/costs.jsonl` (mode 0600), keyed by transcript path, so collecting
again replaces lines rather than adding to them. The server never reads
transcripts.

    python3 <kit>/agent.py --state <state dir> costs show --fork RECORD_ID

only reads: it prints that fork's bill, its seats and their fresh, cached
and output tokens and turns, with any untagged subagents of the same sessions listed
apart, never added to the fork's total. `collect` is steward-only. A
symlinked file or folder is skipped, and lines and the file are
size-capped.

## What a project token protects

One console server can host several projects. Each project's agents
reach it with that project's own token. The token is kept in
`~/.config/overture/tokens/NAME` (mode 0600, outside every repository);
`server.json` holds only its hash. `agent.py` picks the project from the
directory it runs in. `agent.py server token rotate NAME` (which you run)
refuses the old token from the next request.

- **What it stops:** cross-talk and mistakes. A wrong `--state`, a skill
  bug, or an agent carrying another project's habits cannot read or
  write another project's console through the kit.
- **What it does not stop:** an agent running as the same OS user that
  sets out to cross over. It can read `tokens/` and the state directories
  directly. Real isolation needs a sandbox or a separate user.
- **An old per-project server is a way around it.** While one still
  listens on `STATE/agent.sock`, that socket answers without a token.
  Stop it before relying on the token.

## Windows + WSL2 (optional)

The server, the tunnel and the systemd units are POSIX; a convenient
layout on a Windows host is to run them in WSL2 while a Claude Code
session lives on either side. A few traps worth knowing:

- **CRLF.** `git config core.autocrlf=true` on Windows gives every file
  in the plugin cache CRLF endings. `install.sh` then fails at once
  (`set: pipefail: invalid option name`), and systemd unit files with a
  `\r` silently misbehave. Install the kit from a copy stripped of CR
  (`sed -i 's/\r$//'` on each `*.sh`, `*.in`, `*.py`, `*.js`, `*.css`,
  `*.html`) or clone with `core.autocrlf=false`.
- **Default branch.** `page-snapshot --from-ref origin/main` is the
  default and fails on a repository whose default is anything else. Pass
  `--from-ref HEAD --unreviewed` while bootstrapping, or point
  `--from-ref` at your actual branch.
- **Page path.** `onboard.py` defaults the page to
  `.overture/page.html`, which `page-snapshot` refuses (leading dot).
  Move the page under `docs/console/page.html` or similar.
- **Items.** The server never runs your adapter. After onboarding, run
  `agent.py --state STATE items-push --adapter PATH` once (and whenever
  the item list changes); until then `ask` on any item but `PROJECT` is
  refused.
- **Reaching the server from Windows.** The agent socket lives in WSL
  and Windows cannot open a WSL2 Unix socket. Options: run the
  agent-side session inside WSL (`wsl -e bash` wrapper), or use the
  one-server HTTP door with a project token on loopback.
- **Linger.** Systemd user units stop when WSL shuts down. Run
  `loginctl enable-linger $USER` in WSL; a Windows process that keeps
  WSL alive still helps when nothing else holds it.
- **Platform guard (1.26+).** `server.py` refuses to start on non-POSIX
  rather than corrupting state under a half-working runtime.
