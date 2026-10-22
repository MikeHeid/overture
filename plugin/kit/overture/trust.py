"""Whose backlinks are trusted (1.58, OPEN-DECISIONS T1 and T2): GitHub's author association.

Anyone with a GitHub account can open a PR or an issue that names a ruling's
qid, and the ruling card would show it as "Shipped:" or "Mentioned in:" (risk 5
in STRATEGY.md). `gh pr list` and `gh issue list` cannot return
`authorAssociation`, so `agent.py prs-push` and `issues-push` ask GitHub for it
in one GraphQL call, in the steward's own process, and send it with each PR or
issue as `association`. The server never talks to GitHub.

OWNER, MEMBER and COLLABORATOR are trusted. Any other value, or none (a push
from an older agent.py, or a lookup that failed), is an outside author: the
console dims that backlink for the owner, and nothing that reaches an agent
carries it.
"""

from __future__ import annotations

FIELD = "association"
# GitHub's CommentAuthorAssociation values; anything else is refused by the snapshot checks.
ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER",
                "MANNEQUIN", "NONE")
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")   # a tuple: `in` never raises on an unhashable value
KINDS = {"pr": "pullRequest", "issue": "issue"}


def problem(v: object, where: str) -> str | None:
    """Why `association` cannot be kept, naming it; None when it can (null, or one of ASSOCIATIONS)."""
    if v is None or v in ASSOCIATIONS:
        return None
    return f"{where}.{FIELD} is null or one of {', '.join(ASSOCIATIONS)}"


def trusted(row: dict) -> bool:
    return row.get(FIELD) in TRUSTED


def gh_query(repo: str, kind: str, numbers: list[int]) -> list[str]:
    """The `gh api graphql` command line (without the leading `gh`) asking for each number's author association.

    agent.py checks the snapshot first, so each number is a whole number; the repository travels as variables.
    """
    owner, name = repo.split("/")
    parts = " ".join(f"n{int(n)}: {KINDS[kind]}(number: {int(n)}) {{ authorAssociation }}" for n in numbers)
    query = f"query($owner: String!, $name: String!) {{ repository(owner: $owner, name: $name) {{ {parts} }} }}"
    return ["api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}"]


def from_gh(doc: object, numbers: list[int]) -> dict[int, str]:
    """number -> association from gh's GraphQL reply. A number GitHub gave no known value for is left out."""
    data = doc.get("data") if isinstance(doc, dict) else None
    repo = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(repo, dict):
        return {}
    out = {}
    for n in numbers:
        node = repo.get(f"n{n}")
        a = node.get("authorAssociation") if isinstance(node, dict) else None
        if a in ASSOCIATIONS:
            out[n] = a
    return out


def with_associations(body: dict, key: str, found: dict[int, str]) -> dict:
    """A copy of the push `body` with each row of `body[key]` carrying its association, or null."""
    return {**body, key: [{**r, FIELD: found.get(r["number"])} for r in body[key]]}
