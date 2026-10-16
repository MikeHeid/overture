#!/usr/bin/env python3
"""Render the README screenshots against the REAL console server.

The script starts `overture.server` in-process with a throwaway RSA key standing
in for Cloudflare Access (the same seam test_server.py uses), publishes
docs/demo/showcase.html as the project's page, and seeds the store the way
agents and the owner would: questions posted on the agent door, answers and
locks posted on the owner door, a ruling made stale by editing the file it
cites, a deliberation round, a Mermaid visual, a chat thread, starred items and
a pushed PR list. Playwright then opens the console with a signed Access token
and captures each capability. Nothing above the network is mocked.

    pip install playwright==1.56.0      # or any version whose Chromium you have
    python3 docs/demo/screenshots.py    # writes docs/screenshots/*.png

The demo project, "Northwind platform rebuild", is planned as 4 waves, 9 phases
and 5 lanes (API, Web UI, Data, Infra, Security); each item carries a
`section` like "wave-2/phase-2.2/lane-api".
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs" / "screenshots"

# Never touch the user's real registry or config.
os.environ["OVERTURE_TEST_CONFIG"] = os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="ck-demo-cfg-")
os.environ.pop("OVERTURE_AGENT", None)
sys.path.insert(0, str(REPO / "plugin" / "kit"))

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from overture import doorbell as D  # noqa: E402
from overture import pagesnap as PS  # noqa: E402
from overture import server as SV  # noqa: E402

TEAM = "demo.cloudflareaccess.com"
AUD = "d" * 64
HOSTNAME = "console.northwind.example"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(email: str = "owner@example.com") -> str:
    now = int(time.time())
    return jwt.encode({"aud": [AUD], "iss": f"https://{TEAM}", "email": email,
                       "iat": now, "exp": now + 3600, "sub": "owner"}, KEY, algorithm="RS256",
                      headers={"kid": "k1"})


# id: (title, section, status)
ITEMS = {
    "W1": ("Wave 1 · Foundations", None, "built"),
    "W2": ("Wave 2 · Core services", None, "claimed"),
    "W3": ("Wave 3 · Scale & harden", None, "open"),
    "W4": ("Wave 4 · Launch", None, "open"),
    "API-1": ("Job queue on Postgres", "wave-2/phase-2.1/lane-api", "built"),
    "API-2": ("Retry & dead-letter policy", "wave-2/phase-2.2/lane-api", "claimed"),
    "API-3": ("Public REST v2 versioning", "wave-2/phase-2.2/lane-api", "open"),
    "API-4": ("GraphQL gateway", "wave-3/phase-3.1/lane-api", "deferred"),
    "UI-1": ("Design tokens & dark mode", "wave-1/phase-1.3/lane-ui", "built"),
    "UI-2": ("Invoice screen", "wave-2/phase-2.2/lane-ui", "claimed"),
    "UI-3": ("Onboarding checklist", "wave-2/phase-2.2/lane-ui", "open"),
    "UI-4": ("Team invites", "wave-2/phase-2.2/lane-ui", "blocked"),
    "DATA-1": ("Usage events pipeline", "wave-2/phase-2.1/lane-data", "built"),
    "DATA-2": ("Billing ledger schema", "wave-2/phase-2.2/lane-data", "claimed"),
    "DATA-3": ("Search index choice", "wave-2/phase-2.3/lane-data", "open"),
    "OPS-1": ("Preview environments", "wave-1/phase-1.1/lane-infra", "built"),
    "OPS-2": ("Backups & restore drill", "wave-2/phase-2.2/lane-infra", "claimed"),
    "OPS-3": ("Second region", "wave-3/phase-3.1/lane-infra", "open"),
    "SEC-1": ("Session expiry", "wave-1/phase-1.2/lane-security", "built"),
    "SEC-2": ("Roles & permissions", "wave-2/phase-2.2/lane-security", "claimed"),
    "SEC-3": ("Audit log export", "wave-3/phase-3.3/lane-security", "open"),
}


def _parent(iid: str) -> str | None:
    sec = ITEMS[iid][1]
    return None if sec is None else "W" + sec.split("/")[0].split("-")[1]


class Adapter:
    def items(self):
        return {i: {"title": t, "parent": _parent(i), "status": st, **({"section": s} if s else {})}
                for i, (t, s, st) in ITEMS.items()}

    def seed_questions(self):
        return []

    def record(self, entries, dry_run):
        return []


# Project files the questions cite as evidence and anchor their rulings on.
FILES = {
    "src/jobs/worker.ts": (
        "import { pool } from '../db/pool'\n"
        "\n"
        "export async function run(job: Job) {\n"
        "  try {\n"
        "    await handlers[job.kind](job.payload)\n"
        "  } catch (err) {\n"
        "    await markFailed(job.id, err)\n"
        "    // TODO(API-2): retry policy\n"
        "    throw err\n"
        "  }\n"
        "}\n"),
    "src/db/queue.sql": (
        "-- the job queue (API-1)\n"
        "SELECT id, kind, payload FROM jobs\n"
        "WHERE run_at <= now()\n"
        "ORDER BY run_at\n"
        "FOR UPDATE SKIP LOCKED\n"
        "LIMIT 10;\n"),
    "ops/backup.yml": (
        "schedule: monthly\n"
        "restore_drill: automated\n"
        "retention_days: 35\n"),
    "src/auth/session.ts": (
        "export const SESSION_IDLE_DAYS = 30\n"),
}


class Demo:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="ck-demo-")
        root = Path(self.tmp.name)
        for rel, text in FILES.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.root = root
        self.cfg = SV.Config(root=root, page=None, state=root / "state", adapter=root / "unused.py",
                             team_domain=TEAM, aud=AUD, hostname=HOSTNAME, port=0, project="northwind")
        self.console = SV.Console(self.cfg, Adapter())
        self.console.seed()
        verify = SV.access_verifier(TEAM, AUD, key_for=lambda _t: KEY.public_key())
        self.owner_srv = SV.owner_server(self.console, verify, 0)
        self.port = self.owner_srv.server_address[1]
        threading.Thread(target=self.owner_srv.serve_forever, daemon=True).start()
        self.agent_srv = SV.agent_server(self.console)
        threading.Thread(target=self.agent_srv.serve_forever, daemon=True).start()
        self._publish_page()

    def close(self) -> None:
        for s in (self.owner_srv, self.agent_srv):
            s.shutdown()
            s.server_close()
        self.tmp.cleanup()

    def _publish_page(self) -> None:
        page = (HERE / "showcase.html").read_bytes()
        commit = "4f2c9e1" + "0" * 33
        PS.stage(self.cfg.state, {"content": base64.b64encode(page).decode(), "ref": "refs/heads/main",
                                  "commit": commit, "path": "docs/console/page.html", "reviewed": True})
        PS.publish(self.cfg.state, commit)

    # -- the two doors -------------------------------------------------------
    def agent(self, path: str, body: dict, name: str | None = None) -> dict:
        if path in ("/question", "/visual", "/message"):   # records carry a nonce; snapshots do not
            body.setdefault("nonce", "n" + secrets.token_hex(8))
        code, out = SV.agent_request(self.cfg.socket, "POST", path, body, agent=name)
        if code != 200:
            raise RuntimeError(f"agent {path}: {code} {out}")
        return out

    def owner(self, path: str, body: dict, email: str = "owner@example.com") -> dict:
        body.setdefault("nonce", "o" + secrets.token_hex(8))
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, body=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "Origin": f"https://{HOSTNAME}",
            "X-Overture-CSRF": self.console._csrf, "Cf-Access-Jwt-Assertion": token(email)})
        r = conn.getresponse()
        out = json.loads(r.read() or b"{}")
        conn.close()
        if r.status != 200:
            raise RuntimeError(f"owner {path}: {r.status} {out}")
        return out

    # -- seeding -------------------------------------------------------------
    def ask(self, qid, text, opts, star, star_by, name, evidence=None, valid_if=None, **extra):
        body = {"qid": qid, "item": qid.split("/")[0], "text": text, "kind": "single",
                "options": [{"id": k, "label": l, "description": d} for k, l, d in opts],
                "star": star, "star_by": star_by, "valid_if": valid_if or [],
                "source": "docs/roadmap.md:1", **extra}
        if evidence:
            body["evidence"] = evidence
        return self.agent("/question", body, name)["record"]

    def answer_and_lock(self, qid, pick, words=""):
        a = self.owner("/api/answer", {"qid": qid, "picks": [pick], "own_text": words})["record"]
        self.owner("/api/lock", {"qid": qid, "answer": a["id"]})
        return a

    def seed(self) -> None:
        # Rulings first, so they are the oldest records.
        self.ask("API-1/Q1", "Where should the job queue live?",
                 [("a", "Postgres + SKIP LOCKED", "No new service; fine to ~1k jobs/s."),
                  ("b", "Redis + BullMQ", "Faster; one more service to run and secure.")],
                 "a", "architect", "agent-2",
                 evidence=[{"cite": "src/db/queue.sql:2-6"}],
                 valid_if=[{"kind": "excerpt", "path": "src/db/queue.sql", "text": "FOR UPDATE SKIP LOCKED"}])
        self.answer_and_lock("API-1/Q1", "a", "Postgres until it hurts. Revisit at 500 jobs/s.")
        self.ask("SEC-1/Q1", "Should sessions expire after inactivity?",
                 [("a", "After 30 days", "Common default; users rarely notice."),
                  ("b", "After 24 hours", "Safer; more sign-ins.")], "a", "security", "agent-1",
                 valid_if=[{"kind": "excerpt", "path": "src/auth/session.ts", "text": "SESSION_IDLE_DAYS = 30"}])
        self.answer_and_lock("SEC-1/Q1", "a")
        self.ask("OPS-2/Q1", "How often should we prove backups restore?",
                 [("a", "Monthly, automated", "A drill that runs itself, every month."),
                  ("b", "Quarterly, by hand", "Less noise; slower to catch rot.")], "a", "devops", "agent-5",
                 evidence=[{"cite": "ops/backup.yml:1-2"}],
                 valid_if=[{"kind": "excerpt", "path": "ops/backup.yml", "text": "restore_drill: automated"}])
        self.answer_and_lock("OPS-2/Q1", "a", "Monthly. A backup we never restored is a hope, not a backup.")
        # ...then the code moves under that ruling: the drill was switched to manual.
        (self.root / "ops/backup.yml").write_text("schedule: monthly\nrestore_drill: manual\nretention_days: 35\n")

        # Open questions from several named agents.
        self.ask("API-2/Q1", "How many times should a failed job retry before a human looks?",
                 [("a", "3 times, exponential backoff", "Then park it in a dead-letter table and ping the owner."),
                  ("b", "Retry forever", "Never loses a job; a broken upstream API gets hammered all night."),
                  ("c", "No automatic retries", "Simplest. Every network blip becomes a manual task.")],
                 "a", "devops", "agent-2", evidence=[{"cite": "src/jobs/worker.ts:6-9"}])
        self.ask("API-2/Q2", "Where do dead-lettered jobs go?",
                 [("a", "A dead_jobs table", "Queryable; replay with one UPDATE."),
                  ("b", "An S3 bucket", "Cheap; harder to replay.")], "a", "architect", "agent-2")
        self.ask("API-3/Q1", "How should the public API be versioned?",
                 [("a", "URL prefix (/v2/...)", "Obvious in logs and docs; cache-friendly."),
                  ("b", "Header (Accept-Version)", "Cleaner URLs; easy to forget in curl examples."),
                  ("c", "Date-pinned per account", "Stripe-style; most work to build and test.")],
                 "a", "architect", "agent-2")
        self.ask("UI-3/Q1", "What should the first screen after sign-up be?",
                 [("a", "A 4-step checklist", "Connect repo, invite team, set billing, run a first job."),
                  ("b", "An empty dashboard with a tour", "Less guided; tours are often skipped."),
                  ("c", "A sample project", "Shows value fastest; needs cleanup later.")], "a", "ux", "agent-4")
        self.ask("SEC-2/Q1", "Which roles do we ship first?",
                 [("a", "Owner, Admin, Member", "Covers most teams; easy to explain."),
                  ("b", "Owner + custom roles", "Flexible; needs a permissions UI now.")],
                 "a", "security", "agent-1")
        # Two answered but unlocked on one item: "Lock all 2 answers".
        self.ask("SEC-2/Q2", "Can an Admin delete the workspace?",
                 [("a", "No, Owner only", "Irreversible; keep it with one person."),
                  ("b", "Yes", "Fewer support tickets.")], "a", "security", "agent-1")
        self.owner("/api/answer", {"qid": "SEC-2/Q1", "picks": ["a"], "own_text": ""})
        self.owner("/api/answer", {"qid": "SEC-2/Q2", "picks": ["a"], "own_text": "Owner only."})
        self.ask("DATA-2/Q1", "Store money as integer cents or decimals?",
                 [("a", "Integer minor units (cents)", "No rounding bugs; matches Stripe."),
                  ("b", "NUMERIC(12,2)", "Readable in SQL; easy to misuse in JS.")], "a", "analyst", "agent-3")
        # One answered but not yet locked.
        self.ask("UI-2/Q1", "Show tax as its own line on the invoice screen?",
                 [("a", "Yes, always", "Required in the EU anyway."),
                  ("b", "Only when non-zero", "Tidier for US customers.")], "a", "ux", "agent-4")
        self.owner("/api/answer", {"qid": "UI-2/Q1", "picks": ["a"], "own_text": ""})

        # A deliberation round on OPS-3: the owner asks for a panel, the panel returns findings.
        fork = self.owner("/api/message", {"item": "OPS-3", "text": "Deliberate the second region",
                                           "intent": "fork", "mode": "tighten"})["record"]
        for n, (text, star) in enumerate([
                ("Which region comes second?", "eu"),
                ("Active-active or warm standby?", "warm"),
                ("Who owns the failover runbook?", "ops")], start=1):
            opts = {"eu": [("eu", "eu-west-1", "Most EU customers; the GDPR story."),
                           ("ap", "ap-southeast-2", "Two large APAC prospects.")],
                    "warm": [("warm", "Warm standby", "Half the cost; minutes of failover."),
                             ("aa", "Active-active", "No failover gap; twice the data headaches.")],
                    "ops": [("ops", "Infra lane", "They run the drills already."),
                            ("each", "Each lane for its service", "Closer to the code; uneven.")]}[star]
            self.ask(f"OPS-3/Q{n}", text, opts, star, "panel", "steward", forked_from=fork["id"])

        # A requested visual, drawn by an agent.
        req = self.owner("/api/message", {"item": "API-2", "text": "Draw the retry flow",
                                          "intent": "visual"})["record"]
        self.agent("/visual", {"request": req["id"], "format": "mermaid", "title": "Retry and dead-letter flow",
                               "content": ("flowchart LR\n  A[Job runs] -->|ok| B[Done]\n"
                                           "  A -->|error| C{Attempts < 3?}\n"
                                           "  C -->|yes| D[Wait 2^n s] --> A\n"
                                           "  C -->|no| E[(dead_jobs)] --> F[Ping owner]\n"),
                               "text": "Three attempts with exponential backoff, then the dead-letter table."},
                   "agent-2")

        # Chat: the owner asks, the steward answers.
        chat = self.owner("/api/message", {"item": "@chat", "text": "Is main green after the queue change?",
                                           "intent": "chat"})["record"]
        self.agent("/message", {"item": "@chat", "text": "Yes. CI green on 4f2c9e1; 212 tests, 0 failures.",
                                "reply_to": chat["id"]}, "steward")

        # Tickets, with blocking chains: the schema blocks the migration, which blocks the backfill.
        def ticket(item, title, kind="task", blocked_by=None, body=""):
            b = {"parent_item": item, "title": title, "kind": kind, "body": body}
            if blocked_by:
                b["blocked_by"] = blocked_by
            return self.owner("/api/ticket-create", b)["ticket"]["id"]
        schema = ticket("DATA-2", "Ledger schema: integer cents")
        migrate = ticket("DATA-2", "Migration for the ledger", blocked_by=[schema])
        ticket("DATA-2", "Backfill last 90 days of invoices", blocked_by=[migrate])
        dlq = ticket("API-2", "dead_jobs table + replay endpoint")
        ticket("API-2", "Alert the owner when a job dead-letters", blocked_by=[dlq])
        ticket("API-2", "Retries hammer Stripe on 5xx", kind="bug")
        roles = ticket("SEC-2", "Owner / Admin / Member roles", body="Admins cannot delete the workspace.")
        ticket("UI-4", "Team invites screen", blocked_by=[roles])
        ticket("OPS-3", "Compare eu-west-1 vs ap-southeast-2 latency", kind="research")
        ticket("UI-3", "Grill: is a checklist better than a sample project?", kind="grilling")
        done = ticket("UI-1", "Dark-mode tokens")
        self.owner("/api/ticket-close", {"id": done})
        self.ticket_ids = {"schema": schema, "migrate": migrate}

        # Stars.
        for key in ("item:API-2", "item:OPS-2"):
            self.owner("/api/favorite", {"id": key})

        # The steward's PR push.
        now = datetime.now(timezone.utc)

        def ts(hours):
            return (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        repo = "northwind/platform"
        prs = [
            (214, "API-2: retry with backoff and dead_jobs table", "open", False, "success", 3, None),
            (213, "UI-2: invoice screen, tax line", "open", True, "pending", 5, None),
            (212, "API-1: job queue on Postgres SKIP LOCKED", "merged", False, "success", 30, 26),
            (211, "SEC-1: 30-day idle session expiry", "merged", False, "success", 50, 48),
            (209, "OPS-2: switch restore drill to manual", "merged", False, "success", 4, 2),
        ]
        body = {"repo": repo, "window_days": 30, "prs": [
            {"number": n, "title": t, "state": st, "draft": d, "head": f"feat/{n}", "base": "main",
             "author": "agent-bot", "created_at": ts(c), "updated_at": ts(m if m else 1),
             "merged_at": ts(m) if st == "merged" else None, "closed_at": ts(m) if st == "merged" else None,
             "url": f"https://github.com/{repo}/pull/{n}",
             "merge_commit": (secrets.token_hex(20) if st == "merged" else None), "checks": ck,
             "head_sha": secrets.token_hex(20)}
            for n, t, st, d, ck, c, m in prs]}
        self.agent("/prs", body, "steward")

        # 1.32: screenshots agents posted on items (FEED-ASSETS.md). Real ones: the tab bar before and
        # after the icons PR, and a UX component rendered by tools/ux_check.py.
        shots = HERE / "assets"
        def asset(item, name, caption, kind, who, **extra):
            data = base64.b64encode((shots / name).read_bytes()).decode()
            self.agent("/asset", {"item": item, "content_b64": data, "caption": caption, "kind": kind, **extra}, who)
        asset("UI-3", "plan-picker-375.png", "Plan picker at 375px, dark, scripts off", "screenshot", "agent-4")
        asset("UI-1", "tabs-before.png", "Tab bar before icons", "before", "agent-4")
        asset("UI-1", "tabs-after.png", "Tab bar with icons: five tabs fit one line at 515px", "after", "agent-4",
              pr=214)

        # 1.33: a UX item with two drawn versions of a component, for the UX View modal.
        comp = (REPO / "plugin/skills/console-ux/references/example-plan-picker.html").read_text()
        ureq = self.owner("/api/message", {"item": "UI-3", "text": "Draw the plan picker", "intent": "visual",
                                           "purpose": "ux"})["record"]
        self.agent("/visual", {"request": ureq["id"], "format": "html", "title": "Plan picker",
                               "content": comp.replace("Pro", "Team", 1), "text": "First pass: three plans."}, "agent-4")
        ureq2 = self.owner("/api/message", {"item": "UI-3", "text": "Make the price clearer", "intent": "visual",
                                            "purpose": "ux"})["record"]
        self.agent("/visual", {"request": ureq2["id"], "format": "html", "title": "Plan picker", "content": comp,
                               "text": "Second pass: clearer price and a recommended plan."}, "agent-4")

        # 1.33: UI-3 is linked to a Claude Design whose artifacts an agent listed (the UX View picker), and the
        # owner has attached a picture of their own to it.
        design = "https://claude.ai/design/p/fee63c71-69b8-455c-bb5b-c7935342adc1"
        self.owner("/api/message", {"item": "UI-3", "intent": "ux-link", "url": design, "text": "Link the design"})
        self.agent("/design-inventory", {"url": design, "nonce": "di1", "artifacts": [
            {"path": "components/plan-card.html", "title": "Plan card"},
            {"path": "components/checkout-form.html", "title": "Checkout form"},
            {"path": "buttons/primary.html", "title": "Primary button"},
            {"path": "buttons/secondary.html", "title": "Secondary button"},
            {"path": "tokens/colors.html", "title": "Colour tokens"},
            {"path": "tokens/type.html", "title": "Type scale"},
            {"path": "layout/two-column.html", "title": "Two-column layout"}]}, "agent-4")
        sketch = base64.b64encode((shots / "tabs-before.png").read_bytes()).decode()
        self.owner("/api/asset-upload", {"item": "UI-3", "content_b64": sketch, "caption": "My sketch: keep the plans in one row"})

        # The steward is watching and synced a minute ago.
        self.agent("/cursor", {"last_synced_at": (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                   "steward")
        D.write_watch(self.cfg.state, True, every=3600)


# Scroll an element's BOTTOM edge into view (with a little air), so a box that opens below the
# fold is shown whole; scroll_into_view_if_needed only guarantees its top edge.
SHOW_WHOLE = "el => { el.scrollIntoView({block: 'end'}); const p = el.closest('.ck-body') || el.parentElement;" \
             " if (p && p.scrollBy) p.scrollBy(0, 24); }"


# -- capture ---------------------------------------------------------------
def capture(demo: Demo) -> list[str]:
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{demo.port}/"
    problems: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        def page_for(scheme, width=1680, height=1000):
            ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme,
                                      device_scale_factor=2,
                                      extra_http_headers={"Cf-Access-Jwt-Assertion": token()})
            pg = ctx.new_page()
            pg.goto(url)
            pg.wait_for_selector(".ck-panel[data-open='true']", timeout=15000)
            pg.wait_for_timeout(1500)
            return pg

        def panel(pg, name):
            pg.locator(".ck-panel").screenshot(path=str(OUT / f"{name}.png"))

        def shot(name, fn, scheme="dark"):
            try:
                pg = page_for(scheme)
                fn(pg)
                pg.context.close()
                print("wrote", name)
            except Exception as e:  # one failed scene never stops the others
                problems.append(f"{name}: {str(e).splitlines()[0]}")

        def item(pg, iid, wait=1500):
            pg.evaluate("id => { location.hash = '#item=' + id }", iid)
            pg.wait_for_timeout(wait)

        # Full-page heroes, both themes.
        def overview(scheme):
            def f(pg):
                pg.screenshot(path=str(OUT / f"overview-{scheme}.png"))
            return f

        def question(scheme):
            def f(pg):
                item(pg, "API-2")
                pg.screenshot(path=str(OUT / f"question-{scheme}.png"))
            return f
        for scheme in ("dark", "light"):
            shot(f"overview-{scheme}", overview(scheme), scheme)
            shot(f"question-{scheme}", question(scheme), scheme)

        # One panel shot per capability.
        def answer_lock(pg):
            item(pg, "API-2")
            pg.locator(".ck-question").first.screenshot(path=str(OUT / "feature-answer.png"))
        shot("feature-answer", answer_lock)

        def round_form(pg):
            item(pg, "OPS-3")
            pg.locator(".ck-panel button", has_text="Answer this round").first.click()
            pg.wait_for_timeout(900)
            pg.keyboard.press("1")
            pg.wait_for_timeout(900)
            panel(pg, "feature-round")
        shot("feature-round", round_form)

        def send_bar(pg):
            item(pg, "UI-2")
            panel(pg, "feature-send")
        shot("feature-send", send_bar)

        def lock_all(pg):
            item(pg, "SEC-2")
            pg.locator(".ck-panel button", has_text="Lock all").first.click()
            pg.wait_for_timeout(700)
            panel(pg, "feature-lock-all")
        shot("feature-lock-all", lock_all)

        def locked(pg):
            item(pg, "API-1")
            panel(pg, "feature-locked")
        shot("feature-locked", locked)

        def deliberate(pg):
            item(pg, "API-3")
            b = pg.locator(".ck-panel button", has_text="Deliberate").first
            b.click()
            pg.wait_for_timeout(800)
            panel(pg, "feature-deliberate")
        shot("feature-deliberate", deliberate)

        def next_step(pg):
            item(pg, "API-1")
            pg.locator(".ck-q-line").first.click()
            pg.wait_for_timeout(500)
            b = pg.locator(".ck-panel button", has_text="Next step").first
            b.click()
            pg.wait_for_timeout(600)
            panel(pg, "feature-next-step")
        shot("feature-next-step", next_step)

        def flowchart(pg):
            item(pg, "OPS-3")
            pg.locator(".ck-panel summary", has_text="Status flowchart").first.click()
            pg.wait_for_timeout(3500)
            panel(pg, "feature-flowchart")
        shot("feature-flowchart", flowchart)

        def project_map(pg):
            pg.locator(".ck-panel summary", has_text="Project map").first.click()
            pg.wait_for_timeout(3500)
            panel(pg, "feature-project-map")
        shot("feature-project-map", project_map)

        def visual(pg):
            item(pg, "API-2", wait=3500)
            v = pg.locator(".ck-visual").first
            v.scroll_into_view_if_needed()
            pg.wait_for_timeout(1500)
            v.screenshot(path=str(OUT / "feature-visual.png"))
        shot("feature-visual", visual)

        def tab(name, label, wait=1500):
            def f(pg):
                t = pg.locator(f"#ck-tab-{label}")
                if t.count():
                    t.click()
                else:
                    pg.locator(".ck-tab-more").click()
                    pg.wait_for_timeout(300)
                    pg.get_by_role("menuitem", name=label.capitalize()).first.click()
                pg.wait_for_timeout(wait)
                panel(pg, name)
            return f
        shot("feature-favorite", tab("feature-favorite", "favorite"))
        shot("feature-chat", tab("feature-chat", "chat"))
        shot("feature-feed", tab("feature-feed", "feed"))
        shot("feature-prs", tab("feature-prs", "prs"))

        def stale(pg):
            item(pg, "OPS-2")
            line = pg.locator(".ck-q-line").first
            if line.count() and line.get_attribute("aria-expanded") == "false":
                line.click()
                pg.wait_for_timeout(400)
            why = pg.locator(".ck-panel button", has_text="What changed").first
            if why.count():
                why.click()
                pg.wait_for_timeout(1200)
                pg.locator(".ck-why").first.evaluate(SHOW_WHOLE)
                pg.wait_for_timeout(300)
            panel(pg, "feature-stale")
        shot("feature-stale", stale)

        def feed_assets(pg):
            pg.locator("#ck-tab-feed").click()
            pg.wait_for_timeout(900)
            pg.select_option("#ck-feed-kind", "asset")
            pg.wait_for_timeout(1200)
            panel(pg, "feature-assets")
        shot("feature-assets", feed_assets)

        def ux_view(pg):
            item(pg, "UI-3")
            pg.get_by_role("button", name="Open UX View for UI-3").click()
            pg.wait_for_selector("#ck-ux-view")
            pg.wait_for_timeout(1200)
            pg.screenshot(path=str(OUT / "feature-ux-view.png"))
        shot("feature-ux-view", ux_view)

        def ux_picker(pg):
            item(pg, "UI-3")
            pg.get_by_role("button", name="Open UX View for UI-3").click()
            pg.wait_for_selector("#ck-ux-view")
            pg.locator(".ck-ux-settings summary").click()
            boxes = pg.locator(".ck-ux-ref input[type=checkbox]")
            boxes.nth(0).check()
            boxes.nth(2).check()
            pg.locator(".ck-ux-refmode").nth(2).select_option("swap")
            pg.wait_for_timeout(1200)
            pg.screenshot(path=str(OUT / "feature-ux-picker.png"))
        shot("feature-ux-picker", ux_picker)

        def pr_merge(pg):
            pg.locator("#ck-tab-prs").click()
            pg.wait_for_timeout(900)
            pg.get_by_role("button", name="Merge pull request 214 into main").click()
            pg.wait_for_timeout(500)
            panel(pg, "feature-pr-merge")
        shot("feature-pr-merge", pr_merge)

        def attach(pg):
            item(pg, "UI-3")
            pg.locator(".ck-attach-row").scroll_into_view_if_needed()
            pg.evaluate("document.querySelector('.ck-attach-row').scrollIntoView({block: 'center'})")
            pg.wait_for_timeout(500)
            panel(pg, "feature-attach")
        shot("feature-attach", attach)

        def asset_viewer(pg):
            item(pg, "UI-1")
            pg.locator(".ck-assets-fold .ck-asset-thumb").last.click()
            pg.wait_for_timeout(900)
            pg.screenshot(path=str(OUT / "feature-asset-viewer.png"))
        shot("feature-asset-viewer", asset_viewer)

        def tickets_tab(pg):
            pg.locator("#ck-tab-tickets").click()
            pg.wait_for_timeout(900)
            panel(pg, "feature-tickets")
        shot("feature-tickets", tickets_tab)

        def ticket_graph(pg):
            pg.locator("#ck-tab-tickets").click()
            pg.wait_for_timeout(600)
            pg.locator(".ck-panel summary", has_text="What blocks what").first.click()
            pg.wait_for_timeout(3500)
            pg.locator(".ck-ticket-chart").first.screenshot(path=str(OUT / "feature-ticket-graph.png"))
        shot("feature-ticket-graph", ticket_graph)

        def chat_menu(pg):
            item(pg, "API-2")
            pg.locator(".ck-panel .ck-split-more").first.click()
            pg.wait_for_timeout(500)
            panel(pg, "feature-chat-menu")
        shot("feature-chat-menu", chat_menu)

        def footer_keys(pg):
            pg.locator(".ck-footer-keys").click()
            pg.wait_for_timeout(600)
            pg.screenshot(path=str(OUT / "feature-footer-keys.png"))
        shot("feature-footer-keys", footer_keys)

        def ribbon(pg):
            pg.locator(".ck-priority-ribbon").first.screenshot(path=str(OUT / "feature-priority.png"))
        shot("feature-priority", ribbon)

        def palette(pg):
            pg.keyboard.press("Control+k")
            pg.wait_for_timeout(500)
            pg.keyboard.type("retry")
            pg.wait_for_timeout(700)
            pg.locator("#ck-palette").screenshot(path=str(OUT / "feature-palette.png"))
        shot("feature-palette", palette)

        def shortcuts(pg):
            pg.locator("body").click(position={"x": 400, "y": 600})
            pg.keyboard.press("?")
            pg.wait_for_timeout(700)
            pg.locator("#ck-shortcut-help").screenshot(path=str(OUT / "feature-shortcuts.png"))
        shot("feature-shortcuts", shortcuts)

        record_gifs(browser, url, problems)
        team_scenes(demo, shot, tab, panel, item)
        try:
            later_scenes(demo, shot, tab, panel, item)
        except Exception as e:  # the seeding itself failed: name it, keep the shots already taken
            problems.append(f"later scenes: {str(e).splitlines()[0]}")
        link_scenes(browser, problems)
        browser.close()
    return problems


# -- the team features (1.39–1.45) ------------------------------------------
def team_scenes(demo: Demo, shot, tab, panel, item) -> None:
    """Roles, routing, two-key locks, Settings and notifications. Captured last: once roles are on, every
    question carries a "For" line, so the scenes above (and the animations) are taken without them."""
    from overture import notify as NT
    from overture import roles as RO
    from overture import settings as SET
    st, me = demo.cfg.state, "owner@example.com"   # the page's own login, as token() signs it
    RO.set_role(st, me, "owner")
    RO.set_role(st, "bob@example.com", "member", ["API-2", "UI-2"], by=me)
    RO.set_role(st, "carol@example.com", "viewer", director=True, by=me)
    RO.set_two_key(st, ["SEC-2"], by=me)
    SET.put(st, "chat_per_minute", 4, by=me)
    SET.put(st, "lanes", {"lane-api": {"label": "API", "color": "blue"}}, by=me)
    SET.put_name(st, "bob@example.com", "bob", by=me)
    NT.set_url(st, "https://hooks.slack.com/services/T0DEMO/B0DEMO/not-a-real-hook")
    SET.put(st, "notify_on", True, by=me)
    SET.put(st, "notify_quiet", {"from": "22:00", "to": "07:00"}, by=me)
    # A first key on SEC-2/Q2 (answered in seed): the card waits for a second person.
    demo.owner("/api/lock", {"qid": "SEC-2/Q2", "answer": demo.console.store.head("SEC-2/Q2")["id"]})

    shot("feature-people", tab("feature-people", "people"))
    shot("feature-settings", tab("feature-settings", "settings"))

    def notify(pg):
        tab("feature-settings", "settings")(pg)
        pg.locator(".ck-settings-notify").screenshot(path=str(OUT / "feature-notify.png"))
    shot("feature-notify", notify)

    def routing(pg):
        pg.evaluate("ConsoleKit.openTab('inbox')")
        pg.wait_for_timeout(1500)
        panel(pg, "feature-routing")
    shot("feature-routing", routing)

    def two_key(pg):
        item(pg, "SEC-2")
        card = pg.locator(".ck-question[data-qid='SEC-2/Q2']")
        if not card.locator(".ck-two-key-note").count():
            pg.locator(".ck-q-line[data-qid='SEC-2/Q2']").click()
            pg.wait_for_timeout(800)
        card.screenshot(path=str(OUT / "feature-two-key.png"))
    shot("feature-two-key", two_key)


# -- automation, lessons, second keys and the shift (docs/features/*.md) ---------------------
def later_scenes(demo: Demo, shot, tab, panel, item) -> None:
    """Captured after the team scenes (roles stay on). Triggers are armed only now, so every shot above is taken
    without the Inbox's Triggers fold: the server loads .overture/triggers.json at start, and the demo re-reads it
    here the same way (Console.triggers.set_all(triggers.load(root)))."""
    from overture import lessons as LN
    from overture import roles as RO
    from overture import triggers as TR
    st, me = demo.cfg.state, "owner@example.com"

    # Playbooks under .overture/playbooks/, and two triggers that fire them (a webhook and a cron).
    books = demo.root / ".overture" / "playbooks"
    books.mkdir(parents=True, exist_ok=True)
    (books / "release-triage.json").write_text(json.dumps({
        "description": "Before a release: a heads-up while questions wait, a retry diagram, a round once clear.",
        "steps": [
            {"kind": "chat", "text": "Release window opens Monday 09:00. Anything blocking?",
             "when": {"kind": "project_has_state", "state": "awaiting_you", "min": 1}},
            {"kind": "visual", "item": "API-2", "text": "Draw the dead-letter replay path."},
            {"kind": "round", "item": "API-3", "mode": "tighten", "text": "Confirm the v2 cut-over gates.",
             "when": {"kind": "not", "of": {"kind": "project_has_state", "state": "awaiting_you", "min": 1}}}]}))
    (books / "weekly-review.json").write_text(json.dumps({
        "description": "Monday review: a round on the search index, and billing once it is on the plan.",
        "steps": [
            {"kind": "round", "item": "DATA-3", "mode": "explore", "text": "Postgres full-text or a search service?"},
            {"kind": "round", "item": "BILL-1", "mode": "explore", "text": "Invoice numbering per region.",
             "when": {"kind": "item_exists", "item": "BILL-1"}}]}))
    secret, sha = TR.mint()
    (demo.root / ".overture" / "triggers.json").write_text(json.dumps({"triggers": {
        "pr-merged": {"playbook": "release-triage", "token_sha256": sha},
        "monday-review": {"playbook": "weekly-review", "cron": "0 9 * * MON"}}}))
    demo.console.triggers.set_all(TR.load(demo.root))
    # One firing of each kind, through the real paths: the webhook over HTTP, the clock's own fire_cron, a replay.
    conn = http.client.HTTPConnection("127.0.0.1", demo.port, timeout=10)
    conn.request("POST", "/api/trigger/pr-merged", body=b"{}", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {secret}", "Cf-Access-Jwt-Assertion": token()})
    r = conn.getresponse()
    r.read()
    conn.close()
    if r.status != 200:
        raise RuntimeError(f"webhook trigger: {r.status}")
    demo.console.fire_cron("monday-review")
    demo.owner("/api/trigger-replay", {"name": "monday-review"})

    # A lesson: the owner withdrew an earlier versioning ruling on API-3, and the open question looks like it.
    LN.record(st, "API-3/Q0", "API-3", "withdraw", "How should the public API be versioned for partners?",
              "Header versioning is out: partners' curl examples kept dropping Accept-Version. Prefer the URL.",
              (datetime.now(timezone.utc) - timedelta(days=12)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    shot("feature-playbooks", tab("feature-playbooks", "playbooks"))
    def triggers_tab(pg):
        tab("feature-triggers", "triggers")(pg)
        nested = pg.locator(".ck-body details.ck-triggers summary")   # the firing log, a fold of its own
        if nested.count():
            nested.first.click()
            pg.wait_for_timeout(500)
        panel(pg, "feature-triggers")
    shot("feature-triggers", triggers_tab)

    def inbox_top(pg):
        pg.evaluate("ConsoleKit.openTab('inbox')")
        pg.wait_for_timeout(1200)
        panel(pg, "feature-inbox-top")
    shot("feature-inbox-top", inbox_top)

    def snooze(pg):
        pg.locator(".ck-priority-ribbon .ck-snooze-btn").first.click()
        pg.wait_for_timeout(400)
        pg.locator(".ck-priority-ribbon").first.screenshot(path=str(OUT / "feature-snooze.png"))
    shot("feature-snooze", snooze)

    def status_pop(pg):
        pg.locator(".ck-status-chip").first.click()
        pg.wait_for_selector("#ck-status-pop")
        pg.wait_for_timeout(600)
        pg.locator("#ck-status-pop").screenshot(path=str(OUT / "feature-status.png"))
    shot("feature-status", status_pop)

    shot("feature-portfolio", tab("feature-portfolio", "portfolio"))

    def export_today(pg):
        pg.locator("#ck-tab-feed").click()
        pg.wait_for_timeout(900)
        pg.locator(".ck-feed-digest").click()
        pg.wait_for_selector("#ck-digest")
        pg.wait_for_timeout(800)
        pg.screenshot(path=str(OUT / "feature-export-today.png"))
    shot("feature-export-today", export_today)

    def branch_out(pg):
        item(pg, "UI-3")
        pg.locator(".ck-panel button", has_text="Branch out").first.click()
        pg.wait_for_selector(".ck-branch-pane")
        pg.wait_for_timeout(500)
        pg.locator(".ck-branch-pane").screenshot(path=str(OUT / "feature-branch-out.png"))
    shot("feature-branch-out", branch_out)

    def variant(pg):
        item(pg, "UI-3", wait=3000)
        v = pg.locator(".ck-visual", has=pg.locator(".ck-visual-variant")).first
        v.scroll_into_view_if_needed()
        pg.wait_for_timeout(1500)
        v.screenshot(path=str(OUT / "feature-variant.png"))
    shot("feature-variant", variant)

    def preview(pg):
        tab("feature-playbook-preview", "playbooks")(pg)
        pg.locator(".ck-playbook-row", has_text="release-triage").locator("button", has_text="Preview").click()
        pg.wait_for_selector(".ck-pb-plan-row")
        pg.wait_for_timeout(500)
        pg.locator("#ck-pb-preview").screenshot(path=str(OUT / "feature-playbook-preview.png"))
    shot("feature-playbook-preview", preview)

    def delegate(pg):
        pg.locator(".ck-delegate-summary").click()
        pg.wait_for_timeout(400)
        pg.locator(".ck-delegate-bar input[value='playbook']").check()
        pg.wait_for_timeout(400)
        pg.locator(".ck-delegate-bar").screenshot(path=str(OUT / "feature-delegate.png"))
    shot("feature-delegate", delegate)

    def impact(pg):
        item(pg, "API-2")
        fold = pg.locator(".ck-panel details.ck-item-chart", has_text="Impact graph").first
        fold.locator("summary").click()
        pg.wait_for_timeout(4000)
        fold.evaluate(SHOW_WHOLE)
        pg.wait_for_timeout(300)
        fold.screenshot(path=str(OUT / "feature-impact-graph.png"))
    shot("feature-impact-graph", impact)

    def lesson_chip(pg):
        item(pg, "API-3")
        card = pg.locator(".ck-question[data-qid='API-3/Q1']")
        if not card.locator("summary.ck-q-lessons-chip").count():
            pg.locator(".ck-q-line[data-qid='API-3/Q1']").click()
            pg.wait_for_timeout(600)
        card.locator("summary.ck-q-lessons-chip").click()
        pg.wait_for_timeout(500)
        card.screenshot(path=str(OUT / "feature-lesson-chip.png"))
    shot("feature-lesson-chip", lesson_chip)

    def launch_idea(pg):
        item(pg, "UI-4")
        pg.locator(".ck-panel button", has_text="Launch Idea").first.click()
        pg.wait_for_selector("#ck-launch-pane")
        pg.fill("#ck-launch-pane input[aria-label='Idea title']", "Invite a whole team from a CSV")
        pg.fill("#ck-launch-pane textarea[aria-label='Idea pitch']",
                "Admins at larger customers add 40 people at once; one-by-one invites are the top support ask.")
        pg.locator("#ck-launch-pane button", has_text="Grill it").click()
        pg.wait_for_timeout(400)
        pg.fill("#ck-grill-user", "Priya, the IT admin at a 200-seat customer.")
        pg.wait_for_timeout(300)
        pg.locator("#ck-launch-pane").screenshot(path=str(OUT / "feature-launch-idea.png"))
    shot("feature-launch-idea", launch_idea)

    def shift(pg):
        pg.keyboard.press("Control+k")
        pg.wait_for_timeout(400)
        pg.keyboard.type("operator shift")
        pg.wait_for_timeout(500)
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#ck-shift")
        pg.wait_for_timeout(600)
        pg.locator("#ck-shift").screenshot(path=str(OUT / "feature-shift.png"))
    shot("feature-shift", shift)

    def role_log(pg):
        tab("feature-role-log", "people")(pg)
        log = pg.locator(".ck-people-log").first
        log.evaluate(SHOW_WHOLE)
        pg.wait_for_timeout(300)
        panel(pg, "feature-role-log")
    shot("feature-role-log", role_log)

    def locked_by(pg):
        item(pg, "API-1")
        card = pg.locator(".ck-question[data-qid='API-1/Q1']")
        if not card.locator(".ck-receipt-by").count():
            pg.locator(".ck-q-line[data-qid='API-1/Q1']").click()
            pg.wait_for_timeout(600)
        card.screenshot(path=str(OUT / "feature-locked-by.png"))
    shot("feature-locked-by", locked_by)

    # The second key on SEC-2/Q2: another administrator locks the same answer.
    RO.set_role(st, "dana@example.com", "owner", by=me)
    demo.owner("/api/lock", {"qid": "SEC-2/Q2", "answer": demo.console.store.head("SEC-2/Q2")["id"]},
               email="dana@example.com")

    def confirmed(pg):
        item(pg, "SEC-2")
        card = pg.locator(".ck-question[data-qid='SEC-2/Q2']")
        if not card.locator(".ck-receipt-by").count():
            pg.locator(".ck-q-line[data-qid='SEC-2/Q2']").click()
            pg.wait_for_timeout(600)
        card.screenshot(path=str(OUT / "feature-two-key-confirmed.png"))
    shot("feature-two-key-confirmed", confirmed)


# -- sign-in links (1.46): a second console, --auth link, no Cloudflare --------------------------
def link_scenes(browser, problems: list[str]) -> None:
    """The sign-in page, the not-signed-in page, and People's signed-in browsers. Invites and sign-ins go through
    devices.invite / redeem against the devices file beside the TEMP registry (XDG_CONFIG_HOME, set above), and the
    browser signs itself in by pressing the page's own button."""
    import socket
    from overture import devices as DV
    cfg_home = os.path.realpath(os.environ["XDG_CONFIG_HOME"])
    if not os.path.realpath(DV.location()).startswith(cfg_home + os.sep):
        problems.append(f"link scenes: devices file {DV.location()} is outside the temp config; not run")
        return
    tmp = tempfile.TemporaryDirectory(prefix="ck-demo-link-")
    root = Path(tmp.name)
    with socket.socket() as s:   # the console's origin names its port, so pick one first
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    cfg = SV.Config(root=root, page=None, state=root / "state", adapter=root / "unused.py", team_domain="",
                    aud="", hostname="", port=port, project="northwind", auth="link", origin=origin)
    console = SV.Console(cfg, Adapter())
    console.seed()
    page = (HERE / "showcase.html").read_bytes()
    commit = "4f2c9e1" + "0" * 33
    PS.stage(cfg.state, {"content": base64.b64encode(page).decode(), "ref": "refs/heads/main",
                         "commit": commit, "path": "docs/console/page.html", "reviewed": True})
    PS.publish(cfg.state, commit)
    owner = SV.owner_server(console, SV.link_verifier(cfg), port)
    threading.Thread(target=owner.serve_forever, daemon=True).start()
    try:
        mine = DV.invite(None, "owner@example.com", cfg.state)[0]
        bob = DV.invite(None, "bob@example.com", cfg.state)[0]
        DV.redeem(None, bob, "Chrome on Android", cfg.state)
        url = origin + "/"
        ctx = browser.new_context(viewport={"width": 1680, "height": 1000}, color_scheme="dark", device_scale_factor=2)
        pg = ctx.new_page()
        for name, step in (
                ("feature-signed-out", lambda: (pg.goto(url), pg.wait_for_selector("text=Not signed in"))),
                ("feature-signin", lambda: (pg.goto(url + "signin?t=" + mine),
                                            pg.wait_for_selector("text=Sign this browser in as")))):
            try:
                step()
                pg.locator("main").screenshot(path=str(OUT / f"{name}.png"))
                print("wrote", name)
            except Exception as e:
                problems.append(f"{name}: {str(e).splitlines()[0]}")
        try:
            pg.click("button:has-text('Sign this browser in')")
            pg.wait_for_url(url)
            pg.wait_for_selector(".ck-panel[data-open='true']", timeout=15000)
            pg.evaluate("ConsoleKit.openTab('people')")
            pg.wait_for_selector(".ck-device-row")
            pg.wait_for_timeout(800)
            pg.locator(".ck-panel").screenshot(path=str(OUT / "feature-devices.png"))
            print("wrote feature-devices")
        except Exception as e:
            problems.append(f"feature-devices: {str(e).splitlines()[0]}")
        ctx.close()
    finally:
        owner.shutdown()
        owner.server_close()
        tmp.cleanup()


