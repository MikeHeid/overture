"""Linear, outbound only (1.64.0, OPEN-DECISIONS L1-L3): a comment on an item's Linear issue when a ruling on it
is locked or withdrawn, or kept but no longer checked.

- **L1, what Linear gets:** the question, what the owner ruled, who locked it by the owner-set short name (never
  an email), when, and a link to the ruling file in the repository. Every word from the store passes the PR
  comment's `_md` (no markup, no mention, no bare link). It is the first outbound post that carries a question's
  text; the Slack digest (notify.py) never does, and that stays so.
- **L2, which issue:** an item's `linear` field, the issue identifier (`ENG-123`), set by the owner where items
  are set (the project's adapter, pushed with `items-push`). Nothing is guessed: an item with none posts nothing.
- **L3, who posts and where the key lives:** like `notify-url`. `agent.py linear-key` writes STATE/linear.json
  (0600); it is the owner's alone and refused inside a session. The server posts, once a minute, from an outbox
  (STATE/linear-state.json), so a slow or failing Linear never holds up a lock. The console shows only that a
  key is set, and how the last post went.

    STATE/linear.json         {"key": "lin_api_...", "teams": ["ENG"], "repo": "owner/name" | null}

**What only the owner decides (1.64 security review).** Items arrive by `items-push`, from the project's adapter,
which an agent can edit; so an item's `linear` alone never chooses where the owner's words go. The owner names,
with the key, the Linear teams the console may post to (`--teams`), and the repository the ruling link points
at (`--repo`; none, no link). An issue outside those teams is never queued.
    STATE/linear-state.json   {"pending": [{"id", "issue", "body"}], "done": [id...], "last_ok", "last_error"}

An event is queued only while a key is set, so setting a key never posts a backlog. A post Linear refuses for
good (no such issue, a key that cannot see it) is dropped and named in `last_error`; one that fails for a reason
that may pass (the network, a 5xx, a rate limit) stays queued and is tried again next minute.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import nullcontext
from pathlib import Path

from . import roles as RO

KEY_FILE = "linear.json"
STATE_FILE = "linear-state.json"
API = "https://api.linear.app/graphql"
KEY = re.compile(r"^lin_api_[A-Za-z0-9]{16,128}\Z")     # a Linear personal API key
TEAM = re.compile(r"^[A-Z][A-Z0-9]{0,9}\Z")              # a team key, the part of ENG-123 before the dash
REPO = re.compile(r"^(?!\.\.?/)[A-Za-z0-9._\-]{1,100}/(?!\.\.?\Z)[A-Za-z0-9._\-]{1,100}\Z")   # rulecheck's REPO
MAX_TEAMS = 20
ISSUE = re.compile(r"^[A-Z][A-Z0-9]{0,9}-[0-9]{1,9}\Z")   # an issue identifier: ENG-123
TIMEOUT = 10.0
TOTAL = 30.0
MAX_REPLY = 64 * 1024
MAX_PENDING = 200        # queued posts kept; the oldest are dropped, named, past this
MAX_DONE = 5000
PER_TICK = 5             # posts tried in one look
LOOK = 60.0              # seconds one look may spend posting, so the Slack digest beside it is never held long
MAX_TRIES = 1440         # a post that keeps failing in a way that may pass is dropped, named, after a day of tries
# Linear's error codes that pass with time or with the owner's fix (a new key): the post stays queued for those.
PASSING = ("RATELIMITED", "AUTHENTICATION_ERROR", "FORBIDDEN", "INTERNAL_SERVER_ERROR")
RULED_CHARS = 1000       # the owner's words, as in the PR comment (1.61)


class LinearError(Exception):
    """A key or state file the kit refuses, or a post that failed. `lasting` says retrying will not help."""

    def __init__(self, msg: str, lasting: bool = False) -> None:
        super().__init__(msg)
        self.lasting = lasting


def key_problem(key: object) -> str | None:
    if not isinstance(key, str) or not KEY.match(key):
        return "a Linear personal API key starts lin_api_ (Linear: Settings, Security & access, Personal API keys)"
    return None


def issue_problem(issue: object) -> str | None:
    if not isinstance(issue, str) or not ISSUE.match(issue):
        return "a Linear issue identifier is a team key and a number, e.g. ENG-123"
    return None


def config_problem(key: object, teams: object, repo: object) -> str | None:
    if key_problem(key):
        return key_problem(key)
    if (not isinstance(teams, list) or not 1 <= len(teams) <= MAX_TEAMS
            or not all(isinstance(t, str) and TEAM.match(t) for t in teams)):
        return f"name the Linear teams the console may post to: 1-{MAX_TEAMS} team keys, e.g. --teams ENG OPS"
    if repo is not None and (not isinstance(repo, str) or not REPO.match(repo)):
        return "--repo is the GitHub repository as owner/name"
    return None


def load_config(state: Path) -> dict | None:
    """{"key", "teams", "repo"} as the owner set them, or None when no key is set. A file the kit refuses raises."""
    p = Path(state) / KEY_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as e:
        raise LinearError(f"{p}: not readable ({type(e).__name__})") from None
    if (not isinstance(doc, dict) or set(doc) != {"key", "teams", "repo"}
            or config_problem(doc["key"], doc["teams"], doc["repo"])):
        raise LinearError(f'{p}: not the file linear-key writes; set it again with agent.py linear-key --set')
    return doc


def load_key(state: Path) -> str | None:
    cfg = load_config(state)
    return cfg["key"] if cfg else None


def team_allowed(state: Path, issue: str) -> bool:
    """Whether the owner named this issue's team when setting the key (the security review's confused deputy)."""
    try:
        cfg = load_config(state)
    except LinearError:
        return False          # a refused key file posts nowhere; status() names the problem in Settings
    return bool(cfg) and issue_problem(issue) is None and issue.split("-", 1)[0] in cfg["teams"]


def set_key(state: Path, key: str | None, teams: list[str] | None = None, repo: str | None = None) -> None:
    """Set (None: remove) the key with its teams and repository, logged in the role log as set or removed only."""
    if key is not None:
        why = config_problem(key, teams, repo)
        if why:
            raise LinearError(why)
    p = Path(state) / KEY_FILE
    doc = {"key": key, "teams": sorted(set(teams or [])), "repo": repo} if key else None

    def plan():
        try:
            before = load_config(state)
        except LinearError:
            before = None
        if before == doc and p.exists() == (doc is not None):
            return None
        return ({"setting": {"key": "linear_key", "from": "set" if before else None, "to": "set" if doc else None}},
                lambda: _write(p, doc))
    RO.logged_change(state, None, plan)


def fresh() -> dict:
    return {"pending": [], "done": [], "last_ok": None, "last_error": None}


def load_state(state: Path) -> dict:
    p = Path(state) / STATE_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fresh()
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as e:
        raise LinearError(f"{p}: not readable ({type(e).__name__})") from None
    ok = (isinstance(doc, dict) and set(doc) == set(fresh()) and isinstance(doc["pending"], list)
          and all(isinstance(e, dict) and set(e) - {"tries"} == {"id", "issue", "body"}
                  and all(isinstance(e[k], str) for k in ("id", "issue", "body"))
                  and (type(e.get("tries", 0)) is int and 0 <= e.get("tries", 0) <= MAX_TRIES)
                  for e in doc["pending"])
          and isinstance(doc["done"], list) and all(isinstance(i, str) for i in doc["done"])
          and all(doc[k] is None or isinstance(doc[k], str) for k in ("last_ok", "last_error")))
    if not ok:
        raise LinearError(f"{p}: not the Linear state the kit writes")
    return doc


def save_state(state: Path, doc: dict) -> None:
    _write(Path(state) / STATE_FILE, {**doc, "done": doc["done"][-MAX_DONE:]})


def enqueue(state: Path, event_id: str, issue: str, body: str, lock=None) -> bool:
    """Queue one post; False when no key is set, the issue's team is not one the owner named, the event was queued
    or posted before, or the issue is malformed."""
    if issue_problem(issue) or not team_allowed(state, issue):
        return False
    with lock or nullcontext():
        return _enqueue(state, event_id, issue, body)


def _enqueue(state: Path, event_id: str, issue: str, body: str) -> bool:
    try:
        doc = load_state(state)
    except LinearError:
        doc = {**fresh(), "last_error": _set_aside(state)}   # a damaged file starts over, named, kept beside it
    if event_id in doc["done"] or any(e["id"] == event_id for e in doc["pending"]):
        return False
    pending = doc["pending"] + [{"id": event_id, "issue": issue, "body": body}]
    dropped = len(pending) - MAX_PENDING
    if dropped > 0:
        doc = {**doc, "last_error": f"{dropped} queued post(s) dropped: more than {MAX_PENDING} waited"}
    save_state(state, {**doc, "pending": pending[-MAX_PENDING:]})
    return True


def _set_aside(state: Path) -> str:
    """Move a damaged state file aside (kept for the owner) and say so; the posts queued in it are not made."""
    p = Path(state) / STATE_FILE
    aside = p.with_name(f"{STATE_FILE}.bad-{time.strftime('%Y%m%dT%H%M%S')}")
    try:
        os.replace(p, aside)
        where = f"kept as {aside.name}"
    except OSError as e:
        where = f"not moved ({type(e).__name__})"
    return f"the Linear queue file was damaged and started over ({where}); the posts queued in it were not made"


# -- what a post says -------------------------------------------------------------------------------------------

def _md(s: str) -> str:
    from .rulecheck import _md as md   # the PR comment's escaping (1.61): no markup, no mention, no bare link
    return md(s)


def ruled_words(question: dict, answer: dict) -> str:
    labels = {o["id"]: o["label"] for o in question.get("options") or []}
    words = [labels.get(p, p) for p in answer.get("picks") or []]
    if answer.get("own_text"):
        words.append(answer["own_text"])
    text = "; ".join(words) or "(no words)"
    return text if len(text) <= RULED_CHARS else text[:RULED_CHARS - 1] + "…"


LOCKED_SEG = re.compile(r"^(?!\.\.?\Z)[A-Za-z0-9._\-]{1,100}\Z")


def file_link(repo: str | None, locked: str, qid: str) -> str | None:
    """The ruling file on the default branch (`blob/HEAD`): the steward commits it after the lock (`fold.py export`),
    so the link works from that commit on. None without the repository the OWNER set with the key, and None for a
    ruling folder that is not plain relative segments (no `.`, no `..`): an agent can edit `.overture.json`."""
    from urllib.parse import quote
    from . import fold as F
    if not repo or not REPO.match(repo) or not all(LOCKED_SEG.match(s) for s in locked.split("/")):
        return None
    return f"https://github.com/{repo}/blob/HEAD/{quote(locked, '/')}/{quote(F.locked_filename(qid), '')}"


def body_locked(project: str, question: dict, answer: dict, lock: dict, who: str | None, link: str | None) -> str:
    lines = [f"**Overture ruling locked** · {_md(project)} · {_md(question['qid'])}", "",
             f"**Question:** {_md(question['text'])}",
             f"**The owner ruled:** {_md(ruled_words(question, answer))}",
             f"Locked by {_md(who) if who else 'the owner'} on {lock['ts'][:10]}."]
    if link:
        lines.append(f"[The ruling file]({link})")
    return "\n".join(lines)


def body_settled(project: str, question: dict, rec: dict) -> str:
    what = {"withdraw": "withdrawn", "untrack": "kept, but no longer checked"}[rec["type"]]
    lines = [f"**Overture ruling {what}** · {_md(project)} · {_md(question['qid'])}", "",
             f"**Question:** {_md(question['text'])}"]
    if rec.get("reason"):
        lines.append(f"**Why:** {_md(rec['reason'])}")
    lines.append(f"By the owner on {rec['ts'][:10]}.")
    return "\n".join(lines)


# -- posting ---------------------------------------------------------------------------------------------------

def _graphql(key: str, query: str, variables: dict) -> dict:
    import http.client
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)

    req = urllib.request.Request(API, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 method="POST", headers={"Content-Type": "application/json", "Authorization": key,
                                                         "User-Agent": "overture-linear"})
    deadline, raw = time.monotonic() + TOTAL, b""
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=TIMEOUT) as r:
            while len(raw) <= MAX_REPLY:
                if time.monotonic() > deadline:
                    raise LinearError(f"Linear took more than {TOTAL:.0f}s to answer")
                chunk = r.read1(4096)
                if not chunk:
                    break
                raw += chunk
    except urllib.error.HTTPError as e:
        try:
            said = e.read(MAX_REPLY)
        except OSError:
            said = b""
        e.close()
        # Linear answers most errors 400 with a code in the body. Only a request it refuses for good is lasting:
        # a rate limit, a bad key (the owner sets a new one) or its own outage keeps the post queued.
        passing = e.code >= 500 or e.code in (401, 403, 429) or any(c.encode() in said for c in PASSING)
        raise LinearError(f"Linear answered HTTP {e.code}" + (f" ({_code(said)})" if _code(said) else ""),
                          lasting=not passing) from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        raise LinearError(f"Linear could not be reached ({type(getattr(e, 'reason', e)).__name__})") from None
    try:
        doc = json.loads(raw) if len(raw) <= MAX_REPLY else None
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        raise LinearError("Linear's answer was not JSON")
    if doc.get("errors"):
        first = doc["errors"][0] if isinstance(doc["errors"], list) and doc["errors"] \
            and isinstance(doc["errors"][0], dict) else {}
        code = _code(json.dumps(first).encode())
        msg = str(first.get("message") or "an error")[:160]
        raise LinearError(f"Linear refused it: {msg}" + (f" ({code})" if code else ""), lasting=code not in PASSING)
    return doc.get("data") or {}


def _code(raw: bytes) -> str | None:
    """The first of Linear's error codes named in `raw` (its errors carry extensions.code), or None."""
    m = re.search(rb'"code"\s*:\s*"([A-Z_]{3,40})"', raw)
    return m.group(1).decode() if m else None


