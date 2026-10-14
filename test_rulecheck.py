#!/usr/bin/env python3
"""The CI ruling check (1.36.0): which locked rulings a change breaks, from the committed files alone.

Each test builds a real git repository with a cited source file and a ruling
exported the way `fold.py export` writes it, commits that as the base, then
makes the change a pull request would and runs `rulecheck.py` as CI does.

    python3 test_rulecheck.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_kit import ITEMS, KIT, answer, lock, question  # test_kit also isolates the user's registry
from overture import fold as F  # noqa: E402
from overture import rulecheck as RC  # noqa: E402
from overture.store import Store  # noqa: E402

SCRIPT = KIT / "rulecheck.py"
CITED = "def charge(cents):\n    return round_half_even(cents)\n"
EXCERPT = {"kind": "excerpt", "path": "src/pay.py", "text": "return round_half_even(cents)"}
RULING = "LANE.1__Q1.json"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


class Repo(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name) / "proj"
        (self.root / "src").mkdir(parents=True)
        (self.root / "src/pay.py").write_text(CITED)
        (self.root / "README").write_text("unrelated\n")
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        self.tick = 0
        self.store_path = Path(self._td.name) / "store.jsonl"
        self.store = Store(self.store_path, known_items=ITEMS, clock=self.clock)
        self.store.append(question(valid_if=[EXCERPT], source="src/pay.py:2"))
        self.a1 = self.store.append(answer())
        self.store.append(lock(self.a1))
        self.export()
        self.base = self.commit("base: a ruling on how charges round")

    def tearDown(self):
        self._td.cleanup()

    def clock(self):
        self.tick += 1
        return f"2026-10-13T00:00:{self.tick:02d}Z"

    def export(self):
        F.write_export(F.export(self.store), self.root / ".overture/locked")

    def commit(self, msg: str) -> str:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", msg)
        return git(self.root, "rev-parse", "HEAD").strip()

    def check(self, *args: str) -> tuple[int, str, str]:
        r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def report(self, *args: str) -> tuple[int, dict]:
        rc, out, err = self.check(*args, "--format", "json")
        self.assertEqual(err, "")
        return rc, json.loads(out)

    def break_code(self):
        (self.root / "src/pay.py").write_text("def charge(cents):\n    return int(cents)\n")

    def ruling(self) -> Path:
        return self.root / ".overture/locked" / RULING


class Standalone(Repo):
    def test_an_untouched_ruling_holds(self):
        # Catches: a check that fails every ruling, so CI is always red and gets switched off.
        rc, rep = self.report()
        self.assertEqual(rc, 0)
        self.assertEqual([j["qid"] for j in rep["holds"]], ["LANE.1/Q1"])

    def test_changing_the_cited_text_breaks_the_ruling_and_says_why(self):
        # Catches: a check that reads the files but never evaluates an excerpt against the code.
        self.break_code()
        rc, out, err = self.check()
        self.assertEqual((rc, err), (1, ""))
        self.assertIn("BROKEN LANE.1/Q1", out)
        self.assertIn("no longer in src/pay.py", out)

    def test_moving_the_cited_text_keeps_the_ruling(self):
        # Catches: a check keyed to line numbers, which fails every PR that adds a line above the cited one.
        (self.root / "src/pay.py").write_text("import x\n\n" + CITED)
        self.assertEqual(self.report()[0], 0)

    def test_no_server_and_no_store_are_needed(self):
        # Catches: a "standalone" check that still opens the console's socket or store (CI has neither).
        self.store_path.unlink()
        self.assertEqual(self.check()[0], 0)

    def test_the_locked_folder_comes_from_overture_json(self):
        # Catches: a check hard-wired to .overture/locked, which silently checks nothing in a project
        # whose `fold.locked` names another folder, and passes.
        os.rename(self.root / ".overture/locked", self.root / "rulings")
        (self.root / ".overture.json").write_text(json.dumps({"fold": {"locked": "rulings"}}))
        self.break_code()
        self.assertEqual(self.check()[0], 1)

    def test_a_settled_ruling_is_not_checked(self):
        # Catches: a check that fails a ruling the owner already withdrew, which no PR can ever clear.
        e = json.loads(self.ruling().read_text())
        e["outcome"] = {"kind": "withdrawn", "by": "owner", "at": "2026-10-13T01:00:00Z",
                        "record": "a" * 24, "reason": "rounding moved to the ledger"}
        self.ruling().write_text(json.dumps(e))
        self.break_code()
        rc, rep = self.report()
        self.assertEqual((rc, rep["settled"]), (0, [{"qid": "LANE.1/Q1", "outcome": "withdrawn"}]))

    def test_a_forged_ruling_file_stops_the_run(self):
        # Catches: a check that trusts a file fold would refuse (here a pick the owner never made),
        # so a hand-edited ruling decides what CI passes. Exit 2, not 0 or 1, and the file is named.
        e = json.loads(self.ruling().read_text())
        e["locked"]["picked_labels"] = ["Option A"]
        self.ruling().write_text(json.dumps(e))
        rc, out, err = self.check()
        self.assertEqual((rc, out), (2, ""))
        self.assertIn(f"{RULING}: picked_labels does not match", err)

    def test_a_symlinked_ruling_file_is_refused(self):
        # Catches: a check that follows a symlink out of the checkout and reads whatever it points at.
        os.symlink("/etc/hostname", self.root / ".overture/locked/X__Q1.json")
        rc, _, err = self.check()
        self.assertEqual(rc, 2)
        self.assertIn("never a symlink", err)

    def test_paths_stay_inside_the_project(self):
        # Catches: a --locked or --adapter outside the checkout; the adapter is imported, so it is code.
        for flag in ("--locked", "--adapter"):
            rc, _, err = self.check(flag, "../elsewhere")
            self.assertEqual(rc, 2, flag)
            self.assertIn("inside the project", err)

    def test_an_item_status_is_unchecked_without_the_register_and_checked_with_it(self):
        # Catches: an item_status read as holding when nothing could check it (a quiet pass), and an
        # adapter whose register is never consulted.
        e = json.loads(self.ruling().read_text())
        e["valid_if"] = [EXCERPT, {"kind": "item_status", "item": "LANE.1.a", "status": "proposed"}]
        self.ruling().write_text(json.dumps(e))
        rc, rep = self.report()
        self.assertEqual((rc, [j["qid"] for j in rep["unchecked"]]), (0, ["LANE.1/Q1"]))
        (self.root / "adapter.py").write_text(
            "def items():\n    return {'LANE': {'status': 'open'}, 'LANE.1': {'status': 'open'},\n"
            "            'LANE.1.a': {'status': 'done'}}\n"
            "def record(e, d):\n    return []\n"
            "def seed_questions():\n    return []\n")
        rc, out, _ = self.check("--adapter", "adapter.py")
        self.assertEqual(rc, 1)
        self.assertIn("Item LANE.1.a was expected to be proposed; it is now done", out)


class PullRequest(Repo):
    def test_a_pr_cannot_clear_its_failure_by_rewriting_the_ruling(self):
        # Catches: checking the rulings as the PR leaves them. Here the PR changes the code AND edits
        # the ruling's anchors to match (same lock, no owner involved), and must still fail.
        self.break_code()
        e = json.loads(self.ruling().read_text())
        e["valid_if"] = [{"kind": "excerpt", "path": "src/pay.py", "text": "return int(cents)"}]
        self.ruling().write_text(json.dumps(e))
        self.commit("pr")
        self.assertEqual(self.check()[0], 0)   # the PR's own view: clean
        rc, rep = self.report("--base", self.base)
        self.assertEqual(rc, 1)
        self.assertEqual([j["qid"] for j in rep["broken"]], ["LANE.1/Q1"])
        self.assertEqual(rep["files"]["edited"], [RULING])

    def test_a_pr_cannot_clear_its_failure_by_deleting_the_ruling(self):
        # Catches: iterating the PR's ruling files, so a deleted ruling is simply never checked.
        self.break_code()
        self.ruling().unlink()
        self.commit("pr")
        rc, rep = self.report("--base", self.base)
        self.assertEqual((rc, rep["files"]["removed"]), (1, [RULING]))

    def test_an_owner_relock_in_the_pr_passes_and_is_named_for_the_reviewer(self):
        # Catches: a check that blocks the legitimate flow (code change plus the owner's re-lock,
        # exported in the same PR), and one that passes it without saying a ruling was re-made.
        self.break_code()
        a2 = self.store.append(answer(picks=("a",), supersedes=self.a1["id"], reason="int is fine now"))
        self.store.append(lock(a2, anchors=[{"kind": "excerpt", "path": "src/pay.py", "text": "return int(cents)"}]))
        self.export()
        self.commit("pr")
        rc, rep = self.report("--base", self.base)
        self.assertEqual(rc, 0)
        self.assertEqual([(j["qid"], j["by"]) for j in rep["reruled"]], [("LANE.1/Q1", "lock")])

    def test_a_relock_that_does_not_hold_still_fails(self):
        # Catches: treating any new lock id as a re-ruling, so a stale re-export clears a real break.
        a2 = self.store.append(answer(picks=("a",), supersedes=self.a1["id"], reason="again"))
        self.store.append(lock(a2))
        self.export()
        self.break_code()
        self.commit("pr")
        self.assertEqual(self.report("--base", self.base)[0], 1)

    def test_a_new_ruling_the_pr_adds_must_hold_too(self):
        # Catches: checking only the base's rulings, so a ruling exported already stale slips in.
        self.store.append(question(qid="LANE.1/Q2", source="README:1",
                                   valid_if=[{"kind": "excerpt", "path": "README", "text": "text that is not there"}]))
        self.store.append(lock(self.store.append(answer(qid="LANE.1/Q2"))))
        self.export()
        self.commit("pr")
        rc, rep = self.report("--base", self.base)
        self.assertEqual((rc, [j["qid"] for j in rep["broken"]], rep["files"]["added"]),
                         (1, ["LANE.1/Q2"], ["LANE.1__Q2.json"]))

    def test_a_touched_file_that_still_holds_is_listed(self):
        # Catches: a report that is silent about a PR editing a cited file, where the reviewer should look.
        (self.root / "src/pay.py").write_text(CITED + "# a note\n")
        self.commit("pr")
        rc, rep = self.report("--base", self.base)
        self.assertEqual((rc, [(j["qid"], j["files"]) for j in rep["touched"]]), (0, [("LANE.1/Q1", ["src/pay.py"])]))

    def test_a_pr_cannot_point_the_check_at_an_empty_folder(self):
        # Catches: reading `.overture.json` from the PR (1.36.0 review, HIGH). The PR breaks the code
        # and sets fold.locked to a folder with nothing in it; the base's config still decides.
        self.break_code()
        (self.root / ".overture.json").write_text(json.dumps({"fold": {"locked": "nowhere"}}))
        self.commit("pr")
        rc, rep = self.report("--base", self.base)
        self.assertEqual((rc, rep["locked"]), (1, ".overture/locked"))

    def test_no_rulings_found_is_said_aloud(self):
        # Catches: a wrong folder (an explicit --locked here) read as "all 0 rulings hold" with nothing
        # to tell it from a real pass. It is not notable: a project with no rulings yet would get a
        # comment on every pull request (1.36.0 review round 2).
        rc, out, _ = self.check("--base", self.base, "--locked", "elsewhere", "--format", "markdown")
        self.assertEqual(rc, 0)
        self.assertNotIn(RC.NOTABLE, out)
        self.assertIn("No ruling files were found in elsewhere", out)

    def test_an_outcome_added_in_the_pr_is_reruled_and_notable(self):
        # Catches: a settle-in-the-PR that passes silently; the cheapest re-ruling must reach the reviewer.
        self.break_code()
        e = json.loads(self.ruling().read_text())
        e["outcome"] = {"kind": "withdrawn", "by": "owner", "at": "2026-10-13T01:00:00Z",
                        "record": "b" * 24, "reason": "moved"}
        self.ruling().write_text(json.dumps(e))
        self.commit("pr")
        rc, rep = self.report("--base", self.base)
        self.assertEqual((rc, [j["by"] for j in rep["reruled"]], rep["notable"]), (0, ["outcome"], True))

    def test_an_edited_ruling_file_is_notable_even_when_all_holds(self):
        # Catches: a PR that quietly rewrites a ruling (here its conditions, to text that holds) with
        # no comment, since nothing broke; an edit to a ruling is for the reviewer to see.
        e = json.loads(self.ruling().read_text())
        e["valid_if"] = [{"kind": "excerpt", "path": "src/pay.py", "text": "def charge(cents):"}]
        self.ruling().write_text(json.dumps(e))
        self.commit("pr")
        rc, rep = self.report("--base", self.base)
        self.assertEqual((rc, rep["files"]["edited"], rep["notable"]), (0, [RULING], True))

    def test_strict_fails_when_no_ruling_files_were_found(self):
        # Catches: --strict passing a run that checked nothing (a wrong folder), the same "could not be
        # checked" it exists to fail (1.37.0 review). Text and json say it too.
        rc, out, _ = self.check("--base", self.base, "--locked", "elsewhere", "--strict")
        self.assertEqual(rc, 1)
        self.assertIn("No ruling files were found, which --strict fails.", out)
        rc, rep = self.report("--base", self.base, "--locked", "elsewhere", "--strict")
        # Notable too: a strict failure reaches the pull request, not only the job summary.
        self.assertEqual((rc, rep["exit"], rep["strict"], rep["notable"]), (1, 1, True, True))

    def test_a_clean_pr_is_not_notable(self):
        # Catches: "notable" set on every run, so the Action comments on every clean pull request.
        (self.root / "README").write_text("still unrelated\n")
        self.commit("pr")
        self.assertFalse(self.report("--base", self.base)[1]["notable"])

    def test_a_root_below_the_top_of_the_work_tree_is_refused_with_base(self):
        # Catches: ls-tree, REF:path and diff disagreeing about paths below the top, where cited files
        # silently stop matching what the change touched.
        r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root / "src"), "--base", self.base],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not the top of its git work tree", r.stderr)

    def test_an_unknown_or_option_shaped_base_is_refused(self):
        # Catches: a base passed to git as an option (`--output=...`), and a missing base read as
        # "no rulings", which would pass every PR on a shallow clone.
        for bad in ("--output=/tmp/x", "nope", "a..b"):
            rc, _, err = self.check(f"--base={bad}")
            self.assertEqual(rc, 2, bad)
            self.assertIn("--base", err)


class Markdown(Repo):
    def test_the_comment_names_the_ruling_and_is_inert(self):
        # Catches: ruling text printed raw into a PR comment, where @someone pings a person and
        # <img> or a link renders. The comment also starts with the marker the Action updates by.
        e = json.loads(self.ruling().read_text())
        e["question"] = "Ask @octocat <img src=x> [here](http://evil) or https://evil.example and www.evil.example"
        self.ruling().write_text(json.dumps(e))
        self.break_code()
        rc, out, _ = self.check("--format", "markdown")
        self.assertEqual(rc, 1)
        self.assertTrue(out.startswith(RC.MARKER + "\n"))
        self.assertIn("1 of 1 ruling(s) broken", out)
        for raw in ("@octocat", "<img", "[here](", "://", "www."):   # the last two: GitHub autolinks bare URLs
            self.assertNotIn(raw, out)
        self.assertIn("```diff", out)

    def test_a_backtick_run_in_a_diff_cannot_close_the_fence(self):
        # Catches: a fixed ``` fence that a cited line containing ``` ends early, spilling markup.
        fence = RC._fence("- a ``` b\n+ c")
        self.assertTrue(fence.startswith("````diff\n") and fence.endswith("\n````"))


ACTION = Path(__file__).resolve().parent / "action.yml"
# A stand-in for `gh`: it logs every call, and answers the comment listing with $GH_EXISTING (an id or nothing).
FAKE_GH = "#!/bin/sh\necho \"$*\" >>\"$GH_LOG\"\ncase \"$*\" in *--paginate*) [ -n \"$GH_EXISTING\" ] && echo \"$GH_EXISTING\";; esac\nexit 0\n"


class Action(Repo):
    @staticmethod
    def steps() -> dict[str, dict]:
        """Each step of action.yml by id: its `if:`, its env keys and its run block (dedented)."""
        out = {}
        for chunk in ACTION.read_text().split("    - id: ")[1:]:
            sid, body = chunk.split("\n", 1)
            head, _, run = body.partition("      run: |\n")
            out[sid] = {"if": next((ln.split("if:", 1)[1].strip() for ln in head.splitlines()
                                    if ln.strip().startswith("if:")), None),
                        "env": [ln.split(":")[0].strip() for ln in head.split("env:", 1)[-1].splitlines()
                                if ln.startswith("        ") and ":" in ln],
                        "run": "\n".join(ln[8:] for ln in run.splitlines() if ln.startswith("        ") or not ln)}
        return out

    def test_the_action_never_interpolates_inputs_into_shell(self):
        # Catches: `${{ inputs.x }}` or a PR field pasted into a `run:` block, a script injection from a PR.
        st = self.steps()
        self.assertEqual(list(st), ["check", "comment", "finish"])
        for sid, s in st.items():
            self.assertNotIn("${{", s["run"], sid)
        self.assertIn("rulecheck.py", st["check"]["run"])

    def test_the_check_never_holds_the_token_and_no_comment_follows_an_adapter(self):
        # Catches: the token in the environment of the step that runs the adapter, the pull request's own
        # code (Sourcery on PR #162), and a comment step that runs after it, where the adapter could have
        # written GITHUB_ENV for the token-holding step.
        st = self.steps()
        self.assertNotIn("GH_TOKEN", st["check"]["env"])
        self.assertIn("GH_TOKEN", st["comment"]["env"])
        # Exactly, since the harness below stands in for the runner's evaluation of it.
        self.assertEqual(st["comment"]["if"],
                         "inputs.comment == 'true' && inputs.adapter == '' && github.event.pull_request.number")

    def test_strict_takes_any_case_and_refuses_anything_else(self):
        # Catches: a case-sensitive `= true`, where `strict: "True"` quietly turned the gate off, and a
        # value like "yes" read as false (1.37.0 review, HIGH).
        e = json.loads(self.ruling().read_text())
        e["valid_if"] = [EXCERPT, {"kind": "item_status", "item": "LANE.1.a", "status": "proposed"}]
        self.ruling().write_text(json.dumps(e))
        self.base = self.commit("base with an item status")
        self.assertEqual(self.step("", strict="True")[:2], (1, "fail"))
        rc, result, summary, _ = self.step("", strict="yes")
        self.assertEqual((rc, result), (2, "error"))
        self.assertIn("strict must be true or false", summary)

    def test_an_adapter_refuses_to_run_beside_a_persisted_token(self):
        # Catches: the adapter (the PR's code) run where actions/checkout left the job's token in
        # .git/config, which it could simply read; a warning alone let it run (1.37.0 review, HIGH).
        (self.root / "adapter.py").write_text("raise SystemExit('the adapter ran')\n")
        git(self.root, "config", "http.https://github.com/.extraheader", "AUTHORIZATION: basic x")
        rc, result, summary, _ = self.step("7", adapter="adapter.py")
        self.assertEqual((rc, result), (2, "error"))
        self.assertIn("persist-credentials: false", summary)
        self.assertNotIn("the adapter ran", summary)

    def step(self, pr: str, existing: str = "", adapter: str = "", strict: str = "false"
             ) -> tuple[int, str, str, list[str]]:
        """Run the Action's steps as the runner would: (exit, `result` output, summary, gh calls).

        The comment step runs when its `if:` holds (comment on, no adapter, a pull request), with the
        check's outputs; the finish step's exit is the Action's.
        """
        st = self.steps()
        tmp = Path(self._td.name)
        (tmp / "bin").mkdir(exist_ok=True)
        (tmp / "bin/gh").write_text(FAKE_GH)
        (tmp / "bin/gh").chmod(0o755)
        for f in ("out", "summary", "gh.log"):
            (tmp / f).write_text("")
        env = {**os.environ, "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}", "GITHUB_WORKSPACE": str(self.root),
               "RUNNER_TEMP": str(tmp), "GITHUB_OUTPUT": str(tmp / "out"), "GITHUB_STEP_SUMMARY": str(tmp / "summary"),
               "GH_LOG": str(tmp / "gh.log"), "GH_EXISTING": existing}
        env.pop("GH_TOKEN", None)

        def bash(run: str, extra: dict) -> int:
            # As the runner starts `shell: bash`: errexit and pipefail on, so a failing line ends the step.
            return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", run],
                                  env={**env, **extra}, capture_output=True, text=True,
                                  timeout=60).returncode

        self.assertEqual(bash(st["check"]["run"], {"KIT": str(KIT), "BASE": self.base, "LOCKED": "",
                                                   "ADAPTER": adapter, "STRICT": strict}), 0)
        outs = dict(ln.split("=", 1) for ln in (tmp / "out").read_text().splitlines())
        if pr and not adapter:
            self.assertEqual(bash(st["comment"]["run"], {"PR": pr, "REPO": "o/r", "RC": outs["rc"],
                                                         "REPORT": outs["report"], "GH_TOKEN": "t"}), 0)
        rc = bash(st["finish"]["run"], {"RC": outs["rc"]})
        return rc, outs["result"], (tmp / "summary").read_text(), (tmp / "gh.log").read_text().splitlines()

    def test_strict_fails_an_unchecked_ruling_and_says_so(self):
        # Catches: --strict wired to nothing (an item status nobody checked still passes), and a strict
        # failure that reads "all hold" in the comment.
        e = json.loads(self.ruling().read_text())
        e["valid_if"] = [EXCERPT, {"kind": "item_status", "item": "LANE.1.a", "status": "proposed"}]
        self.ruling().write_text(json.dumps(e))
        self.base = self.commit("base with an item status")
        self.assertEqual(self.step("7")[:2], (0, "pass"))
        rc, result, summary, _ = self.step("7", strict="true")
        self.assertEqual((rc, result), (1, "fail"))
        self.assertIn("could not be checked, which --strict fails", summary)

    def test_an_adapter_run_posts_no_comment(self):
        # Catches: a comment posted after the pull request's adapter code ran in this job.
        (self.root / "adapter.py").write_text("def items():\n    return {'LANE.1': {'status': 'open'}}\n"
                                              "def record(e, d):\n    return []\ndef seed_questions():\n    return []\n")
        self.break_code()
        self.commit("pr")
        rc, result, _, calls = self.step("7", adapter="adapter.py")
        self.assertEqual((rc, result, calls), (1, "fail", []))

    def test_a_broken_ruling_fails_the_step_and_posts_one_comment(self):
        # Catches: a step that swallows rulecheck's exit (a green check over a broken ruling), and one
        # that posts a fresh comment on every push instead of keeping one.
        self.break_code()
        self.commit("pr")
        rc, out, summary, calls = self.step("7")
        self.assertEqual((rc, out), (1, "fail"))
        self.assertIn(RC.MARKER, summary)
        self.assertEqual([c.split()[:2] for c in calls], [["api", "repos/o/r/issues/7/comments"]] * 2)
        rc, _, _, calls = self.step("7", existing="99")
        self.assertEqual(calls[-1].split()[:4], ["api", "-X", "PATCH", "repos/o/r/issues/comments/99"])

    def test_a_passing_reruling_still_posts_the_comment(self):
        # Catches: a comment posted only on failure, so a re-ruling (a claim the reviewer must confirm)
        # shows only in the job summary nobody opens (1.36.0 review).
        self.break_code()
        a2 = self.store.append(answer(picks=("a",), supersedes=self.a1["id"], reason="int is fine now"))
        self.store.append(lock(a2, anchors=[{"kind": "excerpt", "path": "src/pay.py", "text": "return int(cents)"}]))
        self.export()
        self.commit("pr")
        rc, out, _, calls = self.step("7")
        self.assertEqual((rc, out, len(calls)), (0, "pass", 2))

    def test_a_run_that_cannot_check_replaces_a_stale_comment(self):
        # Catches: an error run that leaves an earlier red (or green) comment standing as if current.
        # The bad value is quoted in the error; its backticks must not end the fence and spill markup.
        e = json.loads(self.ruling().read_text())
        e["asked_at"] = "````\n@octocat <img src=x>"
        self.ruling().write_text(json.dumps(e))
        self.commit("pr")
        rc, out, summary, calls = self.step("7", existing="99")
        self.assertEqual((rc, out), (2, "error"))
        self.assertIn("could not run", summary)
        self.assertEqual(summary.count("````"), 2)
        self.assertEqual(calls[-1].split()[:4], ["api", "-X", "PATCH", "repos/o/r/issues/comments/99"])

    def test_a_clean_pr_posts_nothing_new_and_passes(self):
        # Catches: a comment on every clean pull request, which teaches people to ignore it.
        rc, out, _, calls = self.step("7")
        self.assertEqual((rc, out), (0, "pass"))
        self.assertEqual(len(calls), 1)   # only the lookup for an earlier comment


if __name__ == "__main__":
    unittest.main()
