#!/usr/bin/env python3
"""Bump the kit's version, and publish a release in order.

    python3 release.py X.Y.Z                              bump only, as before
    python3 release.py publish X.Y.Z [--pr-body FILE]     prepare: gate, bump, test, commit, push, pull request
    python3 release.py publish --release [--target SHA]   after the merge: zip, release, attest, verify

The bump writes the new version to:
  VERSION
  plugin/.claude-plugin/plugin.json          (top-level `version`)
  plugin/kit/overture/__init__.py            (`__version__`, which /health and the footer report)
  .claude-plugin/marketplace.json            (plugins[0].version; what Claude Code reads from the GitHub route)
  README.md, action.yml                      (the version badge and the `uses: MikeHeid/overture@vX.Y.Z` pins, 1.65)

1.53 review C1: first it runs `agent.py notes check` on this checkout and
refuses the release while it finds anything (a stale, undeclared or
malformed area note, or a refusal such as a shallow clone), naming each. This
is the release gate for the area notes; no unit test reads this repository's
own notes, so a suite stays green mid-work, in a zip or in a vendored copy.
Every file the bump writes inside a declared area is listed in `.overture.json`
"notes_ignore", so the bump alone makes no note stale and the next release is
not held back by it (test_build.py asserts the list covers them). The pins in
README.md and action.yml are outside every area; docs/features/mcp-and-ci.md
shows `@vX.Y.Z` and points at the README for the number.

`publish` (1.65, OPEN-DECISIONS E2, CP1-CP3) runs the steps the earlier
versions of this script only printed, in order, and stops at the first that
refuses:

  prepare   the notes gate; a CHANGELOG section for the version; the bump;
            test_build; one commit on the lane's branch (never main); push;
            the pull request, when a body is given.
  release   only for the merge commit of a merged pull request on main: nothing
            merges without the owner's approve, so the merge is the approve
            (CP2). Then the zip, scanned against ~/.config/overture/deny.txt
            (CP3; refused without it), `gh release create --target`, the
            attest-release.yml run, and `gh attestation verify`.

Added in 0.9.2 after /health kept showing 0.8.18 across the 0.9.0 and 0.9.1
releases: `__version__` and the repo-marketplace manifest had drifted from
VERSION. `test_build.py::test_every_place_that_states_the_version_agrees`
asserts they stay equal; this script makes it easy to keep them equal.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

VERSION_RE = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:[-+].+)?$")
PIN_FILES = ("README.md", "action.yml")                  # outside every area note (see the docstring)
BADGE = re.compile(r"(img\.shields\.io/badge/version-)\d+\.\d+\.\d+(-)")
USES = re.compile(r"(MikeHeid/overture@v)\d+\.\d+\.\d+")
ATTEST_WAIT = 15 * 60       # seconds to wait for attest-release.yml after the release is published
ATTEST_POLL = 20


class ReleaseError(Exception):
    """A step that refuses; its message says which and why."""


def set_version(version: str) -> list[str]:
    """Update every file that carries the kit's version. Returns a list of files changed."""
    if not VERSION_RE.match(version):
        raise ValueError(f"{version!r} is not a semver string (X.Y.Z[-tag])")

    changed: list[str] = []

    def write(path: Path, data: str) -> None:
        if path.read_text(encoding="utf-8") != data:
            path.write_text(data, encoding="utf-8")
            changed.append(str(path.relative_to(ROOT).as_posix()))

    # VERSION — trailing newline matches the existing convention.
    write(ROOT / "VERSION", version + "\n")

    # plugin.json — plain top-level "version"; keep key order and indentation.
    plugin_json = ROOT / "plugin" / ".claude-plugin" / "plugin.json"
    pj = json.loads(plugin_json.read_text(encoding="utf-8"))
    pj["version"] = version
    write(plugin_json, json.dumps(pj, indent=2) + "\n")

    # marketplace.json — plugins[0].version is what Claude Code reads for the GitHub route.
    market_json = ROOT / ".claude-plugin" / "marketplace.json"
    mj = json.loads(market_json.read_text(encoding="utf-8"))
    if not isinstance(mj.get("plugins"), list) or not mj["plugins"]:
        raise ValueError(f"{market_json}: plugins[] is empty; cannot bump version")
    mj["plugins"][0]["version"] = version
    write(market_json, json.dumps(mj, indent=2) + "\n")

    # overture/__init__.py — /health and the footer read this.
    init_py = ROOT / "plugin" / "kit" / "overture" / "__init__.py"
    text = init_py.read_text(encoding="utf-8")
    new = re.sub(r'(__version__\s*=\s*)"[^"]*"', lambda m: f'{m.group(1)}"{version}"', text, count=1)
    if '__version__' not in new or f'"{version}"' not in new:
        raise ValueError(f"{init_py}: __version__ assignment not found; expected `__version__ = \"...\"`")
    write(init_py, new)

    # The pins (1.65): the README's badge and the `uses:` lines a project copies. Both files sit outside every
    # area note, so this stales none; a pin the files do not carry is an error, not a silent skip.
    for name in PIN_FILES:
        p = ROOT / name
        text = p.read_text(encoding="utf-8")
        new, n_uses = USES.subn(lambda m: f"{m.group(1)}{version}", text)
        new, n_badge = BADGE.subn(lambda m: f"{m.group(1)}{version}{m.group(2)}", new)
        if n_uses == 0 and n_badge == 0:
            raise ValueError(f"{p}: no version pin found (MikeHeid/overture@vX.Y.Z or the version badge)")
        write(p, new)

    return changed


