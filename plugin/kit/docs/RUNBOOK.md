# Console runbook

Symptom, then checks, then the fix. Placeholders are the ones in `DEPLOY.md`
(`<name>`, `<state>`, `<vendored>` or the installed kit, `<port>`). Nothing here
needs a secret; never paste `console.env` or a token into a ticket.

## First: health

    python3 <vendored>/agent.py --state <state> health; echo rc=$?

| Result | Meaning | Go to |
|---|---|---|
| `rc=0`, `"ok": true` | server up, register readable | the symptom's own section |
| `rc=1`, `"register": "error"` | server up, the adapter's `items()` fails | the journal (below); fix the register file |
| `rc=2`, `cannot reach the console server` | server down, or `<state>` is wrong | "Console 502" |

`"agent": "listening"` means a session is waiting on the doorbell now;
`"idle"` means none is (the last one stopped or went quiet); `"never"` means
none ever has on this state dir. The console's status bar shows the same thing.

The journal names every start-up error and every failed register read:

    journalctl --user -u <name>-console.service -n 50 --no-pager

## Console 403

    curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<port>/api/view    # 403 = server up and gated

The 403's JSON body names the reason (the journal logs only the request line,
never a header). Read it in the browser:

- **`no Access token`**: the request did not come through Access. Check that
  the Access application's domain is exactly the tunnel's hostname, and that
  its policy includes you.
- **`Access token refused (InvalidAudienceError)`**: `CONSOLE_AUD` is not the
  Access application's AUD tag. Correct it in the env file and restart.
- **`(InvalidIssuerError)`**: `CONSOLE_TEAM_DOMAIN` is not your team domain.
- **`(ExpiredSignatureError)`**: log in again; if it repeats, check the
  machine's clock (`timedatectl`).
- **`(PyJWKClientError)`** or similar: the server cannot fetch the team's keys.
  Check outbound HTTPS from the machine to `https://<team>/cdn-cgi/access/certs`.
- **A POST fails with `a write from another site, or with no Origin`**:
  `CONSOLE_HOSTNAME` is not the hostname in the browser's address bar.

## Console 502 (or Cloudflare 1033 / 530)

Cloudflare reached the tunnel but not the server, or not the tunnel at all.

    systemctl --user status <name>-console.service <name>-console-tunnel.service --no-pager
    ss -ltn | grep ':<port> '

- Server not running: read the journal. A `StoreError` on start is "Store
  damaged" below. `the agent socket path is N bytes` means `--state` is too
  long a path; shorten it.
- Server running, tunnel not: restart the tunnel unit, then check that its own
  config (`~/.cloudflared/config-<tunnel>.yml`) has ingress
  `http://127.0.0.1:<port>`, and that `<port>` is `CONSOLE_PORT`.
- Both running: the DNS record may point at another tunnel. Route it again
  with `--config` for this tunnel (`CLOUDFLARE.md`).

## macOS: the launchd service (1.51.0)

On a Mac the one server (`server.py --all`) runs as the LaunchAgent
`overture.console` that `server.py service install` writes; there is no journal.

    python3 <kit>/server.py health
    launchctl print gui/$(id -u)/overture.console | grep -E 'state =|pid =|last exit code ='

(`$(id -u)` is your user id, e.g. 501.)

- **Where things are:** the plist is `~/Library/LaunchAgents/overture.console.plist`;
  the server's output goes to `~/.local/state/overture/server.log` (the daemon's
  log, rotated at install past 5 MiB).
- **Restart** (after an upgrade, or on "version skew"):
  `launchctl kickstart -k gui/$(id -u)/overture.console`.
  **Stop:** `launchctl bootout gui/$(id -u)/overture.console` (it loads again at
  your next login; `server.py service uninstall` removes it for good).
- **`Could not find service "overture.console"`** (exit 113): the plist is
  there but the job is not loaded, so `health` says `inactive`. Load it with
  `server.py service install --start`.
- **`--start` says `Bootstrap failed: 5` (or 125) and "launchd needs your
  login session":** you are on SSH, or nobody is logged in at the Mac, so
  there is no `gui/$(id -u)` domain to load into. The plist is written: log in
  at the Mac and run `--start` again, or it loads at your next login.