def post(key: str, issue: str, body: str) -> None:
    """Comment `body` on `issue`. The identifier is resolved first, which also proves the key can see it."""
    found = _graphql(key, "query($id: String!) { issue(id: $id) { id team { key } } }", {"id": issue})
    uid = (found.get("issue") or {}).get("id")
    if not isinstance(uid, str):
        raise LinearError(f"Linear has no issue {issue} this key can see", lasting=True)
    now_in = ((found.get("issue") or {}).get("team") or {}).get("key")
    if now_in != issue.split("-", 1)[0]:
        # Linear still answers an old identifier after the issue moves team: the owner named the team, not the issue
        raise LinearError(f"{issue} is now in another team ({_md(str(now_in))[:20]})", lasting=True)
    made = _graphql(key, "mutation($input: CommentCreateInput!) { commentCreate(input: $input) { success } }",
                    {"input": {"issueId": uid, "body": body}})
    if (made.get("commentCreate") or {}).get("success") is not True:
        raise LinearError(f"Linear did not create the comment on {issue}")


def tick(state: Path, now_iso: str, send=post, lock=None) -> str | None:
    """One look: post what is queued, up to PER_TICK. "sent", "failed", or None (no key, nothing queued).

    `lock` (the server's) is held only to read and to write the state, never across a post, so a lock that
    queues an event waits for a file write, not for Linear. The results are applied to the state as it is
    then, so an event queued meanwhile is kept.
    """
    lock = lock or nullcontext()
    cfg = load_config(state)
    if cfg is None:
        return None
    key = cfg["key"]
    with lock:
        try:
            batch = list(load_state(state)["pending"][:PER_TICK])
        except LinearError:
            save_state(state, {**fresh(), "last_error": _set_aside(state)})
            return "failed"
    if not batch:
        return None
    gone: list[str] = []
    ok_at, error, stuck = None, None, None
    until = time.monotonic() + LOOK
    for ev in batch:
        if time.monotonic() > until:
            break
        team = ev["issue"].split("-", 1)[0]
        if issue_problem(ev["issue"]) or team not in cfg["teams"]:
            # checked again at the post: the owner may have narrowed --teams since it was queued
            gone.append(ev["id"])
            error = f"{ev['issue']}: team {team} is not one the key was set for (dropped)"
            continue
        try:
            send(key, ev["issue"], ev["body"])
        except LinearError as e:
            tries = ev.get("tries", 0) + 1
            if not e.lasting and tries < MAX_TRIES:
                # may pass: keep it, moved behind the others so one issue never blocks the rest, and stop this
                # look rather than hammer a Linear that is down
                error, stuck = f"{ev['issue']}: {e}", ev["id"]
                break
            gone.append(ev["id"])
            why = str(e) if e.lasting else f"{e}; still failing after {tries} tries"
            error = f"{ev['issue']}: {why} (dropped)"
            continue
        gone.append(ev["id"])
        ok_at = now_iso
    with lock:
        try:
            doc = load_state(state)
        except LinearError:
            doc = fresh()
        keep = [e for e in doc["pending"] if e["id"] not in gone]
        back = [{**e, "tries": e.get("tries", 0) + 1} for e in keep if e["id"] == stuck]
        doc = {**doc, "pending": [e for e in keep if e["id"] != stuck] + back,
               "done": doc["done"] + [i for i in gone if i not in doc["done"]]}
        if ok_at:
            doc["last_ok"] = ok_at
        if error:
            doc["last_error"] = error
        save_state(state, doc)
    return "failed" if error else "sent"


def status(state: Path) -> dict:
    """For the Settings tab: whether a key is set (never the key), what waits, and how the last post went."""
    out: dict = {"key_set": False, "teams": [], "problem": None, "pending": 0, "last_ok": None, "last_error": None}
    try:
        cfg = load_config(state)
        out["key_set"], out["teams"] = cfg is not None, (cfg or {}).get("teams") or []
    except LinearError:
        out["problem"] = "the Linear key file cannot be read, so nothing is posted; set it again with agent.py linear-key"
    try:
        doc = load_state(state)
        out.update(pending=len(doc["pending"]), last_ok=doc["last_ok"], last_error=doc["last_error"])
    except LinearError:
        pass
    return out


def _write(p: Path, doc: dict | None) -> None:
    if doc is None:
        p.unlink(missing_ok=True)
        return
    data = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()
    tmp = p.with_name(f".{p.name}.{os.urandom(8).hex()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
