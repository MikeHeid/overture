"""Tests for the MCP server (1.35): the agent door spoken as the Model Context Protocol, over stdio.

The end-to-end tests start `mcp_server.py` as a real subprocess, the way an MCP
client does, against the real console server from test_server.py's `_Live`.
The protocol tests call `handle()` directly, since they need no console.

    python3 test_mcp.py
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import unittest
from pathlib import Path

from test_server import KIT, _Live, token  # test_server also isolates the user's registry

MCP = str(KIT / "mcp_server.py")
sys.path.insert(0, str(KIT))
import mcp_server as M  # noqa: E402

SPEC = "# Spec\n\nUploads retry three times with exponential backoff, then fail loudly.\n"


class Client:
    """An MCP client over a real pipe: one JSON message per line each way, every stdout line checked."""

    def __init__(self, state: Path, cwd: Path, *extra: str) -> None:
        self.proc = subprocess.Popen([sys.executable, MCP, "--state", str(state), *extra], cwd=cwd,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.n = 0

    def send(self, msg: dict) -> None:
        self.proc.stdin.write(json.dumps(msg).encode() + b"\n")
        self.proc.stdin.flush()

    def recv(self) -> dict:
        ready, _, _ = select.select([self.proc.stdout], [], [], 30)
        if not ready:
            raise AssertionError("the MCP server sent nothing within 30 s")
        return json.loads(self.proc.stdout.readline())   # anything on stdout but one JSON message fails here

    def request(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, **({"params": params} if params else {})})
        resp = self.recv()
        assert resp["id"] == self.n, resp
        return resp

    def tool(self, name: str, **args) -> tuple[str, bool]:
        res = self.request("tools/call", {"name": name, "arguments": args})["result"]
        return res["content"][0]["text"], res["isError"]

    def close(self) -> str:
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        err = self.proc.stderr.read().decode()
        self.proc.stdout.close()
        self.proc.stderr.close()
        return err


class McpEndToEndTests(_Live, unittest.TestCase):
    """A non-Claude agent asks, the owner rules, the agent reads the ruling, and is told when it goes stale."""

    def setUp(self):
        _Live.setUp(self)
        (self.cfg.root / "spec.md").write_text(SPEC)
        self.client = Client(self.cfg.state, self.cfg.root, "--as", "cursor-1")
        init = self.client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                  "clientInfo": {"name": "test", "version": "0"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        self.client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def tearDown(self):
        self.client.close()
        _Live.tearDown(self)

    def question(self, n=7, **over):
        q = {"qid": f"LANE.1/Q{n}", "item": "LANE.1", "text": "How many upload retries?", "kind": "single",
             "options": [{"id": "three", "label": "Three", "description": "as the spec says; slower to fail"},
                         {"id": "none", "label": "None", "description": "fails at once; flaky networks hurt"}],
             "star": "three", "source": "spec.md:3",
             "valid_if": [{"kind": "excerpt", "path": "spec.md",
                           "text": "Uploads retry three times with exponential backoff"}]}
        q.update(over)
        return q

    def test_a_question_asked_over_mcp_is_ruled_on_and_goes_stale_when_its_evidence_moves(self):
        # Catches: a tool that never reaches the console; a write that loses the client's --as name;
        # `answers` that cannot see the owner's lock; `check` that misses the edit under a ruling.
        text, err = self.client.tool("ask", question=self.question())
        self.assertFalse(err, text)
        view = self.req("GET", "/api/view", tok=token())[1]["view"]
        self.assertEqual(view["questions"]["LANE.1/Q7"]["question"]["agent"], "cursor-1")
        code, a = self.req("POST", "/api/answer", self.answer(qid="LANE.1/Q7", picks=["three"],
                                                              nonce="mcpanswer001"), tok=token())
        self.assertEqual(code, 200, a)
        code, lk = self.req("POST", "/api/lock", {"qid": "LANE.1/Q7", "answer": a["record"]["id"],
                                                  "nonce": "mcplock00001"}, tok=token())
        self.assertEqual(code, 200, lk)
        text, err = self.client.tool("answers", item="LANE.1")
        self.assertFalse(err, text)
        row = {r["qid"]: r for r in json.loads(text)["rows"]}["LANE.1/Q7"]
        self.assertEqual(row["state"], "locked")
        text, err = self.client.tool("check")
        self.assertFalse(err, text)
        self.assertEqual(json.loads(text)["stale"], {})
        (self.cfg.root / "spec.md").write_text(SPEC.replace("three times", "five times"))
        text, err = self.client.tool("check")
        self.assertFalse(err, text)
        self.assertIn("LANE.1/Q7", json.loads(text)["stale"])

    def test_rulings_lists_the_rulings_on_a_path_as_the_socket_does(self):
        # Catches (1.52.0): a `rulings` tool that never reaches the console, reads another shape than the
        # agent socket's, or drops one of several paths.
        self.client.tool("ask", question=self.question())
        code, a = self.req("POST", "/api/answer", self.answer(qid="LANE.1/Q7", picks=["three"],
                                                              nonce="mcpanswer002"), tok=token())
        self.assertEqual(code, 200, a)
        self.assertEqual(self.req("POST", "/api/lock", {"qid": "LANE.1/Q7", "answer": a["record"]["id"],
                                                        "nonce": "mcplock00002"}, tok=token())[0], 200)
        text, err = self.client.tool("rulings", paths=["spec.md", "docs/"])
        self.assertFalse(err, text)
        doc = json.loads(text)
        self.assertEqual(doc["source"], "server")
        self.assertEqual([h["qid"] for h in doc["rulings"]["spec.md"]], ["LANE.1/Q7"])
        self.assertEqual(doc["rulings"]["docs/"], [])
        self.assertEqual(doc["rulings"], self.agent_post("/rulings", {"paths": ["spec.md", "docs/"]})[1]["rulings"])
        text, err = self.client.tool("rulings", paths=["../x"])
        self.assertTrue(err)
        self.assertIn("leaves the project", text)

    def test_a_refused_question_comes_back_as_a_tool_error_naming_why(self):
        # Catches: a refusal turned into a protocol error (the model never sees it, so cannot fix it),
        # or one reported as success; and a re-ask of a minted qid getting through.
        text, err = self.client.tool("ask", question=self.question(star="nope"))
        self.assertTrue(err)
        self.assertIn("star", text)
        self.assertFalse(self.client.tool("ask", question=self.question())[1])
        text, err = self.client.tool("ask", question=self.question(text="Again?"))
        self.assertTrue(err, text)
        self.assertIn("minted once", text)   # the reason reaches the model, so it picks the next Q<n>

    def test_text_that_looks_like_a_flag_is_posted_as_text(self):
        # Catches: argv built without `--`, where a reply of "--as owner" or "-h" is parsed by argparse:
        # "-h" would print help and post nothing, and "--as owner" would be a refusal, not a message.
        for body in ("-h", "--as owner"):
            text, err = self.client.tool("reply", item="LANE.1", text=body)
            self.assertFalse(err, text)
            rec = json.loads(text)["record"]
            shown = {m["id"]: m for m in self.req("GET", "/api/view", tok=token())[1]["view"]["threads"]["LANE.1"]}
            self.assertEqual((rec["text"], rec["by"], shown[rec["id"]]["agent"]), (body, "agent", "cursor-1"))

    def test_a_lesson_match_and_no_match_are_both_answers(self):
        # Catches: lesson-match's exit 1 ("none match") reported as a failure, which teaches a model
        # that the check is broken; and a match that never reaches the client.
        from overture import lessons as LN
        text, err = self.client.tool("lesson_match", text="How many upload retries?", item="LANE.1")
        self.assertFalse(err, text)
        self.assertIn("No lessons match", text)
        LN.record(self.cfg.state, "LANE.1/Q0", "LANE.1", "withdraw", "How many upload retries now?",
                  "obsolete: uploads moved to the batch endpoint", "2026-10-01T00:00:00Z")
        text, err = self.client.tool("lesson_match", text="How many upload retries?", item="LANE.1")
        self.assertFalse(err, text)
        self.assertIn("batch endpoint", text)

    def test_reads_and_working_reach_the_console(self):
        # Catches: a tool whose argv agent.py rejects (each is built here, not typed by a person).
        for name, args in (("todo", {}), ("view", {"item": "LANE.1", "since": 0}), ("health", {}),
                           ("working", {"items": ["LANE.1"]})):
            text, err = self.client.tool(name, **args)
            self.assertFalse(err, f"{name}: {text}")
            json.loads(text)
        text, err = self.client.tool("view", item="NOPE")
        self.assertTrue(err)

    def test_a_relative_state_means_where_the_client_started_the_server(self):
        # Catches: --state resolved after --project moved the process, so `--state state` named
        # <project>/state, a console that does not exist, and every tool failed to reach it.
        sub = self.cfg.root / "checkout"
        sub.mkdir()
        c = Client(Path(self.cfg.state.name), self.cfg.root, "--project", str(sub))
        try:
            text, err = c.tool("health")
            self.assertFalse(err, text)
        finally:
            c.close()


class McpStartTests(unittest.TestCase):

    def test_a_bad_agent_name_is_refused_before_serving(self):
        # Catches: a name checked only on the first write, so a client runs for hours under a name
        # every write will refuse; and "owner", which would let an agent pass as the owner in the feed.
        for bad in ("owner", "Bad Name"):
            p = subprocess.run([sys.executable, MCP, "--state", "/nonexistent", "--as", bad],
                               input=b"", capture_output=True, timeout=30)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertEqual(p.stdout, b"")


class McpProtocolTests(unittest.TestCase):
    """The protocol itself, in both eras, with no console behind it."""

    door = M.Door(Path("/nonexistent/state"), None)

    def call(self, method, params=None, mid=1):
        msg = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            msg["params"] = params
        return M.handle(self.door, msg)

    def test_initialize_echoes_a_version_it_speaks_and_offers_its_newest_otherwise(self):
        # Catches: a server that always answers one version (an older client then drops it) or
        # echoes any string it is sent (a client then believes a version nobody implemented).
        for v in M.LEGACY:
            self.assertEqual(self.call("initialize", {"protocolVersion": v})["result"]["protocolVersion"], v)
        self.assertEqual(self.call("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"],
                         M.LEGACY[0])

    def test_the_stateless_era_discovers_and_marks_results_complete(self):
        # Catches: a 2026-07-28 client probing with server/discover, getting an error, and falling back
        # to a handshake; and results missing resultType, which that revision requires.
        meta = {"_meta": {M.META_VERSION: "2026-07-28"}}
        d = self.call("server/discover", meta)["result"]
        self.assertEqual((d["resultType"], d["supportedVersions"]), ("complete", ["2026-07-28"]))
        self.assertEqual(self.call("tools/list", meta)["result"]["resultType"], "complete")
        bad = self.call("tools/list", {"_meta": {M.META_VERSION: "1900-01-01"}})
        self.assertEqual(bad["error"]["code"], -32022)
        self.assertNotIn("resultType", self.call("tools/list")["result"])   # a 2025 client gets 2025 shapes

    def test_only_the_agent_door_is_offered(self):
        # Catches: a steward or owner command (watch, synced, register, server, steward, role) or a
        # checkout writer (the exports, lessons --fold) exposed to any client that connects.
        tools = self.call("tools/list")["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {"todo", "view", "answers", "check", "lesson_match", "health",
                                                      "ask", "reply", "working", "rulings"})
        for t in tools:
            self.assertFalse(t["inputSchema"]["additionalProperties"], t["name"])

    def test_errors_are_shaped_by_who_can_fix_them(self):
        # Catches: bad arguments as protocol errors (the model never reads them) and an unknown tool
        # or method answered as if it ran.
        self.assertEqual(self.call("tools/call", {"name": "watch", "arguments": {}})["error"]["code"], -32602)
        self.assertEqual(self.call("resources/list")["error"]["code"], -32601)
        for args in ({"since": True}, {"since": -1}, {"item": ""}, {"bogus": 1}):
            r = self.call("tools/call", {"name": "view", "arguments": args})["result"]
            self.assertTrue(r["isError"], args)
        r = self.call("tools/call", {"name": "ask", "arguments": {"question": "not an object"}})["result"]
        self.assertTrue(r["isError"])
        self.assertIsNone(M.handle(self.door, {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(M.handle(self.door, [1])["error"]["code"], -32600)

    def test_an_unreachable_console_is_a_tool_error_not_a_crash(self):
        # Catches: the server dying (and the client losing every tool) when the console is down.
        r = self.call("tools/call", {"name": "health", "arguments": {}})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("cannot reach", r["content"][0]["text"])

    def serve(self, *lines: bytes) -> list[dict]:
        """Feed `lines` through serve(); every output line must be one ASCII JSON message."""
        import io
        tx = io.BytesIO()
        M.serve(self.door, io.BytesIO(b"\n".join(lines) + b"\n"), tx)
        out = tx.getvalue()
        out.decode("ascii")
        return [json.loads(x) for x in out.splitlines()]

    def test_bad_json_and_blank_lines_keep_the_stream_alive(self):
        # Catches: a parse error that ends the read loop, or one that writes a non-JSON line.
        lines = self.serve(b"not json", b"", b'{"jsonrpc":"2.0","id":9,"method":"ping"}')
        self.assertEqual([x.get("error", {}).get("code") for x in lines], [-32700, None])
        self.assertEqual(lines[1]["id"], 9)

    def test_no_hostile_line_ends_the_server(self):
        # Catches (review of 1.35.0, each one killed the process and every later reply): a list as the
        # tool name (unhashable), a lone surrogate echoed into the reply (cannot encode to UTF-8), and
        # JSON nested past the recursion limit (not a ValueError).
        ping = b'{"jsonrpc":"2.0","id":99,"method":"ping"}'
        lines = self.serve(b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":["x"]}}',
                           b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"\\ud800"}}',
                           b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"view",'
                           b'"arguments":{"\\ud800":1}}}',
                           b"[" * 200_000, ping)
        self.assertEqual([x.get("error", {}).get("code") for x in lines], [-32602, -32602, None, -32700, None])
        self.assertTrue(lines[2]["result"]["isError"])
        self.assertEqual(lines[-1]["id"], 99)

    def test_an_unexpected_failure_fails_one_request_and_says_so(self):
        # Catches: an error nobody planned for (a full disk, a bug in a handler) ending the server
        # instead of failing one call; and one swallowed without a word to the client.
        import io
        from unittest import mock
        log = io.StringIO()
        with mock.patch.object(M.sys, "stderr", new=log):
            with mock.patch.object(M.tempfile, "TemporaryDirectory", side_effect=OSError("No space left on device")):
                r = self.call("tools/call", {"name": "todo", "arguments": {}})["result"]
            with mock.patch.object(M, "handle", side_effect=KeyError("boom")):
                lines = self.serve(b'{"jsonrpc":"2.0","id":5,"method":"ping"}')
        self.assertTrue(r["isError"])
        self.assertIn("No space left", r["content"][0]["text"])
        self.assertEqual((lines[0]["id"], lines[0]["error"]["code"]), (5, -32603))
        self.assertIn("Traceback", log.getvalue())   # logged for the person running it, not swallowed

    def test_a_bare_double_dash_is_refused_not_mangled(self):
        # Catches: "--" as a text or item, which argparse swallows (3.11 hands the tool [] as text).
        for name, args in (("reply", {"item": "LANE.1", "text": "--"}), ("lesson_match", {"text": "--", "item": "X"}),
                           ("working", {"items": ["--"]})):
            r = self.call("tools/call", {"name": name, "arguments": args})["result"]
            self.assertTrue(r["isError"], name)
            self.assertIn("--", r["content"][0]["text"])


if __name__ == "__main__":
    os.environ.pop("OVERTURE_AGENT", None)
    unittest.main(verbosity=1)
