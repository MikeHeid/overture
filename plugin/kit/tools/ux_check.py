#!/usr/bin/env python3
"""Check a UX component the way the console will show it (console-ux skill, step 5).

    ux_check.py COMPONENT.html [--out DIR]

1. Runs it through the server's own sanitizer and names what would be stripped
   (elements, `style=""` attributes, scripts, event handlers), so nothing the
   owner sees differs from what you drew.
2. If Playwright is installed, renders the SANITIZED file inside `<iframe sandbox="">`
   under the server's own CSP for HTML visuals, with JavaScript OFF, at 375, 768 and
   1280 px in light and dark, and saves a screenshot of each to DIR.

Exit 0 when nothing is stripped, 1 when something would be (each named), 2 on a
usage problem. It reads only the file you name and writes only under DIR.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from overture.visuals import sanitize_html  # noqa: E402

WIDTHS = (375, 768, 1280)
MAX_BYTES = 256 * 1024


def what_is_stripped(src: str, clean: str) -> list[str]:
    """Plain-words list of what the sanitizer removed; a heuristic over tag and attribute names."""
    out = []
    if re.search(r"<script\b", src, re.I):
        out.append("<script> (scripts are removed while Scripts is off)")
    if re.search(r"\son[a-z]+\s*=", src, re.I):
        out.append("on* event attributes")
    if re.search(r"\sstyle\s*=", src, re.I):
        out.append('style="" attributes (put styles in the <style> block, on classes)')
    tags = lambda s: {t.lower() for t in re.findall(r"<([A-Za-z][A-Za-z0-9-]*)", s)}  # noqa: E731
    gone = sorted(tags(src) - tags(clean) - {"script"})
    if gone:
        out.append("elements: " + ", ".join(f"<{t}>" for t in gone))
    attrs = lambda s: {a.lower() for a in re.findall(r"\s([A-Za-z][A-Za-z0-9:-]*)=", s)}  # noqa: E731
    lost = sorted(a for a in attrs(src) - attrs(clean) if a != "style" and not a.startswith("on"))
    if lost:
        out.append("attributes: " + ", ".join(lost))
    return out


def render(clean: str, out: Path) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []
    from overture.server import VISUAL_HTML_CSP
    host = ('<!doctype html><body style="margin:0"><iframe sandbox="" src="http://ux.check/c" '
            'style="border:0;width:100vw;height:100vh"></iframe>')

    def handle(route):
        if route.request.url.endswith("/c"):
            route.fulfill(status=200, body=clean, headers={"Content-Type": "text/html; charset=utf-8",
                                                           "Content-Security-Policy": VISUAL_HTML_CSP})
        else:
            route.fulfill(status=200, body=host, headers={"Content-Type": "text/html"})

    shots = []
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for scheme in ("light", "dark"):
            for w in WIDTHS:
                ctx = browser.new_context(viewport={"width": w, "height": 900}, java_script_enabled=False,
                                          color_scheme=scheme)
                ctx.route("http://ux.check/**", handle)
                pg = ctx.new_page()
                pg.goto("http://ux.check/")
                pg.wait_for_timeout(300)
                path = out / f"{scheme}-{w}.png"
                pg.screenshot(path=str(path))
                shots.append(str(path))
                ctx.close()
        browser.close()
    return shots


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("component")
    ap.add_argument("--out", default="ux-check")
    a = ap.parse_args(argv)
    p = Path(a.component)
    if not p.is_file():
        print(f"ux_check: {p} is not a file", file=sys.stderr)
        return 2
    src = p.read_text(encoding="utf-8")
    problems = []
    if len(src.encode("utf-8")) > MAX_BYTES:
        problems.append(f"{len(src.encode('utf-8'))} bytes; a visual is at most {MAX_BYTES}")
    clean, _ = sanitize_html(src)
    problems += what_is_stripped(src, clean)
    for line in problems:
        print("ux_check: would strip or refuse:", line)
    shots = render(clean, Path(a.out))
    for s in shots:
        print("ux_check: wrote", s)
    if not shots:
        print("ux_check: Playwright is not installed, so nothing was rendered; check by eye in UX View")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
