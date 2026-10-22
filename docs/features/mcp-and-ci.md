# MCP and CI

[← Back to README](../../README.md)

Agents other than Claude Code ask and read through an MCP server, and a CI check blocks a merge that breaks a ruling.

## Use it from any agent (MCP, 1.35)

Agents other than Claude Code reach the console through an MCP server,
`plugin/kit/mcp_server.py`. Any client that speaks the Model Context
Protocol (Cursor, Codex, Copilot, Claude and others) launches it over
stdio. Register the project first (`agent.py register`, as for Claude
Code), then add it to the client's MCP config. The MCP server runs where
the console runs: Linux, macOS or WSL, since it reaches the console's Unix
socket. On native Windows it refuses in one line on stderr
([Windows](hosting.md#windows)).

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
| `rulings` | The rulings on files or folders before an edit, labelled `holds` or `cites` (1.52) |

The server tells the client how to use these when it connects: read
`answers` before asking, run `lesson_match` first, prefer an excerpt
for `valid_if`. Every tool runs `agent.py` underneath, so the same
checks apply: the project picks its console and token, `--as` (or
`OVERTURE_AGENT`) names its writes, and the console server validates
each one. A bad request fails alone; the server stays up. The steward's
and the owner's commands are not offered. Standard library only.

## Guardrails for Codex, Cursor and Copilot (1.56)

The MCP server lets any agent ask. The Claude plugin also says things
unasked, in its hooks: the note a session starts with, and the owner's
rulings on a file around an edit. From 1.56 Codex CLI, Cursor and Copilot
CLI get the same, through their own hooks (owner V1–V4 in
[OPEN-DECISIONS.md](../proposals/OPEN-DECISIONS.md#wave-4-adapters-for-other-agent-vendors-decided-2026-10-21)).

    python3 <kit>/agent.py adapter install --vendor codex     # or cursor, copilot
    python3 <kit>/agent.py adapter agents-md                  # in a registered checkout: its AGENTS.md block

**What it installs.** `install` writes the vendor's own user config, never
the repository's, and leaves everyone else's entries alone:

| Vendor | Hooks | MCP server |
|---|---|---|
| Codex CLI | `~/.codex/hooks.json` | `~/.codex/config.toml` |
| Cursor | `~/.cursor/hooks.json` | `~/.cursor/mcp.json` |
| Copilot CLI | `~/.copilot/hooks/overture.json` | `~/.copilot/mcp-config.json` |

`uninstall --vendor V` takes out only what `install` put in. Codex runs new
hooks once you trust them: type `/hooks` in Codex and approve the two. You
run these commands, never a session.

**When it speaks.** Each vendor's hooks decide it:

- **Codex** before an edit, as Claude Code does: the rulings on each file a
  patch touches, once per session, and a warning every time the patch would
  break one. A rename of a definition a ruling rests on is followed, with
  the `propose-anchor` command.
- **Cursor and Copilot** after an edit, because before a tool they can only
  allow or deny it. The warning says the edit broke the ruling. Where the
  tool's input shows the old and new text, the edit is undone in memory to
  tell a ruling this edit broke from one that was already stale. Where it
  does not, a stale ruling is named without blaming the edit.

It never allows or denies anything, and it fails open: any error is
"nothing to add", exit 0.

**Which projects.** Only those registered on this machine (`agent.py
register`), as for the Claude plugin. The MCP server it installs has no
`--state`: it takes the console your registry names for the project it runs
in, and refuses anywhere else.

**Known limits.** The vendors' hook inputs were built from their docs
(2026-10-21), not yet from a captured run. Copilot does not document its
edit tools' arguments and Cursor names few of its tools, so the file and
text are looked for under the keys they are known to use; a shape not
recognised says nothing. Cloud agents (Copilot's coding agent, Cursor's
background agents) cannot reach the console's socket; the CI check below
covers them. Antigravity CLI, which replaced Gemini CLI, waits until its
hooks are documented (V1).

## The protocol, published (1.55)

The format underneath both is a published spec: [docs/spec/PROTOCOL.md](../spec/PROTOCOL.md),
version 1.0. It covers the four decision records (question, answer, lock,
anchor), the `valid_if` conditions and what makes a ruling stale, and the
ruling files this check reads. A JSON Schema and conformance vectors sit
beside it, and `test_spec.py` holds Overture to all three. A tool that writes
rulings, or checks them in its own CI, can follow the spec without running
Overture. The spec has its own version, separate from Overture's: a minor
version adds only optional things, so a valid record never changes meaning.
It ships in each release zip (`overture/spec/`), so the release's attestation
covers it. The owner's choices are P1–P5 in
[OPEN-DECISIONS.md](../proposals/OPEN-DECISIONS.md#wave-4-the-protocol-decided-2026-10-21).

## Block a merge that breaks a ruling (CI, 1.36)

`plugin/kit/rulecheck.py` checks the rulings your project has
committed (the files `fold.py export` writes, `.overture/locked` by
default) against the checkout, with no console server. A ruling whose
cited text a change edits or deletes fails the check, with the same
reason and diff **What changed?** shows. A ruling on a definition (1.54)
fails when its body changes. When the change only renames or moves the
definition, the ruling passes and is listed as **moved**, with the new place
and the `propose-anchor` command that records it ([Rulings on a
definition](inbox-and-rulings.md#rulings-on-a-definition-154)).

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