- **`failed`, and the log repeats the same error every 10 s:** launchd has no
  start limit; with `KeepAlive` it starts a server that exits non-zero again
  after `ThrottleInterval` (10 s), forever. Read the log, fix the cause (a bad
  `server.json`, a missing dependency), then `kickstart -k`.
- **Nothing after a reboot until you log in:** expected. A LaunchAgent lives in
  your login session (the `gui` domain); there is no linger on macOS.

## The doorbell does not wake the session

1. Is anything listening? The status bar, or `health`, says `listening`.
   If not, no session is running `agent.py watch`: start one (the
   `console-process` skill re-arms it after each run).
2. Did the owner's action ring? Only "Answers are in" (`process`), a chat message (`chat`) and a
   deliberation request (`fork`) wake a watch; answers, locks and messages
   do not.

       tail -n 3 <state>/inbox.jsonl
       python3 <vendored>/agent.py --state <state> inbox --all | tail -n 3

3. Has the agent already passed it? The watch starts after the agent's cursor.

       cat <state>/agent-cursor.json

   If `through` is at or past the wake line's `seq`, that line was already
   processed. `inbox --since <seq-1>` shows it again.
4. Same state dir? The watch, the server and the registry must name the same
   `<state>`: compare the unit's `--state` with
   `~/.config/overture/projects.json`.
5. `... is not a regular file`: something replaced the doorbell or a state
   file with a FIFO or device. Remove it; the server recreates the doorbell
   on the next owner write.

"Agent active" that never clears lapses on its own after an hour, or at once
on `agent.py synced`.

## The console does not update by itself (0.7.0)

An open tab keeps one long poll to `/api/wait`; each answers within 25 s.

1. Reload once. A tab opened before the server was upgraded has the old page.
2. In the browser's network panel, `/api/wait` should show one request at a
   time, each lasting up to 25 s. A `403` means the Access session expired:
   reload to log in again. A `429` means more than 16 tabs are polling; close
   some. A `404` means the server is older than 0.7.0 (`health` shows the
   version); the page then stops polling and **Refresh** still works.
3. A hidden tab does not poll; it catches up the moment it is shown.
4. While you type in the panel, a change shows a **New activity · Show**
   note instead of redrawing the box you are typing in. The chat is the
   exception: replies appear in its log as you type.
5. The server log shows one `GET /api/wait` line per poll. Several a second
   from one tab is a bug: note the browser and version.

## "Lock all & process" says nothing was locked (0.7.0)

It checks the whole batch first and writes nothing if the store would refuse
any of it; each question's line says why. The usual cause is a question
locked from another tab or card since you drafted it: re-open the round (it
shows as already locked) and lock the rest. To change a locked answer, use
**Change my answer** on its card, which asks for a reason.

**"Stopped part way"** means a write failed (a full disk, say) after some
questions were locked. Those stay locked; the rest were not written and no
process request was sent. Fix the cause (`df -h <state>`), then press **Lock
all & process** again: already-locked questions are skipped and one process
request is sent.

## A chat message is not answered (0.7.0)

1. The Chat tab says whether an agent is listening. If not, the message waits
   for the next session; nothing is lost.
2. A watch started before 0.7.0 does not wake on chat: restart it (the
   `console-process` skill re-arms it).
3. `tail -n 3 <state>/inbox.jsonl` shows a line with `"intent": "chat"` and
   `"item": "@chat"` for each message.
4. **429 "at most 6 chat messages a minute"** (or 60 an hour): wait and send
   again. What you typed stays in the box.

## The server will not start: `.overture.json` (0.8.0)

The journal says `console: .overture.json: specs_dir ...` (or
`visuals_dir`, `next_step`). The server refuses a folder that is not a plain
relative path at least one folder deep, one that climbs out or resolves
outside the project through a symlink, a `visuals_dir` inside `specs_dir`, and
a `next_step` that is not `{"refine"|"drill": "<skill name>"}`. Fix the key,
then `systemctl --user restart <name>-console.service`.

## Upgrading to 0.8.1: visuals a 0.8.0 server wrote into the checkout

0.8.0 wrote each visual, its doc and `INDEX.md` under `<project>/<visuals_dir>/`
in the service checkout, as untracked files. Once an agent landed the same
paths by pull request, `git merge --ff-only` in the checkout was refused
("untracked working tree files would be overwritten by merge") and the
console stopped following main. **0.8.1 ignores those files**: it neither
reads, imports nor deletes anything in the checkout. It looks for every
visual, old or new, in `<state>/visuals/<item>/<name>`. Move them once:

