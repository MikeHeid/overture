# Proposal: how the Overture server should run

**The question.** Should Overture ship a command for each operating system
that installs the server as a background service? Or should the server
start with the main Claude session?

**Recommendation.** Ship an optional per-OS service installer, built on the
one command shape the kit already uses. Do not start the server from a Claude
session. A session can *check* the server and say how to start it, but it
never launches it.

Status: decided on 2026-10-11, with amendments. See [OPEN-DECISIONS.md](OPEN-DECISIONS.md).

---

## What the server has to do

1. **Be up when no Claude session is.** The core loop is asynchronous:
   - agents post questions and stop;
   - you answer from a browser, often from your phone, hours later;
   - the next session picks up what arrived.

   The doorbell and the SessionStart summary exist so that answers given
   *while no session ran* are not lost.
2. **Be the only writer of each store.** The server takes an exclusive lock
   on each project's state directory. Two copies racing to start must not
   both run.
3. **Run no project code.** It runs no git and no adapter. It reads only
   data its own doors received (CONSOLE-kit/Q23, Q24).
4. **Sit behind Cloudflare Access, with a tunnel up.** The browser reaches it
   only through the tunnel, so the tunnel must be running too.

## Option A: a background service (recommended)

One command installs and manages the server and its tunnel as a user-level
service:

    <py> <kit>/server.py --all                     # foreground; Ctrl+C stops it
    <py> <kit>/server.py daemon start|stop         # detached, with a pid file and a log file
    <py> <kit>/server.py service install|uninstall # a user service
    <py> <kit>/server.py status                    # running? which mode? pid, ports
    <py> <kit>/server.py health                    # store locks, tunnel unit state, version skew, linger

(As decided in D1. `health` reads the tunnel's unit state or cloudflared's
local metrics; it never makes an outbound request.)

| OS | Service manager | Notes |
|---|---|---|
| Linux | systemd user units | What `deploy/install.sh` does today. `loginctl enable-linger` keeps it running after logout. |
| WSL2 | systemd in WSL | Same units. Needs `systemd=true` in `/etc/wsl.conf` and linger. A Windows Task Scheduler entry running `wsl -e true` at logon can keep WSL alive. |
| macOS | launchd LaunchAgent | A new `~/Library/LaunchAgents/…plist` with `KeepAlive`. The server already runs on POSIX, macOS included. |
| Windows (native) | none | The server refuses to start without POSIX file locks (1.26). The installer says so and points to WSL2. Making the server portable is a separate, larger decision. |
| Any (optional) | Docker | One image, with the tunnel as a sidecar. Good for a home server or NAS. Already on the roadmap (Wave 2). |

**Why this is the right default:**

- It meets requirement 1: the console answers while your laptop has no
  Claude session open, and even while Claude is not installed.
- It meets requirement 2: one service owns the lock, and the service manager
  restarts it after a crash.
- It is what the kit does already. `install.sh` writes systemd units, and
  the release notes and runbook assume one. The change is only to cover more
  OSes and add `--all`.
- It keeps the trust model. The service runs the installed kit copy, not a
  plugin cache or a checkout that an update or branch switch could change
  underneath it.

**Costs:**

- One more thing to install: about two minutes, and only once.
- Three templates to maintain (systemd, launchd, Docker).
- Native Windows stays unsupported.

## Option B: start with the main Claude session

The plugin's SessionStart hook would start `server.py --all` when it is not
running, and leave it running.

**Why not:**

- **It breaks the async loop.** If the server lives only while a session
  does, you cannot answer from your phone after closing the laptop. If it
  outlives the session, it has become an unmanaged background service: no
  restarts, no logs, no clean stop.
- **It breaks the hooks' trust model.** The README promises that the three
  hooks are standard-library only, read-only outside their known files, and
  never run anything. A hook that spawns a long-lived network server breaks
  that promise, and it fires in every session on the machine.
- **Sessions race.** Several sessions start at once (the steward and named
  agents). They would race for the lock; the losers would need retry logic,
  and you would get confusing "refused" lines in each session.
- **The tunnel is separate anyway.** cloudflared would also need starting, so
  the hook would end up managing two daemons.

## Option C: the session checks, the service runs (recommended alongside A)

Keep Option A as the way the server runs. Add a small, read-only check to
the existing SessionStart hook, which already reads the doorbell:

- When the server is down, it prints one line with the command to start it.
  For example:

      Overture: the console server is not running. Start it with
      `systemctl --user start overture-console` (or `server.py status`).

- When the installed kit is older than the plugin, it says so. Today's
  upgrade banner partly does this already.

This gives the convenience you were asking about, seeing at session start
that something is wrong, without the session owning a daemon.

## A "try it" mode

For a first look, before setting anything up:

    <py> <kit>/server.py --all        # in a terminal; Ctrl+C stops it

The README's quick start can offer this and point to `service install` once
someone decides to keep Overture.

## Proposed work, in order

1. **`server.py daemon|service|status|health`** for Linux and WSL
   (systemd, `--all`). It moves today's `install.sh` unit rendering behind
   one command and adds the main-server unit from [JOIN.md](../JOIN.md).
2. **macOS launchd** behind the same command.
3. **The SessionStart check** (Option C): read-only, one line when the
   server is down.
4. **The Docker image** (Wave 2 on the roadmap).

## Decisions for the owner

- Accept Option A plus Option C, and reject Option B?
- macOS launchd now, or after Linux/WSL ships?
- Should the main server (`--all`) become the default for new installs,
  replacing one server per project?