def notes_gate(root: Path = ROOT) -> list[str] | None:
    """None when `notes check` says every area note at `root` is current, else what it said (C1's gate)."""
    try:
        r = subprocess.run([sys.executable, str(ROOT / "plugin" / "kit" / "agent.py"), "notes", "check",
                            "--root", str(root)], capture_output=True, text=True, timeout=600,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [f"notes check could not run: {e}"]
    if r.returncode == 0:
        return None
    return (r.stdout + r.stderr).strip().splitlines() or [f"notes check exited {r.returncode}"]


# -- publish ---------------------------------------------------------------------------------------------------

def run(*cmd: str, cwd: Path | None = None, timeout: float = 600) -> str:
    """One git or gh call; its stdout. A failure is a ReleaseError naming the command and what it said."""
    try:
        r = subprocess.run(list(cmd), cwd=str(cwd or ROOT), capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except OSError as e:
        raise ReleaseError(f"{cmd[0]}: {getattr(e, 'strerror', None) or e}") from None
    except subprocess.TimeoutExpired:
        raise ReleaseError(f"{' '.join(cmd)}: no answer in {timeout:.0f}s") from None
    if r.returncode != 0:
        raise ReleaseError(f"{' '.join(cmd)} exited {r.returncode}:\n{(r.stderr or r.stdout).strip()}")
    return r.stdout


def changelog_heading(version: str, root: Path = ROOT) -> str | None:
    """The CHANGELOG section title for `version` ("Rulings on Linear" for "## Rulings on Linear (1.64.0)"), or None."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## (.+?) \({re.escape(version)}\)\s*$", text, re.M)
    return m.group(1).strip() if m else None


def deny_path(env=os.environ) -> Path:
    """CP3: the deny list lives in the owner's config folder, never in the repository."""
    return Path(env.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "overture" / "deny.txt"


def gate_or_raise(root: Path) -> None:
    said = notes_gate(root)
    if said is not None:
        raise ReleaseError("the area notes are not current; re-read each named area, fix its note, commit, then "
                           "`python3 plugin/kit/agent.py notes stamp AREA` and commit that:\n  " + "\n  ".join(said))


def prepare(version: str, pr_body: Path | None, root: Path = ROOT) -> str:
    """The lane's release commit, pushed, and its pull request when a body is given. Returns what was done."""
    if not VERSION_RE.match(version):
        raise ReleaseError(f"{version!r} is not a semver string (X.Y.Z[-tag])")
    gate_or_raise(root)
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=root).strip()
    if branch in ("main", "HEAD"):
        raise ReleaseError(f"on {branch}: a release is prepared on the lane's branch and merged by pull request, "
                           "never committed to main")
    if run("git", "status", "--porcelain", cwd=root).strip():
        raise ReleaseError("the working tree has uncommitted changes; commit or stash them first, so the release "
                           "commit holds only the version files")
    heading = changelog_heading(version, root)
    if heading is None:
        raise ReleaseError(f"CHANGELOG.md has no section '## <name> ({version})'; write the release notes first")
    if pr_body is not None and not pr_body.is_file():
        raise ReleaseError(f"--pr-body {pr_body}: not a file")
    changed = set_version(version)
    lines = [f"bumped to {version}: " + (", ".join(changed) if changed else "nothing changed")]
    r = subprocess.run([sys.executable, "-B", str(root / "test_build.py")], cwd=str(root), capture_output=True,
                       text=True, timeout=900, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise ReleaseError("test_build failed after the bump; the version files are changed but not committed "
                           "(`git checkout -- .` undoes them):\n" + (r.stderr or r.stdout)[-2000:])
    lines.append("test_build: OK")
    gate_or_raise(root)      # the bump writes outside every area, so this holds unless a pin moved into one
    if changed:
        run("git", "add", "-A", cwd=root)
        run("git", "commit", "-q", "-m", f"release: {version} version files", cwd=root)
        lines.append(f"committed on {branch}")
    run("git", "push", "-q", "-u", "origin", branch, cwd=root)
    lines.append(f"pushed {branch}")
    existing = json.loads(run("gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url", cwd=root)
                          or "[]")
    if existing:
        lines.append(f"pull request already open: {existing[0]['url']}")
    elif pr_body is not None:
        url = run("gh", "pr", "create", "--base", "main", "--head", branch, "--title",
                  f"release: {version} — {heading}", "--body-file", str(pr_body), cwd=root).strip()
        lines.append(f"pull request opened: {url}")
    else:
        lines.append("no pull request opened (give --pr-body FILE, or `gh pr create` yourself)")
    lines.append("next: the owner's approve, the merge, then `python3 release.py publish --release` on main")
    return "\n".join(lines)


def merged_pull(sha: str, nwo: str, root: Path = ROOT) -> int:
    """The number of the merged pull request whose merge commit is `sha`, or a ReleaseError (CP2)."""
    raw = run("gh", "api", f"repos/{nwo}/commits/{sha}/pulls", cwd=root)
    try:
        pulls = json.loads(raw or "[]")
    except ValueError:
        raise ReleaseError("gh api: the pull request list was not JSON") from None
    hits = [p for p in pulls if isinstance(p, dict) and p.get("merged_at") and p.get("merge_commit_sha") == sha]
    if len(hits) != 1:
        raise ReleaseError(f"{sha[:12]} is not the merge commit of one merged pull request on main. Nothing "
                           "merges without the owner's approve, so nothing is released from a commit that was "
                           "not merged that way")
    return int(hits[0]["number"])


def wait_attested(tag: str, root: Path = ROOT, deadline: float = ATTEST_WAIT, poll: float = ATTEST_POLL) -> int:
    """The attest-release.yml run for `tag`, once it has completed successfully; its id."""
    until = time.monotonic() + deadline
    while True:
        raw = run("gh", "run", "list", "--workflow", "attest-release.yml", "--limit", "10", "--json",
                  "databaseId,status,conclusion,headBranch", cwd=root)
        runs = [r for r in json.loads(raw or "[]") if r.get("headBranch") == tag]
        done = [r for r in runs if r.get("status") == "completed"]
        if done:
            if done[0].get("conclusion") != "success":
                raise ReleaseError(f"attest-release.yml run {done[0]['databaseId']} for {tag} ended "
                                   f"{done[0].get('conclusion')}; the release is published but not attested")
            return int(done[0]["databaseId"])
        if time.monotonic() > until:
            raise ReleaseError(f"attest-release.yml has not completed for {tag} in {deadline:.0f}s; check "
                               "`gh run list --workflow attest-release.yml` and verify by hand")
        time.sleep(poll)


def release(target: str | None, root: Path = ROOT, env=os.environ) -> str:
    """After the merge: the zip, the GitHub release, the attestation, the verification. Returns what was done."""
    import build_zip as B
    sha = run("git", "rev-parse", target or "HEAD", cwd=root).strip()
    head = run("git", "rev-parse", "HEAD", cwd=root).strip()
    if sha != head:
        raise ReleaseError(f"the checkout is at {head[:12]}, not {sha[:12]}: check out the commit to release, so "
                           "the zip is built from it")
    if run("git", "status", "--porcelain", cwd=root).strip():
        raise ReleaseError("the working tree has uncommitted changes; the zip must be built from the merge commit "
                           "alone")
    run("git", "fetch", "-q", "origin", "main", cwd=root)
    try:
        run("git", "merge-base", "--is-ancestor", sha, "origin/main", cwd=root)
    except ReleaseError:
        raise ReleaseError(f"{sha[:12]} is not on origin/main") from None
    nwo = json.loads(run("gh", "repo", "view", "--json", "nameWithOwner", cwd=root))["nameWithOwner"]
    pr = merged_pull(sha, nwo, root)
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    tag = f"v{version}"
    if run("git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", cwd=root).strip():
        raise ReleaseError(f"{tag} is already released")
    heading = changelog_heading(version, root) or version
    deny_file = deny_path(env)
    try:
        deny = B.read_deny_file(deny_file)
    except B.BuildError as e:
        raise ReleaseError(f"{e}\n  CP3: put your deployment's own values (hostnames, team domain, home path, "
                           f"names), one per line, in {deny_file}") from None
    try:
        out, digest, note = B.build(deny, check=True)
    except B.BuildError as e:
        raise ReleaseError(str(e)) from None
    lines = [note, f"built {out} sha256 {digest}"]
    notes = (f"{heading}. See CHANGELOG.md, \"{heading} ({version})\". Merged as #{pr} with the owner's approve; "
             f"the zip is rebuilt from this tag and attested by attest-release.yml.")
    url = run("gh", "release", "create", tag, str(out), "--target", sha, "--title", f"{tag} — {heading}",
              "--notes", notes, cwd=root).strip()
    lines.append(f"released {url}")
    run_id = wait_attested(tag, root)
    lines.append(f"attested by run {run_id}")
    raw = run("gh", "attestation", "verify", str(out), "--repo", nwo, "--signer-workflow",
              f"{nwo}/.github/workflows/attest-release.yml", "--source-ref", f"refs/tags/{tag}",
              "--deny-self-hosted-runners", "--format", "json", cwd=root)
    if digest not in raw:
        raise ReleaseError("gh attestation verify answered, but not for this zip's digest:\n" + raw[:500])
    lines.append(f"verified: the attestation names sha256 {digest[:12]}… from refs/tags/{tag}")
    return "\n".join(lines)


# -- entry -------------------------------------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "publish":
        return _publish(argv[2:])
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    said = notes_gate()
    if said is not None:
        print("release: refused: the area notes are not current; re-read each named area, fix its note,",
              file=sys.stderr)
        print("  commit, then `python3 plugin/kit/agent.py notes stamp AREA` and commit that:", file=sys.stderr)
        for line in said:
            print(f"  {line}", file=sys.stderr)
        return 1
    try:
        changed = set_version(argv[1])
    except (ValueError, OSError) as e:
        print(f"release: {e}", file=sys.stderr)
        return 1
    if not changed:
        print(f"release: already at {argv[1]}; nothing changed.")
        return 0
    print(f"release: bumped to {argv[1]}; files updated:")
    for p in changed:
        print(f"  {p}")
    print()
    print("Next: write the CHANGELOG section, then `python3 release.py publish " + argv[1] + "` does the rest in")
    print("order (test_build, the commit, the push, the pull request), and after the owner's approve and the")
    print("merge, `python3 release.py publish --release` builds, releases, and verifies the attestation.")
    return 0


def _publish(args: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="release.py publish", description="the release steps, in order")
    ap.add_argument("version", nargs="?", help="prepare this version on the lane's branch")
    ap.add_argument("--pr-body", type=Path, help="with a version: open the pull request with this body")
    ap.add_argument("--release", action="store_true", help="after the merge, on main: zip, release, attest, verify")
    ap.add_argument("--target", help="with --release: the merge commit (default HEAD)")
    a = ap.parse_args(args)
    if a.release == bool(a.version):
        ap.error("give a version to prepare, or --release after the merge, not both")
    try:
        said = release(a.target) if a.release else prepare(a.version, a.pr_body)
    except ReleaseError as e:
        print(f"release: refused: {e}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as e:
        print(f"release: {e}", file=sys.stderr)
        return 1
    print(said)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
