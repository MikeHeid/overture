# Owner decisions: one deliberation

Every question still waiting on the owner, in one place. They come from:

- [SERVER-HOSTING.md](SERVER-HOSTING.md): how the server runs;
- [UX-VIEW.md](UX-VIEW.md): the UX View modal;
- the icons and lane-colors plan, which was only in a chat until now;
- the steward-role question raised with the **Master agent name** setting;
- what to build next.

Each decision had lettered options and a ★ recommendation. A ★ the owner
deferred to is recorded as an *architect default*, not as the owner's
decision, so a later review can audit it.

Status: **decided on 2026-10-11**, except D13. The owner's answers and
amendments are below. The option tables after them are kept as the record of
what was weighed.

| # | Decision | Outcome |
|---|---|---|
| D1 | How the server runs | **A, amended.** One command runs the server in the foreground, detaches it as a daemon, installs or removes it as a service, and reports status and health (see "D1 as decided"). Same command shape as `lean-ctx`. |
| D2 | When macOS gets a service installer | **B.** Right after Linux/WSL, as its own PR. |
| D3 | One main server for new installs? | **A.** `--all` by default. |
| D4 | What a saved UX component is | **A, amended.** One self-contained HTML document, scripts off by default. A switch turns scripts on for one component (see "D4 as decided"). |
| D5 | Where components are saved | **A.** `components/<item>.md`, with backups in `components/.history/`. |
| D6 | Which items get UX View | **B.** Default lanes, configurable. |
| D7 | How a saved component reaches the repository | **A, amended.** Through the steward and a PR, and the PR can be merged from the console's PR tab (see "D7 as decided"). |
| D8 | Where the icons come from | **A.** A Lucide subset, bundled. |
| D9 | How tabs show icons | **B, amended.** Always icon plus label. The inbox column is always wide enough to show the menus without wrapping. |
| D10 | How lanes get colors | **A.** Automatic, with a named override. |
| D11 | A per-machine steward role setting? | **B**, as an *architect default*: the owner deferred to the recommendation. |
| D12 | What to build next | **A.** Icons and status indicators, then lane colors. |
| D13 | How a UX item is tied to a Claude Design project | **Open.** Needs a real Claude Design link to pin the accepted URL shapes. |

### D1 as decided

One entry point with five modes, modelled on `lean-ctx`:

    <py> <kit>/server.py --all                     # foreground; Ctrl+C stops it
    <py> <kit>/server.py daemon start|stop         # detached, with a pid file and a log file
    <py> <kit>/server.py service install|uninstall # systemd user unit (Linux, WSL); launchd next (D2)
    <py> <kit>/server.py status                    # running? which mode? pid, port per project, last restart
    <py> <kit>/server.py health                    # per project: store lock, tunnel reachable, version skew, linger

- `daemon start` refuses when a service is already installed and running,
  and the reverse. Both name the other mode.
- `status` and `health` read the pid file, the unit state and the agent
  socket. They never start anything.
- Following `lean-ctx doctor`, `health` warns when linger is off, reports
  the restart count, and cleans up a stale pid or socket file left by a dead
  process.
- The SessionStart hook still only reads: when the server is down, it
  prints the one-line `status` hint.

### D4 as decided

- Components render with scripts **off** by default.
- A **Scripts** switch in the UX View modal turns them on for that component
  only.
- The switch is an owner act: it is sent as a message, so it is in the audit
  trail. The steward records it in the component's front matter as
  `scripts: true`.
- With scripts on, the frame changes from `sandbox=""` to
  `sandbox="allow-scripts"`, never with `allow-same-origin`, so it runs in an
  opaque origin. That is the same arrangement as today's Mermaid frame.
- Its CSP sets `connect-src 'none'` and allows no outside script sources, so
  a component's script can't reach the network, the console or its cookies.

### D7 as decided

- Saving still goes through the steward and a PR.
- The PR tab gets a **Merge** button on a PR whose checks pass.
- The server runs no git and holds no GitHub token, so the button does not
  merge anything itself. It sends an owner message with `intent: "pr-merge"`
  and the PR number, and the doorbell rings.
