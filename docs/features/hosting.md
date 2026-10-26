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
    <py> <kit>/server.py service install --start   # systemd (Linux, WSL) or launchd (macOS, 1.51)
    <py> <kit>/server.py status                    # which mode, pid, each project's port
    <py> <kit>/server.py health                    # agent door, version skew, linger; clears stale files

`status` and `health` only read; a daemon and a service refuse to run
together, each naming the other. `server.py --all` in the foreground is
unchanged.

### macOS: launchd (1.51)

On a Mac, the same `server.py service install [--start]` writes a launchd
LaunchAgent, `~/Library/LaunchAgents/overture.console.plist` (label
`overture.console`), and with `--start` loads and starts it in your login
session (`launchctl enable`, then `launchctl bootstrap gui/<uid>` to load
it); installing again boots the old job out first. Without `--start` it
only writes the plist, which loads at your next login. Over SSH, or with
nobody logged in at the Mac, `--start` cannot load it and says to log in
at the Mac. `service uninstall` boots the job out and removes the plist
(and still boots out a job whose plist was deleted by hand).

- The plist runs `server.py --all --server-file <server.json>` as an argv
  list, so a space in a path is fine; a path that is not absolute or holds
  a control character is refused by name.
- It starts at login and again after a crash (`KeepAlive` on a failed
  exit). launchd has no start limit: a server that keeps failing is tried
  again every 10 seconds, and `health` shows the service as `failed`.
- Output goes to the daemon's log, `~/.local/state/overture/server.log`.
- A LaunchAgent runs while you are logged in to the Mac. It survives
  sleep and closing every terminal; there is no linger to turn on.
