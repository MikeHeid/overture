"""build_zip.py: the right files, a valid marketplace, the same bytes twice, and no secrets.

    python3 test_build.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import build_zip as B

# Skills the console's rounds lean on, shipped in the plugin so a fresh install has them.
SHIPPED_SKILLS = ("roar", "refine", "drill", "deliberate", "waypoint")


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)

    def built(self, deny=(), sub="out"):
        out, digest, _ = B.build(list(deny), check=False, out_dir=self.tmp / sub)
        return out, digest


class LayoutTests(Base):
    def test_the_zip_is_a_marketplace_holding_the_plugin_and_the_kit(self):
        out, _ = self.built()
        self.assertEqual(out.name, f"overture-{B.version()}.zip")
        names = set(zipfile.ZipFile(out).namelist())
        for must in ("overture/.claude-plugin/marketplace.json", "overture/INSTALL.md",
                     "overture/plugins/overture/.claude-plugin/plugin.json",
                     "overture/plugins/overture/hooks/hooks.json",
                     "overture/plugins/overture/hooks/session_start.py",
                     "overture/plugins/overture/skills/console-onboard/SKILL.md",
                     "overture/plugins/overture/skills/console-process/SKILL.md",
                     *(f"overture/plugins/overture/skills/{s}/SKILL.md" for s in SHIPPED_SKILLS),
                     "overture/plugins/overture/agents/security.md",
                     "overture/plugins/overture/kit/onboard.py",
                     "overture/plugins/overture/kit/agent.py",
                     "overture/plugins/overture/kit/server.py",
                     "overture/plugins/overture/kit/deploy/install.sh",
                     "overture/plugins/overture/kit/overture/console.js",
                     "overture/plugins/overture/kit/requirements.txt"):
            self.assertIn(must, names)
        for n in names:
            with self.subTest(entry=n):
                self.assertFalse(Path(n).name.startswith("test_"), n)
                self.assertNotIn("__pycache__", n)
                self.assertNotIn("/.git/", n)
                self.assertNotIn("/dist/", n)

    def test_the_protocol_ships_beside_the_plugin(self):
        # Catches (1.55): a zip without docs/spec, so a release's attestation would not cover the protocol it
        # implements, or one that ships it inside the plugin, where Claude Code would load it as plugin files.
        names = set(zipfile.ZipFile(self.built()[0]).namelist())
        for must in ("overture/spec/PROTOCOL.md", "overture/spec/overture-protocol-1.schema.json",
                     "overture/spec/vectors/records.json", "overture/spec/vectors/store.json"):
            self.assertIn(must, names)
        self.assertEqual([n for n in names if n.startswith("overture/plugins/") and "/spec/" in n], [])

    def test_no_area_note_ships_in_the_zip(self):
        # Catches (1.53.0): Overture's own area notes (CLAUDE.md, facts about this repository's code) shipped in
        # the plugin, where they would describe the kit's source to a user's sessions; the skip must hold for a
        # note at any depth, and keep a file that merely has CLAUDE.md in its name.
        for rel in ("kit/overture/CLAUDE.md", "hooks/CLAUDE.md", "skills/CLAUDE.md", "CLAUDE.md"):
            self.assertTrue(B.SKIP.search(rel), rel)
        self.assertFalse(B.SKIP.search("skills/NOT-CLAUDE.md.txt"))
        names = zipfile.ZipFile(self.built()[0]).namelist()
        self.assertEqual([n for n in names if Path(n).name == "CLAUDE.md"], [])

    def test_the_marketplace_points_at_the_plugin_at_the_same_version(self):
        z = zipfile.ZipFile(self.built()[0])
        market = json.loads(z.read("overture/.claude-plugin/marketplace.json"))
        plugin = json.loads(z.read("overture/plugins/overture/.claude-plugin/plugin.json"))
        self.assertEqual(market["name"], B.MARKET)
        [entry] = market["plugins"]
        self.assertEqual(entry["name"], plugin["name"])
        self.assertEqual(entry["source"], "./plugins/overture")
        self.assertEqual(entry["version"], plugin["version"])
        self.assertEqual(plugin["version"], B.version())

    def test_every_place_that_states_the_version_agrees(self):
        # 0.6.0: /health reports overture.__version__, and a vendoring project carries no
        # VERSION file, so the package must say the same as VERSION and both manifests.
        init = (B.ROOT / "plugin/kit/overture/__init__.py").read_text(encoding="utf-8")
        [pkg] = re.findall(r'^__version__ = "([^"]+)"', init, re.M)
        repo_market = json.loads((B.ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        plugin = json.loads((B.ROOT / "plugin/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual({pkg, plugin["version"], *(p["version"] for p in repo_market["plugins"])}, {B.version()})

    def test_scripts_are_executable_and_the_rest_is_not(self):
        z = zipfile.ZipFile(self.built()[0])
        mode = {i.filename: (i.external_attr >> 16) & 0o777 for i in z.infolist()}
        self.assertEqual(mode["overture/plugins/overture/kit/deploy/install.sh"], 0o755)
        self.assertEqual(mode["overture/plugins/overture/kit/onboard.py"], 0o755)
        self.assertEqual(mode["overture/INSTALL.md"], 0o644)

    def test_the_same_tree_gives_the_same_bytes(self):
        (_, a), (_, b) = self.built(sub="a"), self.built(sub="b")
        self.assertEqual(a, b)


class RefusalTests(Base):
    def test_a_denied_string_refuses_the_build_and_writes_no_zip(self):
        with self.assertRaisesRegex(B.BuildError, "holds a denied string"):
            self.built(deny=["CLOUDFLAREACCESS.com"])      # case-insensitive
        self.assertFalse((self.tmp / "out").exists())

    def test_a_version_mismatch_is_refused(self):
        with mock.patch.object(B, "version", return_value="9.9.9"):
            with self.assertRaisesRegex(B.BuildError, "plugin.json version"):
                self.built()

    def test_secret_shaped_content_and_names_are_refused(self):
        cases = {
            "a.txt": "-----BEGIN PRIVATE KEY-----\nMII...\n",
            "b.json": '{"AccountTag": "x", "TunnelSecret": "y"}',
            "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b.json": "{}",
            "cert.pem": "x",
            ".overture/console.env": "CONSOLE_NAME=x\n",
            "c.md": "token ghp_" + "a" * 36,
        }
        for rel, text in cases.items():
            with self.subTest(file=rel):
                top = self.tmp / rel.replace("/", "_") / "top"
                p = top / rel
                p.parent.mkdir(parents=True)
                p.write_text(text)
                with self.assertRaises(B.BuildError):
                    B.scan(top, [])

    def test_a_clean_tree_passes_the_scan(self):
        top = self.tmp / "clean"
        (top / "docs").mkdir(parents=True)
        (top / "docs/CLOUDFLARE.md").write_text("never open ~/.cloudflared/cert.pem or <id>.json")
        B.scan(top, ["example-deploy.net"])


class NeutralTests(unittest.TestCase):
    """0.8.2 (owner, 2026-09-30, "Scrub in 0.8.2 ★"): the public kit names no project that vendors it."""

    # Spelled in two halves, so this test's own source is not a match for the search it runs.
    CONSUMER = "gradi" + "ance"

    @unittest.skipUnless((B.ROOT / ".git").exists() and shutil.which("git"), "not a git checkout")
    def test_no_tracked_file_names_the_reference_consumer(self):
        # Catches: a comment, a test string or a function name that still names the one project the
        # kit was first built for. `git grep` exits 1 when nothing matches, 0 when something does.
        r = subprocess.run(["git", "-C", str(B.ROOT), "grep", "-n", "-i", self.CONSUMER], capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)


class ReleaseNotesGateTests(unittest.TestCase):
    """1.53 review C1: release.py runs `notes check` and refuses while it finds anything; no test reads this
    repository's own notes, so the suites stay green mid-work, in a zip or in a vendored copy."""

    GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
               "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True,
                              timeout=60, env={**os.environ, **self.GIT_ENV}).stdout

    @unittest.skipUnless(shutil.which("git"), "no git")
    def test_the_gate_names_a_stale_note_in_a_repository_and_passes_a_current_one(self):
        # Catches: a release gate that passes whatever the notes say (the check not run, or its exit ignored), or
        # one that refuses a repository whose notes are current.
        import release as REL
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.repo = Path(td.name)
        self.git("init", "-q", "-b", "main")
        (self.repo / "docs").mkdir()
        (self.repo / "docs/x.md").write_text("x\n")
        (self.repo / ".overture.json").write_text(json.dumps({"areas": ["docs"]}))
        self.git("add", "-A")
        self.git("commit", "-qm", "start")
        sha = self.git("rev-parse", "--short", "HEAD").strip()
        (self.repo / "docs/CLAUDE.md").write_text(f"<!-- area: docs · checked: {sha} -->\n- a fact\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "note")
        with mock.patch.dict(os.environ, self.GIT_ENV):
            self.assertIsNone(REL.notes_gate(self.repo))
            (self.repo / "docs/x.md").write_text("changed\n")
            self.git("commit", "-qam", "docs change")
            said = REL.notes_gate(self.repo)
        self.assertIsNotNone(said)
        self.assertTrue(any(line.startswith("stale: docs/CLAUDE.md") for line in said), said)

    @unittest.skipUnless((B.ROOT / ".overture.json").exists(), "no .overture.json (not a checkout)")
    def test_every_file_the_version_bump_writes_in_an_area_is_in_notes_ignore(self):
        # Catches: set_version writing a file inside a declared area that .overture.json "notes_ignore" does not
        # list (a new version file, or the list trimmed), so every release stales that area's note and the next
        # release is refused until someone re-stamps a note whose facts did not change; and a "notes_ignore"
        # entry notes.py refuses (a '.claude-plugin' segment), which would refuse every notes check and release.
        # The bump runs on a copy, never this tree.
        import sys
        import release as REL
        sys.path.insert(0, str(B.ROOT / "plugin" / "kit"))
        self.addCleanup(sys.path.remove, str(B.ROOT / "plugin" / "kit"))
        from overture import notes as NO
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        copy = Path(td.name)
        for rel in ("VERSION", "plugin/.claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                    "plugin/kit/overture/__init__.py", *REL.PIN_FILES):
            (copy / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(B.ROOT / rel, copy / rel)
        with mock.patch.object(REL, "ROOT", copy):
            written = REL.set_version("999.0.0")
        self.assertEqual(len(written), 6, written)
        # 1.65: the pins moved out of the docs area (mcp-and-ci.md shows @vX.Y.Z), so a bump stales no note
        # without growing notes_ignore; every `@vN.N.N` and the badge now say the new version.
        for rel in REL.PIN_FILES:
            text = (copy / rel).read_text(encoding="utf-8")
            self.assertEqual(set(re.findall(r"MikeHeid/overture@v(\d+\.\d+\.\d+)", text)) - {"999.0.0"}, set(), rel)
        self.assertIn("version-999.0.0-", (copy / "README.md").read_text(encoding="utf-8"))
        with mock.patch.object(REL, "ROOT", copy):      # a pre-release suffix is replaced whole, not appended to
            REL.set_version("999.1.0-rc1")
            REL.set_version("999.1.0")
        for rel in REL.PIN_FILES:
            self.assertNotIn("rc1", (copy / rel).read_text(encoding="utf-8"), rel)
        self.assertNotIn("@v1.", (B.ROOT / "docs/features/mcp-and-ci.md").read_text(encoding="utf-8"))
        declared = NO.areas(B.ROOT)
        ignore = NO.ignored(B.ROOT, declared)
        in_areas = sorted(f for f in written if any(f.startswith(a + "/") for a in declared))
        self.assertIn("plugin/kit/overture/__init__.py", in_areas)
        self.assertEqual([f for f in in_areas if f not in ignore], [])

    def test_a_release_is_refused_before_the_bump_while_the_gate_finds_anything(self):
        # Catches: release.py bumping the version (and listing the notes check as a mere next step) while the
        # area notes are stale, or not saying which note held it back.
        import contextlib
        import io
        import release as REL
        err = io.StringIO()
        with mock.patch.object(REL, "notes_gate", return_value=["stale: docs/CLAUDE.md (checked abc1234): ..."]), \
                mock.patch.object(REL, "set_version") as bump, contextlib.redirect_stderr(err):
            self.assertEqual(REL.main(["release.py", "9.9.9"]), 1)
        bump.assert_not_called()
        self.assertIn("stale: docs/CLAUDE.md", err.getvalue())
        with mock.patch.object(REL, "notes_gate", return_value=None), \
                mock.patch.object(REL, "set_version", return_value=[]) as bump, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(REL.main(["release.py", "9.9.9"]), 0)
        bump.assert_called_once_with("9.9.9")


def run_blocks(text: str) -> list[str]:
    """The `run:` scripts of a workflow file, one string each."""
    blocks, current, indent = [], None, 0
    for line in text.splitlines():
        stripped = line.lstrip()
        if current is not None:
            if stripped and len(line) - len(stripped) <= indent:
                blocks.append("\n".join(current))
                current = None
            else:
                current.append(line)
                continue
        if stripped.startswith("run:"):
            indent = len(line) - len(stripped)
            current = [stripped[4:]]
    if current is not None:
        blocks.append("\n".join(current))
    return blocks


class PublishTests(unittest.TestCase):
    """1.65 (OPEN-DECISIONS E2, CP2, CP3): `release.py publish` runs the release steps in order and refuses at the
    first that fails; the release phase runs only for the merge commit of a merged pull request on main."""

    SHA = "a" * 40
    DIGEST = "d" * 64

    def setUp(self):
        import release as REL
        self.REL = REL
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        (self.root / "VERSION").write_text("1.65.0\n")
        (self.root / "CHANGELOG.md").write_text("# Changelog\n\n## CI and publish (1.65.0)\n\n- x\n\n"
                                                "## Rulings on Linear (1.64.0)\n")
        self.cfg = self.root / "cfg"
        (self.cfg / "overture").mkdir(parents=True)
        (self.cfg / "overture" / "deny.txt").write_text("# mine\nconsole.example.com\n")
        self.env = {"XDG_CONFIG_HOME": str(self.cfg)}
        self.calls: list[tuple] = []
        self.order: list[str] = []
        self.pull = {"number": 201, "merged_at": "2026-11-07T00:00:00Z", "merge_commit_sha": self.SHA,
                     "base": {"ref": "main"}}
        # Every git or gh call the two phases make has an answer here; a call with none FAILS the test (clearer
        # 1.65, M3), so a new or renamed step cannot pass unnoticed.
        self.answers = {("git", "rev-parse"): self.SHA + "\n", ("git", "status"): "", ("git", "fetch"): "",
                        ("git", "merge-base"): "", ("git", "ls-remote"): "", ("git", "add"): "",
                        ("git", "commit"): "", ("git", "push"): "",
                        ("gh", "repo", "view"): '{"nameWithOwner": "o/r"}',
                        ("gh", "api"): json.dumps([self.pull]), ("gh", "release", "create"): "https://example.com/rel\n",
                        ("gh", "run", "list"): json.dumps([{"databaseId": 7, "status": "completed",
                                                            "conclusion": "success", "headBranch": "v1.65.0"}]),
                        ("gh", "attestation", "verify"): json.dumps([{"digest": {"sha256": self.DIGEST}}])}
        p = mock.patch.object(REL, "run", side_effect=self.fake_run)
        p.start()
        self.addCleanup(p.stop)
        self.built = mock.patch.object(B, "build", return_value=(self.root / "overture-1.65.0.zip", self.DIGEST,
                                                                "validate: ok"))
        self.built.start()
        self.addCleanup(self.built.stop)
        p = mock.patch.object(REL, "ATTEST_POLL", 0)
        p.start()
        self.addCleanup(p.stop)

    def fake_run(self, *cmd, cwd=None, timeout=600):
        self.calls.append(cmd)
        if cmd[:2] == ("git", "commit"):
            self.order.append("commit")
        hits = sorted((p for p in self.answers if cmd[:len(p)] == p), key=len)   # the most specific answer wins
        if not hits:
            raise AssertionError(f"release.py made a call the test has no answer for: {cmd}")
        ans = self.answers[hits[-1]]
        if isinstance(ans, Exception):
            raise ans
        return ans

    def names(self):
        return [" ".join(c[:3]) for c in self.calls]

    def test_release_runs_zip_release_attest_verify_in_order_for_a_merged_pull_request(self):
        # Catches (CP2): the zip built or the release created before the merge was checked, the verify skipped,
        # or the release notes not naming the pull request the owner approved.
        said = self.REL.release(None, self.root, self.env)
        self.assertTrue(B.build.called)
        n = self.names()
        self.assertLess(n.index(f"gh api repos/o/r/commits/{self.SHA}/pulls"), n.index("gh release create"))
        self.assertLess(n.index("git fetch -q"), n.index("git merge-base --is-ancestor"))   # a fresh origin/main
        self.assertLess(n.index("gh release create"), n.index("gh run list"))
        self.assertLess(n.index("gh run list"), n.index("gh attestation verify"))
        create = next(c for c in self.calls if c[:3] == ("gh", "release", "create"))
        self.assertEqual(create[3:6], ("v1.65.0", str(self.root / "overture-1.65.0.zip"), "--target"))
        self.assertEqual(create[6], self.SHA)
        self.assertIn("#201", create[create.index("--notes") + 1])
        self.assertIn("v1.65.0 — CI and publish", create)
        self.assertIn("verified", said)
        self.assertIn("released https://example.com/rel", said)

    def refused(self, saying: str, *, built: bool = False):
        with self.assertRaises(self.REL.ReleaseError) as cm:
            self.REL.release(None, self.root, self.env)
        self.assertIn(saying, str(cm.exception))
        self.assertEqual(B.build.called, built)
        self.assertNotIn("gh release create", self.names())
        return str(cm.exception)

    def test_release_refuses_a_commit_that_is_not_a_merged_pull_request_before_building(self):
        # Catches (CP2): a release cut from a commit pushed to main without a pull request, which nobody approved;
        # a pull request that merely contains the commit (another merge_commit_sha); two merged pull requests
        # claiming the same commit; a pull request merged into another branch; a target that is not what is
        # checked out; a commit not on origin/main. Each stops before the zip is built (clearer 1.65, H1, M2).
        REL = self.REL
        for bad, why in (([{**self.pull, "merged_at": None}], "not the merge commit"),
                         ([{**self.pull, "merge_commit_sha": "b" * 40}], "not the merge commit"),
                         ([self.pull, {**self.pull, "number": 202}], "not the merge commit"),
                         ([{**self.pull, "base": {"ref": "dev"}}], "not the merge commit"),
                         ([], "not the merge commit")):
            self.answers[("gh", "api")] = json.dumps(bad)
            self.refused(why)
        self.answers[("gh", "api")] = json.dumps([self.pull])
        self.answers[("git", "merge-base")] = REL.ReleaseError("git merge-base exited 1")
        self.refused("not on origin/main")
        del self.answers[("git", "merge-base")]
        self.answers[("git", "merge-base")] = ""
        self.answers[("git", "rev-parse", "--verify", "--end-of-options", "other")] = "c" * 40 + "\n"
        with self.assertRaises(REL.ReleaseError) as cm:
            REL.release("other", self.root, self.env)
        self.assertIn("check out the commit to release", str(cm.exception))
        self.answers[("git", "status")] = " M release.py\n"
        self.calls.clear()
        self.refused("uncommitted")
        self.assertNotIn("gh api", " ".join(self.names()))      # the dirty tree is refused before any gh call

    def test_release_verifies_this_zips_digest_with_the_tag_and_the_signer_pinned(self):
        # Catches: a verify that answers for some other artifact, or one run without the source ref, the signer
        # workflow or --deny-self-hosted-runners, so any attestation on the repository would do (clearer 1.65, H1).
        self.answers[("gh", "attestation", "verify")] = json.dumps([{"digest": {"sha256": "e" * 64}}])
        with self.assertRaises(self.REL.ReleaseError) as cm:
            self.REL.release(None, self.root, self.env)
        self.assertIn("not for this zip's digest", str(cm.exception))
        verify = next(c for c in self.calls if c[:3] == ("gh", "attestation", "verify"))
        for needed in ("--source-ref", "refs/tags/v1.65.0", "--signer-workflow",
                       "o/r/.github/workflows/attest-release.yml", "--deny-self-hosted-runners", "--format", "json"):
            self.assertIn(needed, verify)

    def test_release_refuses_without_the_owners_deny_list_and_names_where_it_goes(self):
        # Catches (CP3): a zip published unscanned because the deny list was not given, the 1.62 refusal bypassed.
        (self.cfg / "overture" / "deny.txt").unlink()
        with self.assertRaises(self.REL.ReleaseError) as cm:
            self.REL.release(None, self.root, self.env)
        self.assertIn(str(self.cfg / "overture" / "deny.txt"), str(cm.exception))
        self.assertIn("CP3", str(cm.exception))
        self.assertFalse(B.build.called)
        (self.cfg / "overture" / "deny.txt").write_text("# only a comment\n")
        with self.assertRaises(self.REL.ReleaseError):
            self.REL.release(None, self.root, self.env)
        self.assertFalse(B.build.called)

    def test_release_refuses_a_tag_already_released_and_a_failed_attestation(self):
        # Catches: a second `gh release create` for a version already out, and a verify run against a release whose
        # attest workflow failed (the message must say the release is published but not attested).
        self.answers[("git", "ls-remote")] = f"{self.SHA}\trefs/tags/v1.65.0\n"
        with self.assertRaises(self.REL.ReleaseError) as cm:
            self.REL.release(None, self.root, self.env)
        self.assertIn("already released", str(cm.exception))
        self.assertFalse(B.build.called)
        self.answers[("git", "ls-remote")] = ""
        self.answers[("gh", "run", "list")] = json.dumps([{"databaseId": 8, "status": "completed",
                                                           "conclusion": "failure", "headBranch": "v1.65.0"}])
        with self.assertRaises(self.REL.ReleaseError) as cm:
            self.REL.release(None, self.root, self.env)
        self.assertIn("published but not attested", str(cm.exception))
        self.assertNotIn("gh attestation verify", self.names())

    def test_prepare_refuses_on_main_a_dirty_tree_and_a_missing_changelog_section_before_bumping(self):
        # Catches: version files committed to main, a release commit carrying unrelated edits, and a release with
        # no notes; each must stop before set_version touches anything.
        REL = self.REL
        with mock.patch.object(REL, "notes_gate", return_value=None), mock.patch.object(REL, "set_version") as bump:
            self.answers[("git", "rev-parse", "--abbrev-ref")] = "main\n"
            with self.assertRaises(REL.ReleaseError) as cm:
                REL.prepare("1.65.0", None, self.root)
            self.assertIn("never committed to main", str(cm.exception))
            self.answers[("git", "rev-parse", "--abbrev-ref")] = "feat/x\n"
            self.answers[("git", "status")] = " M release.py\n"
            with self.assertRaises(REL.ReleaseError) as cm:
                REL.prepare("1.65.0", None, self.root)
            self.assertIn("uncommitted", str(cm.exception))
            self.answers[("git", "status")] = ""
            with self.assertRaises(REL.ReleaseError) as cm:
                REL.prepare("1.66.0", None, self.root)
            self.assertIn("CHANGELOG.md has no section", str(cm.exception))
            bump.assert_not_called()
        with mock.patch.object(REL, "notes_gate", return_value=["stale: docs/CLAUDE.md"]), \
                mock.patch.object(REL, "set_version") as bump:
            with self.assertRaises(REL.ReleaseError) as cm:
                REL.prepare("1.65.0", None, self.root)
            self.assertIn("stale: docs/CLAUDE.md", str(cm.exception))
            bump.assert_not_called()

    def test_prepare_bumps_tests_commits_pushes_and_opens_the_pull_request_in_order(self):
        # Catches: a commit made before test_build ran, a push with nothing committed, a second pull request opened
        # beside an existing one, or a title without the CHANGELOG's name for the release.
        REL = self.REL
        body = self.root / "pr.md"
        body.write_text("the body\n")
        self.answers[("git", "rev-parse", "--abbrev-ref")] = "feat/x\n"
        self.answers[("gh", "pr", "list")] = "[]"
        self.answers[("gh", "pr", "create")] = "https://example.com/pr/9\n"
        order = self.order
        with mock.patch.object(REL, "notes_gate", return_value=None), \
                mock.patch.object(REL, "set_version", side_effect=lambda v: order.append("bump") or ["VERSION"]), \
                mock.patch.object(REL.subprocess, "run", side_effect=lambda *a, **k: order.append("test_build") or
                                  mock.Mock(returncode=0, stdout="OK", stderr="")):
            said = REL.prepare("1.65.0", body, self.root)
        n = self.names()
        self.assertEqual(order, ["bump", "test_build", "commit"])     # the commit holds only a bump that tested green
        self.assertLess(n.index("git commit -q"), n.index("git push -q"))
        self.assertLess(n.index("git push -q"), n.index("gh pr create"))
        create = next(c for c in self.calls if c[:3] == ("gh", "pr", "create"))
        self.assertIn("release: 1.65.0 — CI and publish", create)
        self.assertIn("pull request opened: https://example.com/pr/9", said)
        self.calls.clear()
        self.answers[("gh", "pr", "list")] = '[{"url": "https://example.com/pr/9"}]'
        with mock.patch.object(REL, "notes_gate", return_value=None), \
                mock.patch.object(REL, "set_version", return_value=[]), \
                mock.patch.object(REL.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")):
            said = REL.prepare("1.65.0", body, self.root)
        self.assertNotIn("gh pr create", self.names())
        self.assertNotIn("git commit -q", self.names())           # nothing changed, nothing to commit
        self.assertIn("already open", said)

    def test_the_changelog_heading_is_read_for_the_version_alone(self):
        # Catches: "1.65.0" matching "1.65.01", or the heading taken from the wrong release.
        self.assertEqual(self.REL.changelog_heading("1.65.0", self.root), "CI and publish")
        self.assertEqual(self.REL.changelog_heading("1.64.0", self.root), "Rulings on Linear")
        self.assertIsNone(self.REL.changelog_heading("1.6.0", self.root))


class CiWorkflowTests(unittest.TestCase):
    """1.65 (E2, CP1): ci.yml runs every suite at the repository root on each pull request, one job each, with
    read-only access and nothing from the pull request reaching a shell unquoted."""

    PATH = B.ROOT / ".github" / "workflows" / "ci.yml"

    def setUp(self):
        if not self.PATH.exists():
            self.skipTest("no .github/workflows (not a checkout)")
        self.text = self.PATH.read_text(encoding="utf-8")

    def test_every_suite_at_the_root_is_in_the_matrix_once(self):
        # Catches: a new test_*.py nobody added to CI, or a suite listed twice.
        suites = sorted(p.stem for p in B.ROOT.glob("test_*.py"))
        listed = re.findall(r"^\s+- (test_\w+)\s*$", self.text, re.M)
        self.assertEqual(sorted(listed), suites)
        self.assertEqual(len(listed), len(set(listed)))

    def test_it_runs_on_pull_requests_with_read_access_only_and_pinned_actions(self):
        # Catches: a workflow that could sign or write, that runs on a release or a tag, or an action pinned to a tag
        # whoever controls can move.
        self.assertRegex(self.text, r"(?m)^on:\n  pull_request:")
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read\n")
        self.assertNotIn("write", self.text)
        self.assertNotRegex(self.text, r"(?m)^\s+release:|^\s+push:|^\s+tags:")
        for u in re.findall(r"^\s*-?\s*uses:\s*(\S+)", self.text, re.M):
            self.assertRegex(u, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$", u)
        self.assertIn("persist-credentials: false", self.text)
        self.assertIn("timeout-minutes:", self.text)

    def test_nothing_from_the_event_is_expanded_inside_a_shell_step(self):
        # Catches: `${{ matrix.suite }}` or any event field pasted into `run:`; values reach the shell through env.
        blocks = run_blocks(self.text)
        self.assertGreaterEqual(len(blocks), 2, blocks)
        for block in blocks:
            self.assertNotIn("${{", block)
        self.assertIn("SUITE: ${{ matrix.suite }}", self.text)


class AttestWorkflowTests(unittest.TestCase):
    """2026-10-21 (owner, "Actions build + attestation"): attest-release.yml rebuilds a release's zip from its tag,
    refuses a zip that differs from the uploaded one, and attests it with the workflow's identity."""

    PATH = B.ROOT / ".github" / "workflows" / "attest-release.yml"

    def setUp(self):
        if not self.PATH.exists():
            self.skipTest("no .github/workflows (not a checkout)")
        self.text = self.PATH.read_text(encoding="utf-8")

    def run_blocks(self) -> list[str]:
        return run_blocks(self.text)

    def test_every_action_is_pinned_to_a_full_commit_sha(self):
        # Catches: `uses: actions/checkout@v7` or a short sha, where whoever controls the tag controls what signs.
        uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", self.text, re.M)
        self.assertGreaterEqual(len(uses), 2, uses)
        for u in uses:
            self.assertRegex(u, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$", u)

    def test_no_expression_is_expanded_inside_a_shell_step(self):
        # Catches: `${{ ... }}` pasted into a `run:` script, where a crafted tag or input becomes shell code;
        # values reach the shell only through `env:`.
        blocks = self.run_blocks()
        self.assertGreaterEqual(len(blocks), 3, blocks)
        for block in blocks:
            self.assertNotIn("${{", block)

    def test_it_starts_from_nothing_and_asks_only_what_attesting_needs(self):
        # Catches: a workflow that inherits the repository's default token scopes, or loses the scopes Sigstore
        # signing needs.
        self.assertRegex(self.text, r"(?m)^permissions:\s*\{\}\s*$")
        for scope in ("contents: write", "id-token: write", "attestations: write"):
            self.assertIn(scope, self.text)

    def test_it_rebuilds_from_the_tag_and_refuses_a_different_zip(self):
        # Catches: attesting whatever was uploaded without rebuilding it, building something other than the tag,
        # or building on a runner whose zlib can give other bytes.
        self.assertIn("types: [published]", self.text)
        self.assertIn("ref: refs/tags/${{ env.TAG }}", self.text)
        self.assertIn("python3 build_zip.py", self.text)
        self.assertIn("runs-on: ubuntu-24.04", self.job("build"))
        self.assertLess(self.text.index("Check the tag"), self.text.index("actions/checkout@"))
        # The mismatch branch must stop the job, and the attest step must come after the match.
        match = next(b for b in self.run_blocks() if 'cmp -s "$BUILT"' in b)
        start = match.index('cmp -s "$BUILT"')
        mismatch = match[start:start + re.search(r"\n\s*fi\b", match[start:]).start()]
        self.assertIn("exit 1", mismatch)
        self.assertLess(self.text.index('cmp -s "$BUILT"'), self.text.index("actions/attest-build-provenance@"))

    def job(self, name: str) -> str:
        start = self.text.index(f"\n  {name}:\n")
        nxt = re.search(r"\n  [a-z][\w-]*:\n", self.text[start + 1:])
        return self.text[start:start + 1 + nxt.start()] if nxt else self.text[start:]

    def test_the_tag_s_code_runs_without_write_scopes_or_a_signing_identity(self):
        # Catches: build_zip.py from the tag running in a job that could mint the OIDC token or write the release
        # (id-token is job-wide, so a step-level token move is not enough); the token left in .git/config; the
        # attesting job checking out and running the tag's code; a trigger that runs on others' code.
        build, attest = self.job("build"), self.job("attest")
        self.assertIn("python3 build_zip.py", build)
        self.assertRegex(build, r"permissions:\n\s+contents: read\n")
        for scope in ("write", "id-token"):
            self.assertNotIn(scope, build)
        self.assertIn("persist-credentials: false", build)
        self.assertNotIn("actions/checkout@", attest)
        self.assertNotIn("build_zip", attest)
        self.assertIn("needs: build", attest)
        self.assertEqual(self.text.count("GH_TOKEN:"), 1)
        self.assertIn("GH_TOKEN:", attest)
        self.assertNotRegex(self.text, r"pull_request|workflow_run|issue_comment|repository_dispatch")

    def test_a_manual_run_is_accepted_only_from_main(self):
        # Catches: a workflow_dispatch from any branch, whose attestation would carry that branch's identity.
        self.assertIn("if: github.event_name == 'release' || github.ref == 'refs/heads/main'", self.job("build"))


class UnitTemplateTests(unittest.TestCase):
    """The rendered unit passes the server only flags it defines, and not `--page` (Q28) or `--adapter` (Q24): never read."""

    KIT = B.ROOT / "plugin" / "kit"

    def test_the_unit_passes_only_flags_the_server_defines_and_not_the_page(self):
        # Catches: a dead `--page` left in the template (every start then logs "--page ... is not read"), and a
        # flag removed from the server's parser but still in the template, which would stop the unit starting.
        unit = (self.KIT / "deploy" / "console.service.in").read_text()
        start = unit.split("ExecStart=", 1)[1].split("\nRestart", 1)[0]
        flags = re.findall(r"(?<!\S)(--[a-z][a-z-]*)", start)
        self.assertIn("--root", flags)   # the parse found the ExecStart at all
        self.assertNotIn("--page", flags)
        self.assertNotIn("--adapter", flags)   # IGNORED since Q24: the steward pushes items, nothing runs it
        parser = (self.KIT / "overture" / "server.py").read_text()
        for f in flags:
            self.assertIn(f'ap.add_argument("{f}"', parser, f)

    def test_the_link_unit_passes_only_flags_the_server_defines_and_none_of_access(self):
        # Catches (1.47.0, L7): the sign-in-link unit carrying an Access flag (empty in a link console.env), a
        # flag the parser lacks, no --auth link at all (it would start behind Cloudflare), and install.sh's
        # --listen/--origin (rendered into @LINK_ARGS@) not defined by the server.
        unit = (self.KIT / "deploy" / "console-link.service.in").read_text()
        start = unit.split("ExecStart=", 1)[1].split("\nRestart", 1)[0]
        flags = re.findall(r"(?<!\S)(--[a-z][a-z-]*)", start)
        self.assertIn("--auth", flags)
        self.assertIn("--auth link", start)
        self.assertIn("@LINK_ARGS@", start)
        for f in ("--team-domain", "--aud", "--hostname", "--page", "--adapter"):
            self.assertNotIn(f, flags)
        parser = (self.KIT / "overture" / "server.py").read_text()
        install = (self.KIT / "deploy" / "install.sh").read_text()
        for f in flags + re.findall(r'LINK_ARGS="[^"]*?(--[a-z-]+)', install):
            self.assertIn(f'ap.add_argument("{f}"', parser, f)

    def test_every_console_unit_stops_retrying_a_server_that_fails_at_once(self):
        # Catches (1.47, C2): a per-project unit (link or Cloudflare) with no StartLimit lines, so a server that
        # fails at once (--listen on an eth0 address) restarts every 5 s forever (systemd's default, 5 within
        # 10 s, never catches a RestartSec=5 loop); and the lines put under [Service], where systemd ignores them.
        for name in ("console-link", "console", "overture-console"):
            unit = (self.KIT / "deploy" / f"{name}.service.in").read_text()
            head = unit.split("[Unit]", 1)[1].split("[Service]", 1)[0]
            with self.subTest(unit=name):
                self.assertIn("\nStartLimitIntervalSec=120\n", head)
                self.assertIn("\nStartLimitBurst=5\n", head)
                self.assertIn("\nRestartSec=5\n", unit)   # 5 starts at once land well inside 120 s

    def test_the_tunnel_is_ordered_after_the_console_but_not_bound_to_it(self):
        # Catches (1.62, audit A4): `Requires=` or `BindsTo=` on the console (stopping it stopped the tunnel,
        # which then stayed down), or `Wants=` on the per-project console, which one-server mode stops and a
        # tunnel start would bring back.
        unit = (self.KIT / "deploy" / "console-tunnel.service.in").read_text()
        head = unit.split("[Unit]", 1)[1].split("[Service]", 1)[0]
        lines = [ln for ln in head.splitlines() if not ln.startswith("#")]
        self.assertIn("After=network-online.target @NAME@-console.service overture-console.service", lines)
        for ln in lines:
            if ln.startswith(("Requires=", "BindsTo=", "Requisite=", "PartOf=", "Wants=")):
                self.assertNotIn("console", ln, ln)


class DenyFileTests(unittest.TestCase):
    """1.62 (audit A4): build_zip says when nothing was scanned, and refuses a deny list that lists nothing."""

    def run_main(self, *args):
        import contextlib
        import io
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()), mock.patch.object(B, "build", return_value=(Path(td), "d", "n")) as b:
            rc = B.main([*args, "--no-validate", "--out-dir", td])
        return rc, err.getvalue(), b.called

    def test_no_deny_file_builds_with_a_warning(self):
        # Catches: a zip built silently with no deny list, the default a hurried release falls into.
        rc, err, built = self.run_main()
        self.assertEqual((rc, built), (0, True))
        self.assertIn("WARNING: no --deny-file", err)

    def test_an_empty_or_missing_deny_file_is_refused(self):
        # Catches: a deny file of only comments or blank lines (scans for nothing), and a typo'd path crashing.
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "deny.txt"
            empty.write_text("# my values\n\n")
            rc, err, built = self.run_main("--deny-file", str(empty))
            self.assertEqual((rc, built), (1, False))
            self.assertIn("lists no string; nothing was built", err)
            bad = Path(td) / "latin1.txt"
            bad.write_bytes(b"caf\xe9\n")
            rc, err, built = self.run_main("--deny-file", str(bad))
            self.assertEqual((rc, built), (1, False))
            self.assertIn("nothing was built", err)
            rc, err, built = self.run_main("--deny-file", str(Path(td) / "nope.txt"))
            self.assertEqual((rc, built), (1, False))
            self.assertIn("nothing was built", err)


@unittest.skipUnless(shutil.which("claude"), "`claude` is not on PATH")
class ValidateTests(Base):
    def test_claude_validates_the_marketplace_and_the_plugin_strictly(self):
        _, _, note = B.build([], check=True, out_dir=self.tmp / "v")
        self.assertIn("pass `claude plugin validate --strict`", note)


@unittest.skipUnless(shutil.which("claude"), "`claude` is not on PATH")
class InstalledPluginTests(Base):
    """Install for real, into a throwaway Claude config, by BOTH routes, and look inside.

    The repository's own marketplace once pointed at a plugin folder without the
    kit: installing from GitHub gave skills that stopped at "the plugin is
    incomplete", while the zip (a different marketplace) was fine. Only an
    install shows what a user gets.
    """

    def install(self, marketplace_dir: Path, plugin_id: str) -> Path:
        cfg = self.tmp / f"cfg-{plugin_id.split('@')[1]}"
        env = {**os.environ, "CLAUDE_CONFIG_DIR": str(cfg)}
        for argv in (["plugin", "marketplace", "add", str(marketplace_dir)], ["plugin", "install", plugin_id]):
            r = subprocess.run(["claude", *argv], env=env, capture_output=True, text=True, timeout=120,
                               stdin=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [skill] = cfg.glob("plugins/cache/*/overture/*/skills/console-onboard/SKILL.md")
        return skill.parent

    def assert_complete(self, skill_dir: Path):
        kit = (skill_dir / "../../kit").resolve()     # where SKILL.md looks
        for rel in ("onboard.py", "agent.py", "server.py", "deploy/install.sh", "docs/CLOUDFLARE.md",
                    "adapter_template.py", "demo/index.html", "overture/console.js", "requirements.txt"):
            self.assertTrue((kit / rel).is_file(), f"installed plugin lacks kit/{rel}")
        # Every KIT/<path> a skill tells a session to read must be in the installed kit.
        for skill in (skill_dir / "..").resolve().glob("*/SKILL.md"):
            # Anywhere: inline code, indented or fenced blocks, quoted arguments.
            for rel in re.findall(r"KIT/([A-Za-z0-9_./-]*[A-Za-z0-9_])", skill.read_text(encoding="utf-8")):
                self.assertTrue((kit / rel).exists(), f"{skill.parent.name} cites KIT/{rel}, not in the installed kit")

    def test_an_install_from_the_repository_carries_the_kit(self):
        self.assert_complete(self.install(B.ROOT, "overture@overture"))

    def test_an_install_from_the_release_zip_carries_the_kit(self):
        out, _ = self.built()
        with zipfile.ZipFile(out) as z:
            z.extractall(self.tmp / "unzipped")
        self.assert_complete(self.install(self.tmp / "unzipped/overture", "overture@overture-local"))

    def test_the_default_next_step_skills_resolve_from_the_installed_plugin_and_never_the_repository(self):
        # Catches: a fresh install where Refine and Drill are refused because the skills the
        # onboarding default names were never shipped; a resolver that finds `overture:refine`
        # anywhere but the installed plugin; and one that lets a repository's own
        # .claude/skills/refine stand in, under either name, for what the user installed.
        import sys
        sys.path.insert(0, str(B.ROOT / "plugin/kit"))
        from overture import projectcfg as PC
        import onboard as O
        skill_dir = self.install(B.ROOT, "overture@overture")
        cfg = self.tmp / "cfg-overture"
        installed = (skill_dir / "..").resolve()
        for name in SHIPPED_SKILLS:
            with self.subTest(skill=name):
                text = (installed / name / "SKILL.md").read_text(encoding="utf-8")
                self.assertTrue(text.startswith(f"---\nname: {name}\n"), name)
        proj = self.tmp / "proj"
        (proj / ".claude/skills/refine").mkdir(parents=True)
        (proj / ".claude/skills/refine/SKILL.md").write_text("repo-supplied: do something else\n")
        (proj / ".overture.json").write_text(json.dumps({"next_step": O.DEFAULT_NEXT_STEP}))
        self.assertEqual(PC.load(proj).next_step, {"refine": "overture:refine", "drill": "overture:drill"})
        for kind, name in O.DEFAULT_NEXT_STEP.items():
            with self.subTest(kind=kind):
                got = PC.resolve_skill(name, proj, cfg)
                self.assertEqual(got, (installed / kind / "SKILL.md").resolve())
                self.assertNotIn(proj.resolve(), got.parents)
        # The plain name the repository's own folder carries is still not an installed user skill.
        with self.assertRaisesRegex(PC.ConfigError, "not an installed user skill"):
            PC.resolve_skill("refine", proj, cfg)
        # And the CLI a fork session runs says the same, with the real install.
        env = {**os.environ, "CLAUDE_CONFIG_DIR": str(cfg)}
        agent = [sys.executable, str(B.ROOT / "plugin/kit/agent.py"), "--state", str(self.tmp / "st"), "next-step"]
        ok = subprocess.run([*agent, "refine", "--project", str(proj)], capture_output=True, text=True, env=env,
                            timeout=60)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(json.loads(ok.stdout)["skill_md"], str((installed / "refine/SKILL.md").resolve()))
        self.assertNotIn("repo-supplied", ok.stdout + ok.stderr)
        (proj / ".overture.json").write_text(json.dumps({"next_step": {"refine": "refine"}}))
        bad = subprocess.run([*agent, "refine", "--project", str(proj)], capture_output=True, text=True, env=env,
                             timeout=60)
        self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
        self.assertIn("not an installed user skill", bad.stderr)
        self.assertNotIn("repo-supplied", bad.stdout + bad.stderr)


if __name__ == "__main__":
    unittest.main()
