"""The artifacts of a Claude Design project, as an agent lists them, for the UX View picker (1.33).

The server never reads a Claude Design project and never fetches its link. An agent that can open the design
(with the owner's own login) posts what is in it: `agent.py design-inventory --url LINK --file LIST`. The server
checks the list against the closed shape below, keeps the last list per design link in STATE/designs.json, and
shows it to the owner so they can pick artifacts to reference ("inspire" or "swap") when asking for a component.

A list is untrusted text from an agent: paths are plain relative paths, titles one short line, every count capped,
and the console draws them as text.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from . import atfile as AF
from . import schema as S

FILE = "designs.json"
MAX_FILE = 512 * 1024
MAX_DESIGNS = 20              # links with a kept list; the least recently pushed is dropped past this
MAX_ARTIFACTS = 300           # per list
MAX_PATH = 200
MAX_TITLE = 120
from .schema import MAX_REFS, REF_MODES, PATH, path_problem, refs_problem  # noqa: E402,F401  (the request side lives in schema)
STATE_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class DesignError(ValueError):
    """A list that cannot be kept, named; nothing was written."""


def artifacts_problem(artifacts: object) -> str | None:
    if not isinstance(artifacts, list) or not artifacts:
        return "artifacts is a non-empty list of {path, title?}"
    if len(artifacts) > MAX_ARTIFACTS:
        return f"artifacts has {len(artifacts)} entries; the limit is {MAX_ARTIFACTS}"
    seen: set[str] = set()
    for i, a in enumerate(artifacts):
        if not isinstance(a, dict) or not {"path"} <= set(a) <= {"path", "title"}:
            return f"artifacts[{i}] is {{path, title?}}"
        why = path_problem(a["path"], f"artifacts[{i}].path")
        if why:
            return why
        if a["path"] in seen:
            return f"artifacts[{i}].path {a['path']!r} is listed twice"
        seen.add(a["path"])
        t = a.get("title")
        if t is not None and (not isinstance(t, str) or len(t) > MAX_TITLE or CONTROL.search(t)):
            return f"artifacts[{i}].title is one line of at most {MAX_TITLE} characters"
    return None


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(state: Path) -> dict:
    """{url: {artifacts, pushed_at, by}}; an absent or unreadable file is empty (logged), never an error."""
    sfd = os.open(state, STATE_FLAGS)
    try:
        raw = AF.read_at(sfd, FILE, MAX_FILE)
    except OSError as e:
        sys.stderr.write(f"console designs: {FILE} not readable: {type(e).__name__}\n")
        return {}
    finally:
        os.close(sfd)
    if not raw:
        return {}
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        sys.stderr.write(f"console designs: {FILE} is not JSON; ignored\n")
        return {}
    designs = doc.get("designs") if isinstance(doc, dict) else None
    if not isinstance(designs, dict):
        return {}
    return {u: d for u, d in designs.items()
            if S.design_url_problem(u) is None and u != "" and isinstance(d, dict)
            and artifacts_problem(d.get("artifacts")) is None}


def store(state: Path, url: object, artifacts: object, by: str | None, at: str | None = None) -> dict:
    """Keep `artifacts` as the list for design link `url` (replacing its last one). Raises DesignError, naming why."""
    why = S.design_url_problem(url) if isinstance(url, str) and url else "url must be a Claude Design link"
    if why:
        raise DesignError(why)
    why = artifacts_problem(artifacts)
    if why:
        raise DesignError(why)
    designs = load(state)
    designs[url] = {"artifacts": artifacts, "pushed_at": at or now(), "by": by}
    if len(designs) > MAX_DESIGNS:
        oldest = min(designs, key=lambda u: designs[u]["pushed_at"] if u != url else "9999")
        del designs[oldest]
    data = json.dumps({"designs": designs}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_FILE:
        raise DesignError(f"the kept lists would be {len(data)} bytes; the limit is {MAX_FILE}")
    sfd = os.open(state, STATE_FLAGS)
    try:
        AF.write_at(sfd, FILE, data)
    finally:
        os.close(sfd)
    return designs[url]
