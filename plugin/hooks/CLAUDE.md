<!-- area: plugin/hooks · checked: c238ebf -->
- Claude Code runs these hooks in every session of the user's (hooks.json), so all but install_notice.py (a banner once per version) act only in a project the user registered with `agent.py register`: trust comes from the user's registry, never the repository (session_start.py, §7.7).
- They fail open: an error of any kind prints nothing and exits 0, so a guardrail never costs the owner a session, a prompt or an edit.
- Only ask_guard.py makes a permission decision: it denies AskUserQuestion to a session that is not the steward (0.8.3). ruling_lookup.py prints `additionalContext` only, because "allow" would skip the owner's own prompt (1.52 R2).
- They load on native Windows Python, which lacks fcntl and O_NONBLOCK/O_NOFOLLOW/O_CLOEXEC: session_start.py takes each as optional and refuses a symlink by lstat, naming a session there is refused by name, and ruling_lookup.py stands down when the kit will not import there (on POSIX that still raises). POSIX flags are unchanged (1.53.1, test_kit WindowsHookTests).
- Standard library only. ask_guard.py and name_session.py import only session_start.py beside them; ruling_lookup.py imports `overture.lookup` and install_notice.py `overture.prereqs` from this plugin's own `../kit`, never the registry's kit or the project's.
- session_start.py re-implements the registry and doorbell reads from the kit; test_kit holds both copies to one fixture.
- What a hook prints enters the session's context, so every field shown is held to a shape (a seq an int, a path plain characters), else `?`.
- Each hook has a short timeout in hooks.json (5 to 10 s); the ruling lookup keeps its own 1.5 s deadline for the server.
- The PreToolUse hooks carry `"onFailure": "continue"`, so a hook that cannot run (no `python3`) never blocks a tool (1.53.2).
