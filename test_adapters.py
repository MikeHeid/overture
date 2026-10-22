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
from test_rulecheck import BILL, KIT, _Registered, git, sym  # test_kit (through it) isolates the user's registry
from overture import adapters as AD  # noqa: E402
from overture import lookup as L  # noqa: E402

HOOK = KIT / "adapter_hook.py"
AGENT = KIT / "agent.py"
MCP = KIT / "mcp_server.py"
KEEP = "return round_half_even(cents)"     # what the ruling rests on
BROKEN = "def charge(cents):\n    return int(cents)\n"
VENDORS_WITH_JSON = ("cursor", "copilot")


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

    def test_a_ruling_that_changed_since_the_list_was_said_is_said_again(self):
        # Catches: the once-per-session record keyed on the file alone, so a ruling the agent was shown as
        # holding goes stale and the agent never hears it (1.56 review round 2, mutant q).
        body = patch("*** Update File: src/pay.py", "@@", "-def charge(cents):", "+def charge(cents, /):",
                     f"     {KEEP}")
        self.assertIsNotNone(self.edit(body))
        self.break_code()
        text = self.edit(patch("*** Update File: src/pay.py", "@@", " def charge(cents):",
                               "-    return int(cents)", "+    return int(cents)  # kept"))
        self.assertIsNotNone(text)
        self.assertIn("LANE.1/Q1", text)

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

    def test_hunks_apply_in_order_each_after_the_last(self):
        # Catches: each hunk searched from the top, landing on text an earlier hunk wrote. Mutant n.
        self.assertEqual(AD.after_patch("x\nx", [("x", "x y"), ("x", "z")]), "x y\nz")

    def test_end_of_file_does_not_drop_the_files_later_hunks(self):
        # Catches: `*** End of File` read as the end of the file's section (1.56 review, LOW).
        _, [(_p, blocks)] = AD.parse_patch(patch("*** Update File: a.py", "@@", "-a", "+A", "*** End of File",
                                                 "@@", "-b", "+B"), Path("/w"))
        self.assertEqual(blocks, [("a", "A"), ("b", "B")])


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
                self.assertFalse(where["hooks"].exists())

    def toml(self, text: str) -> Path:
        p = AD.paths("codex", self.home)["mcp"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
        return p

    def test_a_reinstall_with_our_mcp_table_in_place_still_writes_the_hooks(self):
        # Catches: install stopping when config.toml already holds our table, so a hooks file the user
        # deleted is never written back (1.56 review round 2, mutant N12).
        where = AD.paths("codex", self.home)
        self.toml('model = "x"\n')
        AD.install("codex", KIT, "codex", self.home)
        before = where["mcp"].read_bytes()
        where["hooks"].unlink()
        AD.install("codex", KIT, "codex", self.home)
        self.assertEqual(where["mcp"].read_bytes(), before)
        self.assertIn("apply_patch", [g["matcher"] for g in json.loads(where["hooks"].read_text())["hooks"]["PreToolUse"]])

    def test_a_hook_of_ours_written_for_powershell_is_ours(self):
        # Catches: only `command`/`bash` read, so an entry of ours in Copilot's `powershell` field is doubled on
        # install and left behind on uninstall (1.56 review round 2, mutant N13).
        where = AD.paths("copilot", self.home)["hooks"]
        where.parent.mkdir(parents=True)
        old = {"type": "command", "powershell": AD.hook_command(Path("/old kit"), "copilot", "edit")}
        where.write_text(json.dumps({"version": 1, "hooks": {"postToolUse": [old]}}))
        AD.install("copilot", KIT, "copilot", self.home)
        self.assertEqual(len(json.loads(where.read_text())["hooks"]["postToolUse"]), 1)
        AD.uninstall("copilot", self.home)
        self.assertFalse(where.exists())

    def test_a_table_after_ours_and_its_comment_survive_uninstall(self):
        # Catches: uninstall cutting from our table to the end of the file, or taking the next table's comment.
        # Mutant m.
        p = self.toml('model = "x"\n')
        AD.install("codex", KIT, "codex", self.home)
        p.write_text(p.read_text() + "\n# theirs, below\n[mcp_servers.theirs]\ncommand = \"t\"\n")
        AD.uninstall("codex", self.home)
        text = p.read_text()
        self.assertIn("# theirs, below\n[mcp_servers.theirs]", text)
        self.assertEqual(tomllib.loads(text), {"model": "x", "mcp_servers": {"theirs": {"command": "t"}}})

    def test_our_table_with_a_comment_or_in_another_form_is_never_doubled(self):
        # Catches: a header with a trailing comment not seen, so install appends a second table and Codex's
        # config no longer parses; an inline table edited by a regex it does not match (1.56 review, MEDIUM).
        p = self.toml('[mcp_servers.overture] # mine\ncommand = "x"\n')
        self.assertIn("already names", AD.install("codex", KIT, "codex", self.home)[1])
        self.assertEqual(p.read_text(), '[mcp_servers.overture] # mine\ncommand = "x"\n')
        AD.uninstall("codex", self.home)
        self.assertEqual(tomllib.loads(p.read_text()), {})
        inline = 'mcp_servers = { overture = { command = "x" } }\n'
        self.toml(inline)
        AD.install("codex", KIT, "codex", self.home)
        self.assertIn("remove it by hand", " ".join(AD.uninstall("codex", self.home)))
        self.assertEqual(p.read_text(), inline)

    def test_crlf_is_kept_and_uninstall_restores_the_file(self):
        # Catches: CRLF line ends turned into LF in the user's config (1.56 review, LOW).
        original = 'model = "x"\r\n\r\n[mcp_servers.theirs]\r\ncommand = "t"\r\n'
        p = self.toml(original)
        AD.install("codex", KIT, "codex", self.home)
        raw = p.read_bytes()
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertIn("overture", tomllib.loads(raw.decode())["mcp_servers"])
        AD.uninstall("codex", self.home)
        self.assertEqual(tomllib.loads(p.read_bytes().decode()), tomllib.loads(original))
        self.assertNotIn(b"\n", p.read_bytes().replace(b"\r\n", b""))

    def test_a_symlinked_config_stays_a_link(self):
        # Catches: a dotfiles link replaced by a plain file (1.56 review, MEDIUM).
        real = self.home / "dotfiles" / "config.toml"
        real.parent.mkdir()
        real.write_text('model = "x"\n')
        p = AD.paths("codex", self.home)["mcp"]
        p.parent.mkdir(parents=True)
        p.symlink_to(real)
        AD.install("codex", KIT, "codex", self.home)
        self.assertTrue(p.is_symlink())
        self.assertIn("overture", tomllib.loads(real.read_text())["mcp_servers"])

    def test_a_users_own_hook_named_adapter_hook_is_not_ours(self):
        # Catches: every command containing "adapter_hook.py" taken as ours and removed (1.56 review, MEDIUM).
        for vendor in VENDORS_WITH_JSON:
            with self.subTest(vendor):
                where = AD.paths(vendor, self.home)["hooks"]
                where.parent.mkdir(parents=True, exist_ok=True)
                mine = {"command": "/me/adapter_hook.py --check", "bash": "/me/adapter_hook.py --check"}
                where.write_text(json.dumps({"version": 1, "hooks": {"sessionStart": [mine]}}))
                AD.install(vendor, KIT, vendor, self.home)
                AD.uninstall(vendor, self.home)
                self.assertEqual(json.loads(where.read_text())["hooks"], {"sessionStart": [mine]})
        where = AD.paths("codex", self.home)["hooks"]
        where.parent.mkdir(parents=True, exist_ok=True)
        theirs = {"type": "command", "command": "/me/adapter_hook.py --check"}
        where.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "apply_patch", "hooks": [
            theirs, {"type": "command", "command": AD.hook_command(Path("/old kit"), "codex", "edit")}]}]}}))
        AD.uninstall("codex", self.home)   # ours from an older kit path goes; theirs in the same group stays
        self.assertEqual(json.loads(where.read_text())["hooks"]["PreToolUse"][0]["hooks"], [theirs])

    def test_a_bad_mcp_file_writes_nothing_at_all(self):
        # Catches: hooks written before the MCP file is read, leaving half an install (1.56 review, LOW).
        where = AD.paths("cursor", self.home)
        where["mcp"].parent.mkdir(parents=True)
        where["mcp"].write_text("{broken")
        with self.assertRaises(AD.InstallError):
            AD.install("cursor", KIT, "cursor", self.home)
        self.assertFalse(where["hooks"].exists())

    def test_file_modes_are_kept(self):
        # Catches: a config the user made world-readable on purpose turned 0600, or the reverse. Mutant x.
        where = AD.paths("cursor", self.home)["mcp"]
        where.parent.mkdir(parents=True)
        where.write_text("{}")
        where.chmod(0o644)
        AD.install("cursor", KIT, "cursor", self.home)
        self.assertEqual(where.stat().st_mode & 0o777, 0o644)

    def test_agents_md_with_a_stray_begin_keeps_the_users_text(self):
        # Catches: a BEGIN marker with no END above our block taking the text between them (1.56 review, LOW).
        text = f"intro\n{AD.AGENTS_BEGIN}\nthe user's own words\n"
        once = AD.agents_md(text)
        self.assertIn("the user's own words", once)
        self.assertEqual(AD.agents_md(once), once)

    def test_uninstall_leaves_no_empty_hooks_file_it_made(self):
        # Catches: `{"hooks": {}}` left behind in a vendor folder that had no hooks file before install
        # (found in the 2026-10-22 real run).
        for vendor in ("codex", "cursor"):
            with self.subTest(vendor):
                AD.install(vendor, KIT, vendor, self.home)
                AD.uninstall(vendor, self.home)
                self.assertFalse(AD.paths(vendor, self.home)["hooks"].exists())

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


