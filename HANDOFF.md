# Overture: handoff, 2026-10-13

For the next session. This branch (`handoff/2026-10-13`) is `main` at **v1.34.1** plus this file only.
The previous session's job ended with 1.34.1 shipped; your first job is to **check its work**.

## Check results, 2026-10-13 (agent-8)

All seven items below are done.

- **v1.39.0 released — who may decide** (PR #166, `7e7dbb5`): `STATE/roles.json` (roles.py) owner / member(areas = item
  subtrees) / viewer; no file = all owner; unlisted/no-email = viewer; bad file = writes 503. `Console.role_gate` before
  the body, `area_gate` after (member: answer, lock, plain message {item,text,nonce,reply_to}). Drafts to owners only.
  `agent.py access` (refused under CLAUDECODE). Next in Wave 3: routing ("mine" filter), two-key locks.
- **v1.38.1 released — locked by, on the card** (PR #165, `a5708bb`): owner-door `view["locked_by"]` (answer id → login);
  the receipt shows "Locked by EMAIL" (text only). Browser suite re-run after 1.38.0: 92 OK.
- **v1.38.0 released — who decided** (PR #164, `a095d68`): owner writes keep the Access JWT `email` per request
  (thread-local set in `_gate`, `Store.on_append` / `refactor.Log.on_append` → `STATE/operators.jsonl`, 0600).
  Feed shows "by EMAIL"; agent socket never does. Owner ruled 2026-10-14: no email in committed files, so
  `agent.py operator-name EMAIL NAME` → export adds `locked_by_name` only. Review 3 rounds + Sourcery (session
  listing masks emails). `OperatorTests` 12. Not done: show who locked on the question card (Feed only).
- **v1.37.0 released — strict, no token beside the adapter** (PR #163, `4a68867`): `--strict`/`strict`; Action is
  three steps (check: no token, `env -i`; comment: skipped with adapter; finish); adapter refuses a persisted
  checkout token; exit 0 without a report = error. Verified on scratch repo `MikeHeid/overture-rulecheck-scratch`
  (private; PRs #1 on v1.36.0, #2 on 1.37: fail + comment, fix turns it green). Owner may delete that repo.

- **v1.36.0 released — rulings that block a merge** (PR #162, `acddc57`): `plugin/kit/rulecheck.py` checks the
  committed ruling files (`fold.py export`) against the checkout with no server; `--base` reads rulings and
  `.overture.json` at the PR base, so a PR cannot pass by editing/deleting a ruling; re-lock/settle in the PR is
  "re-ruled" for the reviewer. Root `action.yml` (composite): job summary + one inert PR comment. `test_rulecheck.py`
  30 tests, 23 mutants caught; independent review 3 rounds (HIGH: config read from the PR) then green. Sourcery was
  still pending at merge. Not yet run on a real GitHub PR. Follow-ups: `--strict` (unchecked item_status fails),
  run the Action on a scratch PR, then operator identity on locks.
- **v1.35.0 released — MCP server** (PR #161, `d3096e5`): `plugin/kit/mcp_server.py`, stdlib-only stdio MCP server
  so non-Claude agents (Cursor, Codex, Copilot) use the agent door: todo, view, answers, check, lesson_match, health,
  ask, reply, working. Runs `agent.py` in-process (same door/token/name/cap checks); no steward/owner/checkout
  commands. 2025 handshake + stateless 2026-07-28. `test_mcp.py` 16 tests, 11 mutants caught; independent review
  green after one fix round (crash-on-hostile-line, relative --state, bare `--`). Next per STRATEGY.md: a standalone
  `check` + GitHub Action (stale rulings on PRs), then operator identity on locks. Not yet tried in a real
  Cursor/Codex session.
- **Lane 3 merged** (PR #160, `8ef2571`, test only, no release): `LiveConsoleTests.test_a_related_ruling_reaches_the_card_
  from_the_real_server_under_its_csp`, the 1.34.4 probe made permanent. Fails on three mutants (`related_lessons`
  renamed; CSP loosened; an inline script). Browser 91. ⚠ One unidentified ERROR in 1 of 3 full browser runs; not
  reproduced in two more full runs or 10 loops of the new tests. If it recurs, save the log and name it.
- **v1.34.7 released** (PR #159, `8925dde`): `renderPanel()` looked `#ck-launch-pane` up after clearing the panel, so
  since 1.30.1 every Refresh / live update threw an open Launch Idea or Branch Out pane away. Fixed, plus Launch
  Idea's spawn and Branch Out's two buttons reading pane state after an await (close mid-request threw and dropped
  the rest of the tickets). Three browser tests, each RED on 1.34.6.
- **pip-audit**: shipped pins (`plugin/kit/requirements.txt`) clean. The dev `.venv` had setuptools 65.5.0 (4 PYSEC
  advisories, never shipped); upgraded in place. Remote URL updated to `https://github.com/MikeHeid/overture.git`.

- **v1.34.6 released** (PR #158, `301a0b7`): Launch Idea's spawn now opens the Tickets fold it spawned into, so the
  comment at ~`console.js:2917` is true. The `openForms` half of the LOW below needs nothing: a peer console opens
  in its own tab (`window.open(..., '_blank')`, ~`console.js:1951`), so a page holds one project's keys. Browser 87.
  `pip-audit` not run: the lean-ctx shell allowlist refuses it (`lean-ctx allow pip-audit` to enable).

- **v1.34.5 released** (PR #157, `b9b1234`), from a code and security review of 1.34.1–1.34.4 (security: green,
  JWT pins RS256/aud/iss and fails closed; lessons strings reach the page by textContent only).
  - The 1.34.4 chip bug was in seven more `<details>`: tickets list, Closed group, new-ticket form, sheet rows, roar
    transcript, answered footer, Snoozed. All eight now go through `keepOpen(details, key)` in `console.js`.
  - `agent.py lesson-match` split reasons on `\n` only (security LOW); it and `to_markdown()` now share
    `lessons.reason_lines()`. `lesson-match` had no test; it has one.
  - Tests: kit 392, server 334, onboard 37, vendor 11, build 15, browser 86. Badge 774.
  - Not done (LOW, reviewer): `openForms` keys are never pruned and carry no project; the "Opened by Launch Idea"
    comment above `renderTicketsFold`'s call (~`console.js:2917`) describes code that does not exist.

- **Items 4 and 6, v1.34.4 released** (PR #156, `f7f4509`). Checked in Chromium (Playwright 1.63, in `.venv`)
  against the real owner server, `ServerTests`-style setup, a JWT header and a seeded lesson:
  - Item 4: the 📎 chip shows on the right open question, with date, ruling id, "withdrawn" and the reason with
    its line break. **Bug found and fixed:** every repaint (Refresh, any live update) rebuilt the card and shut
    an opened chip. Its open state now lives in `openForms` (`'lessons-' + qid`). New browser test
    `DockTests.test_a_related_ruling_chip_opens_and_stays_open_across_a_refresh` fails on 1.34.3.
  - Item 6: no CSP violation; `data:` images load; the `/api/wait` live poll picks up a new question. An
    off-origin image and `fetch` are refused, as intended. No change.
  - Tests: kit 391, server 334, onboard 37, vendor 11, build 15, browser 85 (`OVERTURE_BROWSER=1`, 1 skip:
    LiveBoard, no `scripts/register` here).
- **The 1.34.3 review's nested-key `RecursionError` LOW does not reproduce** (100–20 000 levels, 50–900 caller
  frames): `load()` decodes at the same stack depth `record()` encodes, so a row too deep to encode is dropped
  by `load()` first. Closed, no change.
- **`flock` on `record()`: not needed.** `server.py` is the only caller and holds `Console._lock`; one server per
  STATE. Closed.

- **Tests (item 1).** On WSL Linux, Python 3.11.8: kit 386, server 334, onboard 37, vendor 11, build 15, all
  green on `release-1.34.2`. On `main` (1.34.1), `SessionNameTests` had 4 failures and 1 error when run from
  inside a Claude Code session: the inherited `CLAUDE_PROJECT_DIR` beat `run_hook`'s `setdefault`. Fixed in 1.34.2.
- **`test_build.py` (item 2).** Green on Claude CLI 2.1.296, so the manifest is fine; the 1.34.1 failures were the
  2.1.71 CLI. The Windows-side WSL may still carry 2.1.71.
- **v1.34.2 released** (PR #154, `74b59e2`): the test fix, README setup path (`plugin/kit/requirements.txt`;
  there is no root `requirements.txt`), PyJWT 2.15.1, cryptography 50.0.2.
- **v1.34.3 released** (PR #155, `bd6deb6`): every finding below is fixed, each with a test that fails on 1.34.2,
  plus a sanitizer test for the anchor cases. Tests: kit 391, server 334, onboard 37, vendor 11, build 15.
- **Review of items 3, 5 and 7.** Findings (all fixed in 1.34.3):
  - MEDIUM `lessons.py` `load()` (~l.155) catches only `JSONDecodeError`/`LessonError`. A >4300-digit integer
    raises `ValueError`, and a deeply nested line raises `RecursionError` (both reproduced). Either escapes
    `server.py`'s `(LessonError, OSError)` catch (~l.1262), so `/api/view` fails until the file is fixed. Same in
    `agent.py lessons`/`lesson-match` and `record()`. Fix: also catch `(ValueError, RecursionError)`.
  - MEDIUM `to_markdown()` (~l.328) splits the reason on `\n` only; a lone `\r` lets `## H` land at column 0 in
    the folded file (CommonMark treats CR as a line end). Fix: split on `\r\n|\r|\n`.
  - LOW `to_markdown()` trusts `row["text"]` to be one line; only `record()` collapses it. Collapse it here too.
  - LOW `record()`'s byte-cap tripwire (~l.214) cannot fire: a single oversized row would be pruned to empty and
    the file silently emptied. Unreachable today (reason capped at 20k).
  - Sanitizer (item 5): clean. Untested: nested/unclosed `<a href>`, a refused `<a>` inside an open one,
    `javascript:` href followed by `</a>`.
  - README (item 7): the Lessons section says the card shows "the ruling"; it shows date, ruling id, kind and a
    reason preview. `lesson-match` also exits 2 when the file is unreadable. Everything else checked out, CSP
    bullet included.
  All of these are reachable only through a hand-edited STATE (0600 under 0700).

## State

- `main` = v1.39.0 (PR #166), tagged and released. No open PRs. (Below: the state as handed over at v1.34.1.)
- Releases in the last session: 1.33.0 Lessons, 1.33.1 review fixes, 1.34.0 Lesson Match, 1.34.1 housekeeping.
- Tests at release (run under WSL): `test_kit.py` 386, `test_server.py` 334, `test_onboard.py` 37, `test_vendor.py` 11. All pass.
- `test_build.py`: 3 failures, believed environmental. WSL's Claude CLI is **2.1.71**, Windows has **2.1.292**; the old one rejects the manifest's `userConfig` key and `--strict`. Not yet confirmed by updating the WSL CLI.

## Please check (in this order)

1. **Tests.** On Windows, run under WSL (the server needs `fcntl`):
   ```
   wsl -e bash -c "cd '/mnt/c/Users/example/Documents/console-kit' && python3 test_kit.py"
   wsl -e bash -c "cd '/mnt/c/Users/example/Documents/console-kit' && python3 test_server.py"
   ```
   `test_server.py` takes about 9 minutes and is memory-hungry. Run it in the foreground; the harness may kill a background run under memory pressure.
2. **`test_build.py`.** Ask the owner before updating WSL's Claude CLI (`claude update` inside WSL). Then re-run. If it still fails on `userConfig`, the plugin manifest needs fixing, which would be a real install bug.
3. **Lessons code** (`plugin/kit/overture/lessons.py`, 1.33–1.34.1). The 1.33.1 fixes worth a second look:
   - `_fit()` prunes oldest rows until both caps hold (2000 rows, 2 MiB).
   - `_check()` raises only `LessonError`, so a hand-edited row cannot break `/api/view`.
   - `to_markdown()` indents the reason as a code block; the question text is collapsed to one line on record.
   - `match()`: trigram Jaccard, same item only, threshold 0.15, top 3.
   - `stamp()` + `Console._lessons_rows()` in `server.py`: the per-poll cache, keyed on (inode, size, mtime_ns).
4. **Lesson chip in the browser.** `console.js` `renderQuestion()` renders `q.related_lessons` as a 📎 `<details>` chip; CSS in `console.css` (`.ck-q-lessons*`). It was never viewed in a real browser. `test_browser.py` skips without Playwright. Worth a manual look on an open question whose item has a withdrawn ruling with similar text.
5. **Sanitizer changes** (`plugin/kit/overture/visuals.py`, 1.33.1): `<a>` without `href` is not pushed onto the tag stack; `rel` removed from the `<a>` allowlist; `handle_decl` emits a fixed `<!DOCTYPE html>`.
6. **Owner-page CSP** (`server.py`, the `/` handler): now also names `img-src 'self' data:` and `connect-src 'self'`. Check the live console still loads images and polls (no CSP errors in the browser console).
7. **README** sections added in 1.34.1: "Lessons: what you settled stays settled", the feature-map row, Trust bullets. Check they match the code.

## Open items

- **WSL Claude CLI update** on the Windows side (item 2 above). Owner's call.
- Nothing else open. (Closed 2026-10-13: items 4 and 6, the `flock`, the nested-key LOW; see the top.)

## Rules of the house

- **Never update git config.** Commit as the owner per invocation:
  `git -c user.email=<owner email> -c user.name="Michael Heid" commit ...`
- End commit messages and PR bodies with the attribution lines your harness gives you (your own session link).
- Never skip hooks; never force-push `main`.
- State writes go through `plugin/kit/overture/atfile.py` (`write_at`: O_EXCL temp, fsync, rename, O_NOFOLLOW).
- `plugin/hooks/session_start.py` imports nothing from the kit, on purpose.
- Every test names the wrong implementation it exists to catch.
- Comments say why, not what.

## Release flow (what every release followed)

```
git switch -c release-X.Y.Z
python3 release.py X.Y.Z            # bumps VERSION, plugin.json, __init__.py, marketplace.json
# edit CHANGELOG.md: new section above the latest one
# code + tests; run the suites under WSL
git -c user.email=<owner email> -c user.name="Michael Heid" commit
git push -u origin release-X.Y.Z && gh pr create ...
gh pr merge N --squash --delete-branch
git checkout main && git pull
git -c user.email=... -c user.name=... tag -a vX.Y.Z -m "vX.Y.Z — name" && git push origin vX.Y.Z
python3 build_zip.py
gh release create vX.Y.Z dist/overture-X.Y.Z.zip --title "vX.Y.Z — name" --notes "..."
```

After a release, grep the source for leftover version markers. The `sed` scrub for them left dangling punctuation once (fixed in 1.33.1).

## Map

| Path | What |
| --- | --- |
| `plugin/kit/overture/server.py` | HTTP server, routes, CSP, CSRF, `page_payload` |
| `plugin/kit/overture/view.py` | builds the owner's view from the store |
| `plugin/kit/overture/lessons.py` | lessons store + matcher |
| `plugin/kit/overture/visuals.py` | HTML sanitizer |
| `plugin/kit/overture/atfile.py` | atomic file primitives |
| `plugin/kit/overture/console.js` / `console.css` | the browser app |
| `plugin/kit/agent.py` | agent CLI (`lessons`, `lesson-match`, ...) |
| `plugin/hooks/session_start.py` | SessionStart hook |
| `CHANGELOG.md` | every release, in detail |
