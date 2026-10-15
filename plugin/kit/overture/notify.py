"""Notifications (1.45.0): a digest of the questions waiting for an answer, to a Slack-style webhook.

The owner's choices of 2026-10-15 (OPEN-DECISIONS.md "Notifications", N1a N2b N3a N4b N5a):

- **One channel: an incoming webhook** that takes `{"text": ...}` (Slack; Mattermost; Discord's `/slack`
  URL). One HTTPS POST, no mail server.
- **The URL is the owner's, set in the terminal** (`agent.py notify-url`), never from a web page or a
  session: whoever holds it can post to the channel. It lives in STATE/notify.json (0600). The console
  shows only its host. Setting it on or off, how often and the quiet hours are Settings (settings.py).
- **What a message says:** how many questions wait, on which items, and the console's address. Never a
  question's text, never an email: those stay in the console.
- **When:** at most one message every N minutes, only for questions not already told, and none in the
  quiet hours (the console machine's clock). Each question is told once.
- **Who sends:** the console server, to that one host only: HTTPS, no redirects, a short timeout, the
  reply read no further than a few KiB. A failure is kept (its kind, never the URL) for the Settings tab
  and tried again next window.

    STATE/notify.json         {"url": "https://hooks.slack.com/services/..."}
    STATE/notify-state.json   {"told": [QID...], "last_at", "last_ok", "last_error"}
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import roles as RO

URL_FILE = "notify.json"
STATE_FILE = "notify-state.json"
MAX_URL = 512
TIMEOUT = 10.0          # seconds, per socket operation
TOTAL = 30.0            # seconds for the whole reply, however slowly it comes
MAX_REPLY = 4096        # a webhook answers "ok"; nothing longer is read
MAX_ITEMS_NAMED = 10    # a message names at most this many items, then "and N more"
MAX_TOLD = 5000         # told questions kept; the oldest are let go past this
HHMM = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


class NotifyError(Exception):
    """A webhook URL the kit refuses, a notify file it cannot read, or a send that failed; named."""


def url_problem(url: object) -> str | None:
    """Why `url` is not a webhook to post to, or None."""
    if not isinstance(url, str) or not 12 <= len(url) <= MAX_URL or any(c.isspace() or not c.isprintable()
                                                                        for c in url):
        return f"a webhook URL is one line of at most {MAX_URL} characters"
    try:
        u = urlsplit(url)
        port = u.port   # a port that is not a number raises here
    except ValueError:
        return "that is not a URL"
    if u.scheme != "https":
        return "a webhook URL starts with https:// (the message must not cross the network in the clear)"
    if not u.hostname or "@" in u.netloc or u.fragment:
        return "a webhook URL names a host, with no user name, password or #fragment"
    if port is not None and not 1 <= port <= 65535:
        return "that port is not one a URL can have"
    return None


def host(url: str) -> str:
    """The part of the URL the console may show: its host. The path is the secret."""
    return urlsplit(url).hostname or ""


def load_url(state: Path) -> str | None:
    """The webhook URL, or None when none is set. A file the kit refuses raises NotifyError."""
    p = Path(state) / URL_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as e:
        raise NotifyError(f"{p}: not readable ({type(e).__name__})") from None
    url = doc.get("url") if isinstance(doc, dict) and set(doc) == {"url"} else None
    why = url_problem(url)
    if why:
        raise NotifyError(f'{p}: the file is exactly {{"url": "https://..."}}: {why}')
    return url


def set_url(state: Path, url: str | None) -> None:
    """Set (None: remove) the webhook URL, logged in the role log by its host only (the path is the secret)."""
    if url is not None:
        why = url_problem(url)
        if why:
            raise NotifyError(why)
    p = Path(state) / URL_FILE

    def plan():
        try:
            before = load_url(state)
        except NotifyError:
            before = None   # a damaged file is replaced; there is no host to name
        if before == url and p.exists() == (url is not None):
            return None
        return ({"setting": {"key": "notify_url", "from": host(before) if before else None,
                             "to": host(url) if url else None}},
                lambda: _write(p, {"url": url} if url else None))
    RO.logged_change(state, None, plan)


def fresh() -> dict:
    return {"told": [], "last_at": None, "last_ok": None, "last_error": None}


def load_state(state: Path) -> dict:
    """What was told and how the last send went; a fresh start when there is no file. A file the kit
    refuses raises NotifyError (the caller starts fresh, named in its log: the worst is a question told twice)."""
    p = Path(state) / STATE_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fresh()
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as e:
        raise NotifyError(f"{p}: not readable ({type(e).__name__})") from None
    if (not isinstance(doc, dict) or set(doc) != set(fresh()) or not isinstance(doc["told"], list)
            or not all(isinstance(q, str) for q in doc["told"])
            or not all(v is None or isinstance(v, str) for k, v in doc.items() if k != "told")):
        raise NotifyError(f"{p}: not the notify state the kit writes")
    return doc


def save_state(state: Path, doc: dict) -> None:
    _write(Path(state) / STATE_FILE, {**doc, "told": doc["told"][-MAX_TOLD:]})


def quiet(now: dt.datetime, hours: dict | None) -> bool:
    """Whether `now` (the console machine's clock) falls in the quiet hours {"from", "to"} ("22:00", "07:00").
    A span that passes midnight wraps; `from` is inside it, `to` is not."""
    if not hours:
        return False
    t = now.strftime("%H:%M")
    a, b = hours["from"], hours["to"]
    return a <= t < b if a < b else (t >= a or t < b)


def _slack(s: str) -> str:
    """Slack's own escaping for text: &, < and > only (they start links and mentions)."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def message(project: str, new: dict[str, str], waiting: int, console: str) -> str:
    """The digest: how many questions are newly waiting, on which items, and where to answer them.
    `new` is qid -> item; never a question's text or anyone's email."""
    per: dict[str, int] = {}
    for item in new.values():
        per[item] = per.get(item, 0) + 1
    named = sorted(per.items(), key=lambda kv: (-kv[1], kv[0]))
    items = ", ".join(f"{i} ({n})" for i, n in named[:MAX_ITEMS_NAMED])
    if len(named) > MAX_ITEMS_NAMED:
        items += f" and {len(named) - MAX_ITEMS_NAMED} more items"
    n = len(new)
    head = f"{n} new question{'s' if n != 1 else ''} waiting for an answer"
    tail = f" ({waiting} waiting in all)" if waiting > n else ""
    return _slack(f"overture · {project}: {head}{tail}: {items}.") + f" <{_slack(console)}|Open the console>"


def send(url: str, text: str) -> None:
    """POST {"text": text} to the webhook. Raises NotifyError naming what failed, never the URL."""
    import http.client
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        """A redirect would carry the message to a host nobody configured."""
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)

    opener = urllib.request.build_opener(_NoRedirect())
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "overture-notify"})
    deadline = time.monotonic() + TOTAL
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            got = 0
            while got < MAX_REPLY:   # (security review) a reply dripped a byte at a time is cut off, not waited on
                if time.monotonic() > deadline:
                    raise NotifyError(f"the webhook took more than {TOTAL:.0f}s to answer")
                chunk = r.read1(512)
                if not chunk:
                    break
                got += len(chunk)
    except urllib.error.HTTPError as e:
        e.close()   # the refused redirect's (or the error's) response holds the socket open
        raise NotifyError(f"the webhook answered HTTP {e.code}") from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        raise NotifyError(f"the webhook could not be reached ({type(reason).__name__})") from None


