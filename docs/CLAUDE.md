<!-- area: docs · checked: 3504eab -->
- These pages are for the owner and the people who run a console: plain, short sentences, bold lead-ins, no hype.
- Feature pages title each section with the releases that built it (`## Agent worktrees (1.50)`) and link the owner's decisions in proposals/OPEN-DECISIONS.md by id (W1, R2, M1).
- OPEN-DECISIONS.md is where decisions live: other pages and notes cite a row by id and never copy it, so it stays the one place that changes.
- The repository is public, so examples use example.com and /home/example; a real hostname, address, home path or team domain in a page is published with it. build_zip.py `--deny-file` guards the release zip only, not these pages.
- No tracked file names the project the kit was first built for (owner, 0.8.2 "Scrub"; test_build `NeutralTests`).
- CHANGELOG.md holds each release's notes as written when it shipped; the README describes the kit as it is today.
