# MCP and CI

[← Back to README](../../README.md)

Agents other than Claude Code ask and read through an MCP server, and a CI check blocks a merge that breaks a ruling.

## Use it from any agent (MCP, 1.35)

Agents other than Claude Code reach the console through an MCP server,
`plugin/kit/mcp_server.py`. Any client that speaks the Model Context
Protocol (Cursor, Codex, Copilot, Claude and others) launches it over
stdio. Register the project first (`agent.py register`, as for Claude
Code), then add it to the client's MCP config:

```json
{
  "mcpServers": {
    "overture": {
      "command": "python3",
      "args": ["<kit>/mcp_server.py", "--state", "<STATE>",
               "--project", "<your checkout>", "--as", "cursor-1"]
    }
  }
}
```

For Codex, the same in `~/.codex/config.toml`:

```toml
[mcp_servers.overture]
command = "python3"
args = ["<kit>/mcp_server.py", "--state", "<STATE>", "--project", "<your checkout>", "--as", "codex-1"]
```

| Tool | What it does |
|---|---|
| `todo` | What is waiting on this agent |
| `view` | The console's view, narrowed by `item` and `since` |
| `answers` | Every question in a scope and the answer it got |
| `check` | Why each stale ruling is stale |
| `lesson_match` | Past withdrawn rulings that look like a draft question |
| `health` | Whether the console server is up, and its version |
| `ask` | Post a question for the owner |
| `reply` | Post a message on an item's thread |
| `working` | Show the owner "agent active" on items |

The server tells the client how to use these when it connects: read
`answers` before asking, run `lesson_match` first, prefer an excerpt
for `valid_if`. Every tool runs `agent.py` underneath, so the same
checks apply: the project picks its console and token, `--as` (or
`OVERTURE_AGENT`) names its writes, and the console server validates
each one. A bad request fails alone; the server stays up. The steward's
and the owner's commands are not offered. Standard library only.

## Block a merge that breaks a ruling (CI, 1.36)

`plugin/kit/rulecheck.py` checks the rulings your project has
committed (the files `fold.py export` writes, `.overture/locked` by
default) against the checkout, with no console server. A ruling whose
cited text a change edits or deletes fails the check, with the same
reason and diff **What changed?** shows.

In GitHub Actions:

```yaml
on: pull_request
permissions: {contents: read, pull-requests: write}
jobs:
  rulings:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - uses: MikeHeid/overture@v1.47.0
```

The rulings checked, and the `.overture.json` that says where they live,
are the ones committed at the pull request's base, so a pull request
cannot pass by editing or deleting a ruling file. If you re-lock or
settle a ruling and its export lands in the same pull request, it passes
and is listed as re-ruled. The Action posts one comment on the pull
request, and keeps it updated, when a ruling breaks or a reviewer must
look: a re-ruling, an edited ruling file, or a ruling it could not
check. If it finds no ruling files at all, the job summary says so.

What it trusts: ruling files arrive by pull request, as they always
have, so a re-ruling in the comment is a claim for the reviewer to
confirm, not proof that you made it. Make the check a required status
in branch protection, or a pull request can also edit the workflow.

An `item_status` condition is checked only with the `adapter` input.
Without it, such a ruling is listed as unchecked and passes; set
`strict: true` to fail it instead, and to fail a run that found no
ruling files (1.37). A re-ruling never fails strict: it is yours to
make, and the comment shows it to the reviewer.

Your adapter is code from the pull request's checkout, so it is opt-in
and kept apart (1.37). The token is not handed to the step that runs
it, no comment is posted after it (the job summary has the report), and
the check refuses to run when `actions/checkout` left its token header
in `.git/config` (use `persist-credentials: false`). **Give the adapter
run a job of its own with no secrets**, and treat every later step in
that job as untrusted: the adapter runs as the runner's user, which on
GitHub's runners can use sudo and can read other processes'
environments. (The check also starts with a clean environment, so the
job's secrets are not handed to the adapter; that is hygiene, not
isolation.)

Anywhere else, run it yourself: `python3 <kit>/rulecheck.py --base
origin/main` (add `--format markdown` or `--format json`, and
`--strict`). It exits 0 when every ruling holds, 1 when one is broken
(or, with `--strict`, could not be checked), and 2 when it could not
run.
