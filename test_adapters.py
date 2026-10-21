#!/usr/bin/env python3
"""Adapters for other agent vendors (Wave 4, owner V1-V4): Codex CLI, Cursor and Copilot CLI hooks.

Each test runs `plugin/kit/adapter_hook.py` as the vendor would, with the
vendor's documented hook input (read 2026-10-21), against a real checkout that
holds one committed ruling (`test_rulecheck._Registered`: the ruling on
`src/pay.py` rests on the excerpt `return round_half_even(cents)`, and no
console server runs, so the committed rulings answer).

    python3 test_adapters.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from test_kit import answer, lock, question
from test_rulecheck import BILL, KIT, _Registered, sym  # test_kit (through it) isolates the user's registry
from overture import adapters as AD  # noqa: E402
from overture import lookup as L  # noqa: E402

HOOK = KIT / "adapter_hook.py"
AGENT = KIT / "agent.py"
MCP = KIT / "mcp_server.py"
KEEP = "return round_half_even(cents)"     # what the ruling rests on
BROKEN = "def charge(cents):\n    return int(cents)\n"


def patch(*body: str) -> str:
    return "\n".join(["*** Begin Patch", *body, "*** End Patch"])


class _Hook(_Registered):
    def run_hook(self, vendor: str, event: str, payload, env: dict | None = None) -> tuple[int, str]:
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        r = subprocess.run([sys.executable, str(HOOK), vendor, event], input=stdin, env=env or self.env(),
                           capture_output=True, text=True, timeout=30)
        self.assertNotIn("permissionDecision", r.stdout)   # V2: it informs, never decides
        self.assertNotIn('"permission"', r.stdout)
        self.assertNotIn('"decision"', r.stdout)
        return r.returncode, r.stdout

    def said(self, vendor: str, event: str, payload) -> str | None:
        """The note in the vendor's own output shape, or None when it said nothing to add."""
        rc, out = self.run_hook(vendor, event, payload)
        self.assertEqual(rc, 0)
        if vendor == "codex":
            if not out.strip():
                return None
            o = json.loads(out)["hookSpecificOutput"]
            self.assertEqual(set(o), {"hookEventName", "additionalContext"})
            self.assertEqual(o["hookEventName"], "SessionStart" if event == "session-start" else "PreToolUse")
            return o["additionalContext"]
        doc = json.loads(out)
        key = "additional_context" if vendor == "cursor" else "additionalContext"
        self.assertLessEqual(set(doc), {key})
        return doc.get(key)