- The Claude Code session that runs that repository merges the PR with its
  own GitHub access. That session is the steward, or the session for that
  repository when a primary console watches several.
- The PR row shows "merge requested", then "merged" after the next
  `prs-push`.
- If no session for that repository is running, the request waits in its
  inbox, like any other owner message.

---

## Server hosting

### D1. How the server runs

**What depends on it:** whether answers you give from your phone reach
agents when no Claude session is open, and whether the plugin's hooks stay
read-only.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** A per-OS user service, plus a read-only session check | `server.py service install` writes the unit. The SessionStart hook prints one line when the server is down. | The console works with the laptop's sessions closed. Restarts and logs are handled. The hooks stay read-only. | About two minutes of setup, once. Three service templates to maintain. |
| B The main Claude session starts the server | The SessionStart hook spawns `server.py --all` if it isn't running. | No setup step. | Answers stop when the session ends. Hooks would then start a network daemon, breaking the README's trust promise. Sessions race for the lock. |
| C Service only, no session check | Today's `install.sh` units. | Nothing new to build. | A server that is down goes unnoticed until you open the console. |

**Why A:** the async loop is the product: agents ask, you answer later,
from anywhere (SERVER-HOSTING.md, "What the server has to do", 1). Only a
service survives the session ending. The check covers the "people get lost
after install" problem without the hook owning a daemon.
**What would change it:** if most users only use the console while a
session is open, and never from a phone, B's zero setup would win.

### D2. When macOS gets a service installer

**What depends on it:** whether Mac users get a one-command install in the
first release of `service install`.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| A With Linux/WSL, in one PR | A launchd plist template next to the systemd units | Every POSIX user gets it at once. | A bigger PR, and launchd can't be tested in CI here. |
| **B ★** Right after Linux/WSL, as its own PR | Same command; macOS added second | Linux ships sooner. The macOS change is small and reviewed on its own. | Mac users wait one release. |
| C Later, when someone asks | — | No work now. | Mac users write their own plist. |

**Why B:** the command and its tests get settled on systemd, which
`install.sh` already uses, and launchd is then a template behind the same
command.
**What would change it:** if you or your first users are on Macs, choose A.

### D3. One main server for new installs?

**What depends on it:** how many processes, units and loopback ports a user
with several projects has to manage.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** Yes: new installs use `server.py --all` | `install.sh` writes `overture-console.service`. Each project joins with `server add` ([JOIN.md](../JOIN.md)). | One process and one unit. Adding a project needs no new unit. Upgrades restart once. | A restart is needed to pick up a new project. One crash stops every console. |
| B No: one server per project stays the default | Today's `<name>-console.service` | Projects are isolated; this is what exists. | N units, N restarts, N ports to track. |
| C Ask during install | `onboard.py` asks which mode | Both kinds of user are served. | One more question at install time, and two paths to document and test. |

**Why A:** JOIN.md already documents and tests `--all`, and the server
refuses a project it can't open by name while serving the rest, so one bad
project doesn't take the others down.
**What would change it:** if you need strong isolation between projects (for
example, different clients on one machine), choose B.

---

## UX View

### D4. What a saved UX component is

**What depends on it:** what the modal can safely render, and what an agent
produces when you press Generate.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** One self-contained HTML document: inline styles, no scripts | Shown through the existing `/visual` sandbox with scripts off | Uses the sandbox that exists, with no new script surface. Any framework can copy it in. | Interactive behaviour (state, events) can only be described, not shown. |
| B Framework code (React or similar) saved alongside, with HTML as its preview | `components/<item>.jsx` plus the preview HTML | Code that drops straight into the app | Two artifacts to keep in sync. The preview can drift from the code. |
| C Framework code rendered live | A sandboxed iframe with scripts on | True interactivity | A new script-running surface, against the 1.31 hardening. |

