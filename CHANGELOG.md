# Changelog

What each overture release added, oldest first. These sections moved
word for word from the README, where each was written as its release
shipped. The README itself describes the kit as it is today.

## A live console (0.7.0)

- **It updates itself.** An open page long-polls the server (`/api/wait`, at
  most 25 s a request, behind the same Access gate), so a new question, reply
  or lock appears without a reload. The poll pauses while the tab is hidden and
  backs off (2 s up to 60 s) when the server does not answer. A box you are
  typing in is never redrawn under you: a note offers "Show" instead.
- **An unread chip** on the Inbox button counts what an agent wrote since you
  last had the inbox open. "Last looked" is kept in this browser's
  localStorage, so each browser keeps its own; a new browser starts at zero.
- **Feed tab**: every question, answer, lock, re-anchor, deliberation request,
  process request, reply and chat message, newest first, filterable by kind and
  by item. Folds and PR merges are not in the console's store, so they are not
  in the Feed.
- **A round is one form.** A deliberation round's questions open as a form, one
  question per step: ←/→ move, 1–9 pick, a comment per question becomes your
  answer's own words. Picks are drafts (kept in this browser) until the review
  page's **Lock all & process**, which locks each and sends one process
  request. If the server would refuse any of them it locks none and says which;
  if a write fails part way, pressing again finishes the rest.
- **Evidence on a question**: rows citing `path:start-end`, with the command
  run and what it printed. The form shows the cited lines as they are now and
  says whether they changed since the question was asked.
- **Chat tab**: a message not tied to a question. It wakes whichever session
  is watching, which answers in the same thread. Six a minute, sixty an hour,
  4000 characters each.
- Progress rings on items and rounds, and gentle transitions; all motion is off
  under reduced motion.

## Next steps, roar and visuals (0.8.0)

- **"Next step ▾"** beside every locked answer and every round's answers
  offers three kinds of fork: **Follow up** (seats you pick, as before),
  **Refine** and **Drill**. Refine and drill run the project's own skill,
  named in `.overture.json`'s `next_step`, on that answer or round. Neither
  writes into the project before you lock: what they find comes back as
  questions, specs land by pull request, and log entries at merge time.
- **Roar** is a seat in the follow-up picker: a three-round panel
  (independent reads, deliberation, synthesis) on one locked answer, **at most
  once per lock**; the server refuses a second on the same lock, naming the
  first, and a superseded-and-re-locked answer may roar again. Its
  transcript (at most 48 KiB, refused whole if larger, never cut) shows
  collapsed on the round and on each question it produced.
- **Suggested next steps**: small chips beside each question and round say
  which step fits and why (the reason is the chip's accessible text):
  *refine* when a locked answer cites a spec under `specs_dir` that has not
  been edited since the lock, *drill* when your own words name something (any
  `backticked` term or Capitalised word, less common words like "The") that
  no spec and no item title mentions (or a proposed item has no spec),
  *deliberate* when an answer
  is stale or went against the ★. The server works them out by rule
  (`overture/tags.py`); they start nothing.
- **Request a visual** on an item: an agent answers with a Mermaid diagram
  (shown as its source text) or a static HTML mock (shown **only** inside
  `<iframe sandbox="">`, served under a `sandbox` Content-Security-Policy, so
  no script in it runs, even opened on its own), plus a short doc. The server
  stores both in its state directory, beside `store.jsonl`, and **never writes
  into the project's working tree** (0.8.1). To land a visual in the
  repository, an agent runs `agent.py visual-export --project <its own
  worktree>`, which copies it under `visuals_dir` there and regenerates that
  folder's `INDEX.md`; the agent then opens a pull request. The checkout the server runs
  from keeps following main with a plain `git merge --ff-only`.

`docs/ADAPTER.md` documents `specs_dir`, `visuals_dir` and `next_step`.

## Several agents, one console (0.8.2)

- **Agent names.** A session may say who it is: `agent.py --as agent-6`, or
  `OVERTURE_AGENT=agent-6`. The console shows the name wherever it shows
  an agent as the author: "asked by agent-6" on a question, on replies and
  chat messages, visuals, roar transcripts and Feed rows. `fold.py export`
  carries it as `asked_by_agent`, so a ruling can say which agent asked. A
  name is 1 to 32 lowercase letters, digits and single hyphens, and anything
  else is refused by name. With no name, everything reads as in 0.8.1.
- **Names live beside the store, not in it** (`<state>/names.jsonl`). The
  store, its records and `SCHEMA_VERSION` are unchanged, so a 0.8.1 kit still
  starts on a store 0.8.2 wrote; it would refuse a record carrying a field it
  does not know.
- **Each agent's own "agent active" marks.** `working` marks are kept per
  name, and a session's `synced` clears only its own. Unnamed sessions share
  one set, as before. The doorbell cursor is still one for all sessions.
- `agent.py visual-export` exits **3** when it wrote files but refused a
  visual (each refusal named), and 1 only when nothing was written. Its
  directory walk holds each folder open as it goes (`O_DIRECTORY|O_NOFOLLOW`
  with `dir_fd`), so a folder swapped for a symlink mid-export cannot redirect
  a write.

## One steward, many sessions (0.8.3)

Owner decision, 2026-09-30: *"Lock + hook others ★"*.

- **The steward.** The doorbell has one cursor, so one session holds it: the
  steward, named in **your own registry**, never by the repository:

      python3 <kit>/agent.py --state <state> steward agent-5     # or: register ... --steward agent-5
      python3 <kit>/agent.py --state <state> steward --clear     # back to 0.8.2: no lock

  It is set on every project registered on that state (several checkouts of
  one project share one console, so they share its steward).
- **Start the steward session with its name in the environment**:
  `OVERTURE_AGENT=agent-5 claude`. Its `agent.py` calls then carry the
  name, and the question hook recognises it. Start the others with names of
  their own (`OVERTURE_AGENT=agent-6 claude`).
- **The lock.** With a steward set, `agent.py watch`, `agent.py synced` and
  `fold.py` (export and fold) refuse, exit 1, any session whose name
  (`--as`, else `OVERTURE_AGENT`) is not the steward's, and the refusal
  names the steward. `ask`, `reply` and `working` stay open to every
  session, named or not.
- **The question hook.** In a registered project with a steward, the plugin
  blocks `AskUserQuestion` in every session but the steward's, and tells it
  the full `agent.py ask` command instead, so its question reaches your
  inbox. The steward may still ask you live, and mirrors each live answer
  to the console (it posts the question and replies with your answer). The
  hook fails open: if it cannot read your registry, the question goes
  through.
- **A guardrail, not a lock against an attacker.** Every session runs as you,
  on the same socket and files; one that sets `OVERTURE_AGENT` to the
  steward's name is the steward. It keeps your own cooperating sessions from
  racing for the cursor, and nothing more.
- With no steward set, everything is exactly as in 0.8.2.
- **Before going back to 0.8.2, run `agent.py --state <state> steward
  --clear`.** Once a steward is set, a 0.8.2 SessionStart hook reads the
  `steward` key as a malformed entry and reports "Owner console: not
  checked" (the owner's requests are not listed) until the steward is
  cleared (`kit/docs/DEPLOY.md`, "Rollback", step 7).

## Name a session from inside it (0.8.4)

- **`/overture:as NAME`.** Type it in a Claude Code session (e.g.
  `/overture:as agent-5`) instead of starting the session as
  `OVERTURE_AGENT=agent-5 claude`, which still works as the fallback. The
  plugin's UserPromptSubmit hook records the session's id against the name in
  `<state>/sessions.jsonl` (mode 0600, rewritten to its newest lines before it
  passes 64 KiB) for the registered project the session works in. The skill
  itself is user-only (`disable-model-invocation: true`): Claude cannot run it.
- **It lasts as long as the session id.** `claude --resume` and `--continue`
  keep the id, so the name; `/clear` and `--fork-session` start a new session,
  which is named again. After `/clear`, forks and restarts the SessionStart
  note says "This session is not named" when the console has a steward.
- **Everything reads it the same way.** The question hook, the SessionStart
  note, `agent.py` and `fold.py` take this session's name as: `--as` (the two
  scripts), then the name recorded for this session, then
  `OVERTURE_AGENT`. `agent.py` and `fold.py` find the session through
  `OVERTURE_SESSION`, which the SessionStart hook exports into the
  session's Bash environment (`CLAUDE_ENV_FILE`).
- **The file only names sessions; your registry still names the steward.** A
  stale or damaged line cannot make a session the steward the registry does
  not name, and never locks the steward out: the last well-formed line for a
  session wins, so typing the command again fixes it, and a file that cannot
  be read gives no name (the hooks then fall back to `OVERTURE_AGENT`).
- **Still a guardrail.** Any prompt submitted in the session fires the hook:
  one you type, or one another plugin's SessionStart hook injects
  (`initialUserMessage`). Claude calling a tool does not.
- **Messages keep their line breaks.** Owner messages and agent replies in an
  item's thread now render their newlines (`white-space: pre-wrap`), as chat
  messages already did. The text is still set as text, never as HTML.

## Back to the inbox, and one lock for many answers (0.8.5)

- **"← Inbox".** An item opened from the inbox has a button back to the inbox,
  which returns focus to that item's row.
- **"Lock all N answers".** An item with more than one answered, unlocked
  question offers one button. It shows every answer it will lock, locks them
  in order, and stops at the first refusal, naming the question and how many
  were locked. The message can be dismissed.

## A usage footer (0.8.6)

- **What it shows.** A thin bar at the bottom of the console: Claude usage for
  the 5-hour and 7-day windows with their reset times, how old that snapshot
  is, and the signed-in account's email. It polls `GET /api/usage` every 45 s
  while the tab is visible.
- **Off unless you ask for it.** The server reads nothing for the footer until
  it is started with `--usage-file` or `--account-file` (absolute paths), and
  a page talking to an older server shows no footer.
- **`--usage-file`** is a status line's usage snapshot (for claude-hud, the
  file named by `display.externalUsageWritePath`): `updated_at`, and
  `five_hour` / `seven_day` each with `used_percentage` and `resets_at`. The
  status line writes it only while a Claude Code session runs, so with none
  open the footer says how old the numbers are, in italics once they pass
  10 minutes.
- **`--account-file`** is Claude Code's settings file. Only
  `oauthAccount.emailAddress` is read from it; the file also holds other
  account details and project history, and none of that reaches the page.
- **Checked, then forwarded.** Both files are read with a size cap, parsed,
  and reduced to those fields; a percentage must be 0-100 and a timestamp must
  carry a time zone. A problem is shown as a short sentence, never as the
  file's contents.

## Claude Code's own status line input as the usage file (0.8.7)

- **No plugin needed.** Claude Code hands its status line command a JSON
  object on stdin; a status line that saves it to a file (for example
  `printf '%s' "$input" > ~/.claude/usage/statusline-latest.json`, written
  through a temporary file and `mv`) makes a usage file `--usage-file` can
  read. The windows sit under `rate_limits`, reset times are whole epoch
  seconds, and there is no `updated_at`: the file's own write time stands in.
  The status line rewrites the file on every redraw, so that time says a
  session is running, not when the limits were last fetched; with no session
  open it goes stale. A write time more than a minute ahead of the server's
  clock is named as a problem, never shown as fresh, and input from before
  the session's first answer (no `rate_limits` yet) says so.
- **Nothing else in it is forwarded.** That input also carries the session id,
  paths and cost; only the two windows and the write time reach the page.
- **claude-hud's snapshot still works.** A file with `five_hour` / `seven_day`
  at the top level is read exactly as in 0.8.6, and only from there.

## Deliberate before answering (0.8.8)

- **A committee before you answer.** A question you have not locked yet has a
  **⑂ Deliberate before answering** button: pick one to three seats, a mode and
  an optional note, and the form shows the cost first (about 100k tokens a
  seat). The round never answers or locks; it replies on the question with
  `Result: ★ <option>` and its reasons, or, only when the seats show the
  options themselves are wrong, posts a replacement question and replies
  `Result: replaced by <qid>`. Roar, refine and drill still need a locked
  answer.
- **One rule for "done".** A deliberation is finished when a `Result:` reply to
  it exists, or, for every kind except a before-answering round, when its
  questions exist, so rounds finished before 0.8.8 stay finished. A progress
  note never closes a round, and a crash between a replacement question and
  its result leaves the round waiting rather than lost.
- **Your picks survive a refresh.** Seat ticks, the other seat and the mode are
  kept across a re-render, in this form and in "Follow up on this answer".

## Slim reads and a cost sidecar (0.8.9)

- **`agent.py todo`.** Prints only what waits for the agent: forks, threads,
  chat, visuals, inbox and seq. It is computed from the view's own rules, so it
  can never disagree with `view`. Measured once on a 116-question console:
  `todo` printed 184 bytes where `view` would have printed 501,167.
- **Narrower reads.** `view --item ID` prints one item and everything under it
  (`@chat` for the chat). `--since SEQ` on `view` and `answers` keeps only
  questions touched after that seq; a later lock or re-anchor counts as a
  touch, and stale questions are always kept. JSON is compact when stdout is
  not a terminal.
- **A 64 KiB cap.** A `todo`, `view` or `answers` read over 64 KiB exits 4,
  prints nothing on stdout, and names the narrower command; `--full` prints it
  anyway. The console skills say what to do on exit 4.
- **Newer client, older server.** `todo`, `view --item` and `answers` work
  against a 0.8.8 server. `--since` refuses in one line until the server is
  restarted on 0.8.9, because it needs a field only 0.8.9 sends.
- **`agent.py costs collect | show --fork ID`.** Reads token usage from Claude
  Code's own transcripts, only this project's, and only the usage, message id
  and agent type, plus the first 64 characters of a subagent's description to
  find its `ck-fork:<id>` tag. Writes `costs.jsonl` beside the store, never
  into it. `collect` is steward-only; `show` only reads. Symlinks are
  refused, and lines and files are size-capped.

## The server starts no git (0.8.10)

- **Why.** Git obeys the repository's own `.git/config`, which an agent can
  write, and some keys make git run a program. The console server runs
  outside every agent's jail, so it no longer runs git at all. A list of
  forbidden config keys was rejected: git has no switch to ignore repository
  config, so a new key would defeat any list.
- **What you see.** Anything git history fed now says "unavailable (no git in
  the server)" rather than going blank. `check` can't show which version a
  whole-file hash was locked against. `reanchor` leaves locks stale and says
  why. Refine chips show a spec's file time in place of its last commit.
  These return once an agent-side step computes and supplies them.
- **How it is held.** Among the modules the server runs,
  `overture/gitseam.py` is the only place a process can be started, and
  the server closes it before reading the project. (`agent.py` and `tools/`
  still run git, in the agent's or the operator's own process; the server
  never imports them.) A test runs the real server under an audit hook and
  fails if any route starts a process. A second test walks the syntax tree of
  every kit module except those named exceptions, and fails on any other way
  to start one.

## Git history returns, from the steward (0.8.11)

- **What returns.** The panels 0.8.10 marked "unavailable (no git in the
  server)": `check` naming the version a whole-file hash was locked against,
  `reanchor`, and refine chips showing a spec's last commit.
- **How, with still no git in the server.** The steward runs git in its own
  process and pushes what it found:

      python3 <kit>/agent.py --state <state dir> history-push

  run from inside the project's checkout. It sends file contents keyed by
  their SHA-256. The server keeps a pushed file only when its hash is one a
  current lock names, checks it again on every read, and works out the diff
  and the cited lines itself. A commit id the steward reports is shown
  "(from the steward)": the server cannot check it.
- **When nothing has been pushed**, or a key no longer matches, each panel
  falls back to the 0.8.10 label rather than going blank.

## The server runs no project code (0.8.11, owner ruling CONSOLE-kit/Q24)

- **Why.** The project's adapter is Python an agent can write. A server that
  imported it ran that code at its next restart, outside every agent's jail.
- **What changed.** The console server never imports or runs the adapter, at
  start or later. The steward runs it in its own process and sends the
  result, as data:

      python3 <kit>/agent.py --state <state dir> items-push --project <project> --adapter <adapter path>

  Run it from inside the project's checkout, with `--adapter` inside that
  project. The command picks its server from the directory it runs in, and
  refuses an adapter outside the project.

  The server checks what arrives against a closed schema (each item is
  `title`, `parent`, `status`; unknown keys are refused). It keeps the last
  push in the state dir, so a restart shows it. The single server and the
  one server (`server.py --all`) take the same push, refuse in the same words,
  and show the same items.
- **What you see.** Until the first push, the inbox says the items appear when
  the steward pushes them. It never shows a blank or invented items. Push
  again whenever the register changes. `--adapter` is still accepted, so an
  existing unit keeps starting, but it is ignored. If the stored items cannot
  be read, the single server still starts. It shows no items, the inbox says
  why, and `health` answers 200 with its register marked "error" until the
  next `items-push` replaces the file.
  The one server refuses just that project.
- **How it is held.** A test runs the real server under an audit hook, with an
  adapter configured whose import leaves a marker. The test fails if the
  server imports, opens, compiles or runs that file.

## The page is a reviewed snapshot you publish (0.8.12, owner rulings CONSOLE-kit/Q28 and Q29)

- **Why.** The server used to read your page from the project's checkout on
  every request and put the console into it. Any agent that could edit that
  file could put a script in your browser, where it could answer and lock as
  you.
- **What changed.** No server reads a page from a project any more: not
  `--page`, and not the one server's `page` entry in `server.json`. The page it
  serves is a snapshot kept in the console's state dir, and only the steward
  writes it, from a commit:

      python3 <kit>/agent.py --state <state dir> page-snapshot --path <page path in the repository>

  Run it from inside the project's checkout, after a `git fetch`. It reads the
  page from `origin/main` (or `--from-ref <ref>`) with git, never from the
  working tree, so an uncommitted or unmerged edit never reaches your browser.
  It refuses a commit that is not in `origin/main`, unless you pass
  `--unreviewed`. On the one server, `--path` defaults to the project's `page`
  in `server.json`. The server checks what arrives (at most 4 MiB, exactly one
  `</body>`, no console block already in it) and keeps it as data. It never
  runs git.
- **You publish it (owner ruling CONSOLE-kit/Q29).** What `page-snapshot`
  sends is only *proposed*: nothing you are served changes. The console shows
  a strip, "Proposed dashboard: <ref> @ <commit> · <size> · reviewed (agent's
  claim, not checked by the server)" (or "unreviewed"), with a preview and a
  **Use this page** button. The page is
  served only after you press it, through a route behind your Access login.
  No agent can publish, because the agent socket has no route that does.
  **The cost is one click per dashboard update.** The button sends the commit
  you were shown. If a newer page was staged after your page loaded, it is
  refused, naming both commits. Reload, look, and press again. Publishing
  checks the page again (size, schema, the console injection). It cannot
  check that the commit is in `origin/main`, because the server runs no git.
  "reviewed" is only what the sending agent's command reported, so judge the
  commit and the preview, not the label. Any process that can reach the
  console's agent socket can replace the staged page, but a press on a page
  that has since been replaced is refused, naming both commits.
- **The preview never runs the proposed page's scripts.** It is shown in an
  `<iframe sandbox="">` with no allowances. The route it loads from also
  answers under its own `sandbox; default-src 'none'` policy, the one stored
  visuals use. Each layer alone stops the page's scripts, so the preview shows
  the page's markup and styles, never its behaviour. Its scripts first run
  when you publish it.
- **What you see.** A line at the end of the page names where it came from:
  "Dashboard page from origin/main @ <commit> (staged by the steward,
  published by you)", or "(staged from an unreviewed ref, published by you)"
  for a page sent with `--unreviewed`. Until you publish one, the server
  serves the console alone, with a note saying to run `agent.py page-snapshot`
  and then press **Use this page**. The console works either way. Your
  page's own scripts still run once published. Stage and publish again
  whenever the page's merged version changes. `--page` is still accepted, so
  an existing unit keeps starting, but it is never read, and the server logs
  one line saying so.
- **How it is held.** A test runs the real server under strace with `--page`
  naming a page in the project, and with it naming a symlink to a page
  outside. No system call names either path. Another test edits the page in
  the working tree, stages it and runs `page-snapshot` again, and the edit
  never reaches the page served. A test drives every agent route, and none
  changes the served page. A browser test shows that the proposed page's
  script does not run in the preview and does run once published.

## Settling a stale answer (0.8.13, owner rulings CONSOLE-kit/Q30, Q31 and Q32)

- **Why.** A stale answer used to have one way out: re-lock it as it stands.
  A ruling that no longer applies, one whose anchor was the wrong check, or
  one that needs a new question stayed in the inbox for good.
- **What you can do now.** Each act is yours alone, and each works only on a
  stale answer. On anything else it is refused, naming why.
  - **Withdraw…** says the ruling no longer applies. It leaves the inbox and
    reads *withdrawn*, with the reason you give. A reason is required.
  - **Keep, stop checking…** says the ruling stands but is no longer checked
    against the files. It leaves the inbox and reads *locked*, with a note
    saying it is no longer checked. A reason is optional.
  - **Confirm a proposed anchor.** The steward may propose new lines that the
    ruling depends on (`agent.py propose-anchor QID --cite PATH:A-B --basis
    TEXT`). The server reads those lines itself, so the steward names lines and
    never supplies the text. The banner shows what failed beside what is
    proposed. Nothing changes until you press **Confirm**. The server reads the
    file again at that moment, and a proposal that no longer holds is refused,
    naming why. The steward never re-anchors a ruling to a passage it chose.
    (`agent.py reanchor` is unchanged.) A proposal may hold about 40 KB of
    text, so whole `view` and `answers` reads name it by its cites and a
    digest. `view --item` and your page show the text.
  - **Replace.** The steward asks a new question with `"replaces": "<old
    qid>"` in its file. The old ruling stays in force, still stale and linked
    to the new question, until you lock the new one. Then it reads
    *superseded*. One open replacement per ruling. If the question is stored
    but its link is not, the ask fails naming its `nonce`. Sending the same
    ask again with that nonce writes the link, while nobody has answered it.

  Neither withdraw nor keep is a default; the page offers both side by side.
- **Nothing is deleted.** These acts are written to `refactor.jsonl`, beside
  `store.jsonl` in the console's state dir. The store is not changed, and the
  old lock, answer and anchor stay readable. Every act names the lock you were
  shown. A page loaded before a re-lock is refused rather than settling a
  ruling you never saw.
- **The fold records each outcome.** The export carries `outcome` (withdrawn,
  untracked or superseded, with who, when, and the reason or the replacing
  question), and `replaces` on a replacement. fold passes the entry to the
  adapter again when an outcome arrives for a lock it already folded. An
  adapter that does not declare `RECORDS_OUTCOMES = True` is refused such an
  entry and nothing is folded, so a ruling never silently vanishes from your
  project's record. The starter `adapter_template.py` declares it. To update
  an existing adapter, see `docs/MIGRATION.md`.
- **New asks: no whole-file hash where an excerpt fits.** Most answers that go
  stale were anchored to a hash of a whole file that kept changing. A new
  question is refused a `file_sha256` check when its `source` or an evidence
  cite names lines of that same file (the refusal shows the `excerpt` to use
  instead), and on any file over 100 lines. Questions already in the store
  are not affected.
- **If `refactor.jsonl` is damaged** (an edited or torn line, a link, not a
  plain file), the console keeps running and names the problem on the page.
  Withdraw, keep, confirm, propose and replace are refused until the file is
  fixed or moved aside, and every answer reads as if the file were empty, so a
  settled answer reads stale again, never fresh.
- **Rolling back.** An older kit never opens `refactor.jsonl` and reads the
  store as it always did. Every withdrawn, kept or superseded answer reads
  stale again, and every confirmed anchor reads as the old anchor. Nothing is
  lost. Upgrade again and the outcomes return.
- **How it is held.** A test drives every agent route with each act's body,
  and no answer's state changes. Another shows a proposal confirmed after its
  file changed is refused. A test moves the sidecar aside and the answer reads
  stale. A test shows fold refuses an adapter without `RECORDS_OUTCOMES`.

## Skills the plugin ships (0.8.13)

The plugin carries the skills the console's rounds lean on, so a fresh
install needs nothing else: **`roar`** (a three-seat panel on the plugin's
own `overture:architect`, `overture:ux` and `overture:other` sitting
as advisor), **`refine`**, **`drill`** and **`deliberate`**. Run them as
`/overture:roar` and so on. Onboarding now writes `next_step` as
`{"refine": "overture:refine", "drill": "overture:drill"}` when a
project names none; a project's own entry is kept. Inside a console round
none of them writes into the project before the owner locks. The lookup's
trust rules are unchanged: installed user or plugin skills only, never a
skill inside the repository.

## Pull requests on the console (0.8.13)

- **What you can do.** The inbox has a **PRs** tab: the project's open pull
  requests first, then those merged or closed in the last 30 days. Each shows
  its number, title, branch, author, checks (pass, fail, running or none), a
  draft badge, and when it was opened, merged or closed, and links to the PR
  on GitHub. A title or branch that names an item or a question the console
  knows gets an **Open** button for that item. A line says when the steward
  last pushed the list, so a stale list reads as stale.
- **How, with no GitHub call in the server.** The steward runs `gh` in its
  own process and sends the result, as data:

      python3 <kit>/agent.py --state <state dir> prs-push

  run from inside the project's checkout (`--days`, default 30; `--limit`,
  default 50 of each list). The server checks it against a closed schema:
  unknown keys, more than 200 PRs, a title over 1024 characters, a branch
  over 255, and any link other than that PR's own
  `https://github.com/<repo>/pull/<number>` are refused by name. It keeps the
  last push in the state dir (`prs.json`), stamped with when it arrived and
  which agent sent it. Only the agent door takes a push; the owner door can
  only read it. Titles and branches are shown as text, never as HTML.
- **Before the first push** the tab says the steward has not pushed pull
  requests yet. It never shows a blank or invented list.
- **Not in the Feed.** The Feed lists the console's own records, paged by
  their sequence number; a pull request has none, so the Feed's footer points
  to the PRs tab instead.

## Footer version and the stale-board bar (0.8.14)

