<!-- area: plugin/kit/overture · checked: ae27737 -->
- server.py is one process and the store's only writer (store.py: one writer per file); agents write through its socket, never a second Store.
- Two doors: the owner's (HTTP on 127.0.0.1, an Access token or a 1.46 device cookie, D5 even on loopback) stamps `by: owner`; the agent's (a 0600 Unix socket) stamps `by: agent`. The page never picks its author.
- `serve` calls `gitseam.close()` first: the server starts no git (CONSOLE-kit/Q23); git facts arrive pushed by the steward (stewardgit.py). It never imports or runs a project's adapter (Q24, items.py).
- Refusals carry their reason (`RequestError` with the rule's own words), so the agent or owner can act on them; a bad `.overture.json` key stops the start, named (projectcfg.py).
- The view is computed per request and never stored (R5). Owner-only fields such as `stale_worktrees` are dropped per login in `cursor_for` (W3).
- console.js is plain ES2020 in one IIFE: no framework, no external request. Text from GitHub, agents or the store goes in as text nodes through `el()`; innerHTML only empties a box.
- A poll redraw replaces the panel's nodes, so an async fill looks up the box on screen when it lands, not the one it captured (1.52, `loadPRs`); a same-view redraw carries a playing fade on (`playingEnter`, 1.52).
