<!-- area: plugin/kit · checked: f87aaaa -->
- agent.py is the agent's side, run in the agent's own session; its git and gh calls go through overture/gitseam.py, open here and closed in the server (CONSOLE-kit/Q23).
- A command that reaches a console reaches one: the one the working directory's registered project names (K4, `resolve_door`). The user's own commands (`USER_COMMANDS`), `worktree list`/`prune` and `notes` need none.
- watch, synced and the fold belong to the console's steward (`steward_refusal`, 0.8.3). The watch's side work (prune, notes check) runs after its first heartbeat, throttled by a time kept in STATE (1.50 review C2).
- Each entry script calls `overture/posix.require` before any import native Windows lacks, and refuses there in one line, exit 2 (1.53.2). posix.py and prereqs.py import on Windows.
- A project's adapter runs in the steward's process and reaches a server only as data (`items-push`, Q24).
- The tests live at the repository root (test_kit, test_server, test_browser with OVERTURE_BROWSER=1, ...). Each test's comment starts "Catches:" with the wrong implementation it exists to catch.
- Test processes get a throwaway config home (OVERTURE_TEST_CONFIG), so none reads or writes the user's real registry (0.8.3).
- A new test is shown red by reverting the fix it guards, then green; one that passes both ways guards nothing. No test reads this repository's own notes; release.py's `notes_gate` does (1.53 review C1). Its in-area version-bump files are in `.overture.json` "notes_ignore", so a release stales no note (test_build asserts it).
- A "mutant killed" claim holds once someone other than its author re-applies the mutant: at 1.50 a writer's claims fell short on re-run (the clearing round), and 1.52 added tests for the survivors (f2abddc).
