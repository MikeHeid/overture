"""Components (1.32, UX-VIEW.md "Saving"): land an owner's ux-save as `components/<item>.md` in a worktree.

`agent.py ux-export --project WORKTREE --save MESSAGE_ID` asks the server for the saved visual (it writes
nothing) and calls `write` here, in the AGENT's own worktree, never the server's checkout. The steward then
opens the pull request; this module only writes files.

    components/<item>.md          front matter, the doc, and the component HTML in a fenced block
    components/<item>.css         the component's <style> blocks, when it has any
    components/.history/<item>-<sha8>.md|.css   the previous version, named by its own content hash

Running it twice with the same save changes nothing (the backup name is the old content's hash, not a
time). At most HISTORY_KEEP backups are kept per item; older ones are removed in the same change.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

DIR = "components"            # D5 (owner): a fixed folder at the repository's top
HISTORY = ".history"
HISTORY_KEEP = 10
ITEM_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*\Z")
_STYLE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.S | re.I)


class ComponentError(ValueError):
    """A refusal, named; nothing was written."""


def _yaml_str(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def render(item: str, export: dict) -> tuple[str, str | None]:
    """(markdown, css or None) for one ux-export answer from the server."""
    vis = export["visual"]
    save = export["save"]
    content = vis["content"]
    source = export.get("source") if export.get("scripts") else None
    if source:     # the owner switched scripts on for this version: the component is its scripted source
        content = source
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    front = ["---", f"item: {_yaml_str(item)}", f"visual: {vis['id']}", f"save: {save['id']}",
             f"saved_by: {save['by']}", f"saved_at: {_yaml_str(save.get('ts', ''))}", f"sha256: {sha}"]
    if source:
        front.append("scripts: true")
    if export.get("design_url"):
        front += ["design:", f"  url: {_yaml_str(export['design_url'])}"]
    front.append("---")
    fence = "```"
    while fence in content:
        fence += "`"
    body = [f"# {vis.get('title') or item}", "", (vis.get("doc") or "").strip(), "",
            f"{fence}html", content.rstrip("\n"), fence, ""]
    css_parts = [m.strip() for m in _STYLE.findall(content) if m.strip()]
    css = ("/* Generated from components/" + item + ".md; edit the component, not this file. */\n\n"
           + "\n\n".join(css_parts) + "\n") if css_parts else None
    return "\n".join(front) + "\n\n" + "\n".join(body), css


def _safe_dir(top: Path, rel: str) -> Path:
    """`top/rel`, created if missing, refused if it (or any part) is a symlink or leaves `top`."""
    p = top
    for part in Path(rel).parts:
        p = p / part
        if p.is_symlink():
            raise ComponentError(f"{p.relative_to(top)} is a symlink; refused, nothing written")
        if p.exists() and not p.is_dir():
            raise ComponentError(f"{p.relative_to(top)} exists and is not a folder")
        p.mkdir(exist_ok=True)
    if top.resolve() not in p.resolve().parents:
        raise ComponentError(f"{rel} resolves outside the worktree")
    return p


def _read(p: Path) -> str | None:
    if p.is_symlink():
        raise ComponentError(f"{p.name} is a symlink; refused, nothing written")
    return p.read_text(encoding="utf-8") if p.exists() else None


def write(top: Path, item: str, export: dict) -> dict:
    """Write the component for `item` under `top/components`. Returns what was written, moved and pruned."""
    if not ITEM_FILE.match(item):
        raise ComponentError(f"item {item!r} cannot be a file name")
    md, css = render(item, export)
    comp = _safe_dir(top, DIR)
    md_path, css_path = comp / f"{item}.md", comp / f"{item}.css"
    old_md, old_css = _read(md_path), _read(css_path)
    if old_md == md and old_css == css:
        return {"written": [], "backed_up": [], "pruned": [], "unchanged": True}
    out = {"written": [], "backed_up": [], "pruned": [], "unchanged": False}
    if old_md is not None or old_css is not None:
        hist = _safe_dir(top, f"{DIR}/{HISTORY}")
        tag = hashlib.sha256(((old_md or "") + "\0" + (old_css or "")).encode("utf-8")).hexdigest()[:8]
        for old, ext in ((old_md, ".md"), (old_css, ".css")):
            if old is None:
                continue
            dest = hist / f"{item}-{tag}{ext}"
            if not dest.exists():
                dest.write_text(old, encoding="utf-8")
                out["backed_up"].append(str(dest.relative_to(top)))
        # Keep the newest HISTORY_KEEP versions of this item (a version is its .md, with its .css beside it).
        versions = sorted((p for p in hist.glob(f"{item}-*.md") if re.fullmatch(re.escape(item) + r"-[0-9a-f]{8}\.md", p.name)),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        for p in versions[HISTORY_KEEP:]:
            for q in (p, p.with_suffix(".css")):
                if q.exists() and not q.is_symlink():
                    q.unlink()
                    out["pruned"].append(str(q.relative_to(top)))
    md_path.write_text(md, encoding="utf-8")
    out["written"].append(str(md_path.relative_to(top)))
    if css is not None:
        css_path.write_text(css, encoding="utf-8")
        out["written"].append(str(css_path.relative_to(top)))
    elif old_css is not None:
        os.unlink(css_path)     # the new component carries no styles; the old ones were backed up above
        out["written"].append(f"{css_path.relative_to(top)} (removed)")
    return out