1. Stop the server: `systemctl --user stop <name>-console.service`.
2. See what 0.8.0 left (untracked files only; tracked ones already landed):

       git -C <project> status --porcelain --untracked-files=all -- <visuals_dir>

3. Copy every item folder into the state, keeping the file names (not
   `INDEX.md`, which is regenerated wherever visuals are exported). Landed
   (tracked) visuals are copied too, since the server now serves only from
   the state:

       mkdir -p -m 700 <state>/visuals
       for d in <project>/<visuals_dir>/*/; do
         i=$(basename "$d"); mkdir -p "<state>/visuals/$i"
         cp -n "$d"*.mmd "$d"*.html "$d"*.md "<state>/visuals/$i/" 2>/dev/null
       done

   `cp -n` never overwrites; a name the state already holds is kept. The
   server re-checks each file's sha256 against the store when it shows it.
4. Remove the **untracked** copies from the checkout, and nothing else. For
   each untracked path step 2 listed, `rm <project>/<path>`; or, when every
   file under `<visuals_dir>` is untracked (it never landed), preview and then
   clean just that folder:

       git -C <project> clean -n -- <visuals_dir>
       git -C <project> clean -f -- <visuals_dir>

   Visuals that are not yet in the repository are safe: they are in the state
   now, and `agent.py visual-export --project <your worktree>` lands them.
5. Start the server and check the checkout follows main again:

       systemctl --user start <name>-console.service
       git -C <project> status --porcelain --untracked-files=all    # prints nothing
       git -C <project> pull --ff-only

A visual 0.8.0 stored and you did not move shows "not in the console's
state ... stored by 0.8.0 at <path> in the project's checkout": that message
names the file to move.

## A visual does not show (0.8.0)

- **"Not shown: ... changed since the agent stored it"** or a blank frame with
  a 409 in the network log: someone edited the file under `<state>/visuals/`
  after it was stored, or swapped it (or a folder on its way) for a symlink.
  The console shows a visual only while its sha256 matches the store. Restore
  the file from the pull request that landed it (same name, into
  `<state>/visuals/<item>/`), or ask for the visual again.
- **"the visual is not in the console's state"**: the state lost it, or it is
  a 0.8.0 visual still in the checkout (the message says so; see "Upgrading
  to 0.8.1" above). Restore it from its pull request into
  `<state>/visuals/<item>/`.
- **An HTML mock shows unstyled or with gaps**: it loads something from
  outside itself. The mock's policy allows only inline styles and `data:`
  images; the agent should inline them (console-visual skill, step 2).
- **A script or form in a mock does nothing**: by design. A mock runs in
  `<iframe sandbox="">` and is served with a `sandbox` Content-Security-Policy,
  so no script runs, even if its URL is opened in its own tab.
- **`agent.py visual-export` says "this project sets no visuals_dir"**: the
  visual is stored and shown; it only has nowhere to land. Add `visuals_dir`
  to `.overture.json` (by pull request) and restart the server.
- **`visual-export` says "the directory the console server runs from"**: by
  design. Export into your own worktree on a branch
  (`agent.py worktree new --kind visual --item ITEM` makes one and prints its
  path, 1.50.0), then open a PR.
- **`worktree new` says "Name this session first, e.g. `agent.py --as
  agent-5 --state STATE worktree new ...`"** (1.50.0): by design; unnamed
  sessions share one set of marks, so they would share one worktree. Name the
  session as for `working`: `agent.py --as agent-6 ...`,
  `OVERTURE_AGENT=agent-6`, or `/overture:as agent-6` typed in it.
- **`.overture.json` is refused: "worktree_setup[N] holds a control
  character (ESC, U+001B)"**: a word of the setup command carries a
  terminal escape, a newline or the like, which could rewrite what the agent
  sees when it is printed. Take the character out (by pull request).
- **`worktree new` prints "This project suggests a setup step; run it
  yourself in the worktree: ..."**: the project's `worktree_setup`. Overture
  never runs it (it comes from `origin/main`, which any merged PR can change);
  run the printed command yourself, through your own Bash tool and its
  permission prompt, if you trust it.
- **`worktree prune` keeps one: "PR #N merged at A, but this worktree is at
  B"**: the worktree has commits the merged PR did not carry, or the PR was a
  fork's branch of the same name. Look at it (`git -C <path> log`), then
  remove it by hand with `git worktree remove <path>` when you are sure.
  "it has uncommitted changes now" or "its HEAD moved while prune ran": an
  agent wrote into it while prune looked; it is looked at again next time.
  A worktree with no commits of its own is never pruned as landed, even when
  a merged PR of its branch name exists (an old one, before the name was
  freed): it is kept, and listed stale after 14 days; remove it by hand if
  it is not wanted.
- **`worktree prune` keeps one: "removing it took over 120 s and was
  stopped; it may be half-removed"** (or "its folder is gone, but git still
  lists it as a worktree"): a very slow disk. Look at the folder, then run
  `git worktree remove <path>` from the main checkout, or `git worktree
  prune` there if the folder is already gone.
- **The watch says "worktree prune: stopped after 60 s at BRANCH; the rest
  next cycle"**: the steward's prune has 60 seconds in all, its `gh` call
  included, and a slow git or `gh` used them up. Nothing is wrong; the next
  cycle (10 minutes on) takes up after BRANCH, and "listening" stayed fresh
  meanwhile. A `git worktree remove` started late in those 60 seconds is
  never cut short: it may take up to 120 seconds more, so one prune can last
  about 3 minutes.
- **`worktree new` says "the worktree registry is busy: a prune is removing a
  worktree right now ...; try again in a minute"**: the steward's prune holds
  the registry's lock while a `git worktree remove` runs (up to 120 s on a
  slow disk), and `new` waits only 10 seconds for it. Nothing was made; run
  it again shortly. `worktree list` does not wait; while the lock is held it
  says "the registry is busy" and lists what is there.
- **`visual-export` says "... is already there with other content"**: a file
  in your worktree at that path differs from the stored visual. Nothing was
  written. Look at it; move it aside if it is stale, then export again.
- **"INDEX.md was not written by the kit"**: a hand-written `INDEX.md` sits in
  your worktree's `visuals_dir`. Nothing was written; move it aside and export
  again.
- **`visual-export` says "... is inside the work tree ..."**: `--project` must
  be the **top** of your worktree (the folder `git rev-parse --show-toplevel`
  prints), never a folder inside it, because `visuals_dir` is a path from the
  repository's top. Nothing was written.
- **What `visual-export`'s exit code means (0.8.2)**:

  | Exit | Meaning |
  |---|---|
  | 0 | every chosen visual was exported (or was already there, identical) |
  | 3 | files were written, but at least one visual was refused; each is named on stderr as `not exported: visual <id>: <why>`, and listed under `refused` in the JSON |
  | 1 | nothing was written: the export was refused, or every chosen visual was |
  | 2 | the console server could not be reached |

  Before 0.8.2 a partial export exited 1, the same as "nothing was written".
  On 3, land what was written and fix the refused visual as the bullets above
  say (a refused visual is usually one whose file under `<state>/visuals/`
  changed since it was stored).

## Several agents on one console (0.8.2)

- **Every reply says "agent", and you cannot tell the sessions apart**: give
  each session a name. It runs `agent.py --as agent-6 ...` (or sets
  `OVERTURE_AGENT=agent-6`); the console-process skill says where. The
  name then shows on its questions ("asked by agent-6"), replies, chat
  messages, visuals, roar transcripts and Feed rows. A record written with no
  name shows as before.
- **`agent.py` exits 2 with "agent name ... is refused"**: a name is 1 to 32
  lowercase letters, digits and single hyphens, starting with a letter, and
  never `agent` or `owner`. Nothing was sent.
- **One session's `synced` cleared another's "agent active"**: that was 0.8.1,
  where any `synced` deleted `working.json` whole. From 0.8.2 the marks are
  kept per name (`{"agent-6": {"ITEM": "time"}, "agent": {...}}`, where
  `agent` is every unnamed session together), and `synced` clears only the
  caller's own. Two unnamed sessions still share one set of marks: name them.
- **Where the names are kept**: `<state>/names.jsonl`, one line per named
  record, beside `store.jsonl`, never inside it. The server refuses to start
  on a line it cannot read, naming the line (`names.jsonl:N: ...`); move that
  line aside by hand, which only makes that record unnamed. Deleting the file
  unnames every record and loses nothing else.
- **The doorbell cursor is still one for all sessions**: whichever session
  runs `synced --through SEQ` moves it. From 0.8.3, name a steward so only
  one session can ("The steward (0.8.3)" below).

## The steward (0.8.3)

The doorbell has one cursor. With several sessions on one console, name one
of them its **steward** in your own registry; only it watches, syncs and folds.

**Set it up** (you, in a terminal, never a session):

    python3 <kit>/agent.py --state <state> steward agent-5
    python3 <kit>/agent.py --state <state> steward            # prints the steward, or "no steward"
    python3 <kit>/agent.py --state <state> steward --clear    # no lock: 0.8.2 behaviour

It is written to every project registered on `<state>`. Then name each
session, in the session itself (0.8.4):

    /overture:as agent-5      # typed in the steward's session
    /overture:as agent-6      # typed in any other session

The plugin records the session's id against the name in
`<state>/sessions.jsonl`, and the SessionStart hook exports the id to the
session's Bash as `OVERTURE_SESSION`, so the question hook knows the
steward and every `agent.py` call is signed. The name lasts while the session
id does: `--resume` and `--continue` keep it; `/clear` and `--fork-session`
need the command again. Starting a session with its name in its environment
still works, as the fallback:

    cd <project> && OVERTURE_AGENT=agent-5 claude      # the steward
    cd <worktree> && OVERTURE_AGENT=agent-6 claude     # any other session

A name typed in the session wins over the variable. The repository's
`.overture.json` cannot set or change the steward, and the sessions file
cannot either: it only says which name a session goes by.

**What changes:**

- **`agent.py watch` or `synced` exits 1 with "refused: `watch` belongs to
  this console's steward, agent-5"**: the session is not the steward (its
  `--as`, else its `/overture:as` name, else `OVERTURE_AGENT`, is
  another name, or none). Nothing moved:
  no heartbeat, no cursor. It should post with `ask`, `reply` and `working`,
  which stay open to everyone. `fold.py` (export and fold) refuses the same
  way. A non-steward's "agent active" marks are cleared only when they lapse
  (an hour), since its `synced` is refused.
- **`AskUserQuestion` is denied with "Owner console: AskUserQuestion is
  blocked in this session"**: the plugin's PreToolUse hook
  (`hooks/ask_guard.py`) does this in every session of a registered project
  whose console has a steward, except the steward's. Its message carries the
  full `agent.py ask` command. The steward asks you live as before, and
  mirrors each live answer to the console: it posts the question with
  `agent.py ask`, and replies on its item with your answer, so the record
  holds it and you can lock it.
- **The steward itself is refused**: its name did not reach the command.
  Type `/overture:as agent-5` in that session again (after `/clear` or a
  fork it is a new session). If `agent.py` is still refused, run
  `echo $OVERTURE_SESSION` there: empty means the SessionStart hook did not
  export it (restart or resume the session), or pass `--as agent-5` to every
  `agent.py` call.
- **"the registry names more than one steward for the console at ..."**:
  two projects on one state carry different stewards (a hand edit). Run
  `agent.py --state <state> steward NAME` once to set one for all.
- **`watch` says the registry "is not JSON"** (or another registry error):
  the lock does not switch itself off when your registry breaks; fix the file.
  The question hook, by contrast, fails open: while the registry is broken,
  every session may ask live.

- **After going back to 0.8.2, every session says "Owner console: not
  checked"**: a steward is still set. A 0.8.2 hook reads the `steward` key as
  a malformed registry entry and stops there, so the owner's requests are not
  listed. Run `agent.py --state <state> steward --clear` (with the 0.8.3 kit,
  or delete the `"steward"` line from your registry by hand). Do it BEFORE
  downgrading (`DEPLOY.md`, "Rollback", step 7).

**What it is not:** a security boundary. Every session runs as you, on the
same socket and files, and any session that sets `OVERTURE_AGENT=agent-5`
is the steward. It keeps your own cooperating sessions from racing for the
cursor, and nothing more.

**Why the lock is in `agent.py` and `fold.py`, not the server:** `watch`
reads the doorbell file and writes its heartbeat without calling the server,
`synced` moves the cursor file before its one POST, and the fold reads the
store file directly. A server check would see only that POST, so the check
sits where all three pass.

## Roar is refused (0.8.0)

**"LANE/Q3's lock <id> already had its roar: fork <id>"**: by design, a roar
runs at most once per lock (each costs about six agent runs). Follow up with
chosen seats instead, or supersede the answer and lock it again: the new lock
may have its own roar. A transcript
is refused **"transcript is N bytes; the limit is 49152. It is refused, not
truncated"**: the agent shortens its round summaries and sends it again.

## The suggested-next-step chips look wrong (0.8.0)

The chips are rules, not judgement, and each says its reason (hover, or a
screen reader reads it). `overture/tags.py` holds the exact rules.

- **No refine chip ever**: no `specs_dir` in `.overture.json`, or the locked
  question cites no file under it, or the spec's file time is after the lock.
  The served console reads no git (CONSOLE-kit/Q23), so it always compares the
  file's mtime, and the chip says "the last-commit time is unavailable (no git
  in the server)". A checkout that touches every file (a fresh clone, a
  branch switch) can therefore hide refine chips until the next lock.
- **A drill chip for something a spec covers**: the term is spelled
  differently in the spec (a plural, a hyphen) or is a proper name. It is a
  suggestion; ignore it.
- **No chips at all, and the server log says `console tags: ...`**: the tags
  failed for that page view (a spec caught mid-write, git slow); the page
  still works and the next view tries again.

## An answer shows stale

    python3 <vendored>/agent.py --state <state> check

It names each failed condition and why: the text moved, changed or
disappeared, or a status changed.

- **The cited text is still there but the lock is on a whole-file hash**
  (locks from before 0.5.0):

      python3 <vendored>/agent.py --state <state> reanchor --dry-run
      python3 <vendored>/agent.py --state <state> reanchor

  It writes only what git history supports, and lists the rest with a reason.
  Since CONSOLE-kit/Q23 the server reads no git history, so today it writes
  nothing and every such lock is listed with "git history is unavailable (no
  git in the server)"; the owner's "Still holds: re-lock…" still clears one.
- **The text really changed**: the owner reads "Why stale?" and either
  re-locks ("Still holds: re-lock…") or answers again. Never write a lock or
  anchor by hand.
- **Goes stale after every unrelated edit**: the question hashes a busy file.
  Ask it again citing an `excerpt`.

## The ruling lookup says nothing, or says "committed rulings" (1.52.0)

Before an edit, `plugin/hooks/ruling_lookup.py` adds the owner's rulings on
the file to the agent's context. Ask by hand what it would have said:

    python3 <vendored>/agent.py --state <state> rulings --path src/pay.py

- **It says nothing** when the file has no rulings (that is the usual case),
  when this session was already shown them and they have not changed (a
  would-break warning is still always shown), when the checkout is not in
  your registry (`agent.py register`), when the file is in another
  repository than the registered checkout (a nested repo, a sibling clone),
  when a worktree's `.git` file is not matched by git's back link
  (`<main>/.git/worktrees/NAME/gitdir`; `git worktree repair` fixes a moved
  one), when the server refused the request (a 400 naming why), or when
  anything else failed: it fails open and silent. The command above names a
  path it refuses (absolute, `..`, a secrets file) and the server's refusal.
- **It says "from the committed rulings; the console server is not
  answering"** when the agent socket was absent, took over 1.5 s in all,
  answered 401 or 403 (a stale token: `server.py status`), answered 5xx (a
  crash: its log), or runs a kit older than 1.52 (restart it on the new
  kit). The rulings then come from `.overture.json` `fold.locked` in the
  checkout, so a lock made since the last fold is missing. `server.py
  status` says why the server is down.
- **It says "skipped .overture/locked/X.json: …"**: that committed file is
  not a valid ruling (or is a symlink, or too big) and was left out; the
  rest were read. Export again (`fold.py export`). **"(first 500 ruling
  files)"**: the folder holds more than the lookup reads before an edit;
  `rulecheck.py` still checks them all.
- It never blocks an edit; the CI check (`rulecheck.py`) still guards the
  merge.

## `notes check` names a stale, undeclared or malformed note (1.53.0)

Area notes are the short `CLAUDE.md` files in the folders `.overture.json`
`"areas"` declares. Check them from the checkout, before a release and
whenever the steward's heartbeat counts one:

    python3 <vendored>/agent.py notes check [--memory DIR]

- **stale: AREA/CLAUDE.md (checked SHA): N file(s) changed since**: the
  area's code moved on after the commit the note was checked at. Re-read
  the files it names, correct the note, commit, then stamp it with `notes
  stamp AREA` (only its first line changes; refused while the area has
  uncommitted changes, or when its folder or note is a symlink out of the
  checkout) and commit that.
- **undeclared: X/CLAUDE.md**: a note in a folder not on the list. Fold its
  facts into the nearest declared note, or add the folder to `"areas"`.
- **malformed**: no `<!-- area: AREA · checked: SHA -->` first line, a header
  naming another folder, or more than 10 lines.
- **`--memory DIR`** checks the memory index, not the notes: `DIR/MEMORY.md`
  links a file that is gone, links outside DIR (named, never looked up), or
  a memory file in DIR no line links. Each is a **memory:** line.
- **always loaded: CLAUDE.md** is the repository's top-level file, read in
  every session there: said, never an error.
- **refused: ... declares no areas**: the project has not opted in; the
  steward's watch leaves such a project alone.
- **refused: shallow clone**: the history stops short, so staleness cannot
  be judged. Run `git fetch --unshallow` and check again; the steward skips
  that day's check and says why once.
- **release: refused: the area notes are not current**: `release.py` runs
  the check first and bumps nothing until it passes. The files the version
  bump writes are listed in `.overture.json` `"notes_ignore"`, so a release
  alone never stales a note; re-stamp only a note whose area really changed.

## The fold refuses

The fold is all or nothing: one refused file refuses the lot, and each reason
is named. Always run it from the project root, `--dry-run` first.

| Refusal | Fix |
|---|---|
| `schemaVersion ... is not ...` | export and fold with the same kit version as the store |
| `file name does not match qid` | a file was renamed; export again, never rename |
| `item ... does not resolve to a project item` | the item left the register; restore it, or leave that question unfolded |
| `not locked` | the answer is not locked yet; lock it in the console first |
| `must be a relative path inside the project` | run from the project root; fix `--locked`, `--ledger` or `--adapter` |
| `cannot load adapter` / `lacks ...()` | the adapter file is missing or broken on this branch |

Re-export (`fold.py export --store <state>/store.jsonl --out <dir>`) rather
than editing an exported file.

## Store damaged

`store.jsonl` is append-only. The server checks every line's JSON, schema,
`seq` and `id` on start, and will not start past a bad line. Back it up first,
under the same lock the server writes with:

    systemctl --user stop <name>-console.service
    flock <state>/store.jsonl cp -p <state>/store.jsonl <state>/store.jsonl.bak-$(date +%Y%m%d%H%M%S)

- **`line N has no newline, so a write was cut short`**: a crash mid-write.
  That write was never acknowledged, so its sender retries it with the same
  nonce. Drop only the torn last line:

      n=$(wc -l < <state>/store.jsonl)            # counts complete lines only
      head -n "$n" <state>/store.jsonl > <state>/store.jsonl.new
      mv <state>/store.jsonl.new <state>/store.jsonl
      chmod 600 <state>/store.jsonl

- **`not JSON`, `seq or id does not match the line; the file was edited`**, or a
  validation error on a line: the file was edited or damaged. Do not repair
  lines by hand, since an `id` is a hash of its record. Restore the newest
  backup that loads, and name what was lost after it.
- **`schemaVersion ...; this kit reads only ...`**, or `unknown field(s)`: the
  store was written by a newer kit. Upgrade the kit, and never trim the store
  (`DEPLOY.md`, "Rollback").

Then start the server and confirm:

    systemctl --user start <name>-console.service
    python3 <vendored>/agent.py --state <state> health

## The vendored copy drifted

    python3 <kit-clone>/plugin/kit/tools/verify_vendor.py --kit <kit-clone> --ref <tag> --vendored <vendored>

Each `DRIFT` line names a file that differs from `<tag>`, is not a kit file,
or is missing. Re-copy it from `<tag>` (`DEPLOY.md`, "Upgrade"); a local fix
belongs in the kit repository, as a release.