- **The footer names the kit version** (owner, 2026-10-01: "version number
  should be in footer"). It reads "overture 0.8.13", say, taken from the
  page's config, which the server fills from `overture.__version__`: the
  same value `/health` reports, never typed into `console.js`. It shares the
  usage footer's bar, so the page keeps one bottom bar that already makes
  room for itself, and the bar now shows even when the usage footer is off or
  has nothing to say. It is set as text, never markup.
- **The stale-board bar no longer offers Reload** (owner, 2026-10-01: "the
  'board has changed since page loaded' message is not going away"). The page
  is a published snapshot, so a reload served the same page and the bar came
  straight back. It now says the dashboard has changed since the page was
  published, so its live numbers are paused, and names what fixes it: when a
  page is staged and waiting, the proposal's "Use this page", with a button
  that takes you to it; otherwise the steward staging a new page
  (`agent.py page-snapshot`). It stays a status message fixed at the bottom
  and cannot be dismissed, because polling has stopped and it is the only
  sign the numbers on the page are frozen.

## Reviewing a new dashboard page in a dialog (0.8.15)

- **A staged page is reviewed in a modal dialog** (owner, 2026-10-02: "can
  you create a modal rather than place on bottom (button hides under
  header)"). The proposal is no longer a strip at the end of the page. A
  small button fixed at the bottom-left, "New dashboard page waiting ·
  Review", shows whenever a page is staged. It sits above the host page's
  sticky header in the stacking order and away from the top edge, so no
  header covers it at any scroll position. When the stale-board bar is also
  showing, the bar moves up to sit above it.
- **The dialog** is a native `<dialog>` opened with `showModal()`, so focus
  moves into it and stays there, Esc closes it, and the page behind gets a
  backdrop. It is named by its heading, and focus goes back to the button
  that opened it. It shows the ref, commit, size and provenance line, the
  same sandboxed preview (`<iframe sandbox="">` on `/api/page-staged`, under
  the same CSP, unchanged), **Use this page** and **Not now**. It fades and
  scales in only under `prefers-reduced-motion: no-preference`.
- **It never opens by itself.** It opens only from the waiting button or the
  stale-board bar's button, now named "Review the new page". Opening it,
  closing it and pressing Esc publish nothing. Publishing is still only
  **Use this page**, through the same `POST /api/page-publish` with the
  commit the page showed, so a page staged after the owner looked is still
  refused by name.
- **Without the console script** the proposal is still shown. The server
  renders the dialog without `open`, and until `console.js` marks it ready,
  the stylesheet lays it out inline at the end of the page, as the strip
  was. The waiting button and "Not now" stay hidden there, because they
  would do nothing without the script.

## A calmer inbox (0.8.16, owner rulings CONSOLE-kit/Q33 to Q38)

- **One tap locks, after a countdown you can undo.** Tapping Lock starts a
  short visible countdown with an Undo button; nothing is sent at the tap. The
  countdown is cancelled, and the Lock button comes back, on Undo, on opening
  another question or item, on closing the panel, on hiding the tab and on
  leaving the page (including a page kept in the back-forward cache).
- **A pick moves you on.** After a single-choice pick the form moves to the
  next question you have not answered, and says so. It never moves on a
  multi-choice question, while you walk the options with the arrow keys, or
  past the last step.
- **Answer together.** Questions one named agent asked about one item within
  a few minutes are shown as a group. Locking the group still goes through
  your own answer and lock, one question at a time, then sends one process
  request; if one is refused it stops and says "Locked k of n".
- **A send bar you can always see.** Once answers are in, a "send to agent"
  bar appears as a row under the item panel's header, and the panel sits
  above the page's own sticky header, so nothing covers it. It comes from the
  data, so it returns when there is something to send.
- **Locked answers roll up** to one line (question, pick, state); open the
  line for the rest. A stale answer stays whole.
- **Motion** (panels sliding, rows settling) runs only under
  `prefers-reduced-motion: no-preference`.

## Smaller fixes (0.8.16)

- A retry that reuses a nonce but names a different `replaces` (or none) is
  refused by name (409), instead of being taken as the earlier ask. An
  identical retry still succeeds. One case cannot be checked: when the
  earlier ask's link was never written, nothing kept the `replaces` it named,
  so the retry's link is written as the recovery.
- The slim read's pointer says what it left out and names the reads that
  print it: `view --item X` or `answers --item X --json`.
- The unit template no longer passes `--page` or `--adapter`; the server read
  neither. Units installed earlier still start: both flags are accepted and
  ignored.

## Scan for a resolve (0.8.17, owner rulings CONSOLE-kit/Q40 and Q41)

- **Ask the steward to look again.** Every stale answer has a **Scan for a
  resolve** button, and the inbox has **Scan all stale (N)**. A press asks the
  steward to find out whether the ruling still applies: where its cited text
  went, whether its premise still holds, and what replaced it. "Scan all" is
  one request naming every stale ruling at the moment you press it; one that
  went stale after the page loaded is refused by name rather than missed.
- **One scan at a time.** While a scan is open the buttons give way to its
  status ("Scan asked …: k of n rulings still wait"), and a second scan is
  refused, naming the open one.
- **The steward answers each ruling one way:** a proposed new anchor (old and
  new side by side, as before), a replacement question, or new **advice**: a
  ★ Withdraw or Keep recommendation with its evidence, shown beside your own
  Withdraw and Keep buttons. Nothing changes until you press one of them; the
  steward proposes, you decide.
- **A scan is done when records say so, never the files.** Each ruling is done
  once the steward answered it after the scan, or you settled it (withdraw,
  keep, confirm, a replacement, a new answer or a re-lock). A done scan never
  reopens. A ruling whose cited text came back while the scan was open still
  gets an answer: the steward may advise on it (most often Keep), but only
  while that scan is open and waiting on it.
- **Where it is kept.** Scans and advice are two new record kinds in
  `refactor.jsonl`, beside the other stale-answer records; `store.jsonl` is
  untouched, so an older kit still starts on the same state. An older kit
  reads `refactor.jsonl` as unreadable, so it shows every settled answer as
  stale again until it is upgraded. Nothing is lost on disk.
- **For the steward:** `agent.py advise QID --star withdraw|keep --evidence
  TEXT`; a scan rings the doorbell, and `todo` lists open scans with what each
  still waits on. A scan's doorbell line carries `rx`, the refactor seq, and
  keeps waking `watch` until `synced --rx-through RX`. The console-process
  skill's step 4b says how to answer one.

## Every stale answer reaches the inbox (0.8.18)

- **A stale answer from a deliberation round now has its own inbox row.**
  Before this, a locked answer that came out of a round and later went stale
  was still filed under that round. A round lists only the questions still
  waiting for an answer, so the stale one showed as "0 questions", and its
  stale banner and **Confirm** button could only be reached from the item
  page. A question now goes under its round only while it is open; otherwise
  it is an ordinary row that opens its card.
- **Rows say which question and what waits.** A stale row shows the question
  number (the full id is in its title and its accessible name) and says when
  "a new anchor is proposed" or "advice is waiting". Two stale answers on one
  item no longer look the same. Clicking a row scrolls to that question's card.
- **"Answer these together" groups open questions only**, so a stale answer
  is never offered inside a group whose form would skip it.
- Rounds, their forms, the server and the store are unchanged.

## Rendered visuals, favorites, direction in the inbox, and charting (0.9.0)

- **Mermaid visuals are rendered as diagrams**, inside an iframe the console
  grants `allow-scripts` but NOT `allow-same-origin`: the vendored lib runs in
  an opaque origin, so it cannot touch parent cookies, storage or network. The
  response's own CSP allows only the vendored `/api/mermaid.js` and the init
  script that carries the request's nonce. **View source** still shows the raw
  `.mmd`. HTML mocks keep their earlier, scripts-off sandbox.
- **A visual drawn by an agent surfaces at once.** A short chime plays, the
  item appears at the top of the Inbox under **New visuals** with a ◫ badge,
  the Feed row says "Visual drawn", and the unread count rises until you look.
  The badge is seq-gated per browser, like unread elsewhere.
- **Favorite tab** (between PRs and Chat). Tap ☆ on a visual, on the item
  view's title bar, or on an Inbox row to star it. The tab lists starred
  visuals grouped under their items. Favorites are per console (not per
  browser), kept in `STATE/favorites.json`; only the owner door writes to it.
- **Direction stays visible in the Inbox.** Each item with open questions
  carries a collapsible "N answered on this item" under its rows, listing the
  last few locked rulings with the picked option. Items whose questions are
  all locked within the last 24 hours stay on the list under **Recently
  answered**, so what was asked and what you answered sit side by side without
  leaving the Inbox.
- **A Back control at the top of every item view.** The ← Back button no
  longer hides at desktop widths, so **discuss** from the dashboard always has
  a one-tap way home.
- **Status flowchart on every item** (collapsible). The server builds a
  Mermaid flowchart from the item's own questions, rounds, `forked_from`,
  `supersedes` and `follow_up_of`: the item at the left, question nodes
  state-coloured, round nodes shaped apart, dotted edges where a newer
  question supersedes an older one or a round follows up. Lazy-loaded; up to
  40 questions shown, past that an ellipsis names how many more exist.
  Served through `GET /api/item-chart?item=X`, same sandboxed Mermaid frame
  as `/api/visual-render`.
- **Nodes click back.** A chart node emits `postMessage` from inside its
  sandboxed iframe; the parent scrolls to that question's card (opening the
  item first when the owner is not already in it), or opens an item when it
  is an item node. Mermaid runs at `securityLevel: 'antiscript'` for charts,
  so the text in nodes is still sanitised but `click` directives fire.
- **Project map** on the Inbox tab (collapsible, above every other section).
  `GET /api/project-chart` builds a tree of every item, parent → child, with
  each node coloured by its own questions' roll-up (awaiting_you > stale >
  unlocked > locked > nothing) and a short tally like `? 2 · o 3`. A chip row
  above it narrows the map to one state (`?state=awaiting_you|stale|unlocked|locked`
  on the endpoint); ancestors of matching items are kept, drawn muted, so the
  tree stays connected.
- **Clicking a chart node focuses the card**, not just scrolls: tabindex is
  added when missing so keyboard follow-through lands where the pointer did.
- **Save SVG** on every chart and every Mermaid visual. The iframe serialises
  its rendered SVG and posts it back to the parent, which triggers a plain
  browser download (`item-foo-chart.svg`, `project-map.svg`,
  `project-map-stale.svg`, `visual-<rid>.svg`). No same-origin needed; nothing
  reaches the server.
- **Documentation.** The README now has a **Windows + WSL2** section covering
  the CRLF trap (`core.autocrlf`), the `origin/main` default in
  `page-snapshot`, the leading-dot page path, the first `items-push`, reaching
  the agent socket from Windows, and `loginctl enable-linger`.

## Code fixes for the Windows + WSL2 workarounds (0.9.1)

Follow-up to 0.9.0: the README notes stay useful, but a fresh install no
longer needs any of the workarounds they describe.

- **`.gitattributes` pins LF.** Every text file ships as LF everywhere;
  `*.sh`, `*.in` and `*.py` are explicit so `install.sh` and the systemd
  unit templates do not pick up CR on a Windows checkout (`core.autocrlf`
  default). The committed blobs already were LF; this makes the working-tree
  guarantee explicit, so a WSL copy from the plugin cache no longer needs
  the dos2unix dance.
- **A dotfile page path is accepted.** `serverfile.PAGE` now allows a
  single leading dot on the first path segment, so `.overture/page.html`
  (the onboarding default) passes. `.`, `..`, `./foo` and empty components
  are still refused by `_page_problem`.
- **`page-snapshot` reads origin's default branch.** `--from-ref` defaults
  to the ref `git symbolic-ref --short refs/remotes/origin/HEAD` returns
  (`origin/main`, `origin/dev`, `origin/claude/foo-bar`, …), with
  `origin/main` as the fallback when that is not set. The error messages
  and `--unreviewed` wording follow suit. A project whose default branch is
  not `main` no longer needs `--from-ref HEAD --unreviewed` just to bootstrap.
- **`items-push` is called out.** `onboard.py` printed next-steps now
  include an `agent.py … items-push --adapter …` line (step 6), and the
  server's refusal when a write names an unknown item names the push to
  run. The brief defect "item X is not in the project's item list" without
  a next-step is gone.

## Fix /health version drift and automate the bump (0.9.2)

- **`overture.__version__` is in step with VERSION again.** Across 0.9.0
  and 0.9.1 the package's `__version__` stayed at `0.8.18`, so `/health`,
  the dashboard footer, and the `overture` block the server embeds all
  reported the wrong version. The code itself was 0.9.1; only the label
  lied. 0.9.2 brings every version-holding file into sync and reports
  `0.9.2`.
- **`release.py <version>` bumps all four files in one shot.** `VERSION`,
  `plugin/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
  and `plugin/kit/overture/__init__.py` are updated from one invocation,
  so the next release cannot drift. `test_build.py::LayoutTests` already
  asserts the four stay equal; the script just makes passing that test the
  default.

## Scaffold a dashboard, keep it live (0.9.3)

- **`agent.py scaffold-dashboard`** writes a working dashboard page and
  injects a matching `board()` into the project's adapter. The page carries
  Header / Items / Rollout / Engine / Spec / Footer sections, each wrapped
  in `<!-- scaffold:<name> start/end -->` markers so re-running adds
  missing sections without clobbering hand edits. Items / Rollout / Footer
  use `data-live="..."` attributes so values refresh from the adapter's
  `board()` without a new snapshot. The sections mirror the shape a
  mature console (dashboard, rollout, engine, spec) uses, so a fresh
  install does not look bare.
- **`agent.py items-watch`** polls the project's adapter,
  `.overture/items.json`, `.overture.json` and any extra `--watch`
  paths and re-runs `items-push` whenever any changes. A plain stat loop
  (no file-watcher dependency); `--interval` clamps to 1..300 s. Pair
  with the scaffolded `board()` to keep the dashboard fresh "as the
  project evolves".
- **New plugin skill** `scaffold-dashboard` so an agent can offer the
  scaffold on an onboarded project.
- **`docs/ADAPTER.md`** gains an "A live board" section covering `board()`,
  the `data-live-*` contract, and the three fresh-keeping patterns:
  manual push, `items-watch`, or a git `post-commit` hook.

## Marketplace manifest schema + install/upgrade notice (0.9.4)

- **`.claude-plugin/marketplace.json`** moves the marketplace description
  from `metadata.description` to top-level `description`, matching the
  shape `build_zip.py` has emitted for the zip-marketplace since 0.8.12.
  Users on the GitHub-source install (`/plugin marketplace add
  MikeHeid/overture`) can now actually upgrade: Claude Code reads the
  top-level `description` as the spec expects, so `/plugin marketplace
  update overture` picks up the new version and Desktop ungrays Update.
- **A one-time install / upgrade notice**, printed by the SessionStart
  hook the first time a session runs in a registered project after a
  version change. A short banner followed by the commands most useful at
  that moment: `items-push`, `items-watch`, `scaffold-dashboard`,
  `page-snapshot`, `prs-push`, `inbox`. The last-seen version is kept in
  `STATE/last_seen_kit_version`, so the note prints once per project per
  bump.

## Fix 'Mermaid is not defined' in the sandboxed iframe (0.9.5)

- **The vendored lib's `<script>` tag now carries the per-request nonce**
  as well as `src="/api/mermaid.js"`. In an iframe sandboxed with
  `sandbox="allow-scripts"` but no `allow-same-origin`, Chrome rejects a
  `script-src 'self'` match because the document's effective origin is
  opaque, so the lib never ran and `mermaid.initialize` fell into the
  "Mermaid failed to load: mermaid is not defined" fallback. The nonce
  path is honoured whichever way the browser resolves `'self'`.
- **Init is gated on the lib's `load` event** so a slow fetch never races
  ahead of `mermaid.initialize`, and the error UI now names the file to
  check (`plugin/kit/overture/vendor/mermaid.min.js`) rather than only
  the exception.

## Fix Mermaid rendering as text, not SVG (0.9.6)

- **The DOM scan is now explicit.** Mermaid v10's `startOnLoad: true`
  only hooks `DOMContentLoaded`, which has already fired by the time our
  `load`-gated init runs; `<pre class="mermaid">` then stayed as text
  on the Project map, the item Status flowchart, and every rendered
  Mermaid visual. The shared `_mermaid_wrapper` now passes
  `startOnLoad: false` and calls `mermaid.run()` after `initialize`, so
  the diagram renders whether the lib arrives before or after the DOM
  is parsed. Any render error from `mermaid.run()`'s promise is caught
  and surfaced in the same error UI.
- **The wrapper iframes get a real stylesheet** served from
  `/api/wrapper.css` (with the per-request nonce on the `<link>` tag,
  so the sandboxed iframe can load it even when Chrome refuses
  `style-src 'self'`). It matches the console's palette, honours
  `prefers-color-scheme`, caps `.mermaid svg` width to the iframe, and
  tightens the Save SVG button. One stylesheet backs all three
  wrappers — visuals, item chart, project map — so editing it changes
  every rendered diagram at once.

## Fix: Access blocked Mermaid + CSS subresources (0.9.7)

The chart iframes stayed as unrendered text and the new 0.9.6 styles did
not apply. Root cause: an iframe sandboxed with `sandbox="allow-scripts"`
but no `allow-same-origin` has an **opaque origin**, so its subresource
requests (`/api/mermaid.js`, `/api/wrapper.css`) go out WITHOUT the
parent's Cloudflare Access cookies. Access challenged every one of them,
the iframe could not follow the login redirect, and both loads died
silently. Hard refresh didn't help because the top-level wrapper HTML
loaded fine — it was its own navigation and carried the cookie.

- **The vendored `mermaid.min.js` and the wrapper CSS are now inlined**
  into the wrapper HTML (nonce-protected). No subresource requests, so
  no Access challenge. CSP tightens to `script-src 'nonce-...'` and
  `style-src 'nonce-...' 'unsafe-inline'` (the `'self'` legs were only
  useful for the subresource pattern that is gone).
- The response is ~3.3 MB per iframe (the lib dominates). The parsed JS
  is cached in-process (`_mermaid_js_bytes`), so disk is hit once per
  server lifetime, not per request.
- `/api/mermaid.js` and `/api/wrapper.css` endpoints stay for direct
  debugging and for any caller same-origin to the console.
- Defensive escape: `</script>` and `<!--` inside the inlined lib are
  replaced with their JS-safe forms; the current lib has neither, but a
  future bump might.

## Fix: Cross-Origin-Resource-Policy blocked everything served to a sandbox (0.9.8)

0.9.7's inlining dodged the subresource problem for Mermaid, but every
raw response (`_send_raw`: visuals, charts, mocks, the inlined wrapper
HTML itself) carried `Cross-Origin-Resource-Policy: same-origin`. A
sandbox-opaque-origin iframe is not same-origin to the server, so the
browser refused the response with a CORP violation — the same symptom
family as the Access-cookie trap: subresources silently fail to render.

- `_send_raw` now sets `Cross-Origin-Resource-Policy: cross-origin`.
  These responses are specifically designed to be consumed by sandboxed
  iframes with opaque origins; the data (static Mermaid wrapper HTML,
  inlined lib, inlined CSS, stored visuals the owner requested) is not
  sensitive, and the Cloudflare Access tunnel still gates every byte at
  the perimeter.
- JSON responses (`_send`) keep the default and remain protected: they
  carry the owner's view data and are only consumed by the same-origin
  top-level page.

## Dark theme fallback, loading bar, pan + zoom on charts (0.9.9)

- **`console.css` carries a fallback palette** inside `@layer
  console-fallbacks`, so a dashboard page that does not define
  `--c-fg`, `--c-surface`, `--c-border` etc. still renders the console
  with visible text, surfaces, borders and hovers. A
  `prefers-color-scheme: dark` block covers OS-dark users: before, the
  console panel on a dark host looked all black because every token
  resolved to transparent. The host page's own `:root` (unlayered)
  continues to win because unlayered rules beat layered rules in the
  cascade, so no project with its own tokens is affected.
- **A loading bar replaces the flash of unrendered Mermaid source.** The
  `.mermaid` element stays `visibility: hidden` until Mermaid flips it
  to `data-processed="true"`; a thin animated bar + "Rendering…" label
  sits in the viewport until `mermaid.run()` resolves, then hides.
- **Pan + zoom on every Mermaid wrapper.** The diagram lives inside a
  `.ck-stage` viewport with a `.ck-pan` transform wrapper. Mouse wheel
  zooms toward the cursor; drag pans; `+` / `−` / reset buttons sit in
  the wrapper bar. Reset returns to centred, scale 1. Clickable chart
  nodes still fire their click handler because the drag threshold is
  pointer-based and routes clicks through `click` directives first.
  Reduced-motion viewers get no animation on either the loading bar or
  the pan transition.

## Fix: a re-anchor proposal could never be confirmed when a kept excerpt went non-unique (0.9.10)

Reported from a user project (AB-findanchors/Q1, lock `3f1e5e31…`): a
ruling with two excerpts went stale because excerpt #1 was removed; the
steward proposed a new anchor for #1; `propose_anchor` kept excerpt #2
(still holds) in the proposal; Confirm 409'd forever because excerpt
#2's text had become non-unique in its file (3 occurrences). The owner
had no path to re-anchor and had to use `advise --star keep`.

- **`proposal_problem(anchors, tree, strict_excerpts=None)`** gains a
  `strict_excerpts` parameter. When set, exactly-once is enforced only
  on the excerpts in that list (the steward's newly cited anchors); any
  carried-over condition is checked by `tree.holds()` only, matching
  its lock-time invariant. `_confirm_check` computes
  `strict_excerpts = proposal.anchors - proposal.base`, so kept
  conditions can be ambiguous without blocking the confirm. The default
  (no `strict_excerpts`) preserves the old exactly-once-everywhere
  behaviour for other callers.
- **The owner now sees the 409 message in the UI**, not just a silent
  "409 conflict". `renderProposal`'s Confirm button shows the server's
  refusal in an inline alert below itself, in addition to announcing it.
  Styled with the kit's blocked tokens so it stands out against the
  normal confirmation box.

## Lane-board palette alignment and complete tag coverage (0.9.11)

0.9.9 shipped fallback tokens so the console rendered on a host page that
defined no `:root` custom properties. 0.9.11 brings the fallback values
in line with a mature lane-board palette (GitHub Primer family), adds
the tokens the lane board uses but the kit was missing, and completes
the tag styling for every state the view emits.

- **New / changed fallback tokens** (inside `@layer console-fallbacks`):
  `--c-bg` surface warmed to `#f4f6f8`; `--c-accent` → `#0969da`;
  `--c-open` → `#57606a` (muted gray, not accent blue — tags for an
  item in "proposed/open" no longer compete with the accent).
  **New**: `--c-deferred`, `--c-deferred-bg`, `--c-bar-bg`,
  `--c-bar-fill`, `--tree-line`. `--radius-sm` → `6px`, `--radius-md`
  → `10px`. Dark values follow the Primer dark theme. `color-scheme`
  declared on `:root` so native scrollbars and form controls match.
  A `:root[data-theme="dark"]` block honours an explicit toggle too.
- **Status chips now cover every state the view emits.** Previously
  only `awaiting_you / unlocked / locked / stale / agent_active /
  visual` had colour; `awaiting_agent / withdrawn / superseded`
  inherited the base chip look and were hard to tell apart.
  `awaiting_agent` picks up the accent-tint; `withdrawn` and
  `superseded` use the new `--c-deferred` pair.
- **The Mermaid wrapper CSS** mirrors the same palette (`--wrap-*`
  tokens), so an opened chart iframe looks consistent with the console
  panel in both light and dark.
- A host page's own `:root` still wins (unlayered rules beat layered),
  so projects that already define Primer-aligned tokens see no change;
  projects that define a different palette see their own values.

## Dashboard section links, Direction strip, immediate lock (0.9.12)

- **Dashboard section links.** `.overture.json` gains an optional
  `sections` map: `{"AB-2": ["#features/rollout", "#features/timeline"]}`.
  Each item id maps to one or more `#anchor` fragments on the dashboard
  page. The item view renders them as "Dashboard: #features/rollout →"
  chips that break out of the console frame to the dashboard page. Up
  to 16 anchors per item; schema refuses bad shapes by name at server
  start. The server does not resolve them against the page HTML — it is
  pass-through.
- **A `[data-ck-item="X"]` on the host page gets a live badge** injected
  by `console.js` on every live wake: `"X  ◐ 2  ◑ 1  ◌ 3  ○ 4"` (short
  tallies by state). Click the badge to open the panel on that item.
  The badge updates in place on each live wake.
- **Direction strip under each question's text.** Four kinds of chip,
  each wearing a direction glyph: `↑ from round <id>` (forked_from),
  `← supersedes <qid>` (what this ruling replaces), `→ superseded by
  <qid>` (what replaced it), `↳ <path>` (every file an evidence row
  cites, de-duplicated). The supersedes/superseded-by chips are
  clickable and scroll to that question's card in the panel. All
  chip data is already in the view JSON; no new endpoint.
- **The 5-second lock countdown is gone.** `Lock this answer` now sends
  immediately. The countdown apparatus (`renderLockCountdown`,
  `tickLock`, `setCountdown`, `undoLock`, `sendLock`, `pendingLocks`,
  `.ck-lock-countdown` CSS) is removed; `dropAllLocks` /
  `dropLocksNotOnShow` are no-op stubs so the existing pagehide /
  visibilitychange listeners don't need changing. Server-side
  lock-processing is unchanged.

## Auto-insert item sections into the dashboard tree (0.9.13)

- **`agent.py sync-dashboard --page <path>`** inserts a
  `<details id="item-X" data-ck-item="X"><summary>…</summary></details>`
  stub into the dashboard page for every item not already there, nested
  under its parent via per-item `<!-- ck:item X start/end -->` markers
  with a `<!-- ck:children X -->` insertion point inside each parent's
  `<details>`. Idempotent: re-runs only add new items, and hand-edits
  inside each node survive.
- **`agent.py items-push --sync-dashboard <path>`** chains the two
  steps so new lanes/phases/waves land on the dashboard in the same
  command as the push. The agent still commits + runs page-snapshot;
  no server-side mutation of the project.
- Items whose parent is not (yet) in the tree are inserted at the top
  of the ck:items block. Smoke-tested: 5-item tree with grandchildren,
  idempotent re-sync, add-child-under-existing-parent, hand-edit
  preservation, and orphan placement.

## Zoom-in further, drag anywhere, inbox default open, README updates (0.9.14)

- **Mermaid wrappers**: zoom clamp raised to 0.1x..20x so you can
  browse into a dense diagram. Drag now works anywhere in the stage
  (nodes included); a 5px click-vs-drag threshold means a tap on a
  node still fires its handler, and a drag that reaches the threshold
  swallows the next click so the pointer-up doesn't trigger a
  navigation you didn't ask for.
- **Inbox opens by default on docked (wide) screens** after the first
  view loads. Closing the panel once sticks for the session
  (`sessionStorage: ck-inbox-closed`).
- **README additions**: a "Name the session, bootstrap the dashboard"
  section with `/overture:as`, the full `scaffold-dashboard →
  sync-dashboard → page-snapshot → items-watch` chain, and the CSS
  custom-property surface for re-skinning. A new "Hooks the plugin
  ships" section documents `SessionStart` (the doorbell),
  `UserPromptSubmit` (`name_session.py`) and `PreToolUse`
  (`ask_guard.py`). Replaced the stale "undo for five seconds" bullet
  to match 0.9.12's immediate lock.

## Delegate — orchestrate from the Inbox (0.10.0)

The owner can already start a round, request a visual, or send a chat
from the item view. 0.10.0 makes the same primitives one click from
the Inbox header, so orchestration doesn't require opening an item
first. A collapsed **⚑ Delegate** bar above the tabs expands into a
quick form: pick kind (round / visual / chat), target item, mode +
focus (for rounds), and a free-text brief. Submits to the existing
`/api/message` endpoint — no new server routes.

This is step 1 of the "ultimate web orchestrator" arc. On deck:
0.11 playbooks (codified multi-step delegations), 0.12 triggers
(cron + webhooks that fire delegations), 0.13 cross-project overview,
0.14 impact graph (Cytoscape).

## Playbooks — codified multi-step delegations (0.11.0)

A playbook is `.overture/playbooks/<slug>.json` with a `description`
and an ordered list of `steps`. Each step is `{"kind": "round"|"visual"
|"chat", "item": "...", "text": "...", mode/focus (round only)}`.
Picked from the Delegate bar's "Run a playbook" option.

- **`playbooks.py`** loads, validates, caps (128 files, 24 steps,
  32 KiB). A malformed or badly-named file is skipped silently so one
  bad playbook never hides the rest. `view.playbooks` carries
  `[{name, description, steps}]`.
- **`POST /api/playbook`** fans each step out as an owner `message`
  write (same path the Delegate bar posts individually; same checks,
  same doorbell rings, same view updates). Owner-only. Returns
  `{records, skipped}` so the UI can report partial runs.
- **Delegate bar** gets a fourth option "Run a playbook" with a picker.
  Hidden/empty when no files are present (with a hint pointing at the
  folder). Submit calls the new endpoint and reports step-by-step
  skips if any item is missing from the register.
- No new agent-side work: a step is just an owner message with the
  usual intent (`fork` / `visual` / `chat`); the steward's `watch`
  picks each up in order.

## Webhook triggers — external events fire playbooks (0.12.0)

Codify an external event → playbook mapping in `.overture/triggers.json`:

    {"triggers": {"pr-merged": {"playbook": "security-review",
                                "token_sha256": "<sha256 of the bearer token, hex>"}}}

A caller sends `POST /api/trigger/pr-merged` with
`Authorization: Bearer <token>`. Two gates:

- **Cloudflare Access service token** at the perimeter (configured on the
  Access application).
- **Per-trigger bearer token** at the server: it hashes the received token
  with SHA-256 and compares (constant-time) to the configured
  `token_sha256`. The server **never** stores the plaintext token.

Rate-limited to one firing per trigger per 10 s (in-process). The firing
runs the trigger's named playbook (same path as the Delegate bar's "Run
a playbook"); `{records, skipped}` returns.

- **`agent.py trigger-token`** mints a `token` + its `sha256` so the
  operator can paste the sha into `triggers.json` and hand the plaintext
  to the sender.
- `view.triggers` carries the public shape (`name`, `playbook`) — never
  the token hash — so the UI can list what is wired.
- Smoke-tested: mint round-trip, header extraction, rate limiter,
  config validation for bad names / bad playbook / bad hash.

GitHub webhooks use HMAC-SHA256, not bearer tokens — a 10-line Worker or
small shim can bridge them (document in RUNBOOK). cron.io, cloud
functions, and custom scripts work out of the box.

On deck: 0.13 cross-project overview, 0.14 impact graph. Also 0.12.1 for
in-server cron if the webhook path proves solid.

## Portfolio — one view across every registered console (0.13.0)

- **`agent.py portfolio`** reads `~/.config/overture/projects.json`
  and, for each registered project, opens its `STATE/store.jsonl`
  directly. No HTTP calls, no running server required: it tallies
  open-questions-awaiting-you, unlocked, locked, waiting visuals, and
  the last-locked timestamp per project, then prints a compact table.
  `--json` emits the full rows for programmatic use.
- A single malformed project's state surfaces as `"(error: ...)"` on
  its row; the other projects still render.
- The one-server variant was always able to host many projects
  (`agent.py server add`); this makes the owner's cross-project
  backlog visible in one place without opening N browser tabs.
- Browser portfolio UI is deferred (per-project origins + Access
  cookies make a cross-origin aggregator thorny). The CLI covers 90 %
  of the "where should I spend my time" ask today.

## Impact graph — Cytoscape (0.14.0)

The fifth and last step on the orchestrator arc. Each item view gains an
**Impact graph** collapsible beside the Status flowchart. Nodes: the
item + its ancestors, every question on it, mapped dashboard sections,
cited files. Edges: `parent`, `fork`, `supersedes`, `in_section`,
`cites`. Click a node to highlight everything downstream; click again
to clear. Clicking a question or item node also opens that card in the
panel (same `postMessage` channel as the Mermaid charts).

- **`cytoscape.min.js`** vendored (~425 KB) alongside `mermaid.min.js`;
  both inlined into the wrapper response so the opaque-origin iframe
  does not need Access-authenticated subresources.
- **`impact.py`** builds the Cytoscape-shaped graph; capped at 120
  nodes.
- **`GET /api/impact-graph?item=X`** returns an HTML wrapper with the
  lib + JSON data + a self-contained init. CSP + sandbox match the
  Mermaid wrapper exactly.
- Default layout is `breadthfirst, directed`; wheel-zoom clamped
  0.1x–4x. Drag nodes freely; the layout keeps edges live.

## Cron triggers — the clock fires playbooks (0.15.0)

Companion to 0.12.0's webhooks: triggers can now carry a `cron`
expression and fire on the server's clock, with no external POST.

    {"triggers": {"monday-triage": {"playbook": "inbox-triage",
                                    "cron": "0 9 * * MON"}}}

- 5-field cron: `minute hour day-of-month month day-of-week`. Accepts
  `*`, `a-b`, `a,b,c`, `a-b/n`, `*/n`. Named months (`JAN..DEC`) and
  days-of-week (`SUN..SAT`); 7 is a Sunday alias.
- A background thread sleeps until the top of each minute (+ 0.2 s so
  firings don't race the boundary); fires every matching trigger exactly
  once per (name, minute). A clock jump backward doesn't double-fire;
  a `run_playbook` nonce derived from `name + minute` makes the server
  side idempotent too.
- A trigger can carry `token_sha256` (webhook), `cron` (schedule), or
  both. A webhook POST to a cron-only trigger returns 405 with "cron-
  only; it fires on its schedule".
- `view.triggers[*].kinds` lists `["webhook"]`, `["cron"]`, or both
  so the UI can tell them apart. The cron expression itself stays
  server-side.
- Smoke-tested: 6 valid specs parse, 6 bad shapes refuse by name,
  Mon/Sun/Sat alignments, step matching, cron-only config loads,
  trigger-with-neither refuses the start.

The orchestrator arc now folds the clock in: external HTTP, scheduled
tick, or owner click all share the same playbook execution path.

## Trigger log in the Inbox (0.16.0)

Without visibility, webhook and cron firings felt opaque. 0.16.0 shows
them in the Inbox under a **Triggers** collapsible beside Delegate:

- The configured triggers (name → playbook, with its kinds: webhook,
  cron, or both).
- The last 20 firings, newest first: timestamp, name, kind, step and
  skip counts, and any error.

The server keeps the last 100 firings in an in-process ring; older
ones drop off on restart. `view.trigger_log` carries the slice;
`view.triggers[*].kinds` carries webhook/cron so the row says which
flavour the trigger is armed for.

Both `fire_trigger` and `fire_cron` wrap the playbook call in a
try/except and log the outcome before re-raising, so a failing playbook
still writes a log row with the error.

## Impact graph filter chips (0.17.0)

Dense impact graphs got hard to read. A chip row above the Cytoscape
canvas now toggles visibility by:

- **Kind**: item, question, round, section, file.
- **State** (applied only to question nodes): awaiting_you, unlocked,
  locked, stale.

An empty selection in a group means "all shown"; selecting one or more
narrows the group to just those. Multi-select across groups is AND
(matching nodes in both). A **reset** chip clears everything. Hidden
nodes drag their edges along via a `.ck-hidden` display:none rule.

All filter state lives inside the sandboxed iframe; nothing round-trips
to the server. The hint ("drag · wheel to zoom · click to highlight
downstream") moved to the bottom of the stage so the chip row has
breathing room.

## `/overture:playbook` — run a playbook from any Claude session (0.18.0)

The browser was the only way to run a playbook; now any Claude session
on the project's machine can.

- New plugin skill **`playbook`** (`/overture:playbook <slug>`): the
  agent reads `view.playbooks`, confirms the slug and the step count,
  dispatches, and reports `{records, skipped}` from the server.
- New CLI **`agent.py playbook <name>`** POSTs through the console's
  agent socket.
- New agent-door route **`POST /playbook`** calls the same
  `run_playbook` as the owner door. The agent socket is a user-only
  Unix socket (0600 in a 0700 dir) — the same trust surface
  `items-push`, `prs-push`, and `page-snapshot` already use for
  owner-privileged writes.
- The nonce is minted from `playbook-slug + current second` so a retry
  within the same second dedupes on the server. Slash-command runs are
  not currently logged in the trigger log (that stays scoped to
  webhook + cron firings — slash-command dispatch is closer to a
  Delegate-bar click).

## Browser Portfolio (0.19.0)

For an owner across several projects, one browser tab now shows every
console at a glance and alerts the OS when a sibling needs them.

- **Portfolio tab** between **Favorite** and **Chat**: one card per
  configured peer plus the local console, with the state tallies
  (`?you ~unl !stale ○lock`, plus `◫vis` when a visual is waiting),
  relative last-activity, and a click that opens that peer's console
  in a new tab. Peers that are unreachable show the error on the card
  rather than disappearing.
- **Desktop notifications (opt-in)**: a bell button asks the browser
  for Notification permission; thereafter a peer's `?you` or `!stale`
  going up fires one OS notification per peer, deduped at 60 s, with
  click-to-open. A Snooze button sets a 1-hour DND lid, so a push
  during off-hours stays silent.
- **Portfolio tab note**: `N ?you` sums the `awaiting_you` across all
  peers plus self, so the roll-up is visible from any other tab.
- **How peers talk to the home server**: `.overture/portfolio.json`
  committed in the repo lists each peer's URL, Cloudflare Access
  service-token `client_id`, and the **sha256** of its secret. The
  plaintext secret lives in `STATE/portfolio-secrets/<peer>.json`
  (0600, out of the repo). The home server reads it, hashes it,
  compares, and uses the pair to call each peer's new
  `GET /api/portfolio-slim` (owner-gated, Access-authed) through the
  owner's own `GET /api/portfolio`, which the browser then renders. A
  rotated secret whose sha drifts from the committed config fails
  loudly rather than silently. Peer rows carry only counts and
  timestamps; no owner view content leaves a peer.
- **New CLI** `agent.py portfolio-token` prints the two-file layout
  the owner fills in by hand.
- **Caching + timeouts**: peer fetches are capped at 4 s and cached
  in-process for 5 s, so one slow peer never blocks the aggregator;
  the browser also polls softly (30 s) while the tab is open.

## Playbook branching with `when` predicates (0.20.0)

A playbook step may now carry an optional **`when`** object. The
server evaluates it against the current view and item register at the
start of the firing; a step whose `when` does not pass is skipped with
`{index, why: "when:<reason>"}`, and the rest still run as owner
messages. One playbook can now be the "backlog triage" for every
state the project might be in.

The predicate set is closed — no eval, no user expressions, no
file-system or network reach — so a bad config fails at load, not at a
firing:

- `project_has_state` — the project has at least `min` questions in
  one of `awaiting_you`, `unlocked`, `locked`, `stale`.
- `item_has_state` — the same, scoped to one item id.
- `item_exists` — a specific item is in the register.
- `has_section` — a `.overture.json` section is configured.
- `not` — negates another predicate (nested up to three levels so a
  typo cannot build a loop).

Example — a release-safety playbook that only drafts the chat
heads-up when there is unanswered work:

    {
      "description": "Pre-release triage.",
      "steps": [
        {"kind": "chat", "text": "Any blockers in the air?",
         "when": {"kind": "project_has_state", "state": "awaiting_you", "min": 1}},
        {"kind": "round", "item": "RELEASE-7", "mode": "tighten",
         "text": "Confirm the rollout gates.",
         "when": {"kind": "not", "of": {"kind": "project_has_state", "state": "awaiting_you", "min": 1}}}
      ]
    }

A trigger (webhook or cron) and the Delegate bar and the
`/overture:playbook` slash command all go through the same
`run_playbook`, so the `when` behaviour is the same wherever a
playbook fires. The browser's Delegate bar shows which steps were
skipped in the firing's result row, with the predicate reason.

## Keyboard shortcuts (0.21.0)

An owner across many consoles needs to move fast. Every page now
carries a global keyboard layer; `?` prints the full list in a
modal overlay:

- **`g i / f / p / s / o / c`** — Inbox, Feed, PRs, Favorite, Portfolio, Chat.
- **`g b`** — close the panel (back to the board).
- **`.`** — focus the Delegate bar (opens it if collapsed).
- **`j / k`** — next / previous focusable row inside the panel.
- **Enter / Space** on a focused row — open it (same as click).
- **`?`** — show the help overlay; **Esc** closes it.

Rules the layer follows:

- Never fires in a text input, textarea, select, or
  `contenteditable` — so typing into a comment never hijacks a
  letter.
- `g` is a sticky prefix for 1500 ms; a second key completes the
  pair, anything else cancels it.
- Modifier keys (Ctrl / Meta / Alt) suppress every shortcut, so a
  browser-level binding wins without conflict.

No server changes; the whole layer is in `console.js` and `console.css`.

## Command palette (0.22.0)

**Ctrl+K / Cmd+K** on any page opens a search box over every surface
the console knows about. One keystroke, type a few characters, press
Enter.

- **Items** — type an id or title fragment; Enter opens the item panel.
- **Questions** — their qid plus the first slice of the text; Enter
  opens the owning item.
- **Playbooks** — their slug plus description or step count; Enter runs
  the playbook (same path as the Delegate bar; `when` predicates still
  gate each step).
- **Peers** — portfolio cards by their project name; Enter opens the
  peer's console in a new tab.
- **Tabs** — hop to Inbox, Feed, PRs, Favorite, Portfolio, Chat.
- **Actions** — close the panel, open this help, focus the Delegate
  bar (same bindings as the shortcut layer, so the palette is a
  mouse-and-touch alternative).

The filter is a case-insensitive subsequence match ranked by how
early the query lands in the label; ties break by kind priority
(item → question → playbook → peer → tab → action) so typing an id
wins. The palette is browser-only: no new server routes, nothing
sent on a filter — only one `/api/playbook` POST when you Enter a
playbook row (the same call the Delegate bar makes).

↑/↓ walk the results, Enter runs the selected row, Esc or a click on
the backdrop closes.

## Portfolio peek + status LED (0.23.0)

A peer card now carries real triage context, not just counts, so the
owner can see what is awaiting across every project without opening
every tab.

- **Peek**: the top three `awaiting_you` questions per peer, newest
  first — qid plus the first 60 characters of the question text and
  a relative time. The server includes it in `/api/portfolio-slim`,
  and the aggregator shapes it defensively (bounded to 3 entries,
  120 chars each) before letting it reach the home browser.
- **Status LED** per card:
  - **green** — nothing awaiting;
  - **yellow** — awaiting under an hour;
  - **orange** — awaiting over an hour;
  - **red** — awaiting over 24 hours;
  - **grey/red-outline** — the peer is unreachable.
  The dot's title gives the oldest-awaiting age.
- The peek is `peek: [{qid, item, ts, text}]` on the slim shape; the
  text is already the owner's view, so showing it here is the same
  trust boundary as the question itself. The home console still
  never sees locked answers or chat content.

## Cross-project priority ribbon (0.24.0)

The Inbox tab now opens with a ribbon of the oldest awaiting
questions across every console (self + each portfolio peer). One
glance says what to touch first.

- Up to six rows, sorted by `ts` (oldest first = most urgent).
- Each row: a traffic-light dot (yellow < 1 h, orange < 24 h, red
  > 24 h), the project name, the qid, a 60-char slice of the
  question text, and a relative time.
- Click a row — if it's local, the item panel opens; if it's a
  peer, that peer's console opens in a new tab.
- The summary line names the total and the number of projects
  spanned ("4 of 11 awaiting you across 3 projects"), so the
  owner can tell at a glance whether a backlog is one project or
  many.
- The ribbon self-starts the portfolio fetch: an owner who never
  opens the Portfolio tab still gets the cross-project view the
  first time they open the Inbox. Peer data flows through the
  same aggregator (5 s cache, 4 s timeout), so one slow peer
  never slows the ribbon.
- Nothing to show when every project is quiet; the ribbon
  simply does not render.

## Deep links + Copy link (0.25.0)

The URL hash now activates one view on load, and the hash
updates as the owner navigates:

- `#inbox | #feed | #prs | #favorite | #portfolio | #chat` — open
  the panel on that tab.
- `#item=<id>` — open the item panel.
- `#qid=<id>/Q<n>` — open the owning item.

A deep-link in the URL beats the "open the Inbox by default"
rule, so a shared bookmark lands the receiver exactly where the
sender was. `history.replaceState` is used (not pushState) so a
tab-hop isn't a navigation entry; `hashchange` keeps the view in
sync when the owner edits the bar or hits Back.

The command palette gained **Alt+Enter** on any row: copies a
shareable link to the clipboard — a `#item=…` or `#qid=…`
fragment for local rows, a `#<tab>` for tabs, or the peer's URL
for a portfolio row. The shortcut-help overlay lists this.

Nothing crosses to another browser or another owner — the hash is
only interpreted inside the same console. Peers still require
their own Access login, same as before.

## Snooze a question (0.26.0)

Not every awaiting question is answerable right now. A small ⌛
button on each Priority-ribbon row offers three snooze presets:

- **1h** — one hour from now.
- **til tmrw** — tomorrow at 9am local time.
- **1w** — one week from now.

A snoozed question leaves the Priority ribbon immediately and
reappears when its time comes. The Inbox tab bottom carries a
collapsible **Snoozed · N** section listing every live snooze
with its wake time and a one-click **Unsnooze** button.

Snoozes live in this browser's `localStorage` keyed by
`<project>#<qid>`, so a snooze made in one window does not reach
another and a private window may refuse it — the UX works
without storage. Expired entries are pruned on read; no server
work is involved.

## Trigger replay (0.27.0)

The Triggers section of the Inbox now carries a **↻ Replay**
button on every configured trigger and on every past firing in
the log (as long as the trigger still exists).

- One click POSTs `/api/trigger-replay` with a fresh nonce; the
  server runs the trigger's playbook via the same path
  `fire_cron` and `fire_trigger` already use.
- The firing is appended to the trigger log with
  `kind: "replay"`, so an audit shows manual replays alongside
  webhook and cron firings.
- Replay is owner-only (gated by the Access-authed owner door)
  and bypasses the webhook token + rate limit — the owner
  already proved themselves.
- A playbook step that no longer passes its `when` predicate is
  skipped as usual; the Delegate-bar-style surface shows ran vs.
  skipped counts, with the first skip's reason.

## Export today's rulings as Markdown (0.28.0)

The Feed tab's filter row gains a **⤓ Export today** button that
opens a modal with every ruling locked since local midnight as
Markdown, ready to paste into a standup, a weekly review or a
sprint retro.

Shape of the output:

    # Rulings — 2026-10-08

    From <project> · N locks across M items.

    ## AB-7 · <item title>

    - **AB-7/Q1** — 09:14 UTC
    - **AB-7/Q2** (re-lock) — 11:02 UTC

    ## XX-9 · …

- Browser-only: reads `/api/feed?kind=lock&limit=200`, filters by
  `ts >= start-of-today-local`, groups by item, sorts within an
  item by time.
- The modal has **Copy** (clipboard write; falls back to selecting
  the text if the browser refuses), **Close**, and the standard
  Esc / backdrop close.
- Nothing is sent anywhere else — the generated Markdown stays in
  this browser until the owner pastes it.

## Overture — the 1.0 rename (1.0.0)

**console-kit is now Overture.** The product name, the GitHub repo,
the plugin manifest, the Python package, the slash-command prefix,
the service file, and the on-disk paths all rename at once.
Semantically nothing else changes in 1.0 — every feature from 0.9.6
through 0.28.0 keeps working as it did, under new names.

- **GitHub:** `MikeHeid/console-kit` → `MikeHeid/overture`.
- **Plugin manifest:** `name: overture` (slash commands now
  `/overture:*`, e.g. `/overture:playbook`, `/overture:as`).
- **Python package:** `console_kit` → `overture`.
- **Env vars:** `CONSOLE_KIT_*` → `OVERTURE_*`.
- **Config paths:** `.console-kit.json` → `.overture.json`;
  `.console-kit/` → `.overture/` (playbooks, triggers,
  portfolio.json live under there).
- **State / share dirs:**
  `~/.config/console-kit/`     → `~/.config/overture/`,
  `~/.local/share/console-kit/`→ `~/.local/share/overture/`,
  `~/.local/state/console-kit/`→ `~/.local/state/overture/`.
- **Service / socket:** `console-kit.service` → `overture.service`;
  `console-kit-agent.sock` → `overture-agent.sock`.

**Register-after-upgrade reminder.** A new SessionStart hook,
`install_notice.py`, prints an ASCII Overture banner and the
agent-registration commands exactly once per installed version,
then writes a per-version flag so it stays silent on later
sessions. The flag path encodes the version, so the next upgrade
fires it again. Linux/macOS/WSL users get the direct `agent.py
register` + `systemctl --user start overture.service` pair;
Windows users get the WSL-wrapped variants (`wsl -d Ubuntu-24.04
-- …`), because the server itself only runs on POSIX.

**Upgrading from console-kit 0.28.0 or earlier.** The 1.0
rename is deliberate; it needs a fresh registration. After the
upgrade, run (Linux/macOS/WSL):

    python3 ~/.local/share/overture/kit/plugin/kit/agent.py register

Then start the user service:

    systemctl --user start overture.service

The hook will remind you if you forget — once per installed
version, and it goes quiet after.

## Inbox filter chips (1.1.0)

The Inbox tab opens with a row of four toggle chips above the
sections, so a dense inbox can be trimmed to what you want to look
at right now:

- **? you** — rounds + loose questions awaiting the owner.
- **~ unl** — questions with a draft answer that is not locked yet.
- **! stale** — rulings whose cited evidence has moved.
- **○ lock** — the "Recently answered" footers that nest under each item.

All chips are on by default. Each chip's state is held in this
project's `localStorage`, so the choice sticks per project and
per browser without ever reaching the server. Chips mirror the
Portfolio-card tally glyphs and the Priority ribbon's compact
header, so one visual language carries the whole triage layer.

## Theme toggle (1.2.0)

A compact theme button in every panel header cycles **auto → light
→ dark**:

- `◐ auto` — follows the OS `prefers-color-scheme` (the default).
- `☀ light` — pins the light Primer palette.
- `☾ dark` — pins the dark Primer palette.

The CSS already carried both palettes; the toggle adds the user
override. Choice is held in this project's `localStorage` and
applied by setting `document.documentElement.dataset.theme`, which
the `console-fallbacks` layer keys off. A screen reader hears the
new state (`announce` fires on cycle); the button's `title`
tooltip names the current mode.

## Playbook preview (1.3.0)

Before firing a playbook, see exactly what will happen. A new
**Preview** button in the Delegate bar (visible when the Delegate
form is in `playbook` mode) and a **⌕** button next to each
configured trigger's Replay open a modal that lists:

- Every step with its kind, item, and the first 80 chars of its text.
- Whether the step **would run** (▶ green) or **would skip** (▢
  muted), with the exact reason — a failing `when` predicate, a
  missing item id, etc.
- A header line summarising "would run N of M steps".
- A **Run now** button that fires through the same path as the
  Delegate bar; **Close** / Esc / backdrop closes.

A new owner-only route `GET /api/playbook-plan?name=<slug>`
evaluates the predicates against the current view and item
register and writes nothing. It never fires the playbook; a
"Preview" is always safe to click. The route is route-gated like
the owner door, so a Preview without authentication fails the
same way as `/api/view`.

## Orchestration tree: section field on items (1.4.0)

An item in `items.json` can now carry an optional **`section`**
field — a slash-separated hierarchical slug like
`wave-1/phase-2/lane-ui`. The scaffold materialises every path
segment as a nested `<details data-ck-section="…">` on the
dashboard, and a new item drops into its already-visible
wave/phase/lane node without the owner editing the page.

- **Schema:** `section` is validated at push time:
  up to 5 slash-separated slug segments, each 1–64 chars from
  `[a-z0-9][a-z0-9._-]*`. A bad shape refuses the push with the
  offending segment named.
- **Scaffold:** `sync_items_block` creates missing section nodes
  in order (shallowest first) so each new item sees its full
  parent chain. Hand-edits inside each `<details data-ck-section>`
  are preserved across re-syncs — only the content inside
  `<!-- ck:section-children slug -->` markers is written.
- **Parent still wins:** an item with a `parent` already on the
  page nests under the parent; otherwise it drops into its
  section. Items with neither fall to the top of the items block,
  so no item ever disappears.
- **Order:** parents before children, roots sorted by section
  depth, so a push of 40 items at once produces the right tree in
  one pass.
- **Adapter note:** `plugin/kit/docs/ADAPTER.md` documents the
  new optional field; existing adapters keep working — `section`
  defaults to absent.

The dashboard scaffold ships enough markup for a project's own
CSS to style sections however it likes; data attributes
(`data-ck-section`) make the tree selectable without parsing the
slug.

## `/overture:add-skill` — scaffold a new skill (1.5.0)

A new slash command: **`/overture:add-skill <skill-name> [category]`**
walks you through creating a Claude Code skill end-to-end.

The flow:

1. **Name** — the first argument is the slug (`[a-z0-9][a-z0-9._-]*`,
   up to 64 chars). A missing or malformed slug is refused; a slug
   that already exists is refused rather than overwritten.
2. **Category** — if the second argument is absent or not one of the
   four known values, the skill prompts with `AskUserQuestion`:
   - **agent-review** — reviewer-style skill (code / design / security).
   - **visualizer** — Mermaid or HTML-mock skill.
   - **documentation** — doc-writing skill.
   - **other** — generic skill.
3. **Target** — picks `plugin/skills/<slug>/SKILL.md` when the CWD is
   the Overture plugin repo itself (there is a `plugin/skills/` next
   door); otherwise `.claude/skills/<slug>/SKILL.md` under the
   project.
4. **Scaffold** — writes a `SKILL.md` with the category-appropriate
   template: frontmatter (name, description, argument-hint,
   disable-model-invocation) plus a body stub for the chosen kind.
5. **Confirm** — tells you the path, the category, and that the
   file is a starting point.

The skill touches nothing else — no git, no install, no plugin
reload. A fresh skill becomes available next session (or on next
plugin install when the file landed under `plugin/skills/`).

## Fragment buttons + viewer modal (1.6.0)

When an agent's reply (chat, answer note, fork message, round
message, or message card) contains a **fenced code block**, the
block renders as a compact **📄 button** instead of inline
walls-of-code; clicking opens a monospace viewer modal with
**Copy** + **Close**.

Any language works: `md`, `txt`, `py`, `go`, `rs`, `js`, `ts`,
`json`, `yaml`, `html`, `css`, `sh`, `sql`, … — the button icon
picks a per-language glyph; the lang defaults to `text` when none
is given. A fence may name a file: `` ```md:plan.md `` makes the
button title `plan.md`.

- A **named fence** (`` ```lang:name.ext ``) is always a
  fragment, regardless of length.
- An **anonymous fence** must be ≥ 40 characters so a 10-char
  inline snippet does not turn into a button.
- The viewer modal shows the raw content preformatted (no
  rendering); Copy writes to the clipboard with a
  select-fallback. Esc / backdrop closes.
- Applied uniformly to every surface where agent text renders:
  Chat log, round messages, follow-up messages, locked-answer
  notes, and the sheet view.

## Onboarding + docs cleanup (1.6.1)

Three bug fixes and a doc pass surfaced from a Windows + WSL2
install review:

- **`agent.py scaffold-dashboard --name "Project Name With Spaces"`**
  no longer refuses with "steward: agent name '…' is refused". The
  argument now writes to `project_name_display` instead of `name`,
  so the shared agent-name validator doesn't touch it. `--name` is
  kept as a hidden alias — scripts that use the old flag still
  work.
- **Onboarding auto-adds `.overture/console.env` to `.gitignore`**
  when it is not already listed. The file carries the AUD tag and
  team domain — not secret by the kit's account, but shaped like
  credentials, so Claude Code's safety check used to block the
  commit mid-onboarding. Idempotent; swallows OSErrors into a
  REVIEW line.
- **`ADAPTER.md`** updated: the "The page" section now says the
  server serves the `page-snapshot` from STATE, not
  `CONSOLE_PAGE`; the legacy flag has been ignored since the Q28
  ruling.
- **`INSTALL.md`** gained a WSL2 note (`loginctl enable-linger
  $USER`) and a one-liner about SessionStart hooks loading only in
  a new session, so an owner who installs mid-session knows to
  reopen Claude.

## Numbered item refs — phase 1 (1.7.0)

Items can now carry a **dotted-number ref** like `1`, `1.2`,
`1.2.1`. The owner uses these in chat, on calls and in notes to
point at specific work. The kit owns their assignment, so
numbers do not drift or collide across pushes.

### Fields

- **`ref`** — optional in `items.json`. Dotted non-zero segments,
  `^[1-9][0-9]*(\.[1-9][0-9]*)*$`. The ref must sit exactly one
  segment under its parent's ref (`1.2` under `1`); a top-level
  item has a single-segment ref.
- **`kind`** — `"topic"` | `"item"` (default `"item"`). A topic may
  have no parent even when `require_parent` is on.

### `.overture.json` options

    "items": {
      "auto_ref": true,          // default true — assign missing refs on items-push
      "require_parent": false    // default false — refuse an item with no parent and no "topic"
    }

### Behaviour

- **Store owns the numbers.** `STATE/refs.json` carries
  `{"assignments": {id: ref}, "retired": {ref: last-id}}`. On every
  `items-push`:
  - Items with a stored ref keep it; a push that disagrees refuses
    the whole snapshot with the stored value in the message.
  - Items with no stored ref AND `auto_ref` on get the next free
    number under their parent (walking parents-first so each
    child sees its parent's ref).
  - Items that have left the register move to `retired`;
    retired numbers are **never reused**.
- **Returned to the caller.** `/api/items-push` adds a `refs`
  object to its 200 so the pushing agent sees every assigned ref.
- **Everywhere in the view.** Each item in the live payload
  carries its ref in `items[id].ref`, so a UI update can show
  `1.1 · <title>` beside the id without touching the view
  pipeline.
- **No cycle checks, no `item-move` yet.** Those come in 1.8.0
  along with the browser surfaces (ref beside each title in the
  Inbox, Priority ribbon and command palette).

## Numbered item refs — phase 2 (1.8.0)

Browser surfaces for the refs that 1.7.0 taught the kit to assign.

- **Ref pill beside every item id.** New visual rows, cluster
  cards, loose rows, favorites item headers all show the item's
  ref as a small accent-coloured pill (`1.2`) before the id.
  Items without a ref (older project, auto_ref off) render as
  before — the pill is omitted, not blank.
- **Command palette shows the ref.** An item's row label now
  starts with its ref: `1.2 · AB-2 · <title>`.
- **Palette search by ref.** Typing a dotted-number query (`1.2`)
  treats it as a ref lookup: exact matches rank first,
  descendants of a prefix (`1` matches `1.1`, `1.2`, …) rank
  next. Non-ref queries still filter by label as before.
- Browser-only; no server changes beyond what 1.7.0 already
  carries. `item-move` (the move-vs-alias open question) stays
  deferred.

## Items tree as a live value (1.9.0)

The scaffold page gets a kit-computed, always-current tree of
every item — no `board()` code needed.

- **Server-side.** `Console.board()` now injects an
  `items_tree` key into whatever the project's adapter pushed as
  `values`, unless the project already set that key. The tree is
  plain text, one item per line (`<ref> <title>`), indented two
  spaces per depth, sorted by ref (`1.10` after `1.2`, items
  without a ref last). Orphans whose parent left the register
  show at root.
- **Page.** New scaffolds get a single `<pre
  class="scaf-items-tree" data-live="items_tree">` block in
  place of the old `items_rows` HTML table (which never worked —
  `data-live` sets `textContent`, not inner HTML; brief 1 #17
  closed).
- **Backward compat.** Existing scaffolded pages keep whatever
  markup they have; the `items_tree` value is only applied where
  `data-live="items_tree"` exists. A project that already pushes
  `items_tree` in its own `board()` is untouched.
- **No new routes, no new fields.** The tree is derived at
  render time from `items.json`'s existing shape; no snapshot
  change needed.

## Clickable refs in agent text (1.10.0)

A dotted-number mention like `1.2` or `1.2.1` in agent-authored
text (chat replies, round messages, follow-ups, locked notes,
sheet view, cluster cards) now renders as a clickable pill that
opens that item.

- **Only real refs link.** The browser builds a reverse map
  `ref → id` from the current items view and matches on exact
  equality. A dotted number that nobody has as a ref stays
  plain.
- **Guards against false positives.** A character class
  blocks the lookbehind/lookahead when the token is adjacent to
  letters, digits, dot, underscore, hyphen, or slash — so
  `AB-1`, `x_1.2`, `0.9.3`, `path/1.2`, `1.2.html` never
  wrongly link.
- **Keyboard reachable.** The pill is a real `<button>`;
  Tab-focus and Enter open the item like any other focusable
  row.
- Browser-only; same `renderAgentText` entry point as the
  fragment viewer, so every surface that already shows agent
  text picks this up automatically.

## Scaffold append sets `data-live-shape` (1.11.0)

A scaffold run that appends sections to an existing page now
patches the page's `<body>` tag so the live loop can find it.

- Before: `_page_write` only wrote `<body data-live-shape="…">`
  on a brand-new page. Appending sections to a hand-made page
  left the attribute off, so none of the `data-live="…"`
  elements updated. (Brief 1 #16.)
- Now: `_needs_body_shape` / `_add_body_shape` detect a `<body>`
  without the attribute and inject it next to the existing
  attributes. Idempotent (a page that already has the attr is
  untouched). Case-insensitive — `<BODY class="x">` works too.
- Pages that already carry a different `data-live-shape` are
  left alone (so a project with its own shape is not
  overwritten). Pages with no `<body>` tag are left alone (the
  scaffold is additive, not restorative).

## Topic status rollup in `items_tree` (1.12.0)

Each line of the `items_tree` live value now carries a
rolled-up count tail:

    1 Rollout
      1.1 Rollout plan · ?2 !1
      1.2 Deploy script · ~1
    2 Audit
      2.1 Security pass · ?1

- Three states are counted: `?` = awaiting_you, `~` = unlocked,
  `!` = stale.
- Each item's tail is the **sum of its own open questions plus
  every descendant's**, so a topic shows at a glance what sits
  under it.
- Zero segments are omitted; an item with no open work shows no
  tail. Locked and withdrawn states are not counted (the tree
  is a now-what view, not a history).
- Browser-only consumers see the richer text via the same
  `<pre data-live="items_tree">` block — no page change needed.
- Projects that compute their own `items_tree` in `board()` are
  still unaffected: the kit only writes when the project did
  not.

## Markdown rendering for `md` fragments (1.13.0)

The fragment viewer now **renders** Markdown fragments
(`md` / `markdown` / `mkd` / `mdown`) with real headings,
lists, bold, italic, inline code, blockquotes, horizontal
rules, and `[text](https://…)` links. A **Raw** button toggles
to the preformatted source; other-language fragments (`py`,
`js`, `json`, …) still open preformatted.

- Hand-rolled renderer, no library. Every element is built
  with `document.createElement`; **no HTML pass-through**, so
  a `<script>` or `<img onerror>` in the body cannot inject.
- Supported block structures: `# ## ### #### ##### ######`,
  `- * +` lists, `1. 2.` lists, `>` blockquotes, `---` rules,
  ``` ``` ``` fenced code blocks, paragraphs that fold adjacent
  lines.
- Supported inline: `` `code` ``, `**bold**` / `__bold__`,
  `*italic*` / `_italic_`, `[label](url)` (http(s) only — other
  schemes render as literal text).
- The viewer defaults to **rendered** for Markdown and raw for
  everything else; the toggle re-paints the same body container.
- Copy still copies the **raw** body regardless of what's shown.

## Web skins (1.14.0)

Three palette overlays beyond the Primer default — the owner
cycles the skin independently of the auto/light/dark theme and
each choice persists per project.

- **Primer** (default) — the existing GitHub-aligned palette.
- **Solarized** — warm, cream/mustard base with teal / rust
  accents. Light + dark variants.
- **Nord** — cool blue-grey base with muted accents. Light +
  dark variants.
- **Contrast** — accessibility-forward: pure black-on-white
  (or white-on-black) with saturated accents.

Mechanism:

- `document.documentElement.dataset.skin` is set to the chosen
  key (`solarized` / `nord` / `contrast`); unset for Primer.
- CSS keys off `:root[data-skin="…"]` with the same
  `prefers-color-scheme: dark` + `:root[data-theme="dark"]`
  pattern as the base palette.
- A new `◉`/`S`/`N`/`C` button in the panel header cycles the
  skins; the theme (sun/moon/auto) stays its own button
  alongside.
- Choice persists in `localStorage` as `skin`; it reaches
  nothing outside the browser.

## PR title ref linking (1.15.0)

The PRs tab's "Open" buttons already match **item ids** and
**qids** found in a PR's title or branch; now **dotted-number
refs** in those same strings also become open-item buttons.

- A PR titled "Refactor 1.2 to use typed deps" now surfaces a
  button labelled `1.2 · AB-2` that opens item AB-2 (whose ref
  is `1.2`).
- Guards are the same as 1.10.0's clickable refs in agent
  text: lookbehind + lookahead block adjacent
  letters/digits/dot/underscore/hyphen/slash, so a PR title
  mentioning `v0.9.3` or `/path/1.2.html` never wrongly links.
- Honours the existing `PR_MAX_LINKS` cap and de-duplicates
  against id/qid matches, so a title that mentions both an id
  and its ref produces one button, not two.
- Browser-only; no server changes.

## "What's new since last look" banner (1.16.0)

The Inbox tab opens with a dismissible banner summarising what
has arrived since the panel opened — questions, answers,
visuals, chat — so the owner sees the delta without scanning
every section.

- Counts the four event classes from `view.questions`,
  `view.visuals`, `view.threads` against the `seenAtOpen`
  baseline (frozen at the moment the panel last opened), not
  the live `seen` cursor — so arrivals during the current
  reading stay in the banner.
- One click on **✓ Caught up** advances both the persisted
  `seen` and the panel baseline, so the banner stays dismissed
  until something arrives next.
- Rendered inside the Inbox tab, above the Priority ribbon;
  hidden when nothing is new.
- Browser-only; no server changes.

## `agent.py item-move` — re-parent intent (1.17.0)

Closes the remaining open piece from the numbered-refs brief
(Brief 2 §4.3) with the simpler semantics: **the ref stays, the
move is a signal the adapter picks up next.**

### New owner CLI

    agent.py item-move AB-5 --to AB-2         # move AB-5 under AB-2
    agent.py item-move XX-9 --to-root         # move XX-9 to top level
    agent.py item-move AB-5 --to AB-2 --text "needed under the new epic"

### What writes

- A `message` record on the item's thread with the new intent
  **`move`** and a `move_to` field (target parent id, or `null`
  for root).
- The project's adapter stays the source of truth for parents;
  the move is a documented intent, not an override.
- The message surfaces in the item's thread and the Feed; the
  steward picks it up on next watch.

### Guards

- Target parent must exist in the register (`404` otherwise).
- A move that would form a cycle through pushed parents is
  refused by name.
- An item moving to itself is refused.
- The chat thread never accepts `intent: move` (the schema
  check named-refuses the mismatch).
- Fields validated at the schema layer: `move_to` must be an
  item id or `null`; the fork-only fields (`focus`, `mode`,
  `roles`, …) stay refused on a move; a move on CHAT_ITEM is
  refused.

### Trust surface

- The agent-door `/item-move` route is user-only (0600 Unix
  socket in a 0700 dir) — same trust surface as `items-push`,
  `prs-push`, `page-snapshot`, `playbook`.
- The owner-door `/api/item-move` is Access-authed like every
  other owner route.

## Palette full-text search (1.18.0)

The command palette (`Ctrl+K` / `Cmd+K`) now searches **inside**
item titles, question bodies, and chat messages — not just the
label slice.

- Each row carries a `search` payload with lowercased full
  content; the filter checks label first (startswith /
  substring / subsequence) and falls back to body-text
  substring hits one score tier lower.
- A new **`chat`** row kind indexes the newest 50 chat
  messages. Each row's label is `You: …` / `<agent>: …` with
  the first 80 chars of text; Enter opens the Chat tab (which
  scrolls to its end on render).
- Chat rows only appear once the owner types; an empty palette
  stays short (items / tabs / playbooks / peers / actions).
- Alt+Enter on a chat row copies a `#chat` deep link.
- No new routes — everything comes from the existing view
  (`view.questions`, `view.threads[CHAT_ITEM]`).

## Draft autosave to server (1.19.0)

Unfinished compose text — chat messages half-typed, answer
drafts, visual briefs, follow-up seat picks — now mirrors
across the owner's browsers. Write at home, finish at the office.

- **Server state**: new `STATE/drafts.json`, dir-relative /
  O_NOFOLLOW, same path as `items.json` and `refs.json`. One
  entry per shaped key: `{text, ts}`. Capped at 500 keys and
  1 MiB total; a key's text is capped at 20 000 characters
  (matching the schema's message cap). Over-cap entries are
  pruned oldest-first on write.
- **New owner-only route** `POST /api/draft` with
  `{key, text, nonce}`. Empty text removes the entry.
- **View payload** now carries `view.drafts: {key: text}` so a
  fresh page load merges server drafts into the in-session
  map.
- **Browser side**: a `setDraft(key, value)` helper replaces
  every direct `draftTexts[key] = …` write (17 sites). The
  helper updates the in-session map and schedules a debounced
  server save (1500 ms after the last keystroke); a `clear`
  path is the same helper with an empty string.
- **Merge policy**: on view fetch, server-only drafts (where
  the local map has no key) are copied into the local map.
  Local text that hasn't synced yet never gets stomped by an
  old server value.
- **Trust**: route is Access-authed, same as every other owner
  route. Drafts are per-owner; peers and agents cannot read or
  write them.

## Security + reliability patch (1.19.1)

Two independent reviews surfaced issues worth blocking the next
feature ship on. All fixed in this patch.

### CRITICAL

- **Agent-door `/view` leaked owner drafts.** `payload()`
  added `view.drafts` since 1.19.0, and `AgentHandler.do_GET`
  serves `payload()` straight through. An agent calling
  `/view` on the user-only socket could read the owner's
  half-typed answers and chat text. Fix: drafts now attach in
  `page_payload()` only (the owner door's path). Agents see no
  `drafts` key.
- **Markdown renderer could hang the tab.** `renderMarkdown`
  used a strict fence regex but a loose paragraph exclusion:
  lines like `` ```c++ foo `` or `` ```json {"a":1} `` matched
  neither, so `i` never advanced and `<p>` elements piled up
  forever. CRLF text with a heading hit the same case because
  `.` does not match `\r`. Fix: normalise CRLF; the paragraph
  branch now unconditionally consumes at least one line, so a
  malformed fence falls through as literal text.

### HIGH

- **Access service-token could leak via redirect.**
  `urllib.urlopen` follows 30x redirects AND re-sends custom
  headers, including `CF-Access-Client-Secret`. A crafted peer
  (or MITM) could 302 to `http://attacker/` and receive the
  secret. Fix: `peers._fetch_slim_http` now builds an opener
  with a redirect handler that raises on any redirect; the
  request fails with `HTTP 30x`.
- **Private-host peers refused.** The `peers.py` URL regex
  accepted `https://localhost`, `.local`, `.internal`, and
  RFC1918 ranges. Combined with an in-repo config the agent
  can edit, this could point the Access secret at a host the
  owner never intended. Fix: `_is_private_host` refuses
  loopback / `.local` / `.internal` / `.lan` / `.home` /
  `.corp` / `127.*` / `10.*` / `172.16-31.*` / `192.168.*` /
  `169.254.*` at config load time.
- **Agent-door `/item-move` forged owner authorship.**
  `item_move` always wrote `by: "owner"`. An agent writing to
  the user-only socket could post as the owner. Fix: pass a
  `by` argument through; the agent-door path writes a plain
  advisory message under the agent's own name, and `intent:
  "move"` stays reserved for the owner door.
- **Draft clear could resurrect from a server round-trip.**
  `setDraft(key, '')` deleted locally, but a view fetch
  before the debounced server save landed would see the key
  absent locally and re-add the old server value. Fix: a
  `draftClearedPending` set tracks keys whose clear hasn't
  acked; `syncServerDrafts` skips them. `pagehide` flushes
  pending saves with `sendBeacon`.
- **Peer aggregator could 503 on a bad peer.**
  `_fetch_slim_http` caught `OSError` + `URLError`, but
  `http.client.HTTPException` (and its `BadStatusLine`,
  `LineTooLong`, `IncompleteRead` subclasses) escaped and
  faulted the whole aggregator. Fix: catch `HTTPException`
  explicitly.
- **`refs._topological` recursed.** A 1 000-item parent chain
  hit Python's recursion limit. Fix: iterative walk.
- **`save_draft` had no lock.** Two concurrent saves could
  lose updates on `ThreadingHTTPServer`. Fix: wrap in
  `self._lock`. `OSError` on write now surfaces as 500 with a
  server-log entry rather than an unhandled traceback.
- **`replay_trigger` turned 404s into 500s.** A missing
  playbook on a configured trigger returned 500 instead of
  propagating the inner error's code. Fix: preserve
  `e.code` from the caught `RequestError`.

### MEDIUM

- **`refs.py` reused retired numbers on an explicit push.**
  Uniqueness was checked only against `assignments`. Fix:
  pushing a retired ref is refused by name, unless it is the
  same id getting its own number back. A retired id that
  returns now gets its old ref restored.
- **`drafts.save` could inflate on non-ASCII and silently
  push past `MAX_FILE`.** Fix: `ensure_ascii=False`.
- **`KEY_RE` anchor `$` allowed a trailing newline in a draft
  key.** Fix: `\Z`.

## Test-regression patch (1.19.2)

Follow-up on the parallel reviews. Full-suite agent surfaced four
real regressions in test_kit and test_server; all fixed. The
remaining ~38 server failures are shape drifts from feature
additions (items_tree, auto-ref, sections, drafts) and need
test-fixture updates in the matching test file, not code fixes.

- **`triggers.load` and `peers.load` treated a missing config file
  as a hard fault.** On a project with no `.overture/triggers.json`
  or no `.overture/portfolio.json`, the broad `except OSError`
  swallowed `FileNotFoundError` into a `TriggerError`/`PeersError`,
  which `multiserver.open_project` then surfaced as a project-wide
  refusal. One project with no triggers would 503 everything on
  the one-server. Fix: catch `FileNotFoundError` first and return
  `{}` — "not configured" is not an error.
- **Old-kit regression tests (`v0.8.*`) failed to import `overture`.**
  Pre-1.0 kits still ship the package as `console_kit`; the
  rename sweep updated the OLD_BOOT and start-old shim scripts to
  `from overture import server` without a fallback. Fix: both
  shims try `overture.server` and fall back to `console_kit.server`
  via `importlib.import_module`.
- **`agent.py register` left pre-1.0 hooks orphaned.** The 1.0
  rename moved the registry to `~/.config/overture/projects.json`.
  A user who still had a pre-1.0 plugin install alongside the new
  one saw its SessionStart hook read the empty legacy path and go
  silent. Fix: `register()` dual-writes to
  `~/.config/console-kit/projects.json` as a mirror. The new path
  stays the source of truth.

## Open-items close-out (1.20.0)

Four remaining items from the parallel review backlog, all fixed.

### Peer URL ↔ secret binding

An agent with write access to `.overture/portfolio.json` could
previously change a peer's `url` without re-signing: the drift
check hashed `secret` alone, so a URL swap kept the same hash. The
1.19.1 patch mitigated with redirect refusal + private-host
blocks; **this closes the gap** by binding the hash to the URL:

    token_sha256 = sha256(secret + 0x00 + url).hexdigest()

- `load_secret` prefers the URL-bound form.
- The pre-1.20 shape `sha256(secret)` is still accepted with a
  one-line stderr warning naming the peer and the fix.
- `agent.py portfolio-token` prints the new formula.
- A URL swap without re-signing now fails the drift check with
  the same error the owner sees for a rotated-but-not-updated
  secret.

### `refs.json` unbounded growth

The `retired` map was append-only. A project with high id churn
could grow `refs.json` past `MAX_FILE` and brick `items-push`
("refs.json is not JSON" once the file crosses the read cap). Fix:
`MAX_RETIRED = 5000`; oldest retirements are pruned FIFO when the
cap is hit (Python 3.7+ insertion-ordered dicts). Common
"returning id" case still works for recent retirements; very old
ones get a fresh ref.

### Markdown italic hits `snake_case`

`foo_bar_baz` was rendering as `foo<em>bar</em>baz`. A snake_case
guard in `renderMdInline` detects an underscore-wrapped match
adjacent to a word char on either side and emits the first
underscore as literal text, retrying the rest. `_italic_` on its
own and `_italic_` between non-word chars still work.

## Full test-suite green (1.20.1)

The parallel review's test agent flagged ~38 server-test
failures as "shape drifts from feature additions, not code bugs."
This patch cleans them up and the full suite now passes.

### Code change

- **Refs no longer fold into `items.json` or into
  `view.items`.** Items stay as the project pushed them, a
  shape-stability contract. The sibling `view.refs: {id: ref}`
  map carries the kit's assignments. Browser `itemRef(id)`,
  palette ref search, PR title ref linking, and clickable refs
  in agent text all read from `view.refs` first (fall back to
  legacy `items[id].ref` so an older project upgrading still
  shows refs).
- `items-push` response is shape-stable: `{"items": N,
  "seeds_added": [...]}`. The pushing agent reads assigned refs
  via `/view` instead.
- `MS.POST_ROUTES` catalog grew to include `/playbook` and
  `/item-move`.

### Test-fixture change

- `test_server.test_the_view_carries_tags_and_the_project_dirs`
  accepts `view.config` with `sections: {}`.
- `test_server.test_board_is_behind_the_same_gate` tolerates the
  kit's `items_tree` key in `values`.
- `test_server.test_ac33_a_fixture_copy_keeps_its_bytes_...`
  whitelists `refs.json` alongside `items.json` + `server.lock`.
- `test_server.test_an_older_kit_reads_the_side_file_as_...`
  archives the pre-1.0 package path (`console_kit`), with a
  probe script that imports either module name.
- `test_server.AGENT_POSTS` includes `/playbook` and
  `/item-move`.
- `test_onboard` tests expect one more output line (the
  gitignore append) + idempotent `kept` on rerun.
- `test_vendor` fixture matches sorted order.

### Results

- `test_kit.py`: 303 pass / 3 skip
- `test_server.py`: **285 pass** (was 42 failing)
- `test_onboard.py`: 31 pass
- `test_vendor.py`: 11 pass

## Concurrent peer fetch + total-time cap (1.21.0)

Closes the two peer-aggregator reliability items from the parallel
review.

- **Concurrent fan-out.** `Aggregator.fan_out(peers)` fetches
  every peer in a bounded `ThreadPoolExecutor` (up to
  `MAX_WORKERS = 16`). A deployment with 32 peers no longer takes
  32× `TIMEOUT_S` wall time in the worst case — just one slow
  peer's worth. Order of the returned rows matches the input
  order so the Portfolio grid stays stable across refreshes.
- **Overall deadline.** `OVERALL_DEADLINE_S = 8.0` caps the whole
  fan-out. Peers whose futures are still pending at the deadline
  yield a `"aggregator deadline exceeded"` error row, so one slow
  peer can never block the browser's `/api/portfolio` fetch past
  that cap.
- **Per-peer body-read deadline.** `_fetch_slim_http` enforces a
  total-time cap on the body read (`body_deadline = TIMEOUT_S`),
  reading in chunks against a monotonic clock. A peer that
  trickles one byte right before every socket timeout — which
  used to be able to stall the per-op `TIMEOUT_S` indefinitely —
  now fails with `"body read exceeded"`.
- **One bad peer never faults the aggregator.** `fan_out`'s
  per-future `except Exception` catches everything (not just
  `OSError` + `HTTPException`) so a protocol-level surprise from
  one peer yields an error row for that peer alone.

Smoke-tested: 5 peers return 5 ordered rows in ~17ms (all error
rows under test; a real peer run would see concurrent round-trips).

## Mobile viewport polish (1.22.0)

The console was designed around a docked wide screen (≥1024 px);
below 640 px the Portfolio grid overflowed, the six tabs crowded
off-screen, modals (palette, viewer, help) spilled past the
viewport, and some tap targets were under the ergonomic 36 px
floor. A `@media (max-width: 640px)` block fixes all of this
without touching desktop behaviour.

- **Full-width panel + safe-area insets** on notched phones.
- **36 px tap-target floor** on every button, chip, tab, toggle,
  skin cycle, ref link, snooze preset, inbox filter chip, caught-up
  dismiss, etc.
- **Horizontal-scroll tab bar** with scroll-snap and hidden
  scrollbar — six tabs no longer wrap or clip.
- **Portfolio grid stacks** to one card per row.
- **Modals fit the viewport** at `calc(100vw - 20px)` with 4-6
  vh top padding and 60-70 vh max-height on scrollable bodies so
  the virtual keyboard doesn't eat the content.
- **Shortcut help stacks** key chips over labels (single-column
  list) and gets a position-fixed sheet with `inset: 10px`.
- **Priority ribbon + Inbox rows wrap** so a long title no
  longer pushes the pill off-screen.
- **Snooze menu left-anchors** instead of right-anchoring,
  avoiding right-edge overflow.
- No desktop change: the breakpoint is `max-width: 640px` only;
  the existing `min-width: 1024px` dock rules still rule the
  owner's workstation experience.

### Trust

- The store is append-only in spirit: assignments are permanent
  per id; retired numbers block their own number from being
  given out again.
- `assign_refs` checks shape, parent prefix, and uniqueness
  before writing anything; a conflict leaves the file untouched.
- `STATE/refs.json` is written whole, dir-relative, O_NOFOLLOW —
  same path as `items.json`.

## Visible truth (1.23.0)

A five-reviewer sweep (UX principal, DevOps/SRE, product
strategist, accessibility auditor, UI code review) converged on
one gap: the console confirms nothing visibly, degrades
invisibly, and makes destructive actions look identical to
read-only ones. 1.23.0 closes the honesty gap without touching
the information architecture.

- **Visible toast surface.** Every `announce()` call now
  mirrors as a bottom-right toast (`ok` / `error` / `info`
  tones, 4 s auto-dismiss, dedupe within 1.5 s, errors stick
  until clicked, honors `prefers-reduced-motion`). The
  off-screen `aria-live` region still announces to assistive
  tech. Pre-1.23 sighted operators saw nothing when a lock,
  playbook, or dismiss succeeded.
- **`apiPost` fix.** The POST helper no longer mutates its
  caller's `body` (uses `{...body, nonce}`), parses JSON
  tolerantly (an HTML 502 page no longer surfaces as
  `"Unexpected token '<'"`), normalises every non-OK response
  to `{error}`, and accepts `{quiet, refresh}` options so
  background saves can opt out of the "Sent" announcement and
  the full-view refetch.
- **Draft-autosave is quiet and honest.** The `/draft` autosave
  used to announce "Sent" every 1.5 s of typing pauses and
  silently drop server errors — operators believed their
  draft was saved when the server returned `{error}`. Autosave
  now calls `apiPost` with `{quiet:true, refresh:false}`,
  checks `data.error`, and shows "Draft not saved — will retry
  on next edit" inline next to any compose that opts in via
  `data-ck-draft-key`.
- **Danger button variant + two-click confirm.** New
  `.ck-btn-danger` (muted red resting state, red fill on
  hover) + a `data-armed` state for one-shot irreversible
  actions. First click arms the button and relabels it "Click
  again to withdraw"; a 4 s timeout disarms if the operator
  looks away. Applied to Withdraw (destructive) while Keep
  (stop checking) stays primary.
- **Owner-visible status chip.** New `/api/status` (owner door,
  Access-gated) returns version, register, agent, boot id,
  uptime, live-poll waiters vs `MAX_WAITERS`, chat quota
  remaining in the rolling minute, age of the last cron
  minute-tick, and age of the most recent Portfolio peer
  fetch. A green/amber/red pill in the panel's top-right
  reflects it; click opens a drawer with every row. Polls
  every 30 s while the panel is open; stops cleanly on close.
- **Readiness probe.** `/health` keeps answering 200 even when
  the register is unreadable (liveness: a restart won't help,
  so no supervisor restart loop), but a new sibling `/ready`
  on the same opt-in loopback port returns 503 in that case so
  external monitors can distinguish.
- **Install-vs-upgrade banner.** `install_notice.py` now
  detects prior-version flag files in `~/.local/state/overture`
  and shows the appropriate script: first install still prints
  `register` + `start`; an upgrade prints `restart overture.service`
  only (no re-register, no stray `start`). A rollback re-fires
  because the per-version flag path shifts with `__version__`.
- **Contrast tokens.** `--c-border` darkened from `#d0d7de`
  (1.4:1 on `#fff`) to `#8c959f` (≈3.1:1) so WCAG 2.2 1.4.11
  passes on input, select, chip, and inbox-row borders.
  `--c-fg-muted` darkened from `#656d76` (4.4:1 on
  `--c-surface-alt`) to `#5a6069` (≈4.9:1) so WCAG 1.4.3
  passes on timestamps, hints, and option labels on both
  surfaces. `--c-border-light` moves to the former
  `--c-border` value so divider roles stay quiet.

### Trust

- `/api/status` holds no owner content and no secret: version
  string, counters, and the same two words of state the
  owner door already serves on `/view`.
- Status polling is scoped to the panel's open window; a
  closed dock holds no interval.
- The new `/ready` route is reachable only on the same opt-in
  loopback port as `/health`; the proxy-header / Host /
  loopback refusals still gate it.
- No new secrets, no new disk writes beyond what install
  notice already does, and no change to peer federation.

## First thirty seconds (1.24.0)

If 1.23 made the console honest, 1.24 makes it welcoming. The
UX principal and accessibility auditor both pointed at the
same moment: the first thirty seconds a new operator spends
in Overture. The dock button renders a bare "?", the empty
Inbox shows filesystem paths as "guidance", the dock takes
50% of a 27" monitor on first open, and the fragment viewer
+ palette + playbook preview + digest + shortcut help leak
focus the moment you Tab out of them. 1.24 fixes all of it.

- **First-run hero.** The Q24 muted-paragraph empty state is
  replaced with a real welcome: title, one-sentence pitch,
  the exact `/overture:items-push 'build the ingest service'`
  one-liner (with Copy), and the server's filesystem note
  folded under "How this works". Fires only when the server
  says there is nothing to show.
- **Inbox button loads cleanly.** The pre-load `"?"` becomes
  a muted inbox glyph (`✉`). On load the count renders as a
  real number — "0" for an empty inbox (muted) instead of a
  blank chip that reads as "nothing to click on". The dock
  strip still hides the count when zero (44 px is too narrow
  for text).
- **`onboard.py verify`.** A new subcommand that checks the
  full chain end-to-end: `.overture/console.env` parses,
  `cloudflared` + `curl` on PATH, `overture.service` is
  active, agent socket exists, the owner HTTPS endpoint
  returns an Access challenge (302/401/403). On full success
  prints `Overture is reachable at https://<hostname>`;
  otherwise a per-step ✓/!/✗ diagnosis.
- **Focus trap + return on secondary modals.** Fragment
  viewer, command palette, playbook preview, digest, and
  shortcut help each gained `attachDialogAccessibility`:
  Tab/Shift-Tab stay inside the dialog, focus returns to
  whatever had it when the dialog opened. The main panel's
  existing trap was refactored to share the implementation
  (`trapFocusIn`), eliminating duplicate code.
- **Textarea accessible names.** Chat compose and Delegate
  brief both gained `aria-label` (`"Message the agent"` /
  `"Brief for the delegate"`). Placeholder text alone is not
  a programmatic label and vanishes on typing. Delegate
  status moves from `role=alert` (interruptive, double
  announcement) to `role=status` + `aria-live=polite`.
- **Dock defaults to 420 px, remembered per project.** The
  pre-1.24 `50vw` default ate half of a 27" monitor on first
  open. New default is 420 px; a drag handle on the panel's
  left edge resizes live and persists to localStorage via
  `storeKey`. Keyboard: `←` grows, `→` shrinks, `Shift` for
  48 px steps, `Home`/`End` snap to max/min. Role=separator,
  with `aria-valuenow`/min/max.
- **Inbox rows become real buttons.** The recently-answered
  and awaiting-agent rows had `tabindex="0"` but no
  `keydown` handler — a keyboard operator could focus them
  but not open them. Both now have `role="button"` + Enter/
  Space activation + explicit `aria-label`. The portfolio
  self card had the same dead-focus-stop pattern; it loses
  `tabindex` entirely since it has no action.

### Trust

- The dock resize handle writes to localStorage only; no
  server round-trip. Width is clamped to [320, 60vw] on
  every apply, so stored junk cannot push the panel off
  screen.
- `onboard verify` runs read-only probes: `systemctl is-active`,
  socket existence check, `curl` with `--max-time 8`. Nothing
  touches state. The HTTPS probe hits `/` and expects an
  Access challenge; a 200 is flagged as a warning (the gate
  may not be enforcing).
- The first-run hero renders only the server-provided
  `view.items_note` as textContent — no HTML pass-through.
- No new secrets, no new network callers, no change to peer
  federation. The accessibility work is layered on top of
  the 1.23 toast + chip plumbing without touching it.

## The hero flow (1.25.0)

1.23 made the console honest; 1.24 made it welcoming; 1.25
makes it legible. The product strategist's reading of
Overture is that its most defensible mechanic — rulings
that notice when their anchor in the code no longer holds
— reads as a footnote today, and the information
architecture (Playbooks hidden in a Delegate select,
Triggers only showing when non-empty) buries half the
product. 1.25 names the moat and reshapes the tabs.

- **Living Rulings badge.** A new top-of-fold chip in the
  Inbox counts stale rulings ("3 Living rulings need
  review") and, on click, narrows the filter to stale and
  scrolls the first one into view. The stale banner inside
  each ruling card now carries a "Living ruling" tag so the
  feature has a name, not just a symptom.
- **Playbooks and Triggers are top-level tabs.** Pre-1.25 a
  playbook could only be launched from the Delegate bar's
  select; triggers appeared only as a collapsible firing
  log at the top of the Inbox. Both are now proper tabs:
  Playbooks shows each playbook's description, step count,
  Preview and Run; Triggers shows configured triggers with
  Replay plus the firing log. No new data pipes — both tabs
  read `view.playbooks` / `view.triggers` already shipped
  since 0.11 / 0.12.
- **Favorite and Chat move behind "More ▾".** The main bar
  stays sized for one row: Inbox, Feed, PRs, Playbooks,
  Triggers, Portfolio. Favorite and Chat live under a
  dropdown that still shows notes (chat's awaiting-agent
  dot folds into "More" so the operator never misses it).
  Keyboard shortcuts (`g s`, `g c`) still work; new
  shortcuts `g y` and `g t` jump to Playbooks and Triggers.
- **Rulings → PRs backlinks.** When a tracked PR's title
  mentions a qid literally (e.g. "fix(auth): resolve
  A.1/Q7"), each matching PR appears as a chip under the
  locked ruling — a merged PR renders filled ("shipped as
  #142"), an open one as an outline. Server computes the
  map in `page_payload` from `prs.json` (already in state);
  no network, no gh calls. This is the audit artifact that
  threads a merged outcome back to the decision that caused
  it — the thing nobody else is building.
- **Portfolio empty-state upgrade card.** When no peers are
  configured, the muted "No peers configured" paragraph is
  replaced with a dashed-accent upgrade card: "Add your
  first project" (or "Supervise more than one project at
  once" when self is present), the real
  `/overture:portfolio-add` command with Copy, and a link
  to the setup guide. Visually distinct so it reads as
  "upgrade seam" not "error".

### Trust

- `page_payload` computes PR backlinks from the already-stored
  PR snapshot (never talks to GitHub, never spawns gh). An
  exception is swallowed to a stderr line + `pr_backlinks:
  {}` — the page never faults for this.
- Backlinks appear only on the owner door's `/api/view`,
  never on the agent door's `/view`, because they live
  inside `page_payload` alongside drafts.
- The backlink chip's `href` is the PR's own `url` from the
  stored snapshot, which `prs.py` pins to
  `https://github.com/<repo>/pull/<number>` exactly; nothing
  typed into a PR title can redirect the chip.
- The Living Rulings badge is a pure client computation off
  `view.questions`; no new server endpoint.
- The portfolio upgrade card renders a Copy snippet; the
  text is a constant string, no server data.

## Deliberate (1.26.0)

If 1.25 was *legible*, 1.26 is *deliberate*. A five-way
advisory review (DevOps, integrations, AI web, adversarial,
strategic) converged on reordering what was originally
pitched as "ticket tracker" into Launch Idea as the headline
and tickets as its lightweight downstream artifact. The
release where **starting a thing becomes a first-class,
auditable act.**

- **Launch Idea pane.** A right-rail panel on every item that
  walks the operator through three steps: **Frame** (one-line
  idea + pitch), **Grill** (five adversarial questions —
  user, failure, scale, opportunity cost, evidence), **Spawn**
  (pick which tickets to create, edit inline, go). The pane
  reuses `attachDialogAccessibility` (focus trap + return
  from 1.24), persists its pitch through the existing
  draft-autosave key so a refresh never loses the pitch, and
  collapses on narrow viewports.
- **Tickets as children of items.** A new `tickets.py` module
  (sidecar `STATE/tickets.json`, atomic O_NOFOLLOW writes
  via `atfile`) with four kinds — `task`, `bug`, `research`,
  `grilling`. Three statuses: `open`, `blocked`, `closed`.
  Acyclic blocking is enforced server-side. Caps: 10 000
  tickets per project, 500-char title, 20 000-char body,
  32 blockers per ticket, 2 MiB total on disk. Three
  owner-door routes: `/api/ticket-create`,
  `/api/ticket-update`, `/api/ticket-close`. Tickets are
  owner-write only in 1.26; the agent-door open-up waits for
  the capability-gate work.
- **Tickets fold on every item panel.** Grouped by status
  (open / blocked / closed-collapsed), with inline close
  buttons that use `.ck-btn-danger` + two-click confirm.
  Blocking shows the parent-ticket id. A `+ New ticket` fold
  at the bottom with kind select, title, body.
- **`grill-me` skill.** New `plugin/skills/grill-me/SKILL.md`.
  Overture-native, inspired by mattpocock's `grill me`,
  reshaped around Overture's existing question/answer path —
  so every grill answered becomes a locked ruling in the
  audit trail. Not vendored; capability-gate work for
  third-party skills is a later release.
- **Branch Out wizard.** A sibling of Launch Idea on every
  item: a 3-step wizard patterned after the operator's own
  smart-prompt-maker — Describe → Dig in → Compile. Step 2
  seeds six adversarial axes (Audience, Goals, Constraints,
  Format, Style/Tone, Examples) that the operator can edit
  per-topic and answer inline. Step 3 shows the composed
  Markdown brief and offers three outputs: **Create research
  ticket** (seeds a research-kind ticket under the item with
  the full brief as body), **Spawn deliberate round** (writes
  a `message` with `intent: fork, mode: deliberate` that the
  console-fork skill picks up), or **Copy** for use elsewhere.
  Topic persists via the existing draft-autosave key so a
  refresh never loses it. Reuses the Launch Idea pane chrome;
  only one of {Launch Idea, Branch Out} is open at a time.
- **COOP header + platform guard.** Adversarial review found
  that an earlier brief claimed cross-origin isolation but
  no COOP/COEP was actually set. 1.26 adds
  `Cross-Origin-Opener-Policy: same-origin` on every response
  (always safe, no subresource impact; COEP waits for a 1.27
  iframe audit). The server also hard-refuses to start on
  non-POSIX because `fcntl.flock` is used throughout — a
  Windows run would silently fail; it now exits 2 with a
  clear message pointing to WSL.

### Trust

- Tickets live under `STATE/tickets.json`, written whole and
  atomic via `atfile.write_at` (same O_NOFOLLOW pattern as
  `drafts.json`, `refs.json`, `items.json`). The adversarial
  reviewer's concern was in-place JSONL edits mid-crash; the
  write-whole-and-atomic path sidesteps that entirely.
- Launch Idea is a browser-only wizard; the pane holds no
  state the server does not already see. The pitch persists
  via the existing `/api/draft` autosave; questions and
  tickets are the only server writes.
- Acyclic blocking is enforced on every ticket create and
  update: a `blocked_by` closure that reaches the target id
  is refused by name. A ticket cannot block itself.
- The `grill-me` skill writes through the existing
  `/question` route; nothing is added to the agent's tool
  belt and nothing executes code.
- COOP same-origin isolates the owner window from any
  cross-origin opener; no subresource relationships break.
- The platform guard refuses to start on Windows (where the
  POSIX-only `fcntl` locks would silently no-op) rather than
  corrupting STATE under a half-working runtime.

## Shipped as (1.27.0)

The integrations advisor's sharpest single call-out: Overture's
PR→ruling causal thread closed only half the audit loop. GitHub
Issues — where discussion happens, where repro steps and labels
live, where product and compliance leave their fingerprint — were
nowhere. 1.27 mirrors `prs-push` byte-for-byte with `issues-push`
and threads every GitHub Issue that mentions a `qid` back to the
ruling that caused the discussion. Plus the two security prereqs
the adversarial reviewer flagged in 1.26 as "deferred to 1.27":
real COEP cross-origin isolation and a CSRF double-submit on the
owner door.

- **`issues.py`.** New module modelled on `prs.py` to the line:
  closed schema, `snapshot_problem` validator, atomic
  `STATE/issues.json` via `atfile` with O_NOFOLLOW, a
  `from_gh` adapter that turns `gh issue list` JSON into the
  canonical shape, and a `gh_lists` helper the steward runs.
- **`agent.py issues-push`.** Mirror of `prs-push`: runs `gh
  issue list` on open and recent closed, posts the result as
  data to the agent socket's new `/issues` route. The server
  never talks to GitHub.
- **Owner-door `/api/issues`** reads the stored snapshot back,
  same shape and semantics as `/api/prs`.
- **Rulings → Issues backlinks.** `page_payload` scans every
  stored issue's title AND body for `qid` literals (bodies
  matter — repro templates and discussion threads are where
  qids tend to appear). Browser renders a sibling chip strip
  under each locked ruling labelled **"Discussed in"** (vs.
  "Shipped as" for PRs). Open issues render as outlines;
  closed render as filled grey (the discussion wrapped up).
  Each chip opens the issue via its canonical `url` from the
  stored snapshot, pinned to
  `https://github.com/<repo>/issues/<number>` exactly.
- **CSRF double-submit** on every `/api/*` POST. The server
  generates a boot-scoped token at `Console.__init__`, injects
  it into the HTML config block, and refuses any POST whose
  `X-Overture-CSRF` header doesn't match. `apiPost` echoes it
  automatically; the two direct POST sites (`/lock-all`,
  `/page-publish`) were patched in-line. Belt-and-braces with
  the existing same-origin check.
- **COEP require-corp.** Added
  `Cross-Origin-Embedder-Policy: require-corp` to
  `SECURITY_HEADERS` so every response (main page and every
  iframe-loaded resource) carries it. Combined with COOP
  same-origin from 1.26, this enables true cross-origin
  isolation — the brief claimed it in 1.19 but no header was
  actually set until now. The iframe resources already set
  `Cross-Origin-Resource-Policy: cross-origin` via
  `_send_raw`, so the nested-context load passes the browser's
  require-corp check.

### Trust

- `issues-push` runs `gh` in the steward's own process inside
  its agent jail. The server starts no process and makes no
  network call — same discipline as `prs-push`.
- The issue backlink chip's `href` is the canonical
  `url` from the stored snapshot, which `issues.py` pins to
  `https://github.com/<repo>/issues/<number>` exactly; nothing
  typed into an issue title or body can redirect the chip.
- Issue bodies are capped at `MAX_BODY = 64 KiB` and the
  pushed snapshot at `MAX_FILE = 3 MiB`; a push over cap is
  refused by name, nothing is written.
- CSRF tokens are boot-scoped and never written to disk; a
  restart invalidates every open page's token, which the live
  loop already surfaces as a boot change. The token is
  readable from `document.cookie` only on same-origin
  (actually, we never set it as a cookie — the token travels
  only in the HTML's config block, so an attacker's
  cross-origin page cannot read it even with a stolen Access
  cookie).
- COEP require-corp blocks any accidental cross-origin
  subresource from loading in the console. Everything the
  console needs is inlined or served under `/api/*` from the
  same owner door.

## Active (1.28.0)

The adversarial reviewer's 1.26 veto on uncapped agent spawn
has been sitting as a 1.28 prereq since; this release lands
it. Plus the operability counterpart: operators can see
which named agents are currently holding a mark on an item,
without a terminal and without reading `working.json` by
hand.

- **Real spawn semaphore.** Pre-1.28 `MAX_WORKING=32` was
  only an input validator on one `/working` POST; an agent
  could fan out `N` buckets each at the cap, so a
  Launch-Idea or Branch-Out could in principle leave 100
  agents marked active. 1.28 adds two real caps enforced on
  every write: `MAX_WORKING_GLOBAL=64` (total marks across
  every agent × every item) and `MAX_WORKING_PER_ITEM=8`
  (distinct agents allowed to hold a mark on one item). A
  `/working` POST that would push either over returns `429`
  by name with a one-line message telling the operator what
  to do (close an item, or wait for an agent to sync).
  Enforcement happens under `_working_lock` so concurrent
  writes cannot squeeze past.
- **"Active agents" fold** on every item panel. Reads
  `cursor.working_by` (already served; no new network path)
  and lists every named agent currently holding a working
  mark on this item, with a pulsing green dot, the agent's
  name (or "unnamed session" for the untagged bucket), and
  "since &lt;relative time&gt;". Hidden entirely when nothing is
  active, so the fold is zero-noise. Pulse honors
  `prefers-reduced-motion`.
- **Status chip exposes the caps.** `/api/status` now carries
  `working_global`, `working_global_max`, and
  `working_per_item_max`; the drawer renders
  **"Agents at work: 7/64 (max 8/item)"** so operators
  discover the cap by looking at the status chip before they
  trip it.

### Trust

- Both caps are enforced *before* `_write_working`, with
  the lock held. A refused write writes nothing — nothing is
  half-marked.
- The owner door still has no `/working` route; `/working`
  is agent-door only (Unix socket, 0600 under a 0700 dir).
  The owner CANNOT bump another agent's bucket, so the cap
  cannot be bypassed through the gate.
- The 429 message holds no owner content and no secret: it
  carries the item id (same shape already shown in every
  Feed row and inbox title) and the two caps, which are
  constants in the kit.
- The "Active agents" fold renders bucket names (agent
  identifiers) that are already visible across the Feed and
  every question card via `agentLabel`. No new data surface.
- Status counters are owner-door-only; `/api/status` has
  always been Access-gated.

## Prototype (1.29.0)

The mattpocock integration backlog's last piece. Overture's
visuals have carried HTML and Mermaid since 0.8.0; they
*were* prototypes without the name. 1.29 adds the two things
that make them feel like a first-class prototyping surface
and closes the one adversarial-review veto that was still
only half-held: v0-style variant chips in the UI, and
defense-in-breadth HTML sanitization in the server.

- **Variant chips.** When an item carries more than one
  visual, each visual's title bar now shows a muted
  `v3 of 7` pill with Prev / Next buttons that walk the
  item's siblings in oldest-first order. Click Prev or Next
  to scroll + focus the chosen variant. Honors
  `prefers-reduced-motion`. Pre-1.29 the operator had to
  scroll the panel by hand and count — fine for 2, lost for
  10. Pattern reference: v0's left-rail version stack,
  Figma AI's variant branches.
- **HTML sanitization at write-time.** The adversarial
  reviewer flagged in 1.26 that the sandboxed iframe is the
  *first* line of defense but belt-and-breadth is cheap —
  a stripped-down HTML cannot even reach the iframe. A new
  `visuals.sanitize_html` strips `<script>` / `<style>` /
  `<iframe>` / `<frame>` / `<frameset>` / `<object>` /
  `<embed>` / `<form>` / `<applet>` elements with their
  content, strips `<meta http-equiv=refresh>` and `<base>`
  openers, strips every `on*=` event-handler attribute,
  and strips `javascript:` / `vbscript:` / `data:` URLs on
  `href`, `src`, `action`, `formaction`, and `xlink:href`.
  Case-insensitive, pre-storage, byte-count reflected in
  the stored sha256. The sandbox still enforces its CSP
  (`default-src 'none'`, no `allow-scripts`) — if either
  layer were bypassed, the other would hold.

### Trust

- Sanitization runs *before* the sha256 is computed and the
  content is written, so the stored hash is the clean one.
  A replay with the unsanitized source will not match and
  will be refused by name — this closes the "same qid, two
  bytes" ambiguity.
- Nothing new ships at the network layer. The iframe
  sandbox contract (sandbox="" for HTML, allow-scripts only
  for Mermaid against the vendored lib, never
  allow-same-origin) is unchanged.
- Variant chips are pure client computation off
  `view.visuals[itemId]`; no new endpoint.
- `walkToVariant` scrolls and focuses only inside
  `panelEl`; nothing cross-document.
- `CSS.escape(v.id)` is used to build the DOM selector so
  a malformed visual id (vanishingly unlikely — it's a 24
  hex chars store record id — but still) cannot inject
  attribute-selector syntax.

## Shift (1.30.0)

Two long-standing recommendations from the five-reviewer
advisory finally land. The product strategist's **Operator
Shift view** gives the operator a report they'd screenshot
for a cofounder or team review; the AI-web guru's
**agent-mediated grill** turns the 1.26 static-axis Launch
Idea step 2 into a round-trip with real agent attention.

- **Operator Shift modal.** Reachable from the status chip
  drawer and the command palette (`Ctrl+K` → "Operator
  shift"). Picks a window (Today / This week / This month)
  and composes a Markdown summary from `view.questions` +
  `view.pr_backlinks` + `view.issue_backlinks`:
  - **N rulings locked** in the window
  - **N items advanced** (items with a new lock)
  - **Median time-to-answer** (question.ts → head owner
    lock.ts, formatted as seconds/minutes/hours/days)
  - **N merged PRs tied to a ruling** (deeplinked)
  - **N closed issues tied to a ruling** (deeplinked)
  - **N Living rulings still need review** (not scoped to
    the window — "what still waits on you")
  - Lists for each: item ids, PR/issue chips with URLs
  Copy button sends the whole Markdown to clipboard. Browser-
  only compute; no new server endpoint, no new data pipe.
- **`intent: grill`** added to `schema.INTENTS`. The owner
  writes `/message` with `intent: grill` on an item,
  carrying the pitch; the fleet picks it up and the
  `grill-me` skill writes N adversarial questions back
  through the regular `/question` path. Because the grill
  intent is in `OWNER_INTENTS`, only the owner door can
  write it — an agent cannot forge a grill request on
  itself.
- **"⚡ Grill with agent" button** in Launch Idea step 2.
  Writes the grill message. Static axes stay — the two
  augment each other: static axes for speed, agent grill
  for depth.
- **`grill-me` skill updated** to recognise the new
  `intent: grill` trigger alongside the pre-1.30 slash
  command entry point. Each question answered becomes a
  locked ruling, so the audit trail picks up the reasoning
  automatically.

### Trust

- Shift is a pure client computation. Nothing is sent to the
  server. The composed Markdown lives in a textarea the
  operator can edit before copying.
- `/message` with `intent: grill` is a regular message write:
  same `_check_message` guards (owner intent → `by: owner`,
  move/fork field exclusion), same per-minute throttle, same
  `MAX_TEXT` cap. No new attack surface.
- Agent-authored grill questions arrive via the existing
  `/question` route and face every schema check the regular
  question path enforces.
- The grill button is disabled while in flight; a failure
  surfaces as a sticky error toast, not a swallowed error.

## Patch (1.30.1)

Five-reviewer post-1.30 pass surfaced real correctness bugs
and defense-in-breadth gaps. 1.30.1 lands them.

- **el() ignores false/null/undefined attrs.** Pre-1.30.1
  `el('button', { disabled: null })` emitted `disabled="null"`
  (truthy), permanently disabling the variant Prev/Next
  buttons shipped in 1.29. One-line fix with wide impact.
- **Status chip + dock handle survive a redraw.** Pre-1.30.1
  these were children of `panelEl`, which `renderPanel`
  wipes; after the first open the status chip polled
  `/api/status` into a detached DOM node. Now re-attached
  after every clear.
- **Launch Idea / Branch Out survive a live tick.** Same
  parent-is-wiped bug; the pane now re-attaches after every
  render. `openPanel` closes the pane when the item changes
  so a spawn can't write under the wrong item. `closePanel`
  tears down any open pane and strips the dead 380px gutter.
- **Tickets fold redraws after create / close / spawn.**
  Pre-1.30.1 the "Ticket created" toast fired but the list
  stayed empty — `apiPost` refetched the view but the live
  loop skipped the redraw. Explicit `renderPanel()` after
  every ticket write.
- **fmtAge collision fixed.** Two function declarations
  named `fmtAge` collided via hoisting; the status drawer
  silently got the milliseconds variant when it needed
  seconds. Renamed the second to `fmtAgeMs`.
- **`sanitize_html` hardened.** Loops up to 8 passes to
  defeat nested-tag reconstructions
  (`<scr<script></script>ipt>`). Capped leading whitespace
  at `\s{0,8}` against CPU-DoS. Added `<svg>`, `<link>`,
  `<xml-stylesheet>` to the strip list. `on*=` boundary
  includes `/`, `"`, `'` so `<img/onerror=…>` no longer
  slips. `javascript:` URLs on unquoted attributes are now
  stripped. **Note**: the CHANGELOG for 1.29 overstated this
  as "defense in breadth"; the sandboxed iframe
  (`default-src 'none'` + `sandbox=""`) is still the real
  control.
- **CSP tightened on main page.** Added `object-src 'none';
  base-uri 'none'`. `script-src 'self'` deferred to a release
  that threads a per-request nonce into the inline script
  injection — Console inlines all its JS via `publish.py`.
- **CSRF compare → `hmac.compare_digest`.** Constant-time
  compare closes the timing side-channel on the token.
- **Agent-door `/playbook` writes `by="agent"`.** Pre-1.30.1
  an agent that could author `.overture/playbooks/*.json`
  could run it via the agent socket and forge owner-only
  intents under `by: owner`. The schema's OWNER_INTENTS
  check now refuses forged intents by name instead of
  trusting the handler.
- **`_write_working` + `set_cursor` via `atfile.write_at`.**
  Both pre-1.30.1 wrote to a fixed `.tmp` sibling with
  `write_text` — no `O_NOFOLLOW`, no `O_EXCL`, no fsync, no
  lock. Two concurrent `/cursor` POSTs raced on the same
  temp, and a symlink planted at the path would be followed.
  Both now use the same atomic path as `drafts.json`,
  `tickets.json`, `issues.json`.
- **Tickets load no longer deletes malformed rows.**
  Pre-1.30.1 any row that failed the current shape check was
  dropped on load; the next save rewrote the file without
  it. If an operator ever upgraded past a kind rename, the
  older tickets disappeared. Now `load` keeps all rows with
  a well-formed id key; `as_view` filters at render time.
  A stderr line reports how many rows the parse ignored.
- **Ticket id bumped from 32 → 64 bits.** `token_urlsafe(4)`
  had a birthday-collision horizon around 93k tickets.
  `token_urlsafe(8)` pushes it past 4 billion.

### Trust

- Every file-system write still goes through `atfile.write_at`
  (O_NOFOLLOW on dir fd, O_EXCL temp file, fsync, rename).
  The `_working_lock` now covers both the cursor and the
  working write so they are one atomic sequence.
- CSRF token lifetime is unchanged (boot-scoped). A rotation
  endpoint remains a 1.31 item.
- Sanitizer is clearly labeled as breadth, not boundary. The
  CSP sandbox around every stored visual is unchanged.
- Agent-door `/playbook` continues to run the owner's own
  playbooks from the agent socket; what changed is only the
  authorship of the resulting message records. `_check_message`
  still refuses OWNER_INTENTS from `by: agent`, so forged
  owner intents like `fork` cannot land through this path.

## Hardening (1.31.0)

Lands the five items the 1.30.1 patch deferred as "needs more
than a one-line fix" — real security boundaries, not just
breadth. The regex sanitizer is replaced; the inline script
runs under a nonce'd CSP; CSRF can be rotated without a
restart; backlink chips carry author provenance; grill-origin
questions are visibly distinct from questions the agent raised
on its own.

- **Parser-based `sanitize_html`.** The regex pipeline through
  1.30.1 had plausible bypasses (unquoted `javascript:`,
  entity-encoded schemes, nested-tag reconstruction,
  parser-differential tricks on `<\s*`). 1.31 replaces it with
  `html.parser.HTMLParser` + an allowlist rewriter. Any tag
  not on the allowlist is dropped; `<script>` / `<svg>` /
  `<math>` / `<noscript>` / `<template>` drop their content
  too (rawtext context); URL schemes are allow-listed
  (`http`, `https`, `mailto`, `#frag`, relative, `data:`
  for images only). `on*=` attributes are refused regardless.
  `data-*` attributes pass through (inert). Anchors get
  `rel="noopener noreferrer"` enforced. The parser tokenises
  exactly as the browser does — the whole parser-differential
  bypass class is eliminated. Sandboxed iframe is still the
  first line; this is now a real second line.
- **Per-request CSP nonce** on the inline console script.
  Pre-1.31 the main page's CSP was only `frame-ancestors
  'none'`, which meant any same-origin DOM-XSS could read
  `config.csrf` and read/write everything the operator could.
  Now the server generates a fresh nonce per `GET /` or
  `GET /index.html`, emits `script-src 'nonce-<nonce>'` in
  the CSP header, and tags the inline `<script>` with
  `nonce="<nonce>"`. A DOM-injected `<script>` without the
  nonce is refused by the browser.
- **`POST /api/csrf-rotate`** generates a fresh CSRF token
  and bumps `_boot` so every open page sees a boot change on
  its next long-poll wake and reloads. Pre-1.31 a leaked
  token had no remedy except a server restart.
- **Backlink chips carry author.** The security review flagged
  that anyone with a GitHub account could inject a qid literal
  into an issue body and have it render as "Discussed in" on
  a ruling — integrity, not XSS. Chips now show `#142 by
  @alice`; label changed from "Discussed in" to
  **"Mentioned in"** and from "Shipped as" to **"Shipped:"**.
- **Grill provenance badge.** `page_payload` computes
  `view.grill_qids` — qids whose question was written on an
  item inside an open grill cycle (an owner `message
  intent=grill` with no closing `message intent=process`
  since). Each matching question shows a `⚡ GRILL-ORIGIN`
  chip, so the operator sees that a question is agent-authored
  **in response to their own grill request**, not raised
  independently. Closes the "owner social-engineering via
  agent-authored question" asymmetry the adversarial reviewer
  called out.

### Trust

- The parser-based sanitizer refuses to raise out of
  `sanitize_html`; a parse error falls back to a tag-strip
  (everything becomes text). This is strictly safer and
  bounded by the 256 KiB input cap in `add_visual`.
- The CSP nonce is per-request, generated via
  `secrets.token_urlsafe(16)` (≈96 bits). It never persists
  to disk and never travels off this response.
- `rotate_csrf` is under `_lock` so an in-flight write that
  passed the old token completes before the swap.
- Backlink chip URLs are now double-validated:
  `issues.py`/`prs.py` pin them to canonical GitHub URLs on
  push; the browser additionally refuses any URL that doesn't
  start with `https://github.com/`.
- `view.grill_qids` is a pure client-side display signal; the
  rendering decision is browser-side. The audit trail is
  unchanged: each grill-origin question is still a regular
  `question` record.

## Unknown fields refused at fold (1.55.1)

- **`fold.check_entry` refuses a field the protocol does not define**, at a
  ruling file's top level and on a locked answer, by name ("unknown
  field(s) …"). This closes the known limit 1.55.0 disclosed: PROTOCOL.md
  section 13 says a reader SHOULD refuse one, and the schema's `rulingFile`
  and `lockedAnswer` already did. An earlier answer was refused this way
  already.
- No file `fold.py export` wrote is affected: every version wrote only
  fields the protocol defines (checked against the export code and the
  repository's history). A ruling file someone edited by hand to add a
  field is now refused at fold, naming the field, instead of folded with
  it ignored.
- Two ruling vectors (one per place) and a drift test that holds fold's
  two key sets equal to the schema's. Each new check was shown red by
  re-applying three mutants (either check removed, `fork` dropped from the
  top-level set); this is the author's run, not yet a clearer's.

## The protocol, published (1.55.0)

Wave 4, the owner's P1 to P5 (2026-10-21, every ★): the question, ruling and
`valid_if` format is now a versioned spec, so another tool can write or check
rulings without running Overture. The rulings are in OPEN-DECISIONS.md, "Wave
4: the protocol".

- **`docs/spec/PROTOCOL.md`, protocol 1.0.** It covers the four decision
  records (`question`, `answer`, `lock`, `anchor`): the store's rules, how a
  record's id is derived, with a worked example, and the four conditions with
  what makes a ruling fresh, stale or unchecked. It also covers the committed
  ruling file that `fold.py export` writes and the CI check reads (P5), and
  how the spec is versioned. 1.0 is `schemaVersion` 1, and a minor version
  adds only optional things. `message`, `transcript` and `visual` records stay
  the console's own (P1).
- **`overture-protocol-1.schema.json`** (JSON Schema 2020-12). It checks one
  record, and a ruling file against `#/$defs/rulingFile`. Section 9 of the
  spec lists the checks it cannot express.
- **Conformance vectors** (`docs/spec/vectors/`): 53 records, 14 store
  sequences with each id and seq, and 31 ruling files. Each one is valid or
  invalid, says whether the schema alone catches it, and gives the
  reference's error. `spec_vectors.py` builds them from hand-written verdicts
  and stops if the kit disagrees with one.
- **`test_spec.py`** (stdlib only, P2) holds the kit to the spec. Every vector
  gets `schema.validate`'s, the store's and `fold.check_entry`'s verdict. The
  JSON Schema gets the verdict each vector claims, through a small checker
  that refuses any keyword it does not implement. Its limits, shapes and
  lists equal the kit's constants. The prose states the kit's limits and the
  symbol hash's name (`overture-symbol-1`). The committed vectors equal what
  the generator builds. 20 mutants across the schema, vectors, prose,
  checker and kit were each killed.
- **The release zip carries the spec** under `overture/spec/` (P4), so a
  release's attestation covers the spec it implements.
- Known limit: `fold.check_entry` does not yet refuse unknown fields at a
  ruling file's top level or on a locked answer. The spec says a reader
  SHOULD, and the schema does.
- Docs: mcp-and-ci.md "The protocol, published (1.55)", the README, and
  STRATEGY.md (all three of the board's limits are now answered).
- **Review fixes.** An independent review found places where the spec, the
  schema and the kit disagreed. Each is closed, and a vector failed before
  each kit fix:
  - whitespace is one named set (`str.isspace`), and the schema spells it
    out instead of ECMA-262's `\S`, which differs on U+FEFF, U+001C to
    U+001F and U+0085;
  - a ruling file's forked, starred question needs `star_by` in the schema
    too;
  - the store refuses an unpaired surrogate by name; it used to fail inside
    the id hash;
  - `schemaVersion: true` is no longer read as 1;
  - in ruling files, `picked_star: 0` is no longer read as `false`, a
    timestamp takes only ASCII digits, and a locked answer's `reason` must
    not be blank.

## Symbol anchors (1.54.0)

The owner's B1 and K1 to K3 (2026-10-20, every ★): a ruling can rest on
one function, method or class, and it still applies after that definition
is renamed or moved. The architect defaults are in OPEN-DECISIONS.md,
"Symbol anchors".

- **A `symbol` condition.** An agent writes `"path::Class.method"` in
  `valid_if`, and the server fills in the hash when the question is asked.
  The stored form is `{kind, path, symbol, sha256}`. `SCHEMA_VERSION` stays
  1; an older kit refuses the kind by name.
- **`symbols.py`** (stdlib only, safe to import from a hook). Python is read
  through `ast`. JS/TS, Go, Rust, Java and C# are read by their definition
  lines, with string, comment and template awareness. The hash covers the
  body with comments and spacing normalised, except inside literals, and
  leaves out the definition's own name so a rename can be found. Anything
  the kit cannot read with certainty is *unchecked*, never guessed: two
  definitions with one name, a later rebinding of the name, a file that is
  not UTF-8 or is over 1 MiB, or over 5000 definitions. With `--base`, a
  cited file that read cleanly at the base and cannot be parsed at head is
  *broken* instead.
- **The CI check follows a move (K3).** Rename detection is on. When a
  ruled definition is gone, the changed files of the same language are
  searched for the same body. Exactly one match: the ruling holds, and is
  listed as **moved** (`old path::name -> new path::name`), with the
  `propose-anchor` command. None: broken. Several: unchecked, which fails
  under `--strict`.
- **The console stays strict.** A moved definition shows as stale until
  the owner confirms the steward's proposal; `propose-anchor --symbol
  PATH::NAME` makes one. Nothing is rewritten silently.
- **The lookup before an agent edits** names the definitions a ruling
  rests on, and warns when the edit would change one's body or remove it.
  It parses each file once per call.
- **`agent.py symbol-at PATH:A-B [--json]`** prints the definition that
  holds a question's source lines. It needs no console, and exits 1 when no
  single definition holds them.
- Docs: inbox-and-rulings.md "Rulings on a definition (1.54)",
  mcp-and-ci.md, the console-ask skill, the README.
- **Review fixes.** An independent review found ways a real change could
  keep holding. Each is closed, with a test shown red before its fix:
  - whitespace inside a string, template, regex, Go raw string or C#
    verbatim string is code;
  - in a file with JSX, and inside C# interpolation, comment-like text
    counts;
  - after `)` or `]`, a `/` keeps the rest of its line verbatim;
  - a file that is not UTF-8 is unchecked;
  - an unreadable file elsewhere in the change never turns a broken
    ruling into an unchecked one;
  - a regex that backtracked for 16 s on a hostile 1 MB file is bounded;
  - a redefinition later on a line, or any Python rebinding of the name
    after its definition, makes it unchecked;
  - a Python definition under `try`, `if`, `with` or a loop, whose scope
    binds the name anywhere else (the `try: from fast import f` /
    `except ImportError: def f` fallback), is unchecked;
  - a JS/TS reassignment of the name (`f = …`, `var f = …`, `this.m = …`,
    `A.prototype.m = …`) makes it unchecked, while a parameter or local of
    the same name in another function does not;
  - a cited file that read at the base and no longer parses is broken, and
    only when its definition resolved cleanly there;
  - a redefinition never hides a changed body: when no definition of the
    name still has the ruled hash, the ruling is broken, not unchecked;
  - a file name from the change can no longer forge a line in the report;
  - the `propose-anchor` command is printed only when every value is
    plain (`[A-Za-z0-9_./:-]`), so no shell, POSIX or cmd.exe, runs
    anything from a crafted name.

## Windows, honestly (1.53.2)

On native Windows the console cannot run, and Overture now says so plainly
everywhere, instead of failing with a traceback.

- **Every kit command refuses by name there.** `agent.py`, `mcp_server.py`,
  `fold.py`, `rulecheck.py`, `server.py` and `hosting.py` print one line on
  stderr and exit 2: the console needs a POSIX system, so run Claude Code
  inside WSL. The check runs before any import that fails there; the old
  checks in `server.py` and `hosting.py` were never reached.
- **A failing PreToolUse hook never blocks a tool.** `ask_guard.py` and
  `ruling_lookup.py` carry `"onFailure": "continue"`, so a missing `python3`
  never costs an edit or a question.
- **Onboarding on Windows says to go to WSL.** It prints that once, in place
  of commands with Windows paths a WSL shell cannot run. `verify` no longer
  raises there.
- **The install banner tells the truth on Windows.** The console and its
  agent side run in WSL; use the Claude Code CLI there. Claude Desktop loads
  the plugin only in native sessions, where the console is not reachable.
  The hooks need a `python3` on PATH.
- **A prerequisite scan on install.** The first session after an install or
  upgrade lists what this machine is missing (Python, git, gh, systemd or
  launchd, and WSL, Git for Windows and `python3` on Windows), each with the
  command for your platform where one command is right, and a link. A last
  line counts what is missing. Nothing is printed when nothing is missing.
  `onboard.py prereqs [--json]` runs it again, route tools included, and
  console-onboard runs it first. On native Windows it always lists "Claude
  Code inside WSL", so onboarding stops there and says to onboard in WSL.
- **scaffold-dashboard** runs the plugin's own kit, not a fixed
  `~/.local/share/overture` path.
- **Docs.** Hosting has a Windows section; MCP, INSTALL and the README say
  Claude Code runs in WSL on Windows.

## Hooks on Windows (1.53.1)

A report from a Windows 11 machine (Store Python, Overture 1.49.0): every
hook failed at import, because `session_start.py` imported `fcntl`, which
native Windows Python does not have. Claude Code then showed a hook error on
every session and prompt.

- **The hooks load on native Windows Python.** `fcntl` and the open flags
  Windows lacks (`O_NONBLOCK`, `O_NOFOLLOW`, `O_CLOEXEC`) are optional in
  `session_start.py`. Where a read refuses a symlink, a missing `O_NOFOLLOW`
  is made up for by checking the path first. In a project that is not
  registered, which is every project on native Windows (the registry holds
  POSIX paths), each hook says nothing and exits 0, as it does elsewhere.
- **`/overture:as NAME` there says why it records nothing:** naming a
  session needs POSIX file locks, so run Claude Code inside WSL, where the
  console runs. Before, it said only "failed (AttributeError)".
- **The ruling lookup (1.52) stands down there too.** It loads the kit's
  file reader, which needs the same flags; it now fails open at import, so
  an edit never shows a hook error.
- The server side is unchanged: it runs in WSL on Windows (Hosting).
- Tests: `test_kit.WindowsHookTests` runs each hook with `fcntl` and the
  three flags taken away, as on Windows. It also holds POSIX to what it
  did before: each open keeps its exact flags, and a broken kit still shows
  as a hook error there instead of a silent stand-down.

## Area notes (1.53.0)

The owner's M1 to M4 (2026-10-20, "do recommended"): what an agent should
know about a folder is kept in that folder, short, and checked against the
code. The architect defaults are in OPEN-DECISIONS.md, "M1-M4 as built".

- **Area notes.** A `CLAUDE.md` of at most 10 lines in each folder a
  project declares in `.overture.json` `"areas"`, read by Claude Code only
  when a session works there. Facts with their reason; a ruling or lesson is
  cited by id, never copied. The first line names the commit the facts were
  checked at: `<!-- area: AREA · checked: SHA -->`. Overture's own: `docs`,
  `plugin/hooks`, `plugin/kit`, `plugin/kit/overture`, `plugin/skills`.
- **`agent.py notes check [--root DIR] [--memory DIR] [--json]`** (no
  `--state` needed) names a stale note (its folder's committed files changed
  since that commit; nested declared folders and the note itself do not
  count, nor do the files `"notes_ignore"` lists, such as the version bump's;
  after a squash merge the last commit that changed the note's header
  counts), an
  undeclared one (a `CLAUDE.md` in a folder not declared; ignored folders are
  never looked at), and a malformed one. The top-level `CLAUDE.md` is said as
  "always loaded". `--memory DIR` checks `DIR/MEMORY.md` for links to missing
  files and memory files no line links. Exit 0, 1 on a finding, 2 refused by
  name. It writes nothing; `notes stamp AREA` stamps one re-read note at
  `HEAD` (its first line only, refused over uncommitted changes in that
  folder). Its git goes through the seam, so inside the server it refuses
  (Q23).
- **The steward checks once a day**, after its first heartbeat and only when
  no signal waits, as it prunes worktrees; the counts ride `watch.json`
  (`area_notes`, numbers only). A project with no `"areas"` is left alone; an
  error is said once and never stops the watch. No console view (M3 waits).
- **Packaging.** `build_zip.py` leaves every `CLAUDE.md` out of the zip;
  `verify_vendor.py` neither requires the kit's notes in a vendored copy nor
  counts a project's own note beside it as drift. `release.py` runs the
  notes check first and refuses the release, naming each note, until it
  passes.
- Docs: docs/features/automation.md "Memory in its own place: area notes
  (1.53)", the RUNBOOK ("`notes check` names a stale, undeclared or
  malformed note"), the README. Also fixed: automation.md cited Q24 for the
  server's no-git rule, which is Q23.
- **Review fixes.** The live check of this repository's own notes left the
  unit suite for `release.py`'s gate (C1). A shallow clone is refused by name
  (C2). After a squash, the base is the last commit that changed the note's
  header, so a typo fix elsewhere in the note no longer hides earlier changes
  (C3). Stamping is its own verb, `notes stamp AREA`, and refuses a folder or
  note that is a symlink out of the checkout (C4, S2). A watch run from
  another folder keeps the heartbeat's counts (C5). Every name the check
  prints passes the lookup's `_short`, so an escape or bidi character shows
  as `?` (S1). A memory link leaving its folder is named and never looked up
  (S3); `%20` and `<a b.md>` links are read as the file they name (C8).
  `"notes_ignore"` names committed files only, never a folder or a whole
  area, so a release's version bump does not make a note stale. Clearing
  and mutation testing added boundary tests (10 lines, 20 changed files
  shown) and closed every surviving mutant.

## Ruling lookup before an agent edits (1.52.0)

The owner's R1 to R4 (2026-10-19, every recommendation): before an agent
edits a file it reads the owner's rulings on that file, and is warned by name
when the edit would break one. It is never blocked. The architect defaults
L1 to L9 are in OPEN-DECISIONS.md, "R1-R4 as decided".

- **A PreToolUse hook on Edit, Write, MultiEdit and NotebookEdit**
  (`plugin/hooks/ruling_lookup.py`, registered projects only) adds the
  rulings to the agent's context, each labelled **holds on this file (this
  edit can break it)** or **cites this file (its condition is elsewhere;
  context)**; `--json` keeps the bare `holds` and `cites`. It prints `additionalContext` only, never a permission
  decision, so the edit goes through the owner's normal prompt. Shown once
  per session per file, and again when the rulings change; at most five
  rulings and 2000 characters, then the command for the rest, each part of
  it shell-quoted. A would-break warning is said every time, first, and
  always fits. The note says to go against a ruling only by asking the owner
  a new question (`agent.py ask`). A stale ruling is marked; a withdrawn,
  untracked or superseded one is not listed.
- **Would-break.** The hook works out the file after the edit (Write's
  content, Edit's replacement, MultiEdit's edits in order) and names each
  ruling whose excerpt would be gone or whose file hash would change, in
  three lines: what it breaks, why, and what to do. Only a condition that
  holds now and fails after the edit is named; a file that cannot be read
  now (absent, unreadable), a notebook, a file past 2 MiB, or an
  `old_string` that is not there is informed only. Quotes inside a quoted
  excerpt or question are shown as `'`, so they cannot end the quote.
- **Live, with fallback.** The rulings come from the console server's agent
  socket (`POST /rulings`, the one server's `/p/<project>/rulings` with its
  token), the whole exchange within one 1.5 s deadline; otherwise from the
  rulings committed in the checkout, and the note says so. A 401, 403 or 5xx
  answer counts as no answer and falls back too; only a 400 naming its error
  silences the hook. A bad committed file is skipped and named, the rest
  still read, and at most 500 files (16 MiB) are read, "(first N ruling
  files)". Only the registered checkout's rulings are said: a file in another
  repository gets nothing, and a 1.50 agent worktree is mapped to its main
  checkout by its `.git` file only when git's back link
  (`.git/worktrees/NAME/gitdir`) agrees, with no git run. Any other error
  prints nothing.
- **`agent.py rulings --path P [--path DIR/] [--json]`** and an MCP
  `rulings` tool give the same entries. Paths are project-relative; `..`,
  absolute paths and secrets files are refused by name.
- **Opening another item fades it in all the way** (a fault since 1.48): the
  redraw when its fetch lands carries the fade on instead of cutting it off.
- `overture/lookup.py` holds the matching, shared by all three; rulecheck's
  reading of an export's deciding conditions moved there.
- Docs: docs/features/inbox-and-rulings.md, mcp-and-ci.md, the README's hook
  table, RUNBOOK ("The ruling lookup says nothing"), the console-process and
  console-ux skills.

## The console as a macOS service (1.51.0)

The owner's D2 (B, "Go" on 2026-10-19): the command Linux and WSL got in
1.33 now works on a Mac, through a launchd LaunchAgent. The architect
defaults A1 to A9 are in OPEN-DECISIONS.md, "D2 as decided".

- **`server.py service install [--start]`** on macOS writes
  `~/Library/LaunchAgents/overture.console.plist` with `plistlib`: the
  server as an argv array (a space in a path is fine; a path that is not
  absolute or holds a control character is refused by name), `RunAtLoad`,
  `KeepAlive` on a failed exit, a 10 s `ThrottleInterval`, and the
  daemon's log for its output. `--start` boots out a loaded job first,
  then runs `launchctl enable` and `launchctl bootstrap gui/<uid>`.
  Without `--start` nothing is loaded until your next login. The plist is
  written whole at 0644 (a temp file and a rename). Over SSH, or with
  nobody logged in at the Mac, a failed bootstrap says launchd needs your
  login session; there is no fallback to another domain.
- **`service uninstall`** boots the job out and removes the plist; a job
  still loaded after its plist was deleted by hand is booted out too.
- **`status`, `health` and the one-server gate** read `launchctl print` by
  line name: `running` with its pid, `spawn scheduled`, a failed last exit,
  or not loaded. A daemon is refused while the job runs. `health` checks no
  linger on a Mac: a LaunchAgent runs while you are logged in.
- **Every hint names the platform's command**: `launchctl bootout`,
  `kickstart -k` and `print` on a Mac, `systemctl --user` elsewhere. A
  version-skew problem from a service now names its restart command, and
  so does the plugin's upgrade notice. On a Mac that notice names one
  command, `server.py service install --start` from the new kit, which
  points the LaunchAgent at it and restarts it.
- **`deploy/install.sh` refuses on macOS** by name (its per-project units
  are systemd) and points to `server.py service install`.
- **The PRs tab no longer stays on "Loading…"** when the page redraws while
  it loads (a fault since 1.0); the projects list had the same fault, also
  fixed.
- Docs: INSTALL.md (macOS prerequisites and the logged-in note,
  `cloudflared service install` for a tunnel), docs/features/hosting.md,
  RUNBOOK ("macOS: the launchd service").

## Agent worktrees (1.50.0)

The owner's choices of 2026-10-16 (OPEN-DECISIONS.md, "Agent worktrees", W1
to W4): an agent's work that changes files happens in its own worktree, the
console shows where each agent works, and two agents on one item are warned
about, never blocked. The server still starts no git (CONSOLE-kit/Q24):
worktrees are made, listed and pruned in the agent's own process, and the
server only stores and shows the branch it is told.

- **`agent.py worktree new --kind KIND --item ITEM`** (W1, W2) makes the
  agent's worktree at
  `~/.overture/worktrees/<project>-<hash>/overture/<kind>/<item>`, on the
  branch `overture/<kind>/<item>`, cut from `origin/main` after a fetch (from
  the remote's default branch when there is no `main`, and it says so), and
  prints the path (`--json` for skills). `<hash>` is the first 8 hex of the
  sha256 of the main checkout's real path, so two repositories in folders of
  the same name never share a registry. `KIND` is one of `ticket`, `visual`,
  `ux`, `playbook`, `round` and `fix`; the item follows the server's id rules,
  and git's on top. Refused: a home under `/mnt/` (a Windows drive from WSL),
  a worktrees or project folder that a symlink leads out of the home or onto
  `/mnt/`, a folder in the way that is not a registered worktree of this
  repository, and a session with **no agent name** (unnamed sessions share
  one set of marks, so they would share one worktree): the refusal leads
  with the fix, `agent.py --as agent-5 --state STATE worktree new ...` (or
  `OVERTURE_AGENT`, or `/overture:as`). The same agent asking again for the
  same item and kind gets its worktree back, unless that worktree's PR merged
  or closed: then it gets a fresh `-N` one, and is told the old one waits for
  prune. A PR counts as the worktree's only when its head is the worktree's
  `HEAD`, so an old PR of a freed branch name is not mistaken for it. It marks
  the item worked on, with its branch.
- **Another agent on the item** (W4) gets the next branch
  (`overture/ticket/API-3-2`, then `-3`), and `worktree new` names the other
  agent and its branch, from this machine's registry and from the console's
  marks, then exits 0.
- **`agent.py worktree list [--json]`**: each worktree's branch, item, kind,
  agent, age, last commit, ahead and behind its base, uncommitted changes,
  unpushed commits, PR (one `gh pr list` for the repository, when gh is
  there) and **stale** (no PR, 14 days or older).
- **`agent.py worktree prune [--dry-run]`** (W3) never removes a worktree with
  uncommitted changes, and never one with a commit that is on no remote. A
  worktree has **landed** when its PR merged and that PR's head commit is the
  worktree's `HEAD`: a squash merge deletes the head branch, but the PR keeps
  its head on the remote, so nothing is lost. A landed worktree is removed and
  its local branch deleted only if it still points at that commit (`git
  update-ref -d`, never `branch -D`). A merged PR at another commit (work
  after the merge, or a fork's branch of the same name) keeps the worktree,
  and says why. A worktree with **no commits of its own** (nothing past the
  commit `new` cut it from) is never landed, whatever a PR of its branch name
  did: it is kept, and is stale after 14 days. A closed, unmerged PR's
  worktree goes only when every commit
  is on a remote ref (its branch then with `git branch -d`). It looks again
  right before each removal, under the registry's lock, and keeps one written
  into meanwhile. It acts only on paths under the project's own folder. Never
  `--force`; no remote branch is deleted. Stale ones are listed, never
  removed.
- **The steward's `watch` prunes**, only for the project its working
  directory is in and only for its own console, after its first heartbeat
  (the owner sees "listening" first) and only when no signal is waiting: at
  most once per 10 minutes (the time kept in the state folder), with one `gh`
  call, and for at most 60 seconds in all, that `gh` call included: each git
  and `gh` call is held to the time left (and not started under 2 s), and the
  heartbeat is kept fresh between calls, so "listening" never lapses. Out of
  time, it stops and takes up where it stopped on the next cycle. A
  `git worktree remove` once started is the one call not held to that: it
  is never cut short half-way through its delete, only stopped after 120 s
  (the heartbeat kept fresh meanwhile), and then kept with what to do; one
  started late in the 60 s can so take the prune to about 3 minutes. While it
  runs it holds the registry's lock: an agent's `worktree new` waits at most
  10 s for it and is then refused by name ("a prune is removing a worktree
  right now; try again in a minute"), and `worktree list` never waits. Without
  `gh` it skips, and says so once. A record of its own, or a `watch.json`,
  that will not parse (nested past the JSON parser's depth included) reads as
  nothing.
- **The registry**, `<project>/.registry.json` beside the worktrees (path,
  branch, item, kind, agent, created, base), is written to a temporary file and
  renamed over, under a lock, read tolerantly (a corrupt one is rebuilt from
  git, and said), and reconciled with `git worktree list` on every `new`,
  `list` and `prune`: git wins, and an entry whose path lies outside the
  project's folder is dropped.
- **`worktree_setup`** in `.overture.json`: one command as an argv list (a
  shell string is refused by name) that sets up what git does not carry. A
  word holding a control character (ESC, BEL, a newline, CR, DEL, a C1 such
  as CSI) is refused, by the character's name and the word's index, so it is
  never printed to a terminal.
  **Overture never runs it.** `worktree new` reads it from the new worktree's
  copy, checks it, and prints it as a suggested command ("This project
  suggests a setup step; run it yourself in the worktree: ..."), also in
  `--json` as `setup.argv` and `setup.command`. The agent runs it through its
  own Bash tool, so the user's permission prompt sees it. (The copy comes from
  origin's branch, which any merged PR can change: running it unprompted would
  give that PR the owner's account.) Unset by default; `.venv` is never
  copied or linked for you.
- **The writing skills start with `worktree new`** (W2): console-visual (in
  place of a hand-written `git worktree add`), console-ux's save,
  console-process for ticket work, playbook steps that write and rounds that
  change code, and console-fold. Chat, deliberation and grilling are
  unchanged. The exports still refuse the server's checkout, and their
  refusal now names `worktree new`.
- **The `working` mark takes an optional `branch`** (`overture/<kind>/...`,
  at most 120 after the kind) **and `worktree`** (the folder's name only).
  Anything else, a path above all, is refused by name with a 400; an old
  client's items-only mark works as before (and clears that item's branch).
  The branches sit in `working.json` under `@branches`, go when the agent
  syncs, and reach the page and the agent door as `cursor.branches`. No path
  or home directory is stored or served. `agent.py working` run from inside a
  registered worktree sends its branch by itself.
- **The console shows them** (W4): the item, its Tickets fold, its open cards
  in the Tickets tab (never a closed one) and the PR row whose head is the
  branch each show a chip (the branch icon and name, D9) with the agent's
  name, the whole text in the page ("overture/fix/API-2-2 · agent-6") inside a
  group named "Where agents work on API-2", with the same words and ", branch"
  as its title; on a phone a long one wraps inside its column (touch has no
  hover for a title), never wider than a 320px screen. With two branches on one item all of them warn: "2 agents on
  API-3: overture/fix/API-3-2, overture/ticket/API-3", a note, never a block,
  said once to a screen reader when it first appears (not on each redraw).
  The Active agents fold says which branch each agent is on. Members and
  viewers see branches as they see the marks.
- **The item's header names the agents first**: "agent-5, agent-6 active",
  no longer "1 agent-5, agent-6 active" (the number counts what waits, not
  agents); with more than one thing waiting, the header and the dashboard
  add "(2 waiting on agents)".
- **Stale worktrees** (W3) ride the steward's heartbeat (`watch.json`, branch,
  age and agent only, at most 12), so no new route was needed, and are shown
  only while that heartbeat is at most a day old. The owner sees a quiet "1
  stale worktree" fold at the top of the PR tab with each branch and its age,
  and the same count on the tab's own "pushed" line, which opens it; no other
  login is sent it.
- **The 1.49 leftovers.** A chart click of a kind the console ignores no
  longer stows the phone's sheet (it left focus on the page) (L1). A sheet
  stowed before the window went wide **stays stowed** when it narrows again:
  the chip shows, and focus inside the wide stack goes to the chip, rather
  than the modal sheet coming back over the console (L2). A test now holds the
  stowed sheet hidden, inert, out of the Tab order and the accessibility tree
  (L3). Back from an item that lands on another tab no longer queues its lane
  to open on a later Inbox visit (L4).
- **INSTALL.md** names what is needed now: Python 3.11+, `systemd --user`,
  `git` (and `gh` if you want the PR tab and pruning), and one way in of your
  choosing (Cloudflare Access, sign-in links on Tailscale or ZeroTier, or this
  machine only). Docker is not required, and not offered yet.
- **Documentation and screenshots:** `docs/features/automation.md` ("Agent
  worktrees"), the README; new `feature-worktrees.png` (an item with two
  agents' branch chips and the overlap warning).

**Going back to 1.49.** A 1.49 server skips the `@branches` key in
`working.json` (the marks still show, without branches) and the stale list in
`watch.json`. A 1.50 `agent.py` whose mark a 1.49 server refuses for its
branch (by that server's own words) sends it again without one, and says so;
any other refusal is reported as the server gave it. The worktrees stay on
disk: remove one with `git worktree remove <path>` from the project's
checkout.

## Pop-outs and a calmer Inbox (1.49.0)

The rest of the owner's choices of 2026-10-16 (OPEN-DECISIONS.md, "Sections,
pop-outs and a calmer Inbox", U3 U5 U6): what you read at length opens beside
the console instead of stretching it, and a long Inbox gets lanes, an outline
and keys to move through it.

- **Pop-outs** (U3): an item's status flowchart and impact graph, What blocks
  what (the ticket graph), a visual (a Mermaid diagram or an HTML mock), a
  deliberation round, a long ruling and a screenshot each have a **Pop out**
  button (icon and label, D9) where the console shows them; the screenshot
  viewer has one too. A ruling has one when its question, options and your own
  words come to 280 characters or more. A chart fold's Pop out sits beside its
  heading, so it is there while the fold is shut, and comes before the chart in
  the Tab order; it is named for its chart ("Pop out Status flowchart", "Pop out
  Impact graph", "Pop out What blocks what"). A pop-out opens over the
  dashboard, in the room beside the docked console, never over the console
  itself.
- **A tabbed stack of up to three.** Each pop-out is a tab, with its title,
  **Pin** (`aria-pressed`) and **Close** on its panel. Opening a fourth closes
  the oldest one not pinned, and says so; with all three pinned it opens
  nothing and says to unpin or close one. Opening one already open brings its
  tab forward instead of a twin.
- **How long a pop-out stays: until you close it.** Moving to another tab,
  section or item leaves it open: you opened it to read beside other work, and
  closing it when you moved on would undo that. **Pin keeps a pop-out open
  when the console closes, and protects it from replacement** (it is never the
  one closed to make room for a fourth). Closing the console, by Esc, Close or
  `g b`, closes the ones not pinned; a pinned one stays over the dashboard
  until you close it.
- **Esc** closes the pop-out on show and puts focus back on the Pop out button
  that opened it (its redrawn twin, if the console was redrawn meanwhile; the
  console's tab, or its Close, if that button is gone). The console stays
  open. Esc works with focus inside a pop-out's chart too: the chart pages the
  server builds tell the console when Esc is pressed in them (a bare
  `{type: 'ck-escape'}` message, accepted only from the console's own chart
  frames, in exactly that shape; the frames' sandbox and CSP are unchanged).
  Esc in a chart in the console itself does nothing new. An HTML mock-up is
  the exception: it runs no script at all (an empty sandbox, as in the
  console), so Esc inside one does nothing; click outside it, or use Close,
  one Shift+Tab away.
- **Links:** the address names the pop-out on show, `#item=API-2&pop=flow:API-2`,
  and such a link opens it. The kinds are `flow`, `impact`, `tickets`,
  `visual`, `round`, `ruling` and `asset`. A link is checked as 1.48 checks the
  rest of the fragment: an unknown kind, an id of the wrong shape, a value that
  does not decode, or anything this page's own view does not hold (another
  login's item, a deleted visual, a ruling not yet locked) is ignored, and the
  rest of the link still works. A pop-out draws only from what the console was
  already sent, so it shows nothing the login cannot see there.
- **Room and phones.** With 480px or more beside the console the stack is a
  `role="region"` named "Pop-outs" with a tablist, as wide as the room allows
  (up to 960px); it is not modal, so Tab moves in and out of it and the console
  stays usable. A docked console at its default 576px leaves 480px on a window
  1056px wide or more, so a 1280px laptop gets a pop-out beside the console.
  With less room, or on a phone (640px and under), the same stack is a
  full-screen sheet over the console: `role="dialog"` with `aria-modal`, focus
  kept inside, Close at the top and Esc to close, showing the pop-out on show
  with its tab strip to switch when more than one is open. The sheet keeps the
  same limit of three and the same Pin. A change of layout (a resize, a
  rotation, a dock drag) never closes a pop-out, and a dock drag settles the
  layout when it ends rather than flipping while you drag; focus on a control
  the switch hides moves to the same pop-out's visible one. While the sheet is
  open the console's shortcuts (`.`, `g …`, `?`, `j` / `k`) do nothing behind
  it. Its Pin, like Close, is a 44px touch target.
- **Back to the console from the sheet.** On the sheet, **Show in the console**
  and a click in a chart *stow* it rather than close the pop-out on show: every
  pop-out is kept, pinned or not, the sheet leaves the screen (and the Tab
  order, and the accessibility tree), focus goes to what the console now shows,
  and a **Pop-outs (2)** chip in the console's corner (named "Pop-outs (2): show them",
  44px on touch) brings the sheet back on the pop-out you were reading. Opening
  another pop-out brings it back too, and a window that grows wide enough shows
  the whole stack beside the console as usual. While it is stowed the console
  is the console: its shortcuts work, and Esc closes it as always (the
  pop-outs not pinned go with it; a pinned one is shown again, with focus in
  it).
- **The same sandbox.** A popped-out chart, diagram or mock is made by the very
  function the console uses for its own (`chartFrame`: `sandbox="allow-scripts"`,
  never `allow-same-origin`, `data-ck-chart`, `referrerpolicy="no-referrer"`;
  `mockFrame`: an empty sandbox), from the same URL. No new HTML sink and no
  new server endpoint: rounds, rulings and screenshots are drawn from the view
  with the console's own text-only builders.
- **Live updates** redraw a pop-out in place, only when what it shows changed:
  the panel and its scroll position stay, nothing animates, and a chart's frame
  is swapped only once its replacement has loaded (a second update before then
  replaces that replacement: one frame is ever drawn). Focus on a control
  inside a redrawn pop-out stays on it. A pop-out whose source has gone says
  so instead of vanishing: "This ruling was reopened." when that is what
  happened, otherwise "This is no longer in the view."
- **Motion:** the stack slides in and out (150 ms) and a new tab's panel fades
  in (120 ms), all CSS and none of it under `prefers-reduced-motion`; a live
  update never replays it.
- **The Inbox grouped by lane** (U5): below the Priority list, which stays the
  cross-project "awaiting you" list, the questions and rounds sit in a group
  per lane, each headed by a button (`aria-expanded`) with the lane's chip and
  "2 awaiting you · 3 open". Lanes with questions awaiting you come first, the
  most awaiting first, then the most open, then by name; items with no lane are
  under **Other**, after a named lane it ties with. A round goes in its item's
  lane. A row inside its own lane's group does not repeat the lane's chip (the
  heading names the lane); the Priority list and search keep theirs. Each row
  does what it did: open, snooze, the filter chips, Mine, the palette and
  links. Folded groups are remembered per viewer, per project and lane, and a
  stored value of the wrong shape counts as nothing folded. A link to a
  question (or item) in a folded group, an outline jump, or `j` / `k` opens the
  group for this visit to the Inbox: it stays open through live updates, and is
  folded again once you leave the Inbox (another tab or section, an item, the
  console closed) and come back. Back from an item opens the group of the row
  you return to. Navigation never changes what is remembered; only pressing the
  group's heading does.
- **Priority's count** no longer says "across 1 project": the projects are
  named only when there are several (the 1.48 UX review). Its rows follow
  suit: with one project they no longer repeat its name ("northwind · API-2/Q1
  · …"), which on a phone left the question a few characters.
- **The outline** (U6): the groups with their counts ("2/3", awaiting you of
  open) as a one-line strip that stays at the top of the Inbox while it
  scrolls. A short legend, "awaiting you / open", starts it; each control is
  named with what it shows first, then in full ("Infra 3/4: 3 awaiting you, 4
  open", so a voice user can say what they see: WCAG 2.5.3) and titled "Infra:
  3 awaiting you, 4 open"; and on a wide
  screen it ends with a hint, "j / k next question". Pressing one opens its
  group, brings its heading to the top, clear of the sticky bars, and focuses
  it. At the default column the Inbox is about
  480px wide, and an outline beside it would leave the rows some 300px, cutting
  their ids and questions, so the outline sits above; once the column is
  dragged wide enough for the Inbox to be 720px, it moves beside the groups. On
  a phone it is a native **Go to a lane** menu, each option in full
  ("Infra — 3 awaiting you, 4 open").
- **`j` / `k`** on the Inbox go to the next or previous question waiting for
  you, across the groups in their order, opening a folded group on the way (for
  this view only) and
  scrolling the question into view, and announce "Question 3 of 7". A round's
  card is one stop (its form walks its own questions). At either end they stop
  and say so ("No more below: question 7 of 7."): wrapping round would read as
  the list starting over. They do nothing in a text field or behind a dialog,
  and on other tabs `j` / `k` walk the rows as before. The help sheet and the
  footer's Shortcuts button list them.
- **Mine** (1.41) is sticky at the top of the Inbox while it scrolls, with
  `aria-pressed` as before, and keeps your choice as it did.
- **Documentation and screenshots:** `docs/features/navigation.md` ("Pop-outs",
  "Moving through a long Inbox"), `docs/features/inbox-and-rulings.md` and the
  README; new `feature-popout.png` (a flowchart popped out beside the console,
  two tabs), `feature-popout-laptop.png` (the same on a 1280px window) and
  `feature-inbox-groups.png` (Priority, the outline with its legend and hint,
  the groups), and `feature-phone.png`, `feature-priority.png`,
  `feature-snooze.png` and `feature-inbox-top.png` rendered again (Priority
  rows without the one project's name).

**Going back to 1.48.** 1.49 adds one key to this browser's localStorage,
`ck:<project>:inbox-collapsed` (the folded lane groups), which 1.48 never reads.
On the server only the chart pages change: each gains the Esc message above,
which a 1.48 console ignores. A 1.49 link with `&pop=…` opens the same view in
1.48, without the pop-out.

## Sections (1.48.0)

The owner's choices of 2026-10-16 (OPEN-DECISIONS.md, "Sections, pop-outs and
a calmer Inbox", U1 U2 U8 U9; U1 amends D14 and U8 amends D9): the console's
eleven tabs sit in four sections, a phone gets the whole screen, and moving
between sections and tabs has a little motion. Pop-outs (U3), grouping the
Inbox by lane (U5) and its outline with `j`/`k` (U6) are 1.49.

- **Four sections, each with its own sub-tabs** (U1): **Work** (Inbox, Feed,
  Tickets, PRs), **Automation** (Playbooks, Triggers), **Projects**
  (Portfolio, Favorite) and **Team** (People, Chat, Settings). Chat sits in
  Team (U9). The sections are a slim rail of icon and label on the column's
  leading edge, one `<nav aria-label="Sections">` with `aria-current` on the
  section on show; the section's own tabs are the strip above its view,
  today's tabs with their icons and counts. **"More ▾" is gone.** The docked
  column now opens 576px wide (was 480px), so the content beside the rail
  keeps its room; a width you dragged and the console kept is unchanged.
- **Who sees what is unchanged:** People for an administrator, Settings for
  an administrator or a director. A section none of whose tabs a login sees
  is not shown; Chat keeps Team for everyone.
- **A section's badge** shows the most urgent of its tabs' counts, not their
  sum: the questions open in the Inbox (so Work shows the Inbox tab's
  count), an agent waiting on the chat (the ● "More" carried), questions
  waiting in other projects, new Feed events. Projects counts only the
  other projects' questions: with none connected it stays dark instead of
  repeating Work's count. Counts of things that merely exist (tickets,
  playbooks, triggers, favorites) stay on their own tab.
- **Shortcuts:** every `g` shortcut still opens its tab, and now its section
  too. New: `g 1` Work, `g 2` Automation, `g 3` Projects, `g 4` Team, each on
  the tab you last used there (else its first). The help sheet and the
  footer's Shortcuts button say so.
- **Keyboard and screen readers:** the rail is one Tab stop; the arrow keys
  (and Home, End) move between its buttons, and Enter or Space opens the
  section; its focus ring sits inside the button, clear of the section
  marker, on a band of the rail's colour. Opening a section puts focus on
  its selected tab, so the arrow keys work at once and a screen reader
  names where you are. A tab strip's arrows stay within its section. Each rail button is named with its count
  ("Work, 3 questions open in the Inbox": every open question, so more
  than the Priority list's "awaiting you", which counts only the
  unanswered), and has a tooltip.
- **Links:** the address names the tab and the section, `#feed&section=work`.
  A 1.47 link (`#feed`) opens the same view, and so do `#tab=feed` and
  `#section=team` (a section's first tab you can see; a link that arrives
  before the page has loaded is worked out again when it has, so an owner
  lands on People, not Chat). `#item=` and `#qid=` are unchanged. A tab
  you do not see (`#people` for a viewer), or one you lose while it is open
  (an administrator made a viewer), falls back to its section's first tab
  you do, with a note saying why (1.47 drew a page that said only that).
  The panel title names the tab alone: the rail already says the section,
  and on a phone "Automation · Playbooks" would not fit.
- **Phones** (U2): below 640px, an open console is the whole screen, whatever
  the host page does; a page wider than the phone no longer pushes it 164px in
  and cuts it off. The page underneath neither scrolls nor takes taps until
  you close it. The sections are a bottom bar of four buttons, each at least
  48px and clear of the home indicator; the tabs are a strip at the top that
  scrolls sideways. The section on show has its icon in a filled pill (in
  the marker's colour, 3:1 or better against the bar on every theme and
  skin) besides the line above it: the tinted ground alone was too faint
  to tell. Back and close stay in the header. 640px is where the
  console's phone layout already began; a second breakpoint at 600px would
  have left 600–640px half done.
- **Narrowest widths** (U8): below 400px the rail shows icons only, with a
  tooltip, and the label stays each button's name for a screen reader; from
  400px up, icon and label as D9 requires. A badge there sits on the corner
  of its icon's pill, never over the icon.
- **A calmer Inbox row on a phone:** a Priority row is two lines, which item
  and its ⌛ above, the question and its age below. It was three at 390px,
  the ⌛ alone on the middle one. The "·" that separates the question on
  the one-line row does not lead the second line.
- **Motion** (U9): a new section crossfades (160 ms), a new tab slides in
  (140 ms), and the rail's marker slides to its section (180 ms). All of it is
  CSS, and none of it runs under `prefers-reduced-motion`. A live update never
  animates, nor does a count or a badge: the motion is keyed to a real change
  of section or tab. The 0.18 s fade every redraw used to replay is gone.
- **Contrast:** the rail's words, its marker and its badges read at 4.5:1 or
  better (the marker 3:1 at least) on every theme and skin; the marker is the
  accent drawn a little toward the text colour, as plain accent falls under
  3:1 on Solarized and Nord light.
- **Fixed:** two quick moves (`g 2`, then `g f`) left the address on the first
  tab; every move now updates it. A link with a value the address cannot
  decode (`#item=%E0%A4%A`) threw an error and opened nothing; the bad value
  is now ignored and the rest of the link works.
- **Documentation and screenshots:** `docs/features/navigation.md` and the
  README describe the sections; the screenshots were rendered again, with
  `feature-sections.png` (the rail) and `feature-phone.png` (the Inbox on a
  390px phone).

**Going back to 1.47.** Nothing is stored differently: 1.48 writes no new
state, and a 1.47 console reads everything 1.48 leaves. Its tab bar and
"More ▾" come back. A 1.48 link such as `#feed&section=work` opens the Feed in
1.47 too (the tab comes first); 1.47 ignores `#tab=feed` and `#section=team`.

## Listening on ZeroTier and Tailscale (1.47.0)

The owner's choices of 2026-10-15 (OPEN-DECISIONS.md, "Without Cloudflare",
L4 as refined by L13 L14, L15–L18, and L7), with contract 3 amended by the
owner on 2026-10-16: a console with sign-in links can be reached on its
ZeroTier or Tailscale address directly, and onboarding asks how you will
reach it.

- **`--listen ADDR`** (link mode only; Linux and WSL, "comes with 1.48"
  elsewhere): the owner door binds `127.0.0.1:PORT` **and** `ADDR:PORT`, two
  sockets on one port, never `0.0.0.0`. ADDR must be the address of a
  ZeroTier interface (`zt…`) or a Tailscale one (`tailscale0`, or 100.64/10
  on a `tailscale…` interface), found by `overture/netif.py` through
  rtnetlink, every address of every interface, secondaries included (no
  process, no `ip`; without netlink it falls back to each interface's primary
  address and says so). Refused by name: `0.0.0.0`, loopback, a public
  address that is not Tailscale's, IPv6, an address on any other interface
  (`eth0`, `docker0`, `br-…`, `lo`), and one held by an overlay AND another
  interface.
  `--auth cloudflare` never listens beyond loopback. Without `--listen`
  nothing changes. The agent socket and the health door stay where they were.
- **One origin per socket** (L15): loopback's `http://127.0.0.1:PORT` (and
  `localhost`), and the overlay's `http://ADDR:PORT`. An https `--origin`
  with `--listen` is refused by name (security review): for Tailscale's
  HTTPS, run `tailscale serve` WITHOUT `--listen`, as in 1.46. The origin
  a request must carry is the one of the socket it ARRIVED on, never its
  Host: for `POST /signin`, for every write, and for the cookie's `Secure`.
  The other socket's origin is refused, either way round. A cookie is per
  host, so **sign in once per address you use**. Links and notifications
  name the overlay origin.
- **Host on the overlay** (DNS rebinding): on the `--listen` socket a request
  whose one Host does not name ADDR (or ADDR:PORT) gets the gate's 403 JSON,
  before `/signin` and the gate. Loopback is 1.46's, Host unread.
- **Waiting for ZeroTier** (L16): an address not on any interface yet is
  polled every 2 s for up to 2 minutes, with one line (`overture: waiting for
  ADDR on a ZeroTier or Tailscale interface (up to 2 minutes)`), then bound,
  or exit 1 by name for `Restart=on-failure` to try again. Such starts are
  at least 125 s apart, so the one server's `StartLimitBurst=5` per 120 s
  never trips on a slow boot, while a server that fails at once still stops
  after five tries (the link unit gained the same limit). An address on a
  disallowed interface is refused at once. LISTEN is bound first and
  loopback after; if loopback cannot be, LISTEN is closed again; if either
  socket's loop dies later, both stop and the server exits 1, so a door is
  never half up.
- **Overlap warning** (L17): once ADDR is accepted, every other interface
  whose network overlaps ADDR's (down ones too, marked `(down)`) is named
  with both networks: it may shadow the ZeroTier route; move the ZeroTier
  network or Docker's `default-address-pools`. Startup continues.
- **The one server:** `server.json` gains `"listen"` (absent: none), kept by
  every writer (`server add`, `token rotate`, `server auth`, `server
  listen`). `agent.py server listen [ADDR | --clear]` shows or sets it, link
  mode only, refused in a Claude Code session; an address ZeroTier has not
  brought up yet is set with a warning. Every project's port is on loopback
  and ADDR; an entry with no `origin` is at `http://ADDR:PORT`. `server auth
  cloudflare` is refused while listen is set. `agent.py invite` prints the
  overlay link then (`--origin` overrides).
- **Onboarding** (L7): `onboard.py write --auth link [--listen ADDR]
  [--origin URL]` needs no Cloudflare values (and refuses them by name), and
  writes `CONSOLE_AUTH`, `CONSOLE_ORIGIN` and `CONSOLE_LISTEN`; `show` and
  `install.sh` carry them through to a link unit (`console-link.service.in`,
  no tunnel unit). `onboard.py detect [--json]` lists the ZeroTier and
  Tailscale addresses here, with any overlap warning. Its next steps print
  the owner's commands (install, `invite` in your own terminal, the
  `tailscale serve` line or `http://ADDR:PORT`). `onboard.py verify` in link
  mode says Cloudflare and the tunnel are "not used", and checks that the
  door answers on each address and that `/signin` answers 410 for a token
  nobody made. The console-onboard skill asks first: Cloudflare, Tailscale,
  ZeroTier or this machine only.
- **The two 1.46 LOWs** (L18): an `ovi_` token percent-encoded anywhere in a
  log line (`%6Fvi_`, `ovi%5F`, twice-encoded `%256F`) is cut too; and
  invalid UTF-8 in `roles.json` is a roles error (the gate's 403, People's
  503), not a dropped connection.
- **Also checked by review:** `server listen` re-checks every project's
  origin and refuses, by project name, a change that would break one;
  `agent.py invite --origin http://X` takes plain http only for this
  console's own listen address.
- **Fixes the owner chose to ship now** (OPEN-DECISIONS.md U4, U7, found in
  real screenshots): the Operator shift dialog is one dialog again; the
  snooze menu draws over the next row instead of under it; the panel title
  names the tab you are on, not always "Inbox"; People in link mode speaks
  of sign-in links, not of an Access policy, and its log reads as sentences
  ("X was invited (from the terminal)"); a locked card shows one "locked"
  pill; the Triggers tab lists its firings flat, and the Inbox's quick look
  at firings stays on the Inbox; the impact graph's frame fits its graph,
  with the zoom hint below it, and only that frame may size itself;
  Portfolio's "Setup guide" opens the setup section and its command wraps;
  the Delegate bar fits in playbook mode; a skipped playbook step says why
  in words; and a playbook started from a Claude session (`agent.py
  playbook`, `/overture:playbook`) is refused at once, saying that
  playbooks run from the console's Playbooks tab, instead of quietly doing
  nothing.
- **Documentation:** the README is an overview again, with a complete
  feature map; the detail moved, word for word where it existed, to
  thirteen pages under `docs/features/`, which also document for the first
  time what never was (Delegate, playbooks, triggers and replay, the impact
  graph, snooze, deep links, Export today, theme and skins, Launch Idea,
  Operator shift, and more). Every screenshot was rendered again on this
  release, with new ones of sign-in, signed-in browsers, playbooks,
  triggers, Operator shift and Launch Idea.

**Going back to 1.46.** A 1.46 kit refuses `--listen` (no such flag), so a
unit with it does not start; it ignores `"listen"` in `server.json`, so the
one server comes back on loopback only; it ignores `CONSOLE_AUTH` in
console.env and `onboard.py show` then refuses the file (no hostname).

## Sign-in links (1.46.0)

The owner's choice of 2026-10-15 (OPEN-DECISIONS.md, "Without Cloudflare",
"Defaults": L1 L2 L5 L6, this machine only of L8, L10 L11 L12): a console
can run with no Cloudflare in front of it. The network only decides who can
reach it; the console itself proves who is at the browser.

- **One way in per console** (L5, L6): `server.py --auth cloudflare` (the
  default, unchanged) or `--auth link`. For the one server, `agent.py server
  auth link` sets it for every project in `server.json` (`"auth"`, absent
  means cloudflare; `server add` and `token rotate` keep it). In link mode
  `--team-domain`, `--aud` and `--hostname` are not needed, and `--origin`
  names the console's address as the browser sees it (default
  `http://127.0.0.1:PORT`).
- **Invite in the terminal:** `agent.py invite EMAIL` prints a link once:
  `ORIGIN/signin?t=ovi_…`. It works once and lapses after 24 hours. Only its
  SHA-256 is kept; the token is never stored, logged or put in an error, and
  the server's log shows `/signin?…` (the whole query, however it is
  spelled) and `t=…` elsewhere, and any `ovi_` token anywhere in a log line
  is cut. A Claude Code session is refused, as for
  `access`. A login with no role is warned that it will only read.
- **Opening the link asks, the button signs in.** `GET /signin` never spends
  the invite (link previews and mail scanners open every link); its page has
  no script and posts the token back. `POST /signin` must come from the
  console's own origin (login CSRF), spends the invite under a lock (two
  presses: one browser), and sets the device cookie `overture-device`:
  HttpOnly, SameSite=Lax (Strict would drop it when the console is opened
  from a notification), Path=/, 400 days, Secure on an https origin. Each
  opening of the console re-sends it, so a browser stays signed in until
  revoked. The form's page uses `Referrer-Policy: same-origin`, every other
  sign-in answer `no-referrer`: a browser sends `Origin: null` from a
  no-referrer page, and the button could never sign in.
- **Every other request meets the gate first**, as before (D5): without a
  device cookie, `GET /` is a short page saying how to get a link (naming no
  project, email or path) and everything else today's 403. A Cf-Access header
  is never read in link mode, and a device cookie never in cloudflare mode,
  where `/signin` does not exist. External triggers (`/api/trigger/…`) need a
  signed-in browser in link mode, so a webhook cannot call them there.
- **Devices** live beside your registry, `~/.config/overture/devices.json`
  (0600), one file for the machine (`server.py`, the one server and
  `agent.py` all read the same one, whatever `--server-file` says). **A
  sign-in link opens the project it was made from, plus every project whose
  roles list that email; with roles off, only the projects it was invited
  from** (architect default amending L6, from the security review: one
  machine-wide sign-in would otherwise open every console, as its owner where
  roles are off). A second project's link opened in a signed-in browser of
  the same email adds that project to the same device and cookie. A link
  works only on the console it was made from: on another project's port it
  reads as expired (no email shown) and is not spent. Each
  project's roles decide what that login may do. Every field is checked on
  every read (dates parsed, not only matched), and a damaged file signs
  nobody in, named once in the server log; sign-in and Revoke answer a clean
  503 then. A revoke takes effect on the next request. At most 200 waiting
  invites, 500 browsers, 100 projects per browser.
- **The cookie reaches every port of the host.** Browsers send cookies per
  host name, not per port, so any other program served on the same name (a
  dev server on another `127.0.0.1` port, another service on the tailnet
  name) receives `overture-device` whenever that browser visits it, for its
  400 days. Prefer the Tailscale https name (`tailscale serve`), don't browse
  untrusted local dev servers on the same host name in that browser profile,
  and if in doubt revoke under People. (A `__Host-` prefix is not used: it
  would break `http://127.0.0.1` and the one sign-in shared across ports.)
- **People** (administrators) lists exactly the signed-in browsers the gate
  lets into this project ("Firefox on Linux · signed in 2 h ago · bob@…"), with
  **Revoke**, confirmed in the page; revoking the browser you are using says
  so and signs the page out; Revoke reaches no other browser. `agent.py
  devices` lists every browser on the machine with the projects it was
  invited from (emails masked in a session), and `--revoke ID` signs any one
  out. Invites, sign-ins and revokes are
  lines of the role log, shown in People's log.
- **Tailscale works today** through `tailscale serve` (HTTPS to 127.0.0.1):
  `--origin https://MACHINE.TAILNET.ts.net`. `--listen` on a Tailscale or
  ZeroTier address and onboarding come in 1.47.
- **Two-key areas are an administrator's again** (L10, amends S1): a
  director sees them under Settings, read-only, and `POST /api/two-key`
  refuses them.
- **The two 1.45 LOWs** (L12): a notification error logged once is logged
  again if it comes back after a send went through; and a Settings redraw
  keeps what you typed and have not saved, and the focus.
- Notifications honour `HTTPS_PROXY` (L11), now said in the README.

**Going back to 1.45.** A 1.45 kit refuses a role log holding a device line
by its shape: its People log then says "the role log cannot be read" (roles
and writes are unaffected). It ignores `"auth"` in `server.json`, so a
link-mode one server comes back behind Cloudflare Access, and a project added
with no hostname and AUD is refused until `agent.py server add` gives it them.

## Notifications (1.45.0)

The owner's choice of 2026-10-15 (OPEN-DECISIONS.md, "Notifications", N1a
N2b N3a N4b N5a): the console tells your team's channel when questions are
waiting.

- **One channel: an incoming webhook** that takes `{"text": ...}`: Slack,
  Mattermost, or Discord's `/slack` URL. One HTTPS POST and no mail server.
- **The URL is the owner's, set in the terminal:** `agent.py notify-url
  https://...` (also `--clear`, and `--test` to post a test message). It is
  kept in `STATE/notify.json` (0600). Anyone who holds the URL can post to
  the channel, so the console shows only its host, the role log records only
  its host, and the CLI never prints it back. A Claude Code session is
  refused, as it is for `agent.py access`.
- **Settings → Notifications** (administrators and directors) turns them on,
  sets at most one message every N minutes (5–1440, default 30), and sets
  quiet hours on the console machine's clock (for example 22:00 to 07:00).
  The tab says where messages go, when the last one was sent, and why the
  last one failed.
- **What a message says:** how many questions are newly waiting, on which
  items, and a link to the console, e.g. "overture · northwind: 3 new
  questions waiting for an answer: API-2 (2), OPS-1 (1). Open the console".
  It never includes a question's text or anyone's email. Each question is
  told once. A failed send is tried again in the next window, never every
  minute.
- **Who sends:** the console server, once a minute on a thread of its own.
  It sends only to the configured host, over HTTPS, refusing redirects, with
  a 10-second timeout, and reads at most 4 KiB of the reply. This is the
  server's first outbound request other than to its peers. A reply
  dripped slowly is cut off after 30 seconds. If the record of a send
  cannot be written (a full disk), nothing more is sent until the next
  window, so the channel is never posted the same digest every minute. It
  honours `HTTPS_PROXY` like any Python client.
- The first message after notifications are switched on lists every
  question already waiting. A question answered and later asked again is
  announced again. One console runs per STATE.
- The session refusal is a guardrail between the owner's own sessions, as
  it is for `access`: a session runs as the same user and can still edit
  STATE by hand.
- Nothing of it reaches the agent socket.

## Settings (1.44.0)

The owner's choice of 2026-10-15 (OPEN-DECISIONS.md, "Settings", 1A 2A
3A 4): the settings that are a team's decision are made in the console,
by a project's administrators and its directors.

- **A Settings tab** for an administrator or a director (with roles off,
  every login). People (who has which role) stays the administrator's
  alone, so a director can never raise anyone, themselves included.
  This amends W3: the director flag now also lets a login set the
  project's settings.
- **What it sets:**
  - **Limits:** chat messages a minute (1–60, default 6) and an hour
    (1–1000, default 60), and agents working one item at once (1–50,
    default 8).
  - **Lanes:** a label and a colour for each lane. A field left empty
    keeps the project's own value from `.overture.json`, or an automatic
    colour. A lane's `ux` flag stays in the repo.
  - **Two-key areas**, moved here from People (`POST /api/two-key`,
    which a director may now call too).
  - **Short names:** what a committed ruling says instead of an email,
    as `agent.py operator-name` sets it (`POST /api/operator-name`). The
    email itself stays in the console.
- **Beside the project, never in it.** Values live in
  `STATE/settings.json` on the console's machine (`POST /api/settings
  {"key", "value"}`; a null value restores the default). They override
  the committed defaults, apply at once with no restart, and the console
  still writes nothing into the repo. A damaged file means the defaults,
  with a problem line on the tab and the path only in the server log;
  the next change made on the tab replaces it.
- **Logged.** Every change is a line of the role log
  (`{"setting": {"key", "from", "to"}}`) and is listed under the tab's
  **Changes**: "You set Chat messages a minute to 3 (was the default)".
  `agent.py operator-name` now writes through the same lock and is
  logged too. People's **Role changes** lists role changes only.
- **Who sees what.** Only an administrator's or a director's page
  carries the settings, and never the role roster: the two-key answer
  hands a director the settings, not the list of every login. Nothing
  of it reaches the agent socket.
- Plumbing stays where it is: Access, hosts, ports, paths, tokens, the
  steward and the adapter are never set from a web page. Folders, the
  committee seat and next-step skills stay in `.overture.json` for now.

## Two-key locks (1.43.0)

Wave 3, OPEN-DECISIONS.md W6 A (the owner's choice of 2026-10-14):
per area, set in roles, a lock needs a second person to confirm it.

- **Two-key areas**, set by an administrator under People
  (`POST /api/two-key`), kept in `roles.json` as `"two_key": [ITEM_ID,
  ...]`. An area is an item and everything under it. Roles must be on,
  and the last login cannot be removed while any are set. Each change
  is a line of the role log ("set the two-key areas to …").
- **The first key waits outside the store**, in
  `STATE/pending-locks.json`. Agents, the process request after Lock
  all, the ruling export, stale checks and older kits all read the
  store, so none of them treats an unconfirmed lock as a ruling.
- **A second login confirms** by locking the same answer: anyone who may
  lock there (an administrator, or a member covering the item). The
  lock is then written by that request. The first key's login is
  checked again at that moment; one that may no longer lock there is
  dropped (409), so nobody confirms a removed member's decision alone.
  The same login pressing twice, in any letter case, is one key. A key
  on an older answer never matches a key on a newer one. A service
  token is no key.
- **On the card:** "Two-key area: …" before any key, "You locked this:
  waiting for a second person" for its holder (who gets no second
  button), "A locked this. It needs a second person: confirm to lock
  it" with **Confirm lock** for everyone else, and "Locked by A,
  confirmed by B" once written (`view.confirmed_by`; the first keys are
  kept in `STATE/lock-keys.jsonl`).
- **Re-lock and Lock all follow the rule.** A re-lock's first key waits
  with its reason; the second writes the superseding answer and lock,
  keeping the first person's reason. Lock all writes the answers and
  reports each two-key question as `awaiting_second_key`, locking the
  rest; the item page's Lock all says how many wait, and a loose round
  marks each waiting question. Lock all's dry run refuses the whole
  batch for what a key would refuse (no login, a first key whose login
  may no longer lock), so it never stops half written for that. A
  re-lock sent again by either key finds what landed. The second key's
  resend finishes a confirmed re-lock whose lock failed after its
  answer, on a mark the confirmation saved first; an answer's own nonce
  is the writer's to choose and proves nothing.
- Two-key areas must be items of the project: an unknown id is refused
  rather than shown as set and guarding nothing. A key left on an area
  no longer two-key is not offered for confirmation.
- **What the export says:** a two-key lock's `locked_by` in the ruling
  files is its writer, the second key (operators.jsonl), as for every
  lock record.
- **Downgrade:** 1.42 refuses a `roles.json` that has `two_key` by its
  shape, so writes stop (503) rather than letting one person lock alone
  there. Remove `two_key` by hand to go back. Waiting first keys are
  lost, never confirmed.

## Role changes (1.42.0)

Wave 3, OPEN-DECISIONS.md W5 (the owner's choice of 2026-10-14).

- **A log of every role change**, `STATE/roles-log.jsonl`, beside
  `roles.json`: one line per change, `{"at", "by", "email", "from",
  "to"}`. `by` is the console login that made it, or null for
  `agent.py access` in the owner's terminal; `from` and `to` are the
  role entries (null for not listed). Like `roles.json` it is never
  committed and stays on the console's machine (mode 0600).
- **Shown under People**, newest 50 first: "You added bob@example.com
  as member of LANE", "agent.py access changed … from … to …". It is
  shown with roles off too, since removing everyone is a change. Only an
  administrator's page carries it; agents never see it.
- **No change goes unlogged, and none is logged that did not land.**
  The line is written and synced before `roles.json` is replaced, and
  cut back if that fails. Saving a row unchanged writes nothing. One
  case remains: a process killed between the line and the rename keeps
  a line for a change that did not land (`roles.json` is what is in
  force). A line a killed writer left half-written is cut back by the
  next change, with a note in the server log.
- `access` with a mistyped `--state` now fails ("nothing was written")
  instead of creating that directory.
- **The console and the terminal take turns.** Both read, change and
  rewrite the whole map; the log's lock is now held across that, so a
  People click and an `agent.py access` at the same moment no longer
  drop one another's change.
- A damaged log line is named in the server log by line number and the
  tab says the log cannot be read; it never blocks a role change. A
  last line still being written is left out.
- A file nested too deep to parse is refused like any damaged one, not
  a 500 on every request: a log line so nested shows as "cannot be
  read"; a `roles.json` so nested stops writes (503) while the page
  reads on as a viewer's.
- **Downgrade:** 1.41 ignores the log and writes no lines to it.

## Routing (1.41.0)

Wave 3, as the owner decided on 2026-10-14 (OPEN-DECISIONS.md W1–W4).

- **Who a question is for.** The members whose areas cover its item
  (an area is an item and everything under it); administrators cover
  all. No new question field: it is worked out from `roles.json`.
  An administrator's page shows "For bob@example.com" on Inbox rows
  and question cards (it already has the People list); a member's shows
  "For you" on their own, and never the roster.
- **Mine · All.** A member's Inbox opens on Mine, the questions in their
  areas, with All one click away; the badge and tab count follow it.
  `view.you.mine` carries the areas, or null for everything.
- **Director.** `"director": true` on a member or viewer (People tab
  checkbox, `agent.py access ... --director`): their Inbox opens on
  everything. It widens what is shown, never what may be decided.
- **Viewer areas.** A viewer may carry areas too, for what Mine shows;
  they still write nothing.
- **Drafts per login.** Each login's unsent text is its own, kept in
  the one `drafts.json` under a short hash of the login (never the
  email) and sent only to that login. Drafts saved before 1.41 still
  show until their key is saved again, then the shared copy is dropped,
  so a cleared draft cannot come back. A service token keeps the old
  shared keys. A key the page sends may not start with `u:` (that would
  name another login's stored draft), and stored keys allow the prefix,
  so the page's 256-character limit is unchanged. The 500-draft cap is
  still counted across all logins.
- **"Nothing in Mine."** When Mine is empty but other questions wait,
  the Inbox says so, with a button to All, instead of showing nothing.
- `roles.json` entries may carry `director` and (viewers) `areas`; a
  1.40 kit refuses such a file by name, so a downgrade fails closed
  (writes 503) rather than misreading it. An owner entry stays
  `{"role": "owner"}` only. **After a downgrade** neither the console nor
  1.40's `access` can change that file: remove the `director` and viewer
  `areas` fields from `STATE/roles.json` by hand.

## People (1.40.0)

Roles (1.39) could be set only from a terminal. Now the administrator
manages them in the console, and onboarding says to claim that account.

- **A People tab** (under More), shown only to an administrator (the
  owner role). It lists every login with its role and areas; change a
  role, edit a member's areas (item ids, with the project's items
  suggested), remove someone, or add a person. Each change goes through
  `POST /api/roles`, the same writer as `agent.py access`: it refuses
  to remove the last administrator, writes the file whole (0600), and
  takes effect on the next write.
- **"Make me the administrator."** With roles off, the tab offers one
  button. It makes the login you are signed in with the owner, so roles
  start with you in charge. No email is typed, and none reaches a
  session. With roles off, the first role set must be this one (409
  otherwise), so a first click on someone else cannot lock everyone
  out. A service token (no email) cannot claim it. The button says
  what it does to everyone else: they only read until you add them.
  The owner check is made again under the write lock, so of two logins
  claiming at once only the first lands (the second is a viewer by then).
- **Onboarding** prints a new step 6 to claim it, and the
  `agent.py access YOU@EXAMPLE.COM owner` line for your own terminal.
  The console-onboard skill hands this step over. It never asks for the
  email and never runs `access` (operator emails never reach agents).
- `view.roles` (`on`, `me`, `people`) travels to an administrator's
  page only. Members, viewers and the agent socket never get it.

## Who may decide (1.39.0)

Everyone behind a console's Access policy could answer, lock and run
everything. Now the owner can say who does what.

- **Roles per Access login**, in `STATE/roles.json` (0600, never
  committed: it names logins by email, which stay in the console):
  - **owner**: everything, as before.
  - **member** of one or more areas: answers, locks and plain messages
    on questions and items in those areas. An area is an item and
    everything under it, through `parent`. A member's message is plain:
    `item`, `text`, `reply_to`; any field that asks an agent for
    something (intent, move_to, step, pr...) is the owner's, as are
    playbooks, tickets, lock-all, drafts and the rest.
  - **viewer**: reads the console, writes nothing.
- **No roles file, no change.** Every login is the owner, so a solo
  console needs no setup. Once a file exists, a login it does not list
  is a viewer, and so is a service token (no email).
- **Fails closed.** A roles file the kit cannot read, or one with no
  owner, refuses every owner write (503, named in the server log)
  rather than reading as "no roles".
- **Read on every write**, so a change takes effect without a restart.
- **`agent.py --state STATE access`** lists, shows, sets and clears
  roles: `access bob@example.com member auth billing`. It refuses a
  change that leaves no owner, and refuses to write inside a Claude
  Code session (`CLAUDECODE`), so a session cannot raise a login's role;
  its listing masks emails there.
- **The page says it**: a member or viewer sees one line above the
  Inbox naming their role and areas (`view.you`, owner door only;
  absent when roles are off).
- **Drafts go to owners only.** The synced drafts (`view.drafts`) are
  the owner's unsent text; a member's or viewer's page gets none.
- A role is checked twice on each write: by route before the body is
  read (a viewer cannot make the server take in an upload), then by
  area on the body the route acts on, which is now read once.

## Locked by, on the card (1.38.1)

- **A locked question's card says who locked it**: "Locked by
  alice@example.com" under "Your answer", from the login 1.38.0 keeps.
  It travels on the owner door's view only (`view.locked_by`, answer id
  to email), like drafts; the agent socket's view never carries it. A
  lock with no kept login (a scheduled trigger, a lock taken before
  1.38) shows no line.
- The browser suite was run after 1.38.0's Feed change: 91 tests, all
  green, plus one new test for this line.

## Who decided (1.38.0)

Every owner write was stored `by: "owner"`, so with several people
behind one console's Access policy a lock could not say who took it.

- **The login behind each owner decision.** The owner gate already
  verifies an Access token on every request; its `email` claim is now
  kept, per request, for each record that request writes: answers,
  locks, messages, and the acts kept beside the store (withdraw, keep
  unchecked, confirm). It lives in a sidecar, `STATE/operators.jsonl`
  (`{"email", "id"}` per line, append-only, the first email a record got
  is kept), never in a store record, so an older kit still starts on the
  store. Agent writes, cron and triggers, and a token with no email (a
  service token) or a malformed one keep none.
- **The Feed shows it**: "by alice@example.com" on each owner event.
- **The email stays in the console** (the owner's choice, 2026-10-14:
  no email in a repository that may be public). `agent.py
  operator-name EMAIL NAME` sets a short name in
  `STATE/operator-names.json`, and `fold.py export` then adds
  `locked_by_name` to each lock that login took. With no name, an
  exported file is byte for byte what 1.37 wrote. `fold` and
  `rulecheck.py` hold `locked_by_name` to the agent-name shape.
- **Durable sidecars.** A write cut short (a full disk) is cut back to
  the last whole line, so it cannot stop the next start; `fold.py
  export`, another process, skips a line the console is still writing.
  Both files are created 0600; the names file is replaced whole, through
  a fresh unguessable temp file that never follows a symlink. Emails are
  compared in lower case, so `Alice@` from Access meets a name set for
  `alice@`. The Feed shows emails to everyone the Access policy admits;
  agents never see them, and `operator-name`'s listing masks them
  (`a…@example.com`) when run inside a Claude Code session.
- New `OperatorTests` in `test_server.py` (12 tests), through the real
  owner gate with signed tokens: two logins on one console, a kept-alive
  connection, agent and unnamed writes, letter case, the export, the
  refactor log, a write cut short, the command, a bad sidecar, and the
  agent socket never showing an email.

## Strict, and no token beside the adapter (1.37.0)

- **`--strict`** (`strict: true` in the Action): a ruling that could not
  be checked (an `item_status` condition with no adapter), or a run that
  found no ruling files, fails instead of passing. The verdict says so.
  A re-ruling never fails strict. The Action takes `true` or `false` in
  any case and refuses anything else, so a typo cannot switch it off.
- **The token is not handed to the adapter.** Sourcery's review of PR
  #162 pointed out that with `adapter` the pull request's own code ran
  in the step that held the comment token. The Action is now three
  steps: the check (no token in its environment), the comment (the
  token; skipped whenever an adapter is set, since that code could have
  written the job's later steps' environment), and one that ends with
  the check's exit code. With an adapter, the check refuses to run when
  `actions/checkout` left the token in `.git/config`. The adapter still
  runs as the runner's user (with sudo on GitHub's runners), so the
  README says to treat the rest of that job as untrusted.
- **A clean environment for the check** (Sourcery on PR #163): rulecheck
  starts with only `PATH`, `HOME` and `LANG` (and `SYSTEMROOT` or
  `LD_LIBRARY_PATH` when set), so the calling job's secrets are not
  handed to the adapter. That is hygiene, not isolation: the adapter can
  still read them from the parent process, so the README says to give it
  a job of its own with no secrets. Only git's own "no such key" counts
  as no token header; a config git cannot read refuses. An adapter that
  calls `sys.exit(0)` ends the run with exit 2, and a run that exits 0
  without writing its report is an error, not a pass.
- **Tried on a real pull request.** v1.36.0 ran on a private scratch
  repository: a pull request that changed the cited line failed with
  the comment and diff, and the push that put it back turned the same
  comment green.
- `test_rulecheck.py`: 33 tests. The Action's steps now run under
  `bash -eo pipefail`, as the runner starts them.

## Rulings that block a merge (1.36.0)

A broken ruling can now fail a pull request, with no console server.

- **`plugin/kit/rulecheck.py`.** It reads the ruling files `fold.py
  export` commits (`.overture.json` `fold.locked`, `.overture/locked`
  by default) and the checkout, and nothing else: no store, no server,
  no network. Each ruling is checked the way the console checks it
  (its anchors, else its `valid_if`), with the same plain-words reason
  and diff. Exit 0 every ruling holds, 1 one is broken, 2 it could not
  run.
- **A pull request cannot clear its own failure.** With `--base REF`
  the rulings checked are the ones committed at the base, so editing a
  ruling's anchors or deleting its file in the same pull request still
  fails. A ruling the pull request re-locks (a newer lock whose
  conditions hold) or settles is listed as re-ruled for the reviewer,
  and passes. A ruling the pull request adds must hold too.
- **Every ruling file is held to `fold`'s rules** before anything is
  checked, so a hand-edited file (a pick the owner never made) stops
  the run by name. A symlinked ruling file is refused. An
  `item_status` condition needs the register: it is checked with
  `--adapter` and otherwise listed as unchecked, never as holding.
- **`action.yml`: a GitHub Action.** `uses: MikeHeid/overture@v1.36.0`
  after `actions/checkout` with `fetch-depth: 0`. It writes the report
  to the job summary and, when a ruling breaks, posts one comment on
  the pull request and keeps it updated. Text from ruling files is
  escaped in the comment (no markup, no HTML, no @mention). Inputs
  reach the shell through the environment only.
- New `test_rulecheck.py` (30 tests): real git repositories, a ruling
  exported by `fold.export`, and the changes a pull request would make.
  The Action's shell step runs against a stand-in `gh`.

## Any agent can ask (1.35.0)

Overture's first door for agents other than Claude Code: an MCP server.

- **`plugin/kit/mcp_server.py`.** Any client that speaks the Model
  Context Protocol (Cursor, Codex, Copilot, Claude and others) can
  launch it over stdio and use the agent door as tools: `todo`, `view`,
  `answers`, `check`, `lesson_match`, `health`, `ask`, `reply` and
  `working`. The owner answers in the console as before; rulings,
  stale checks and lessons work the same for these agents.
- **One client, one set of checks.** Each tool runs `agent.py` in the
  server's process with arguments built there, so the project the
  server runs in picks the console and its token, the agent-name rules
  hold, a `view`, `todo` or `answers` read over 64 KiB is refused
  whole, and the console server validates every write. Text that
  starts with a dash stays text. A malformed request, or a failure on
  this machine, fails that one call; the server stays up.
- **Only the agent door.** The steward's commands (`watch`, `synced`,
  `inbox`), the owner's (`register`, `server`, `steward`, `role`) and
  everything that writes into a checkout stay in `agent.py`.
- **Both protocol eras.** The 2025 `initialize` handshake (2024-11-05
  to 2025-11-25) and the stateless 2026-07-28 revision
  (`server/discover`, the version in each request's `_meta`). stdout
  carries nothing but protocol messages. Standard library only.
- New `test_mcp.py` (12 tests): a question asked through a real stdio
  pipe is ruled on by the owner, read back, and reported stale when
  its cited line changes.

## Wizards that stay put (1.34.7)

No new features. Found while fixing a LOW from the 1.34.6 review.

- **An open Launch Idea or Branch Out pane survives a repaint.**
  `renderPanel()` looked the pane up by id only after clearing the
  panel, when it was no longer in the document, so from 1.30.1 on every
  Refresh or live update threw an open wizard away with whatever the
  owner had typed, and left its gutter behind. It now takes the pane
  before the clear and puts it back after.
- **Closing Launch Idea while tickets are being made no longer loses
  the rest.** The spawn read the pane's live state between requests, so
  closing it with a ticket in flight threw on the next one; reopening it
  on another item would have filed the rest there. It now takes the
  item once, before the first request, and closes only the pane it
  started from.
- **Branch Out's research ticket and deliberate round** had the same
  read-after-await; fixed the same way. The research ticket now opens
  the item's Tickets fold, as a Launch Idea spawn does since 1.34.6.

## Spawned tickets in view (1.34.6)

One fix, from the last LOW of the 1.34.5 review.

- **Spawning tickets from Launch Idea opens the item's Tickets fold.**
  The spawn redrew the panel "so the spawned tickets show in the fold",
  but left the fold shut, so the owner saw a closed "Tickets" line and
  none of what they had just made. A comment above the fold already
  said Launch Idea opens it; now it does, through the key `keepOpen`
  reads. A spawn where every ticket failed leaves the fold as it was.
- The other half of that LOW, that the console's open-fold memory is
  never pruned and carries no project, needs nothing: a peer console
  opens in its own tab, so a page only ever holds one project's keys,
  and the set grows only by what the owner opens.

## Folds that stay open (1.34.5)

No new features. A code and security review of 1.34.1–1.34.4 found the
1.34.4 bug in more places, and one renderer the 1.34.3 fix missed.

- **Every fold the owner opens stays open across a repaint.** 1.34.4
  fixed the 📎 chip; seven more `<details>` were rebuilt on every
  Refresh or live update and snapped shut: the tickets list, its
  Closed group, the new-ticket form, each answers-sheet row, the roar
  transcript, the answered footer and the Snoozed section. They now go
  through one helper, `keepOpen(details, key)` in `console.js`, with a
  key per item, question or fork; the chip uses it too.
- **`agent.py lesson-match` splits a reason on `\r\n`, `\r` and `\n`.**
  1.34.3 fixed this in `to_markdown()` but not in the CLI, so a
  hand-edited reason holding `a\r## H` printed a heading at column 0 of
  output an agent reads as Markdown. Both now call
  `lessons.reason_lines()`. `lesson-match` had no test; it has one now,
  which also pins exit codes 0 and 1.
- **Tests:** a browser test for the tickets folds and a sheet row (fails
  on 1.34.4); the 1.34.4 chip test now waits until Refresh has replaced
  the card, so it cannot pass without a repaint; a `LessonTests` name
  says it covers `RecursionError` as well as `ValueError`.
- **Development:** the README says how to install Playwright for
  `test_browser.py`; the test files' usage lines name the repository
  root, not `tools/overture/`; `.venv/` is ignored.

## Lesson chip in a browser (1.34.4)

No new features. The last two open items from the 1.34.1 handoff,
checked in Chromium against the real owner server.

- **An opened 📎 related-rulings chip stays open across a repaint.**
  Every Refresh and every live update rebuilt the question card, so a
  past ruling the owner had opened to read snapped shut the moment an
  agent posted anything. The chip's open state is now kept the way the
  console's other disclosures keep theirs (`openForms`, per question).
  `test_browser.py` gains a test for the chip: shown on the right
  question, reason line breaks kept, open and closed both survive a
  Refresh.
- **Checked, no change:** the owner page's CSP from 1.33.1
  (`img-src 'self' data:`, `connect-src 'self'`). The console loads,
  `data:` images load, the `/api/wait` live poll picks up a new
  question, and the browser console shows no CSP violation; an
  off-origin image or `fetch` is refused, as intended.
- **Checked, no change:** the 1.34.3 review's note that a hand-edited
  lessons row with a deeply nested extra key could make `record()`
  raise `RecursionError`. It does not reproduce: `load()` decodes the
  row at the same stack depth `record()` later encodes it, and a row
  too deep to encode is already too deep to decode, so `load()` drops
  it first. Tried at 100–20 000 levels and 50–900 caller frames.

## Lessons hardening (1.34.3)

No new features. A review of the 1.33–1.34 lessons code found two
contract breaks and two smaller gaps. Each is reachable only through a
hand-edited `STATE/lessons.jsonl` (0600 under 0700).

- **A malformed row can no longer fail the page.** `load()` caught only
  `JSONDecodeError`, but an over-long integer literal raises a plain
  `ValueError` and a deeply nested line raises `RecursionError`. Either
  escaped `/api/view`'s catch, so the console failed on every poll until
  the file was fixed; `agent.py lessons` / `lesson-match` and the next
  record failed too. Such a line is now skipped like any other bad row.
- **A lone `\r` in a reason can no longer spell Markdown.**
  `to_markdown()` indented the reason line by line, splitting on `\n`
  only; CommonMark also ends a line at `\r`, so `a\r## H` put a heading
  at column 0 of the folded file. It now splits on `\r\n`, `\r` and `\n`.
- **The ruling text is collapsed to one line in `to_markdown()` too,**
  not only on record, so a hand-edited row cannot inject a heading there.
- **The size tripwire in `record()` can fire.** It checked the encoded
  size after `_fit()`, which had already pruned an oversized new row and
  every older one, so the write would have emptied the file. It now
  refuses when the new row did not survive `_fit()`, and the file is left
  as it was. Unreachable while the 20 000-character reason cap holds.
- **README:** the related-rulings card shows the ruling's id, not its
  text; `lesson-match` also exits 2 when the lessons file cannot be read.

### Tests

- 4 new `LessonTests`, one per fix above; each fails on 1.34.2.
- `SanitizerTests.test_anchor_nesting_and_refused_hrefs_stay_balanced`:
  nested, unclosed and refused `<a>` and an entity-encoded `javascript:`
  href give balanced output. The 1.33.1 sanitizer already did; this pins it.

## Upkeep (1.34.2)

No new features. Checking the 1.34.1 handoff turned up a test that
only passed outside Claude Code, a stale README path, and two patch
releases of the pinned dependencies.

- **`SessionNameTests` pass when run from a Claude Code session.**
  Claude Code exports `CLAUDE_PROJECT_DIR`, and `run_hook` only
  `setdefault`s it, so the hooks looked at the real, unregistered repo
  and wrote no `export OVERTURE_SESSION=…` line: 4 failures and 1 error.
  The class's `env()` now drops an inherited `CLAUDE_PROJECT_DIR` the
  same way it drops `OVERTURE_SESSION` and `CLAUDE_ENV_FILE`; a test
  that passes its own still gets it.
- **README Development setup** installs from
  `plugin/kit/requirements.txt`. There is no `requirements.txt` at the
  repository root.
- **Pins:** PyJWT 2.15.0 → 2.15.1, cryptography 50.0.1 → 50.0.2.
- **`test_build.py` is green on Claude CLI 2.1.296.** The three
  failures noted at 1.34.1 came from WSL's 2.1.71 CLI, which rejects
  the manifest's `userConfig` key and `--strict`; the manifest was
  right.

## Housekeeping (1.34.1)

No new features. The README catches up with 1.33 and 1.34, and the
leftovers from the 1.33 review are cleared.

- **README.** Lessons and Lesson Match get their own section, a row in
  the feature map, a glossary entry, Trust bullets and changelog
  highlights. The owner-door CSP bullet shows the 1.33.1 directives.
  Version and test-count badges are current.
- **Lessons are cached between page polls.** `/api/view` re-read and
  re-parsed `STATE/lessons.jsonl` (up to 2 MiB) on every poll, and 1.34
  added the matcher on top. The server now keeps the parsed rows keyed
  on the file's (inode, size, mtime_ns); `record()` replaces the file by
  rename, so the next poll reloads. The matcher's trigram sets are
  memoised too.
- **One CSP nonce generator.** The owner page used
  `secrets.token_urlsafe(16)` and the chart routes `token_hex(16)`; all
  now call `_csp_nonce()`.
- **Narrower catch around grill provenance.** `except Exception` became
  `(TypeError, ValueError, AttributeError)`, so a real bug in that path
  is no longer swallowed as a log line.
- **Comments.** Three comments that described what the code does were
  cut to the reason it does it.

### Tests

- `LessonTests.test_stamp_moves_on_every_record` and
  `RefactorTests.test_the_lessons_cache_reloads_after_a_withdraw`: the
  cache key moves on every record, and a withdraw shows up on the next
  poll.

## Lesson match (1.34.0)

Lessons stop being passive. 1.33 wrote the owner's reasons into
`STATE/lessons.jsonl` and told agents to read them on session
start; 1.34 surfaces them AT RULING TIME, so a new question that
rhymes with a past withdrawn one carries a chip the owner can
expand before they lift a finger — the "will I re-litigate this?"
check is now a glance.

- **`lessons.match(text, item, rows)`.** Trigram Jaccard with a
  same-item filter and a newest-first tie-breaker (`unicodedata`
  NFKD + combining-mark strip + casefold, so "Café" matches
  "cafe"). Returns top-3 by default above a 0.15 threshold; the
  tuned threshold catches "retry 5 times on upload" ↔ "5 retries
  with exponential backoff" (same topic) and skips coincidence
  between unrelated short questions.
- **`view.questions[*].related_lessons`** on the owner door's
  `/api/view`. The server reads lessons once per `page_payload`,
  calls `match()` for each OPEN question (`awaiting_you`,
  `unlocked`, `stale` — never for already-settled rulings so the
  chip is never nagging), and attaches
  `[{qid, kind, ts, score, reason_preview}]`. Reason preview is
  capped at 400 chars; the full reason stays behind
  `agent.py lessons`.
- **Chip on the question card.** The owner page shows a 📎 chip
  reading "*N related past rulings — read before answering*"
  which, when clicked, expands a panel with each match's date,
  qid, kind label (`withdrawn` / `kept unchecked`) and reason
  preview in a monospace block. Styling in the warn-tone palette
  so it sits distinct from the grill-origin chip.
- **`agent.py lesson-match "<text>" --item ITEM`.** The ask-side
  mirror. Reads `STATE/lessons.jsonl`, runs the same matcher the
  server runs, prints the top matches as Markdown. Exit 0 on any
  match, 1 when none, so a script can gate on it before posting.
  `--top` and `--threshold` tune the search; the chip is not hidden
  by skipping this step (the server surfaces the same list).

### Trust

- The matcher is pure stdlib (`unicodedata`, set intersection). No
  network, no new state file.
- The item filter is strict: a lesson on `UI` is not a hint for a
  question on `API`, even if their texts rhyme.
- Settled questions (`locked`, `withdrawn`, `superseded`) never
  carry `related_lessons`; the owner is not nagged about rulings
  they already decided.
- Reason previews cap at 400 chars inside the view; a long reason
  only travels whole via `agent.py lessons`, which still gates on
  the STATE socket (0600 under 0700).
- A false positive is a glance the owner wastes; a false negative
  is a re-litigated ruling. The 0.15 threshold errs on recall; raise
  with `--threshold` on the CLI if the chip gets noisy.

### Tests

- 7 new `LessonMatchTests` in `test_kit.py`: ranking by similarity,
  item filter, threshold refuses noise, top-K newest-first tie,
  preview truncation, empty-inputs, NFKD folds "Café" into "cafe".
- 1 new integration test in `test_server.py::RefactorTests`: a
  withdrawn ruling's reason surfaces on a new question's view entry
  on the same item; a sibling-item question gets no match; the
  withdrawn question itself gets no self-reference chip.

## Review fixes (1.33.1)

Three parallel reviews — code, security and Python — crossed the 1.31–1.33
arc after Lessons shipped. 1.33.1 lands every HIGH finding and the
material MEDIUMs. No new features; `agent.py lessons`, `view.lessons`
and the SessionStart line all behave the same way to the owner.

### Lessons: durability and validation

- **`load()` no longer faults `/api/view` on a hand-edited row.** The
  shape validator (`_check`) now returns a `LessonError` for every
  malformation, including a missing field or a non-string value that
  was previously surfacing as `KeyError` or `TypeError` through the
  regex matchers. The server's `(LessonError, OSError)` catch covers
  both server call sites unchanged.
- **Byte-based FIFO prune.** `MAX_LESSONS` (2000 rows) and `MAX_FILE`
  (2 MiB) are now both respected on `record()`: whichever bites first
  wins, so a wall of long reasons cannot wedge the feature by filling
  the file. Pre-1.33.1 the count cap alone meant ~105 maximum-length
  reasons could lock out every later lesson.
- **`MAX_REASON` aligned with `schema.MAX_TEXT`.** The store accepts
  reasons up to 20 000 characters; lessons now does too. A reason in
  the 10 000–20 000 gap previously landed in the fold record but
  silently vanished from the lesson log.
- **Markdown injection closed.** The question `text` is collapsed to
  one line on `record` so a `\n## …` can no longer spell a false
  heading in the folded doc. The owner's `reason` is written as a
  4-space-indented code block so no Markdown spelling inside it
  (headings, lists, HTML) activates. Future agents read it as prose;
  the format itself refuses to pretend any part of it is structure.
- **`agent.py lessons --fold PATH` is now actually atomic.** The old
  path used `write_text` + predictable `.tmp`, which followed a
  pre-planted symlink. 1.33.1 writes via `atfile.write_at` on a dir fd
  on PATH's parent, so the write is O_EXCL + fsync + rename and
  refuses any symlink or non-regular file at the target name
  (`O_NOFOLLOW`).
- **Load splits on `"\n"` only.** `splitlines()` splits on U+2028,
  U+0085 and `\x0b`/`\x0c` too, so a reason containing one of those
  characters could spell a forged row or lose its own on parse. The
  switch keeps control characters inside the reason.
- **The hook flag matches its own docstring.** `_lessons_line` now
  passes `nofollow=True` to `_read_regular` (the docstring already
  claimed it did); the message says "up to N lesson(s)" so the hook
  count and the view count — which validates and the hook does not —
  agree.
- **Windows import works.** `O_DIRECTORY` and `O_NOFOLLOW` fall back
  to 0 on win32, so IDE tooling can import the module without raising
  `AttributeError`. The actual security guarantees still ride on
  `atfile.read_at`/`write_at`, which are POSIX-only and only run on
  POSIX hosts.
- **Tests.** 11 new tests in `test_kit.py::LessonTests`: record +
  load, byte-FIFO prune at the cap, count-FIFO prune at `MAX_LESSONS`,
  reason alignment with `schema.MAX_TEXT`, text collapsed on record,
  reason wrapped as a code block in Markdown, malformed-row isolation
  (`KeyError`/`TypeError` paths no longer fault load), U+2028 cannot
  forge rows, empty state, newest-ts summary.

### Sanitizer: visuals.py

- **Stray `</a>` on refused-link closer.** An `<a>` with no `href` is
  not emitted (correct), but was still pushed onto the tag stack, so
  a later `</a>` emitted a close without an open. The push now
  happens only after a successful emit.
- **Author `rel` can no longer override the forced one.** Browsers
  take the first occurrence of a duplicate attribute; the sanitizer
  appends `rel="noopener noreferrer"` AFTER author attributes, so an
  author `rel` won. `rel` is now dropped from the `<a>` allowlist,
  leaving the forced one in sole possession.
- **`handle_decl` emits a fixed doctype.** A declaration carrying
  `</textarea>` or `</title>` in its text could unbalance the parse
  tree. 1.33.1 emits `<!DOCTYPE html>` for anything that looks like a
  doctype and drops everything else.

### Server: owner-page CSP and CSRF

- **CSP names `img-src` and `connect-src` explicitly.** The owner
  page's response-level policy replaces the shared default (not
  merges), so leaving the directives unstated let both default to any
  origin — COEP `require-corp` incidentally blocked cross-origin
  images, but relying on COEP for subresource restriction mixed
  concerns. The policy now says `img-src 'self' data:` and
  `connect-src 'self'`.
- **`hmac.compare_digest` no longer drops the connection on a
  non-ASCII CSRF header.** A header with any code point above U+007F
  raised `TypeError` outside the response handler, which the server
  turned into a connection drop rather than a 403. 1.33.1 encodes
  both sides to ASCII bytes under a `UnicodeEncodeError` guard; a
  non-ASCII header fails closed with a proper 403.

### Housekeeping

- Three leftover cosmetic edits from the 1.33.0 version-literal
  scrub are reverted — dangling periods and colons in `designs.py`,
  `registry.py`, `view.py`.
- `MEMORY.md` and `AGENTS.md` unchanged. No new dependency, no new
  state file, no API shape change on the owner door.

## Lessons (1.33.0)

The audit trail turns generative. Pre-1.33 the owner's reasons for
withdrawing or stopping-to-check a ruling lived only in the fold
record; a new session saw the ruling was gone but not **why**, and
would often re-litigate the same ground. 1.33 captures those reasons
as **lessons** every new agent reads on session start.

- **`STATE/lessons.jsonl`.** New append-only file written via the same
  `atfile.write_at` pattern as `drafts.json` and `tickets.json`:
  O_NOFOLLOW on the dir fd, O_EXCL on the temp, fsync, atomic rename.
  Each row: `{ts, qid, item, kind, text, reason, replaced_by}`.
  `kind` is `withdraw` or `untrack`. Caps: 2000 lessons (FIFO pruned),
  10 000-char reason, 2 MiB on disk.
- **Wired into `Console.refactor`.** When the owner acts on a stale
  ruling via `/api/refactor` with action `withdraw` or `untrack`, the
  server records a lesson after the regular refactor write lands.
  Confirm (re-anchor) is NOT a lesson — it is the same decision with
  moved evidence. A lesson record failure never faults the refactor:
  the ruling act lands first; a stderr line reports the lesson error.
- **`view.lessons: {count, newest_ts}`** on the owner door's
  `/api/view` so the browser can show "N lessons" alongside drafts,
  tickets and backlinks. Full list is served via the CLI below, so no
  reason text travels through every live view.
- **`agent.py lessons [--fold PATH]`.** Prints the stored lessons as
  Markdown to stdout (one H2 per lesson, newest first). With `--fold
  PATH`, writes atomically to the project tree — commit the file so
  every machine's SessionStart hook reads it from the commit.
- **SessionStart hook mentions the count.** Every registered-project
  session now sees one line: *"N lesson(s) from past rulings. Read
  them with `agent.py lessons`, so this session does not re-litigate
  what the owner has already settled."* Silent when zero.

### Trust

- The lessons file is owner-write only. The refactor route that
  triggers a record is already owner-door only; the agent socket has
  no path to append a lesson.
- Nothing in a lesson travels off the machine. Peers never see the
  file; `/api/view` carries only the count and the newest timestamp.
- The file is written whole on each record (full existing list + the
  new row, FIFO-pruned, atomic rename). A crash mid-write leaves the
  prior file unchanged, as with every other state file.
- The SessionStart line is read-only. The hook opens the file with the
  same `_read_regular` guards it uses for the doorbell: regular file,
  size-capped, non-blocking, no symlink follow.
- The owner's reason is required (uncapped above `MAX_REASON`) because
  a truncated reason loses the signal lessons exist to carry. The
  server refuses over-cap rather than silently cutting.

## View (1.32.0)

UX View is the headline: a component modal on UX items with versions,
sizes, Generate, Save as component, a Claude Design link and its
design-system picker, a Scripts switch, and Merge from the PR tab.
Around it: a Tickets board with a blocker graph, Lucide icons and
distinct state marks, tabs that fit on one line, lane colours,
screenshots in the Feed, attachable images, a server daemon/service
mode, and a Machine role setting. Security: published pages' own
scripts run again under the nonce CSP (by exact hash), the console
listens only to its own chart frames, and HTML visuals' controls are
inert. Mermaid diagrams render again, and the browser suite is green.

- **Design-system picker for UX View.** With a Claude Design linked, an
  agent can list the project's artifacts (`agent.py design-inventory`), and
  UX View's Settings then offers them: filter, tick up to 10, and choose
  **inspire** (borrow the look) or **swap** (build the new version from that
  artifact). **Generate** carries your picks as `refs`; the server refuses a
  pick that is not on the agent's list. Nothing opens or fetches the design
  from the console, and a swap is always a new version, never an overwrite.
  Without a list, **Ask an agent to list it** posts the request on the item.

- **Machine role (D11).** A new plugin setting, **Machine role**
  (`steward` or `worker`), and `agent.py role worker|steward|clear` in your
  registry. On a `worker` machine no session is the steward, whatever it is
  named: `/overture:as <steward>` is refused, a session started under that
  name is told so and cannot ask you live, and `watch`, `synced` and the fold
  refuse. Use it when the steward runs on a home server and laptops only
  work. If the plugin setting and the registry disagree, `worker` wins.

- **Attach your own images (F2).** In an item's Discussion box, **Attach
  image** (or paste an image) puts your picture on that item beside the
  agents' screenshots, shown as "you" in the Feed. It is checked like an
  agent's (PNG, JPEG, WebP or GIF; 2 MiB, or 8 MiB for a GIF), is always a
  screenshot, and has its own rate limit so it never uses an agent's.
- **Fixes.** A Design link you are typing in UX View no longer disappears
  when the console refreshes; UX View follows a new version when you are on
  the newest one; the Feed can be filtered to merge requests and links back
  to the PR tab.

- **Run the server your way: `server.py daemon|service|status|health`
  (D1–D3).** `server.py daemon start|stop` runs the one server detached
  with a pid file and a log; `service install|uninstall` writes and enables
  the `overture-console.service` systemd user unit (Linux, WSL; `--start`
  also starts it); `status` and `health` only read, and `health` reports the
  agent door, each project's port, version skew and linger, and removes a
  stale pid or socket file. A daemon and a service refuse to run together,
  naming each other. When the one server is down, the SessionStart hook adds
  one line saying how to ask. `server.py --all` in the foreground is
  unchanged. macOS launchd comes next.

- **UX View: the Scripts switch (step 4, D4).** A component can now run
  script, only if you turn it on. The visual an agent posts stays
  script-free; an agent may also store a scripted source beside it
  (`agent.py component-source`, write-once). **Settings → Scripts (this
  version)** sends your `ux-scripts` request; only then does
  `/api/component-render` serve that source, in a frame sandboxed with
  `allow-scripts` only (no same-origin, forms, popups or top navigation)
  under `default-src 'none'; connect-src 'none'`. The modal shows "⚡ Scripts
  on", and a save with it on lands the scripted source with `scripts: true`.
  This reverses part of the 1.31 hardening for that one route; it is off by
  default and per version.

- **Merge from the PR tab (UX View step 3, D7).** An open, ready, passing
  pull request gets a **Merge** button on the PR tab, confirmed inline. The
  server merges nothing and holds no GitHub token: Merge sends an owner
  request on the new reserved `@prs` thread naming the PR and the head commit
  you saw, and the steward's session merges with its own `gh`:
  `agent.py pr-merge --project WORKTREE --request ID`. It re-reads the PR,
  refuses by name (not ready, checks failing, new commits since you asked,
  request over 24 hours old) and replies on `@prs` either way; the merge uses
  `--match-head-commit`. The PR snapshot gained an optional `head_sha`
  (`prs-push` sends it), and a kit older than this refuses a store holding an
  `@prs` message, by name.

- **UX View (step 2: the modal).** On a UX item, **◫ UX View** opens a
  full-screen overlay (shortcut `u`; every HTML visual also has **Open in UX
  View**). It shows the item's HTML versions in an empty sandbox at Mobile,
  Tablet, Desktop or Fit width, with a version stepper, **Generate ▾**,
  **Save as component** and a Settings panel for the Claude Design link.
  It sends the step 1 messages and writes no file. The Scripts switch comes
  in a later step.

Found while rendering the new README screenshots against a full
example dashboard.

- **The status chip works.** The chip has said **down** on every
  console since it shipped in 1.23.0. It fetched
  `config.api + '/api/status'`, which is `/api/api/status`, a 404.
  It now fetches `/api/status`, the route the server serves.
- **Snooze menus stay closed until opened.** `.ck-snooze-menu` set
  `display: flex`, which overrides the `hidden` attribute, so every
  priority row drew an empty dropdown under itself. A `[hidden]` rule
  now wins.
- **The docked column is wider and the tabs scroll.** The default
  column went from 420px to 480px, and you can still drag it to any
  width. The tab strip scrolls sideways at every width instead of
  cutting off its last tabs. Before, it only scrolled below 640px.
- **Priority rows truncate their text, not their controls.** A long
  question now ends in "…", and its age and snooze button stay in
  view.
- **Wording.** "1 Living ruling needs review" (it said "need").
- **README.** Rewritten for people new to Overture: what it is in one
  line, screenshots, three steps, and a glossary. The strategy review,
  roadmap lanes and progress estimates are in `docs/STRATEGY.md`.
  `docs/demo/screenshots.py` regenerates the screenshots from
  `docs/demo/showcase.html`, an example dashboard with waves, phases
  and lanes.
- **Release zips.** The release assets for 1.23.0 through 1.31.0 were
  copies of the repository, not the output of `build_zip.py`. So the
  local install route in INSTALL.md (`overture@overture-local`, and
  `~/overture/plugins/overture/kit/...`) did not work from them. The
  last step that `release.py` prints now names the `build_zip.py` and
  `gh release create` commands. A rebuilt `overture-1.31.0.zip`
  passes `claude plugin validate --strict` and installs as
  `overture@overture-local`.
- **"Shipped:" and "Mentioned in" links work on anchored rulings.**
  The backlink scan built the view with `{}` where the function that
  checks rulings belongs. The first question with a `valid_if`
  condition raised "'dict' object is not callable", the error was
  swallowed, and every project with anchored rulings showed no PR or
  issue links at all.
- **Mermaid visuals render.** `/api/visual-render` compared the stored
  format to `"mmd"`, the file suffix, but visuals are stored as
  `"mermaid"`. So every diagram an agent drew answered 400, and the
  owner saw an empty frame. This was broken since at least 1.0.0.
- **Diagrams are styled and fill their frame.** The diagram frame's
  CSP had `style-src 'nonce-…' 'unsafe-inline'`, and browsers ignore
  `'unsafe-inline'` when a nonce is present. That refused the `<style>`
  Mermaid injects, so diagrams drew as black boxes with dark edges.
  `style-src` is now `'unsafe-inline'` alone, which is safe in an
  opaque-origin frame with no network. Mermaid also follows the
  light or dark scheme now. A diagram fits its frame on load, where it
  used to collapse to a small size, and ⬚ re-fits it.
- **README tour.** Each capability in "What you can do" has a
  screenshot, and five GIFs show the interactive ones: answering a
  round, Lock all, a stale ruling's diff, the command palette, and the
  status flowchart. `docs/demo/screenshots.py` now drives the real
  server.
- **Master agent name in the plugin settings.** A new `steward` field
  (`/plugin` → overture → configure) gives onboarding its default
  master agent. `onboard.py write --steward NAME` checks the name and
  prints it into the `register` step, followed by the
  `/overture:as NAME` reminder. The name is never written into the
  project, so a repository still cannot name the steward.
- **docs/JOIN.md.** How to join another project to the main server
  (`server.py --all`): a one-time systemd unit, then per project
  `register`, the Cloudflare app and tunnel rule, `server add`, a
  restart, and `health`. Every command was run in a sandbox first.
  MIGRATION.md no longer says the shared server is unbuilt.
- **docs/proposals/SERVER-HOSTING.md.** A write-up on running the
  server: a per-OS user service (recommended), not one started from a
  Claude session, plus a read-only session check.
- **The first-run banner points to onboarding.** After a plugin install,
  the banner told users to run
  `~/.local/share/overture/kit/plugin/kit/agent.py register`. That path
  does not exist, and `register` needs `--state` and `--project`. It
  also told them to run `systemctl --user start overture.service`, a
  unit that does not exist. It never mentioned
  `/overture:console-onboard`. It now names that one next step, how the
  server gets installed, and the join guide. The upgrade banner names
  the real `install.sh` path and the units that exist. Tests check
  that every command it prints is real.
- **Tickets tab.** A board across every item: Open, Blocked and Closed
  columns, a filter by kind, item chips that open the item, and `g k`.
  It also appears in the command palette and the shortcut sheet.
- **What blocks what.** `/api/ticket-chart` (`?item=` optional) draws
  tickets as a Mermaid graph, with arrows from blocker to blocked. It
  is grouped by item and coloured by status, and clicking a ticket
  opens its item. It appears on the Tickets tab and on an item's
  Tickets fold when that item has blocking. Titles are owner text, so
  labels go through the chart sanitizer.
- **Blockers are named by title.** "Blocked by" shows the blocker's
  title instead of its id; the id is kept in the tooltip.
- **Ticket fixes:**
  - A ticket blocked by an already-closed ticket was marked "blocked"
    for good, because nothing would ever unblock it. A closed blocker
    now blocks nothing.
  - Closing a ticket twice overwrote its first close time. Closing an
    already-closed ticket now changes nothing.
  - A ticket filed under an item the project does not list was stored
    but never shown. It is now refused by name.
- **Ticket tests.** `tickets.py` and its routes had no tests. Now 9
  unit tests and 5 route tests cover create, update and close,
  blocking, cycles, field checks, the view, the chart and the owner
  gate.
- **PR cards.** Each pull request on the PRs tab is a bordered card whose
  left edge shows its state: open, checks running, checks failing,
  draft, merged or closed.
- **Shortcuts button.** The footer has a **⌨ Shortcuts** button that
  opens the shortcut sheet, so `?` is no longer the only way in.
- **Chat ▾ on items.** A split button on every item: **Chat** jumps to
  the item's discussion. Its menu routes to **Branch out**, **Grill**
  (Launch Idea's grill step), **Advise** (the deliberation form) and
  **Delegate** (the Delegate bar, with the item preselected).
- **docs/proposals/UX-VIEW.md.** A proposal for UX View: a component
  modal with Save, Generate and Generate with input; components saved
  to `components/<item>.md` with a dated backup, through the steward;
  new UX items placed into their lane automatically.
- **Icons (D8).** A bundled subset of 24 Lucide icons (lucide-static
  0.460.0, ISC; the licence is in `vendor/LUCIDE-LICENSE.txt`), drawn
  inline with `currentColor`, so there is no icon font, no CDN and no
  request. Every tab, the More menu, the Chat ▾ menu and the footer's
  Shortcuts button show one.
- **State marks.** The near-identical circles (◐ ◑ ○ ◌) are replaced by a
  distinct shape per state, and each keeps its colour and its words:
  - awaiting you: a dotted circle;
  - awaiting an agent: a bot;
  - answered, not locked: an open lock;
  - locked: a lock;
  - stale: a warning triangle;
  - withdrawn: a ban sign;
  - superseded: crossed arrows.

  They appear on question chips, inbox rows, the filter chips, the
  dashboard's item buttons and section badges, the answers sheet,
  round cards and the Portfolio tallies. The Portfolio tallies now read
  `3 you`, `1 stale` instead of `?you`, `!stale`. Markdown exports and
  desktop notifications keep their text marks.
- **Tabs fit on one line (D9).** Tabs show an icon and a label. The
  docked column is never narrower than its tab row: it measures the row
  after each draw and widens if needed. To keep that near the old
  width, Playbooks and Triggers moved behind **More ▾** (their `g`
  shortcuts still work), and the Portfolio tab's count no longer says
  `?you`. In the narrow overlay the row still scrolls sideways.
- **Security: the console hears only its own chart frames.** The
  console's `message` listener acted on any window's `postMessage`.
  Another frame on the dashboard page, or a popup, could force an SVG
  download or steer the panel to an item. Every frame the console makes
  with `allow-scripts` is now marked, and a message is accepted only
  from one of those frames' windows, with the opaque origin `null`.
- **Security: the Mermaid render page sandboxes itself.** Its CSP now
  starts with `sandbox allow-scripts`. Before, `/api/visual-render`
  opened in its own tab ran its script in the console's real origin;
  only the parent's iframe attribute sandboxed it.
- **MIT license.** `LICENSE` at the root and in `plugin/`, so the release
  zip carries it, and `"license": "MIT"` in the plugin manifest.
- **The console-ux skill.** UX components are now drawn by their own
  skill, written as a UX lead and a component engineer in one. It holds
  four researched references (checked on 2026-10-11, with sources):
  - **principles:** WCAG 2.2 AA as rules, the laws of UX, Nielsen's
    heuristics, microcopy;
  - **patterns:** how the leading design systems build each component,
    and the no-JavaScript recipe for each;
  - **style:** tokens in the W3C 2025.10 format, type, colour, motion, and
    which 2025–2026 trends last;
  - **checklist:** a gate every version passes.

  Components work with **no JavaScript** while Scripts is off. They use
  `<details name>`, `popover`, invoker commands, `:has(:checked)` and
  anchor positioning. A worked example, a plan picker, passes the whole
  gate. console-process routes visual requests on UX items to it.
- **`tools/ux_check.py`.** Runs a component through the server's own
  sanitizer and names, by the sanitizer's own rules, every element,
  attribute and attribute value that would be stripped. With Playwright,
  it renders the component exactly as UX View will: sandboxed, under the
  server's CSP, with JavaScript off, at 375, 768 and 1280px, in light and
  dark.
- **Inert controls in HTML visuals (S1).** `button`, `input`, `select`,
  `textarea`, `label`, `fieldset`, `details`/`summary`, `dialog`,
  `progress`, `meter` and friends now survive the sanitizer, as do
  `aria-*`, `popover`, `popovertarget`, and the built-in invoker
  `command`/`commandfor`. Nothing can submit, load or run:
  - there is no `<form>`, `formaction` or `autofocus`;
  - `type="file"` and `type="image"` are refused;
  - custom `--commands` are refused;
  - `autocomplete` is dropped, so a component can't prompt the browser to
    offer saved passwords or cards.

  A self-closed non-void tag such as `<style/>` is now written as an empty
  element. Browsers ignore the `/`, so it used to swallow the rest of the
  visual as CSS.
- **Fix: CSS in an HTML visual was HTML-escaped.** The sanitizer ran
  `<style>` content through the text escaper, so `a > b` became
  `a &gt; b` and `"x"` became `&quot;x&quot;`. Every child selector,
  attribute selector and quoted font or `content` value silently stopped
  matching. CSS now passes through as written, with `<` turned into the
  CSS escape `\3C`, so no markup can be spelled inside it.
- **Screenshots in the Feed** (FEED-ASSETS.md). Agents post screenshots
  and recordings on an item with `agent.py asset ITEM --file … --caption …
  [--kind before|after|screenshot|recording] [--qid] [--pr] [--ticket]`.
  - **Where they show:** in the Feed, under a new **Screenshots** filter,
    with a before and after side by side; in a **Screenshots** fold on the
    item; and in a full-size viewer with ◂ ▸ and the arrow keys.
  - **Your controls:** star one to keep it; delete it from the owner door
    only, with a two-step confirm. Under reduced motion a GIF waits for a
    press of play.
  - **Formats:** PNG, JPEG, WebP or GIF, judged by the file's magic bytes;
    SVG is refused.
  - **Limits:** 2 MiB for a still, 8 MiB for a GIF, 8000 px on a side;
    30 per agent and 120 per project per 10 minutes (unnamed agents share
    one bucket); at most 3000 in the index. Format, size and sides are
    checked before the server takes its lock, and a JPEG's header scan stops
    at 256 KiB, so a crafted file can't stall the console.
  - **Storage:** files are kept under `STATE/assets/`, outside the store, so
    an older kit still opens the project. Each is served sandboxed with
    `nosniff`. The same bytes posted twice on an item are one asset.
  - **When space runs short (F1):** at 100 per item or 300 MiB per project,
    the oldest screenshots that are neither starred nor linked to a PR are
    removed, and the Feed notes each one. A starred "after" keeps its
    "before".
  - **When agents post (F3):** the console-process and console-ux skills
    post a before and an after for every visible change.
- **The Feed's filter row stays on one line (D9).** Its selects now shrink
  instead of wrapping.
- **Lane colours (D10).** A lane is the `lane-…` segment of an item's
  section, inherited from its parent. Each lane gets a colour from an
  8-colour palette, checked at 3:1 or better against the surfaces in light
  and dark.
  - **How colours are picked:** configured colours first, then each other
    lane in name order takes its hash's colour or the next free one. The
    console and the project map use the same rule, and two lanes share a
    colour only past 8.
  - **Where they show:** a lane chip with a matching left edge on inbox and
    Priority rows, and a "Wave › Phase › Lane" trail on the item.
  - **Your dashboard:** items get `data-ck-lane` and `data-ck-lane-color`,
    plus `--ck-lane-<colour>` custom properties to style with.
  - **Config:** `.overture.json` takes `lanes: {"lane-x": {"color", "label",
    "ux"}}`, with palette names only and anything else refused by name.
    `ux: true` makes the lane a UX lane for console-ux and console-process.
- **The project map is boxed by lane and drawn left to right.** A wide,
  shallow tree (waves over many items) used to render as one unreadable
  row, the bug logged earlier. Now its leaves stack down the page, grouped
  in lane-coloured boxes.
- **Tall charts fit to width.** A chart much taller than its frame (the
  project map, now drawn left to right) is scaled to the frame's width and
  opens at its top, so its labels stay readable. Shorter charts still fit
  whole.
- **Fix: no traceback when a browser drops a chart, visual or screenshot
  mid-answer.** The owner door already treated a closed connection as
  normal for JSON answers. Raw answers (`_send_raw`: charts, visuals,
  assets) now do the same, so a re-render or a closed fold no longer logs a
  `BrokenPipeError` traceback.
- **Fix: the status chip no longer covers the skin and theme toggles.** It
  sits in the header's own row, before the toggles. The header's buttons
  keep their width and the title shrinks with an ellipsis instead.
- **Project map filter chips use the state icons** (D8), instead of the old
  `? ! ~ o` text marks.
- **UX View, step 1: the save path, without the console yet**
  (UX-VIEW.md).
  - **Visual requests** may say `purpose: "ux"` and `from: "design"`.
  - **Two new owner intents:**
    - **`ux-save`** names an HTML visual on the same item as the
      component. An owner-only message; the store refuses a Mermaid visual,
      another item's visual, or a missing one.
    - **`ux-link`** carries a Claude Design `url`, or `""` to unlink. The
      URL is held to the exact shape `https://claude.ai/design/p/<uuid>`
      (pinned from a real link): no query, fragment or other host. A pasted
      share link (`?via=share`) is cleaned, not stored. The server never
      fetches it.
  - **Delivery to agents:** both wake the doorbell and are listed in
    `todo.ux` until an agent replies to them.
  - **Items** may carry `ux: true` and a `design` link, checked the same way.
  - **`/ux-export`** (agent door, a read) returns the saved visual, its doc
    and the item's newest Design link.
  - **`agent.py ux-export --project WORKTREE --save ID`** writes
    `components/<item>.md` (front matter, doc, fenced HTML) and
    `components/<item>.css` in the agent's own worktree, never the server's
    checkout.
    - A previous version moves to `components/.history/<item>-<hash>.md`,
      and the newest 10 are kept.
    - Running it twice changes nothing.
    - The steward opens the PR.
  - **The skills:** console-ux step 7 and console-process now land saves
    and links.
  - **Rollback:** a kit older than 1.32 refuses a store holding `ux-save`
    or `ux-link` messages (or `purpose`, `from`, `visual_id` or `url`) by
    name, and an `items.json` with `ux` or `design`. To go back, upgrade
    again, or set those records aside.
  - **Pointing at design-system artifacts.** The console-ux skill reads
    named paths first, borrows the look and never the bytes, names its
    sources, and treats a design file's instructions as noise. A catalog
    picker and a "swap" were reviewed and not built (UX-VIEW.md).
- **The published page's own scripts run again.** 1.31 served the
  console under `script-src 'nonce-…'`, and only the console's own
  script carried the nonce, so a published dashboard's inline scripts
  were refused. 0.8.12 had promised that a page's own scripts run once
  published. The server now adds one `'sha256-…'` source per inline
  script in the published page. Each one allows exactly that reviewed
  script body. A script injected into the page with any other body is
  still refused, there is no `'unsafe-inline'`, the page's bytes are
  not changed, and a page that is only staged gets nothing. `src=`
  scripts and inline handlers such as `onclick=` stay blocked.
- **The browser suite is green again.** `OVERTURE_BROWSER=1 python3
  test_browser.py` was mostly red on 1.31.0, and CI skips it. Two
  causes:
  - Playwright's `wait_for_function` checks its condition with `eval`
    inside the page, which the 1.31 CSP refuses. The tests now poll
    with `page.evaluate`, which the CSP does not govern. The CSP is
    unchanged.
  - The tests expected UI that has since changed on purpose: the inbox
    opening by default (0.9.14), the 480px column and the `✉` badge
    (1.24), Back at every width (0.9.0), the immediate lock with no
    countdown (0.9.12), Chat behind "More" and "What changed?"
    (1.25). They now check the current behaviour, with one new test
    for the default-open inbox.