# -- animations ------------------------------------------------------------
def record_gifs(browser, url: str, problems: list[str]) -> None:
    """Short GIFs of the interactive features, captured step by step from the panel.

    The server refuses an owner POST from any Origin but its own https hostname (a real
    protection, kept). Only here, the recording rewrites the Origin header so the locks and
    requests in the animations are real round-trips to the server.
    """
    from io import BytesIO
    from PIL import Image

    def page_for():
        ctx = browser.new_context(viewport={"width": 1180, "height": 820}, color_scheme="dark",
                                  device_scale_factor=1,
                                  extra_http_headers={"Cf-Access-Jwt-Assertion": token()})
        pg = ctx.new_page()
        pg.route("**/api/**", lambda route: route.continue_(
            headers={**route.request.headers, "origin": f"https://{HOSTNAME}"}))
        pg.goto(url)
        pg.wait_for_selector(".ck-panel[data-open='true']", timeout=15000)
        pg.wait_for_timeout(1200)
        return pg

    def rec(name, steps, target=".ck-panel"):
        """`steps`: (action, hold_ms). A frame is taken after each action and shown for hold_ms."""
        try:
            pg = page_for()
            frames, holds = [], []
            for action, hold in steps:
                if action:
                    action(pg)
                shot_bytes = pg.screenshot() if target is None else pg.locator(target).first.screenshot()
                frames.append(Image.open(BytesIO(shot_bytes)).convert("RGB"))
                holds.append(hold)
            pg.context.close()
            base = frames[0].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
            pal = [f.quantize(palette=base, dither=Image.Dither.NONE) for f in frames]
            pal[0].save(OUT / f"{name}.gif", save_all=True, append_images=pal[1:], duration=holds,
                        loop=0, optimize=True, disposal=1)
            print("wrote", name + ".gif")
        except Exception as e:
            problems.append(f"{name}.gif: {str(e).splitlines()[0]}")

    def go(iid, wait=1300):
        return lambda pg: (pg.evaluate("id => { location.hash = '#item=' + id }", iid), pg.wait_for_timeout(wait))

    def click(text, wait=700, scope=".ck-panel"):
        return lambda pg: (pg.locator(f"{scope} button", has_text=text).first.click(), pg.wait_for_timeout(wait))

    def key(k, wait=600):
        return lambda pg: (pg.keyboard.press(k), pg.wait_for_timeout(wait))

    def typed(text, wait=250):
        return lambda pg: (pg.keyboard.type(text, delay=60), pg.wait_for_timeout(wait))

    # Answer a deliberation round from the keyboard, review, lock everything at once.
    rec("anim-round", [
        (go("OPS-3"), 900),
        (click("Answer this round", 900), 1100),
        (key("1", 1100), 1000),
        (key("1", 1100), 1000),
        (key("1", 900), 900),
        (click("Review all", 900), 1500),
        (click("Lock all", 1500), 2600),
    ])
    # Lock several answered questions on one item in one go.
    rec("anim-lock-all", [
        (go("SEC-2"), 1100),
        (click("Lock all", 800), 1800),
        (lambda pg: (pg.locator(".ck-panel button", has_text="Lock all 2 answers").last.click(),
                     pg.wait_for_timeout(1500)), 2600),
    ])
    # A ruling went stale: ask what changed.
    rec("anim-stale", [
        (go("OPS-2"), 1400),
        (click("What changed", 1400), 1200),
        (lambda pg: (pg.locator(".ck-why").first.evaluate(SHOW_WHOLE), pg.wait_for_timeout(500)), 3600),
    ])
    # Command palette: type, jump.
    rec("anim-palette", [
        (None, 600),
        (key("Control+k", 500), 700),
        (typed("ret"), 500),
        (typed("ry"), 1100),
        (key("Enter", 1300), 2200),
    ], target=None)
    # Tickets: close the blocker; the ticket it blocked moves from Blocked to Open.
    def close_schema(pg):
        card = pg.locator(".ck-ticket-col[data-status='open'] .ck-ticket", has_text="Ledger schema").first
        card.locator("button", has_text="Close").click()
        pg.wait_for_timeout(500)
        return card

    rec("anim-tickets", [
        (lambda pg: (pg.locator("#ck-tab-tickets").click(), pg.wait_for_timeout(900)), 1600),
        (lambda pg: (close_schema(pg), None), 1100),
        (lambda pg: (pg.locator(".ck-ticket-col[data-status='open'] .ck-ticket", has_text="Ledger schema")
                     .first.locator("button", has_text="Click again").click(), pg.wait_for_timeout(1500)), 2800),
    ])
    # Status flowchart: expand, zoom, fit.
    rec("anim-flowchart", [
        (go("OPS-3"), 700),
        (lambda pg: (pg.locator(".ck-panel summary", has_text="Status flowchart").first.click(),
                     pg.wait_for_timeout(3000)), 1500),
        (lambda pg: (pg.frame_locator(".ck-panel iframe").first.locator("#ck-zoom-in").click(),
                     pg.wait_for_timeout(500)), 900),
        (lambda pg: (pg.frame_locator(".ck-panel iframe").first.locator("#ck-zoom-in").click(),
                     pg.wait_for_timeout(500)), 900),
        (lambda pg: (pg.frame_locator(".ck-panel iframe").first.locator("#ck-zoom-reset").click(),
                     pg.wait_for_timeout(600)), 1800),
    ])


def shrink() -> None:
    """Palette the capability stills (flat UI colours survive 256 colours); about a third the bytes."""
    from PIL import Image
    for f in OUT.glob("feature-*.png"):
        Image.open(f).convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(f, optimize=True)


def main() -> int:
    demo = Demo()
    try:
        demo.seed()
        problems = capture(demo)
        shrink()
    finally:
        demo.close()
    for p in problems:
        print("could not capture", p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