- `status`, `health` and the one-server gate read `launchctl print`; every
  hint names the Mac's command (`launchctl kickstart -k
  gui/<uid>/overture.console` to restart, `launchctl bootout ...` to stop and unload).
- The per-project units of `deploy/install.sh` stay systemd: on a Mac it
  refuses by name and points here. For a Cloudflare tunnel on a Mac, use
  `cloudflared service install`, Cloudflare's own launchd installer.

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
  directly. To stop that, sandbox the sessions:
  [Keep agents out of STATE](#isolation).
- **An old per-project server is a way around it.** While one still
  listens on `STATE/agent.sock`, that socket answers without a token.
  Stop it before relying on the token.

<a id="isolation"></a>
## Keep agents out of STATE (1.60)

An agent runs as your OS user, so it can read any file you can. That
includes every console's store, the GitHub trigger secrets, the webhook URL
and the roles. Claude Code's
[sandbox](https://code.claude.com/docs/en/sandboxing) narrows what a
session's commands can read. `agent.py isolation` writes the rules for your
consoles and then checks that they hold (OPEN-DECISIONS I1–I7).

**What a sandboxed session still reaches**, in each registered console's
STATE:

- `agent.sock`, the agent's door;
- `inbox.jsonl`, `sessions.jsonl` and `lessons.jsonl`, to read. The
  doorbell, the session names and the withdrawn rulings hold no secret;
- `steward/`, to read and write. It holds the steward's cursor and
  heartbeat, the watch's two throttles and the cost sidecar. It is the only
  place in STATE a session may write.

Everything else in STATE is hidden. A denied file reads as "not there".

**Sockets.** Some sockets run a command for whoever connects:
Docker's, Claude Code's and Codex's own daemons, X11, dbus, tmux and
process managers. A session that reached one would be outside the sandbox.

- **On macOS** the rules allow each console's `agent.sock` by path, and no
  other socket.
- **On Linux** the sandbox has no per-path socket list. Reaching
  `agent.sock` needs the switch that opens every socket not denied by path.
  So `isolation settings` denies each socket the machine has when you run
  it, the folders daemons keep theirs in, and the names some programs
  make afresh for each process (a .NET diagnostics port, VS Code's IPC).
  The sandbox's own proxy sockets are left alone. That is best-effort:
  software you install later can add a socket the rules don't name.
  `isolation check` finds it, because it tries every socket it can see.
  Re-run both after installing software that runs a daemon. A separate OS
  user for the console, planned for later, is the real fix.

The rules also deny your runtime folder (`/run/user/UID`) and your
ssh-agent.

**Set it up.** You do this once per machine, again after you register a
new console, and on Linux again after installing software that runs a
daemon.

1. Install the sandbox's tools. On Linux, install `bubblewrap` and
   `socat`, for example `sudo apt install bubblewrap socat`. macOS needs
   nothing extra.
2. In your own terminal, outside any session, run:

   ```sh
   <py> <kit>/agent.py isolation settings > isolation.json
   ```

   This also moves each console's old steward files (`agent-cursor.json`,
   `watch.json`, the throttles, `costs.jsonl`) into `steward/`. It refuses
   to run inside a sandbox, which would block the move.
3. Install the file as managed settings. A session or a project cannot
   loosen managed settings, and an agent cannot edit them.

   ```sh
   sudo install -D -m 0644 isolation.json /etc/claude-code/managed-settings.json
   ```

   On macOS the path is
   `/Library/Application Support/ClaudeCode/managed-settings.json`. If the
   file already exists, merge the two `sandbox` and `permissions` blocks
   instead of replacing it. Do not add an `Edit` rule for a whole STATE
   folder. Claude Code turns it into a write denial that overrides
   `allowWrite`, so sessions could no longer write in `steward/`.
4. Start a new session. Ask it to run `agent.py isolation check`. It
   tries every door from inside the session, including every socket it can
   find, and ends with `isolation holds`, or it lists each door that is
   open. It exits 1 if any door is open. It also says if the managed file
   leaves out a registered console. `--json` prints the rows.

**What the rules set.** The sandbox is on and `failIfUnavailable` is set,
so a machine without a working sandbox refuses to start a session; it never
runs quietly without one. `allowUnsandboxedCommands` is off, so a command
cannot retry outside the sandbox. `Read` and `Edit` deny rules cover the
built-in file tools, which the sandbox alone does not. The `Edit` rules name
each file and folder in STATE: those listed in the kit, plus whatever else
STATE holds when you run `settings`. An `Edit` rule also covers
`~/.config/overture`. The sign-in devices are kept there, and a device an
agent added would sign its own browser in.

**Limits.**

- **Any session can write `steward/`.** It can fake the steward's cursor
  (so the watch misses requests) or its heartbeat (so the console shows a
  steward as watching). Both are advisory: the requests stay in the store
  and on the console. A session could already do this before 1.60, and the
  separate-user tier closes it.
- **Linux sockets are best-effort** (above).
- **Hosted mode.** Each project's agent needs its own token, in
  `~/.config/overture/tokens/`. Managed settings cover the whole machine,
  so they cannot give each project only its own token. A sandboxed agent
  can still read the other projects' tokens and use the kit to reach their
  consoles. A separate OS user per project closes that; it is planned, not
  built.
- **Commands only.** The sandbox covers the commands a session runs and the
  built-in tools it denies. An MCP server you add runs outside it.
- **`agent.py portfolio`** reads each console's store to count questions,
  so inside the sandbox it reports every console as having no store.
- **Measured on Linux.** The 1.60 real run was on Linux with bubblewrap.
  The macOS rules have not been run there yet.

<a id="windows"></a>
## Windows (0.9.1, 1.26, 1.53.2)

The console runs on POSIX: Unix sockets, `fcntl` locks, systemd or launchd.
On a Windows machine it runs inside WSL2, and so does everything that talks
to it.

- **The server runs in WSL2.** Install and start it from a WSL shell, as on
  Linux.
- **Claude Code must run in WSL too.** Use the Claude Code CLI inside WSL
  ([setup](https://code.claude.com/docs/en/setup)). The agent's door is a
  Unix socket in WSL, which Windows cannot open, so a native Windows session
  cannot reach the console.
- **Claude Desktop.** Its Code tab loads plugins only in native Windows
  sessions; plugins are not available in its WSL sessions
  ([Desktop](https://code.claude.com/docs/en/desktop)). There the console's
  features are unavailable. Use the CLI inside WSL.
- **What a native Windows session still gets.** The hooks load and stay
  silent (1.53.1). The PreToolUse hooks carry `"onFailure": "continue"`, so a
  failing hook never blocks an edit or a question
  ([hooks](https://code.claude.com/docs/en/hooks)). Every kit command
  (`agent.py`, `mcp_server.py`, `fold.py`, `rulecheck.py`, `server.py`)
  refuses in one line that names this section. `onboard.py` says to onboard
  again inside WSL; `onboard.py prereqs` runs there and lists what is missing.
- **`prereqs` on native Windows always exits 1.** It always lists "Claude
  Code inside WSL" as missing, because a native Windows session is not in
  WSL. Installing things in Windows never clears it: run
  Claude Code inside WSL and onboard there.
- **`python3`.** Claude Code runs hooks in Git Bash when Git for Windows is
  installed, else in PowerShell. The hooks are called as `python3`. Python's
  install manager provides it, from python.org or the Microsoft Store; only
  the old full installer provides just `python` and `py`
  ([Python on Windows](https://docs.python.org/3/using/windows.html)).
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
- **Linger.** Systemd user units stop when WSL shuts down. Run
  `loginctl enable-linger $USER` in WSL; a Windows process that keeps
  WSL alive still helps when nothing else holds it.
- **Line endings.** `.gitattributes` pins LF, so a Windows checkout no
  longer breaks `install.sh` with CRLF (0.9.1).
- **Not yet:** an agent door Windows can reach (TCP), Windows file locks,
  Windows drive paths in the registry, and a `python` fallback for the hooks.