class CodexTests(_Hook):
    """Codex speaks before the edit: PreToolUse on apply_patch, the patch in tool_input.command."""

    def edit(self, body: str, sid: str = "s1", cwd: Path | None = None) -> str | None:
        return self.said("codex", "edit", {"session_id": sid, "cwd": str(cwd or self.root), "turn_id": "t",
                                           "hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                                           "tool_use_id": "u", "tool_input": {"command": body}})

    def test_session_start_in_a_registered_project_tells_the_agent_to_ask_through_the_console(self):
        # Catches: a session that starts with no word of the console, or one told to use Claude-only skills.
        text = self.said("codex", "session-start", {"session_id": "s1", "cwd": str(self.root / "src"),
                                                    "hook_event_name": "SessionStart", "source": "startup"})
        self.assertIn("registered with an Overture console", text)
        self.assertIn("overture MCP `ask` tool", text)
        self.assertIn("`rulings`", text)
        self.assertNotIn("console-ask skill", text)
        self.assertNotIn("/overture:as", text)

    def test_session_start_anywhere_else_says_nothing(self):
        # Catches: a note in every project the user opens (trust comes from the user's registry, §7.7).
        with tempfile.TemporaryDirectory() as other:
            self.assertIsNone(self.said("codex", "session-start", {"session_id": "s1", "cwd": other}))

    def test_a_patch_that_keeps_the_ruling_lists_it_once_per_session(self):
        # Catches: no rulings said before a Codex edit, a warning for an edit that keeps what the ruling rests on,
        # or the same list before every edit.
        body = patch("*** Update File: src/pay.py", "@@", "-def charge(cents):", "+def charge(cents, /):",
                     f"     {KEEP}")
        text = self.edit(body)
        self.assertIn("holds on this file (this edit can break it): LANE.1/Q1", text)
        self.assertIn(f"({AD.HOW_TO_ASK})", text)
        self.assertNotIn("WARNING", text)
        self.assertIsNone(self.edit(body))
        self.assertIsNotNone(self.edit(body, sid="s2"))

    def test_a_patch_that_removes_what_the_ruling_rests_on_is_warned_every_time(self):
        # Catches: a Codex edit that breaks a ruling with no warning, or a warning said only once.
        body = patch("*** Update File: src/pay.py", "@@", " def charge(cents):", f"-    {KEEP}",
                     "+    return int(cents)")
        for _ in range(2):
            text = self.edit(body)
            self.assertIn("WARNING: this edit would break ruling LANE.1/Q1", text)
            self.assertIn("The edit is not blocked.", text)

    def test_deleting_the_file_is_warned(self):
        # Catches: a Delete File hunk read as no change.
        self.assertIn("would break ruling LANE.1/Q1", self.edit(patch("*** Delete File: src/pay.py")))

    def test_a_file_with_no_ruling_or_in_another_repository_gets_nothing(self):
        # Catches: a note on every patch, or rulings said for a repository nobody registered (AS1): a clone
        # carries the same committed ruling, so only the registry keeps it quiet.
        self.assertIsNone(self.edit(patch("*** Update File: README", "@@", "-unrelated", "+other")))
        self.assertIsNone(self.edit(patch("*** Add File: src/new.py", "+x = 1")))
        with tempfile.TemporaryDirectory() as td:
            other = Path(td) / "clone"
            subprocess.run(["git", "clone", "-q", str(self.root), str(other)], check=True, capture_output=True)
            self.assertTrue((other / ".overture/locked" / "LANE.1__Q1.json").is_file())
            self.assertIsNone(self.edit(patch("*** Delete File: src/pay.py"), cwd=other))

    def test_a_tool_that_is_not_apply_patch_says_nothing(self):
        # Catches: a shell command read as an edit.
        self.assertIsNone(self.said("codex", "edit", {"session_id": "s1", "cwd": str(self.root),
                                                      "tool_name": "Bash", "tool_input": {"command": "ls"}}))


class CodexSymbolTests(_Hook):
    """A ruling on a definition (1.54): a Codex patch that renames it, body kept, is followed, not warned."""

    def setUp(self):
        super().setUp()
        (self.root / "src/bill.py").write_text(BILL)
        self.store.append(question(qid="LANE.1/Q2", valid_if=[sym(BILL, "charge")], source="src/bill.py:6"))
        self.store.append(lock(self.store.append(answer(qid="LANE.1/Q2"))))
        self.export()
        self.commit("a ruling on charge()")

    def edit(self, *body: str) -> str | None:
        return self.said("codex", "edit", {"session_id": "s1", "cwd": str(self.root), "tool_name": "apply_patch",
                                           "tool_input": {"command": patch("*** Update File: src/bill.py", *body)}})

    def test_a_rename_is_followed_with_the_proposal_and_a_body_change_is_warned(self):
        # Catches: the rename check (lookup.follows) dropped from the Codex path, or a body change not warned.
        text = self.edit("@@", "-def charge(cents):", "+def charge_cents(cents):")
        self.assertIn("NOTE: this edit renames charge to charge_cents", text)
        self.assertIn("propose-anchor LANE.1/Q2 --symbol src/bill.py::charge_cents", text)
        self.assertNotIn("WARNING", text)
        text = self.edit("@@", "-    return round_half_even(cents)", "+    return int(cents)")
        self.assertIn("WARNING: this edit would break ruling LANE.1/Q2", text)


class CursorTests(_Hook):
    """Cursor speaks after the edit (postToolUse, additional_context)."""

    def edit(self, tool_input: dict, sid: str = "c1") -> str | None:
        return self.said("cursor", "edit", {"conversation_id": sid, "generation_id": "g", "hook_event_name":
                                            "postToolUse", "workspace_roots": [str(self.root)], "tool_name": "Write",
                                            "tool_input": tool_input, "tool_output": "{}", "cwd": str(self.root)})

    def test_an_edit_that_broke_the_ruling_is_warned_after_it(self):
        # Catches: a Cursor edit that breaks a ruling with no word, or one worded as if it had not happened yet.
        self.break_code()   # the edit has happened: the file on disk is the new text
        text = self.edit({"file_path": str(self.root / "src/pay.py"), "old_string": f"    {KEEP}",
                          "new_string": "    return int(cents)"})
        self.assertIn("WARNING: this edit broke ruling LANE.1/Q1", text)
        self.assertIn("What to do: restore what the ruling rests on", text)

    def test_an_edit_elsewhere_in_a_file_whose_ruling_was_already_stale_is_not_blamed(self):
        # Catches: undoing the edit skipped, so a ruling broken earlier is blamed on this edit.
        (self.root / "src/pay.py").write_text("def charge(cents, /):\n    return int(cents)\n")
        text = self.edit({"file_path": str(self.root / "src/pay.py"), "old_string": "def charge(cents):",
                          "new_string": "def charge(cents, /):"})
        self.assertNotIn("WARNING", text)
        self.assertIn("STALE", text)

    def test_with_no_old_text_a_stale_ruling_is_named_without_blaming_the_edit(self):
        # Catches: a write of the whole file read as no edit, or a stale ruling said as one this edit broke for sure.
        self.break_code()
        text = self.edit({"file_path": str(self.root / "src/pay.py"), "content": BROKEN})
        self.assertIn("broke ruling LANE.1/Q1", text)
        self.assertIn("it is stale on the file as it is now (this edit or an earlier one", text)

    def test_a_read_and_an_unruled_file_say_nothing(self):
        # Catches: a note after every tool (postToolUse runs on all of them).
        self.assertIsNone(self.edit({"file_path": str(self.root / "src/pay.py")}))
        self.assertIsNone(self.edit({"file_path": str(self.root / "README"), "content": "x\n"}))

    def test_session_start(self):
        # Catches: Cursor's session-start field names (workspace_roots, additional_context) not read or written.
        text = self.said("cursor", "session-start", {"conversation_id": "c1", "session_id": "c1",
                                                     "workspace_roots": [str(self.root)],
                                                     "hook_event_name": "sessionStart"})
        self.assertIn("registered with an Overture console", text)


class CopilotTests(_Hook):
    """Copilot CLI speaks after the edit (postToolUse, additionalContext); its toolArgs may be a JSON string."""

    def test_an_edit_that_broke_the_ruling_is_warned_after_it(self):
        # Catches: Copilot's camelCase input not read, or toolArgs given as a string not parsed.
        self.break_code()
        args = json.dumps({"path": str(self.root / "src/pay.py"), "old_str": f"    {KEEP}",
                           "new_str": "    return int(cents)"})
        text = self.said("copilot", "edit", {"sessionId": "p1", "timestamp": 1, "cwd": str(self.root),
                                             "toolName": "edit", "toolArgs": args,
                                             "toolResult": {"resultType": "success", "textResultForLlm": "ok"}})
        self.assertIn("WARNING: this edit broke ruling LANE.1/Q1", text)

    def test_session_start(self):
        # Catches: Copilot's camelCase session input (sessionId) not read, or its output key misspelt.
        text = self.said("copilot", "session-start", {"sessionId": "p1", "timestamp": 1, "cwd": str(self.root),
                                                      "source": "new"})
        self.assertIn("registered with an Overture console", text)


class FailOpenTests(_Hook):
    def test_anything_unreadable_is_nothing_to_add_and_exit_0(self):
        # Catches: a hook that crashes or exits non-zero (Copilot blocks a tool on that) on input it cannot read.
        for vendor, quiet in (("codex", ""), ("cursor", "{}"), ("copilot", "{}")):
            for stdin in ("", "not json", "[]", json.dumps({"cwd": 7, "tool_input": None})):
                with self.subTest(vendor=vendor, stdin=stdin):
                    rc, out = self.run_hook(vendor, "edit", stdin)
                    self.assertEqual((rc, out.strip()), (0, quiet))
        self.assertEqual(self.run_hook("nobody", "edit", "{}")[0], 0)

    def test_a_broken_registry_is_nothing_to_add(self):
        # Catches: an unreadable registry that crashes the hook instead of failing open.
        (self.cfg_home / "overture" / "projects.json").write_text("{not json")
        rc, out = self.run_hook("cursor", "session-start", {"cwd": str(self.root)})
        self.assertEqual((rc, out.strip()), (0, "{}"))


class SayTests(unittest.TestCase):
    def test_the_claude_hook_words_are_unchanged(self):
        # Catches: the adapter's wording leaking into the Claude hook's note (V4: the Claude hooks stay as shipped).
        h = {"qid": "Q/1", "question": "q", "answer": "a", "locked_at": "2026-10-21", "label": L.HOLDS,
             "conditions": []}
        text = L.say("a.py", [h], [(h, [{"words": "x"}])], None, "more")
        self.assertIn("WARNING: this edit would break ruling Q/1", text)
        self.assertIn("(`agent.py ask`). The edit is not blocked.", text)
        self.assertIn("(`agent.py ask`; the console-ask skill shows how):", text)


class PatchTests(unittest.TestCase):
    def test_parse_and_apply(self):
        # Catches: hunks applied out of order, context lines dropped, or an Add read as an Update.
        cwd = Path("/w")
        edits, hunks = AD.parse_patch(patch("*** Update File: a.py", "@@ def f", " a", "-b", "+B", "@@", " c",
                                            "-d", "*** Add File: n.py", "+x", "+y", "*** Delete File: z.py"), cwd)
        self.assertEqual([(e.path.name, e.content, e.deleted) for e in edits],
                         [("a.py", None, False), ("n.py", "x\ny\n", False), ("z.py", None, True)])
        [(_p, blocks)] = hunks
        self.assertEqual(blocks, [("a\nb", "a\nB"), ("c\nd", "c")])
        self.assertEqual(AD.after_patch("a\nb\nc\nd\n", blocks), "a\nB\nc\n")
        self.assertIsNone(AD.after_patch("a\nX\n", blocks))


class InstallTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_codex_install_merges_and_uninstall_takes_out_only_ours(self):
        # Catches: an install that overwrites the user's own hooks or MCP servers, a second install that doubles
        # ours, or an uninstall that leaves ours behind or takes theirs.
        where = AD.paths("codex", self.home)
        where["hooks"].parent.mkdir(parents=True)
        theirs = {"type": "command", "command": "their-hook", "timeout": 3}
        where["hooks"].write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [theirs]}]}}))
        where["mcp"].write_text('model = "x"\n\n[mcp_servers.theirs]\ncommand = "t"\n')
        for _ in range(2):
            AD.install("codex", KIT, "codex", self.home)
        doc = json.loads(where["hooks"].read_text())["hooks"]
        self.assertEqual(len(doc["PreToolUse"]), 2)
        self.assertEqual(doc["PreToolUse"][1]["matcher"], "apply_patch")
        self.assertIn(str(KIT / "adapter_hook.py"), doc["SessionStart"][0]["hooks"][0]["command"])
        cfg = tomllib.loads(where["mcp"].read_text())
        self.assertEqual(cfg["mcp_servers"]["overture"]["args"], [str(KIT / "mcp_server.py"), "--as", "codex"])
        self.assertEqual(cfg["mcp_servers"]["theirs"], {"command": "t"})
        AD.uninstall("codex", self.home)
        self.assertEqual(json.loads(where["hooks"].read_text())["hooks"],
                         {"PreToolUse": [{"matcher": "Bash", "hooks": [theirs]}]})
        cfg = tomllib.loads(where["mcp"].read_text())
        self.assertEqual(cfg, {"model": "x", "mcp_servers": {"theirs": {"command": "t"}}})

    def test_cursor_and_copilot_install_and_uninstall(self):
        # Catches: a vendor's version field or own shape missing, or another MCP server lost.
        for vendor in ("cursor", "copilot"):
            with self.subTest(vendor):
                where = AD.paths(vendor, self.home)
                where["mcp"].parent.mkdir(parents=True, exist_ok=True)
                where["mcp"].write_text(json.dumps({"mcpServers": {"theirs": {"command": "t"}}}))
                AD.install(vendor, KIT, vendor, self.home)
                hooks = json.loads(where["hooks"].read_text())
                self.assertEqual(hooks["version"], 1)
                self.assertEqual(set(hooks["hooks"]), {"sessionStart", "postToolUse"})
                servers = json.loads(where["mcp"].read_text())["mcpServers"]
                self.assertEqual(set(servers), {"theirs", "overture"})
                if vendor == "copilot":
                    self.assertEqual(servers["overture"]["type"], "local")
                    self.assertEqual(hooks["hooks"]["postToolUse"][0]["matcher"], "edit|create")
                AD.uninstall(vendor, self.home)
                self.assertEqual(set(json.loads(where["mcp"].read_text())["mcpServers"]), {"theirs"})
                if vendor == "copilot":
                    self.assertFalse(where["hooks"].exists())
                else:
                    self.assertEqual(json.loads(where["hooks"].read_text())["hooks"], {})

    def test_a_config_it_cannot_read_is_refused_and_left_alone(self):
        # Catches: a malformed user config overwritten.
        where = AD.paths("cursor", self.home)
        where["hooks"].parent.mkdir(parents=True)
        where["hooks"].write_text("{broken")
        with self.assertRaises(AD.InstallError):
            AD.install("cursor", KIT, "cursor", self.home)
        self.assertEqual(where["hooks"].read_text(), "{broken")

    def test_agents_md_block_is_written_once_and_replaced_in_place(self):
        # Catches: the block appended again on every run, or the project's own text around it lost.
        once = AD.agents_md("# Mine\n\nkeep this\n")
        self.assertTrue(once.startswith("# Mine\n\nkeep this\n\n" + AD.AGENTS_BEGIN))
        self.assertEqual(AD.agents_md(once), once)
        edited = once.replace("`todo` lists", "OLD") + "after\n"
        self.assertEqual(AD.agents_md(edited), once + "after\n")

    def test_the_command_is_refused_inside_a_session_and_writes_nothing(self):
        # Catches: a session that rewrites its own guardrails' config.
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env["HOME"] = str(self.home)
        r = subprocess.run([sys.executable, str(AGENT), "adapter", "install", "--vendor", "cursor"],
                           env={**env, "CLAUDECODE": "1"}, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)
        self.assertIn("refused inside a Claude Code session", r.stderr)
        self.assertFalse((self.home / ".cursor").exists())
        r = subprocess.run([sys.executable, str(AGENT), "adapter", "install", "--vendor", "cursor"], env=env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.home / ".cursor" / "hooks.json").exists())


class McpStateTests(_Registered):
    def run_mcp(self, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(MCP), "--as", "codex"], cwd=cwd, input="", env=self.env(),
                              capture_output=True, text=True, timeout=30)

    def test_without_state_it_takes_the_registered_projects_console(self):
        # Catches: a user-level MCP config that cannot start (no --state), or one that starts outside any
        # registered project and posts to a console nobody chose.
        self.assertEqual(self.run_mcp(self.root / "src").returncode, 0)
        with tempfile.TemporaryDirectory() as other:
            r = self.run_mcp(Path(other))
            self.assertEqual(r.returncode, 2)
            self.assertIn("is not in a project registered on this machine", r.stderr)


if __name__ == "__main__":
    unittest.main()