**Why A:** UX-VIEW.md's second rule ("the server generates nothing") and the
scripts-off sandbox mean A needs no new trust decision. B can be added later
as an extra file.
**What would change it:** if your UX items are mostly interactive widgets
rather than layouts and styles, B is worth its cost.

### D5. Where components are saved

**What depends on it:** where the steward's PRs write, and where your app
code reads them from.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** `components/<item>.md` plus `.css`, with backups in `components/.history/` | As UX-VIEW.md proposes | Easy to find, and the history sits beside the files. | A new top-level folder in every project. |
| B Under `.overture/components/` | Next to `portfolio.json` and the adapter | Overture's files stay in one place. | Hidden from people who don't know Overture. |
| C Configurable in `.overture.json`, default A | `"components_dir": "…"` | Fits projects with their own layout. | One more setting to validate and test. |

**Why A:** components are project artifacts that people browse and import,
not Overture state. If people ask, C can come later without moving anything.
**What would change it:** if your projects already have a `components/`
folder with another meaning, choose C.

### D6. Which items get UX View

**What depends on it:** which items show the button, and where new UX items
are placed in the dashboard.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| A Fixed: `lane-ui`/`lane-ux` sections plus a `ux` tag | As UX-VIEW.md proposes | Simple, with nothing to configure. | Projects that name their lanes differently get no button. |
| **B ★** The A defaults, overridable in `.overture.json` | `"lanes": {"lane-frontend": {"ux": true}}`, the same registry as D10's colours | Works with any naming. | One small setting. |
| C Every item | The button everywhere | Nothing to configure. | Noise on backend items. |

**Why B:** lane names come from each project's adapter, so a fixed list will
miss some. The setting accepts names only, the same as D10's override.
**What would change it:** if every project you run uses `lane-ui`, A is
enough.

### D7. How a saved component reaches the repository

**What depends on it:** the trust model. Today nothing reaches the
repository without a PR you merge.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** Through the steward and a PR | `ux-save` → steward → `agent.py ux-export` → PR | Same path as rulings and visuals; the server never writes the project. | Save takes effect at merge, not instantly. |
| B The server writes the file directly | The server writes `components/` | Instant | Breaks "the server never writes into the project", a core promise. |
| C A PR that merges itself when checks pass | Like A, with auto-merge | Close to instant | A web page click lands code with no human looking at the diff. |

**Why A:** rule 1 in UX-VIEW.md, and the README's trust section. The modal
can show "saved, PR #N pending" so the delay is visible.
**What would change it:** nothing short of dropping the trust model.

### D13. How a UX item is tied to a Claude Design project

**What depends on it:**

- whether the tie survives outside the console;
- whether agents can build from the design;
- whether the server gains an outbound door.

The full design is in [UX-VIEW.md](UX-VIEW.md), "Linking a Claude Design
project".

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** A link stored in the component's front matter by the steward's PR, and shown on the item. Agents read the design; the server never opens it. | `ux-link` intent → `ux-export` writes `design: {url, kind, synced_version}`; an exact-shape URL check like `prs.py` | Visible in the repository and in git history. Drift raises a question, like stale rulings. No new server network access. | Linking takes effect at merge, like Save. |
| B The link kept only in console state | A field on the item in STATE | Instant | Lost outside the console: other tools and a fresh clone never see it. |
| C The server fetches and previews the design | The server calls claude.ai | A live preview in the modal | The server would need a claude.ai login, and it gets an outbound fetch door. Breaks the trust model. |

**Why A:** the server holding no credentials and never fetching what a page
gives it is the same rule that makes PR links exact-shape (`prs.py`). The
repository is where the component lives, so it is where its source belongs.
**What would change it:** if links are only scratch notes and never need to
outlive the console, B is simpler.

---

## Icons and lane colors

### D8. Where the icons come from