def tick(state: Path, now: dt.datetime, waiting: dict[str, str], cfg: dict, project: str, console: str,
         post=send) -> str | None:
    """One look: tell the webhook about the questions newly waiting, if it is time. Returns "sent",
    "failed", or None (nothing new, not yet, quiet hours, off, or no URL).

    `waiting` is qid -> item of every question waiting for an answer now; `cfg` the notify settings
    (notify_on, notify_every, notify_quiet). Raises NotifyError for a URL file it cannot read.
    """
    if not cfg["notify_on"]:
        return None
    url = load_url(state)
    if url is None:
        return None
    try:
        doc = load_state(state)
    except NotifyError:
        doc = fresh()   # the caller's log names it via status(); a question may be told twice, never lost
    told = set(doc["told"])
    still = [q for q in doc["told"] if q in waiting]   # an answered question is let go: the file stays small
    new = {q: i for q, i in waiting.items() if q not in told}
    # Let go of answered questions first, whatever this look does next (code review): one answered and asked
    # again inside the window or the quiet hours is new again, rather than "told" for good.
    if still != doc["told"]:
        doc = {**doc, "told": still}
        _save(state, doc, "")
    if not new:
        return None
    if doc["last_at"] is not None:
        try:
            last = dt.datetime.fromisoformat(doc["last_at"])
        except ValueError:
            last = None
        # abs: a clock moved back leaves last_at in the future; inside a window of it still counts as recent
        if last is not None and abs(now - last) < dt.timedelta(minutes=cfg["notify_every"]):
            return None
    if quiet(now, cfg["notify_quiet"]):
        return None
    at = now.isoformat(timespec="seconds")
    try:
        post(url, message(project, new, len(waiting), console))
    except NotifyError as e:
        _save(state, {**doc, "last_at": at, "last_error": str(e)}, "after a failed send")
        return "failed"
    _save(state, {"told": still + sorted(new), "last_at": at, "last_ok": at, "last_error": None}, "after a send")
    return "sent"


def _save(state: Path, doc: dict, when: str) -> None:
    """save_state, a write failure named as a NotifyError. The caller (the server) then holds every send for
    one window: with nothing recorded, the next look would post the same digest again a minute later."""
    try:
        save_state(state, doc)
    except OSError as e:
        raise NotifyError(f"the notify state could not be written{' ' + when if when else ''} "
                          f"({type(e).__name__}); nothing is sent until the next window") from None


def status(state: Path) -> dict:
    """For the Settings tab: the webhook's host (never its path), and how the last send went."""
    out: dict = {"host": None, "problem": None, "last_ok": None, "last_error": None}
    try:
        url = load_url(state)
        out["host"] = host(url) if url else None
    except NotifyError:
        out["problem"] = "the webhook file cannot be read, so nothing is sent; set it again with agent.py notify-url"
    try:
        doc = load_state(state)
        out["last_ok"], out["last_error"] = doc["last_ok"], doc["last_error"]
    except NotifyError:
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
