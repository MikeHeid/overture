# Waypoints

One entry for each waypoint: the course check run before a new lane, phase or
wave starts (STRATEGY.md, "How each lane starts"; OPEN-DECISIONS.md WP1–WP3).
The newest entry comes first. The next waypoint's roll-up starts from it.

| Date | Lane | Question | Owner's answer | Roll-up in one line |
|---|---|---|---|---|
| 2026-10-22 | Wave 5, Trust step 1: collaborator-only backlinks (1.58), given in the conversation | On course? Start backlinks now, and how is it run for real? | **a, proceed after #191 merges.** The real run uses a second, throwaway GitHub account that opens a PR citing a qid on a scratch repo. The design round then chose T1 (GitHub association) and T2 (dimmed for the owner, dropped for agents) | 1.57 shipped (#191). Backlinks come from `agent.py prs-push` and carry `author` but no trust signal, and the server attaches them unfiltered (risk 5) |
| 2026-10-22 | After 1.57: the next wave (the first waypoint, given in the conversation because overture has no console on this machine) | On course? The plan names no lane after Wave 4 | **c, re-plan first**, with Trust leading. The deliberation round decided W5-1 to W5-3: Wave 5 is Trust at team scale, and backlinks go first | 1.55 spec, 1.56 adapters and 1.57 waypoints shipped. Waves 1–4 are built, and the board's three limits are answered. Open: the Cursor real run, Antigravity, risk 5 |
