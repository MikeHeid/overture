# Overture: handoff, 2026-10-13

For the next session. This branch (`handoff/2026-10-13`) is `main` at **v1.34.1** plus this file only.
The previous session's job ended with 1.34.1 shipped; your first job is to **check its work**.

## State

- `main` = v1.34.1, tagged and released. No open PRs.
- Releases in the last session: 1.33.0 Lessons, 1.33.1 review fixes, 1.34.0 Lesson Match, 1.34.1 housekeeping.
- Tests at release (run under WSL): `test_kit.py` 386, `test_server.py` 334, `test_onboard.py` 37, `test_vendor.py` 11. All pass.
- `test_build.py`: 3 failures, believed environmental. WSL's Claude CLI is **2.1.71**, Windows has **2.1.292**; the old one rejects the manifest's `userConfig` key and `--strict`. Not yet confirmed by updating the WSL CLI.

## Please check (in this order)

1. **Tests.** On Windows, run under WSL (the server needs `fcntl`):
   ```
   wsl -e bash -c "cd '/mnt/c/Users/Sigma-1/Documents/console-kit' && python3 test_kit.py"
   wsl -e bash -c "cd '/mnt/c/Users/Sigma-1/Documents/console-kit' && python3 test_server.py"
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

- **`flock` on `lessons.record()`.** No live race with one server per STATE; defense-in-depth for a future feature release.
- **WSL Claude CLI update** (item 2 above).

## Rules of the house

- **Never update git config.** Commit as the owner per invocation:
  `git -c user.email=michael@sigma-1.com -c user.name="Michael Heid" commit ...`
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
git -c user.email=michael@sigma-1.com -c user.name="Michael Heid" commit
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