**What depends on it:** how the tab bar, menus, palette and status marks
look, and what gets bundled.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** About 25 Lucide icons, copied into `console.js` as inline SVG with `currentColor` | Pinned with a license note and a checksum, like the bundled libraries | Familiar and consistent. ISC license. No network requests and no icon font. | Paths to update by hand if Lucide changes. |
| B Draw our own | Same inline SVG | Fully ours | Design time, and the result is likely less polished. |
| C An icon font from a CDN | `<link>` to a CDN | Least work | Breaks the no-outside-resources rule (1.31). |

**Why A:** it keeps the 1.31 rule (no outside resources) at almost no cost.
**What would change it:** if you want a distinct brand look, B.

### D9. How tabs show icons

**What depends on it:** whether tabs clip in the side dock.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** Icon plus label when wide, icon only with a tooltip when narrow | A container query on the tab bar | Ends tab clipping for good while staying readable. | Two layouts to test. |
| B Always icon plus label | — | Always readable | Clips in a narrow dock; today the tab bar scrolls. |
| C Icon only | — | Most compact | New users must hover to learn the tabs. |

**Why A:** the dock width is user-set (default 480px), so the tabs must work
at both widths. This was the clipping complaint behind the wider-column fix.
**What would change it:** if nobody uses a narrow dock, B is simpler.

### D10. How lanes get colors

**What depends on it:** the section chips, row edges, project map and
dashboard blocks.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| **A ★** Automatic: a lane's name maps to one of 8 colors that work in both themes. Optional named override in `.overture.json`. | `"lanes": {"lane-api": {"color": "blue", "icon": "server"}}`; palette names only, never raw CSS | Works with no setup, and the same lane always gets the same color. The override can't inject styles. | Two lanes may share a color by chance until overridden. |
| B Config only: lanes without a color stay gray | Same setting, required | Every color is chosen on purpose. | Nothing shows until someone configures it. |
| C No lane colors; icons only | — | Least work | Loses the "where does this belong" view at a glance. |

**Why A:** items already carry `wave-2/phase-2.2/lane-api` in their `section`,
so colors come from data that exists. Color is never the only signal: the
chip's text names the lane.
**What would change it:** if you want a fixed lane legend across projects, B.

---

## The steward

### D11. A per-machine steward role setting?

**What depends on it:** whether a machine can be marked "workers only".

Today the role is per session: `/overture:as <steward name>` makes a session
the master, and any other name makes it a worker. The plugin's **Master agent
name** setting supplies the name.

| Option | In this project | Upside | Cost |
|---|---|---|---|
| A Add `role: steward \| worker` to the plugin settings | A plugin `userConfig` field. With `worker`, `/overture:as <steward>` is refused on that machine. | Enforces "the steward only runs on the home server". | Applies to every session on the machine; one more setting to explain. |
| **B ★** Not now; keep it by session name | Today's behaviour | Nothing new to build or explain. | A laptop session can still name itself the steward. |

**Why B:** a plugin setting applies machine-wide, so it can't express "this
session is the steward". It only helps if the steward runs on a separate
machine.
**What would change it:** if you run the steward on a home server and only
workers on laptops, A is worth adding.

---

## What next

### D12. What to build next

**What depends on it:** the order of the next PRs. Each one is merged before
the next starts.

| Option | Work | Size |
|---|---|---|
| **A ★** Icons and status indicators, then lane colors (D8–D10) | Two PRs: `console.js`, `console.css`, tests, screenshots | Medium |
| B UX View (D4–D7) | Schema intents, the `console-ux` skill, `ux-export`, the modal | Large |
| C `server.py daemon|service|status|health` and the session check (D1–D3) | `server.py`, `session_start.py`, units, docs | Medium |
| D Logged bugs: the project map lays every item out in one row; a `BrokenPipeError` traceback in `_send_raw` | `chart.py`, `server.py`, tests | Small |

**Why A:** its design is finished, and it changes what every screenshot
shows. Doing it first avoids redoing UX View's screenshots later. D is small
enough to ride along with whichever PR touches `chart.py` or `server.py`.
**What would change it:** if new users still get lost after installing, C
first. If a UX project is waiting, B first.