class TrustAndShapeTests(_Hook):
    """The 1.56 review's survivors: each test names the mutant it kills."""

    BREAK = patch("*** Update File: src/pay.py", "@@", f"-    {KEEP}", "+    return int(cents)")

    def codex(self, body: str = BREAK, cwd: Path | None = None, tool: str = "apply_patch", sid: str = "t1"):
        return self.said("codex", "edit", {"session_id": sid, "cwd": str(cwd or self.root), "tool_name": tool,
                                           "tool_input": {"command": body}})

    def test_a_repo_nested_inside_the_registered_one_gets_nothing(self):
        # Catches: the edited file's checkout found by walking up to an enclosing registered root (AS1), so a
        # vendored or nested repository's paths reach the outer project's console. Mutant c2.
        subprocess.run(["git", "clone", "-q", str(self.root), str(self.root / "vend")], check=True,
                       capture_output=True)
        self.assertIsNone(self.codex(self.BREAK.replace("src/pay.py", "vend/src/pay.py")))

    def test_a_real_worktree_of_the_registered_checkout_speaks(self):
        # Catches: worktree support dropped, so an agent working in `agent.py worktree new` hears nothing. Mutant u.
        wt = Path(self._td.name) / "wt"
        git(self.root, "worktree", "add", "-q", "-b", "lane", str(wt))
        self.assertIn("would break ruling LANE.1/Q1", self.codex(cwd=wt))

    def test_a_path_through_a_symlinked_folder_is_the_real_file(self):
        # Catches: paths made absolute without resolving links, so the file is not found under its checkout. Mutant k.
        link = Path(self._td.name) / "link"
        link.symlink_to(self.root)
        self.assertIn("would break ruling LANE.1/Q1", self.codex(cwd=link))

    def test_a_symlinked_file_is_its_target(self):
        # Catches: a link edited under its own name, so the rulings of a path it merely stands for are said. As in
        # the Claude hook, the path is resolved first: here src/pay.py links to real.py, which has no ruling.
        # (`_text`'s own link check is then reached only in a race: mutant l is equivalent, not killed.)
        real = self.root / "real.py"
        (self.root / "src/pay.py").rename(real)
        (self.root / "src/pay.py").symlink_to(real)
        self.assertIsNone(self.codex())

    def test_a_fragment_that_is_not_unique_is_not_undone(self):
        # Catches: an edit undone at a guessed place, blaming it for a break it may not have made. Mutant cc.
        (self.root / "src/pay.py").write_text("def charge(cents):\n    return int(cents)\n# return int(cents)\n")
        text = self.said("cursor", "edit", {"conversation_id": "c9", "cwd": str(self.root), "tool_input": {
            "file_path": str(self.root / "src/pay.py"), "old_string": KEEP, "new_string": "return int(cents)"}})
        self.assertIn("it is stale on the file as it is now", text)
        self.assertNotIn("it changes or removes", text)

    def test_with_no_old_text_a_ruling_that_holds_is_not_warned(self):
        # Catches: the "stale on the file now" fallback naming rulings that still hold. Mutant gg.
        text = self.said("cursor", "edit", {"conversation_id": "c8", "cwd": str(self.root), "tool_input": {
            "file_path": str(self.root / "src/pay.py"), "content": (self.root / "src/pay.py").read_text()}})
        self.assertIn("LANE.1/Q1", text)
        self.assertNotIn("WARNING", text)

    def test_a_malformed_registry_entry_is_no_registration(self):
        # Catches: an entry the kit's own rules refuse (a relative kit path) still used. Mutant ff.
        (self.cfg_home / "overture" / "projects.json").write_text(json.dumps(
            {"projects": {os.path.realpath(self.root): {"state": str(self.state), "kit": "kit"}}}))
        self.assertIsNone(self.codex())

    def test_a_patch_under_another_tool_name_is_not_read(self):
        # Catches: any Codex tool's command read as a patch (the matcher is the vendor's, not ours). Mutant hh.
        self.assertIsNone(self.codex(tool="Bash"))

    def test_input_past_the_cap_is_nothing_to_add(self):
        # Catches: an unbounded read of the hook's input. Mutant ii.
        big = json.dumps({"session_id": "t", "cwd": str(self.root), "tool_name": "apply_patch",
                          "tool_input": {"command": self.BREAK}, "pad": "x" * AD.MAX_INPUT})
        self.assertEqual(self.run_hook("codex", "edit", big), (0, ""))
        # Whole and valid JSON one character past the cap (trailing blanks): still nothing, so the cap is
        # checked, not only the read cut short (1.56 review round 2, mutant ii).
        whole = json.dumps({"session_id": "t", "cwd": str(self.root), "tool_name": "apply_patch",
                            "tool_input": {"command": self.BREAK}})
        self.assertEqual(self.run_hook("codex", "edit", whole.ljust(AD.MAX_INPUT + 1)), (0, ""))
        self.assertIn("WARNING", self.run_hook("codex", "edit", whole.ljust(AD.MAX_INPUT))[1])

    def test_old_text_without_new_text_is_not_an_old_new_edit(self):
        # Catches: old OR new taken as an old/new edit, so a write that carries its whole content beside a stray
        # old text is read as half a replacement (1.56 review round 2, mutant o).
        f = str(self.root / "src/pay.py")
        self.assertIsNone(AD.edit_from_args({"path": f, "old_str": KEEP}, None))
        e = AD.edit_from_args({"path": f, "old_str": KEEP, "file_text": BROKEN}, None)
        self.assertEqual((e.old, e.new, e.content), (None, None, BROKEN))

    def test_a_symlinked_shown_file_is_not_trusted(self):
        # Catches: the once-per-session record read through a link, so a planted file can silence the list.
        # Mutant r.
        keep = patch("*** Update File: src/pay.py", "@@", "-def charge(cents):", "+def charge(cents, /):")
        self.assertIsNotNone(self.codex(keep, sid="r1"))
        shown = self.xstate / "overture" / AD.SHOWN_FILE
        moved = shown.with_name("elsewhere.json")
        shown.rename(moved)
        shown.symlink_to(moved)
        self.assertIsNotNone(self.codex(keep, sid="r1"))

    def test_a_patch_of_many_files_is_cut_to_the_limit(self):
        # Catches: an unbounded number of lookups for one tool call. Mutant p.
        body = patch(*[f"*** Add File: f{i}.py\n+x" for i in range(AD.MAX_EDITS + 5)])
        ev = AD.read("codex", "edit", {"cwd": "/w", "tool_name": "apply_patch", "tool_input": {"command": body}})
        self.assertEqual(len(ev.edits), AD.MAX_EDITS)


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
