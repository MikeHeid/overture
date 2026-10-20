"""onboard.py: every answer validated by name, nothing foreign overwritten, no secret opened.

    python3 test_onboard.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import socket
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent / "plugin" / "kit"))
import onboard as O  # noqa: E402

AUD = "0123456789abcdef" * 4
GOOD = {"name": "acme", "team_domain": "acme.cloudflareaccess.com", "aud": AUD,
        "hostname": "acme-console.example.com", "port": 4793}
TID = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.project = self.root / "proj"
        self.project.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        # Never the real ~/.cloudflared or ~/.local/state.
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "XDG_STATE_HOME": str(self.home / "st")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, **over):
        return O.write(self.project, {**GOOD, **over}, check_port=False)


class CheckTests(Base):
    def test_good_answers_are_normalised(self):
        a = O.check({**GOOD, "name": " Acme ", "hostname": "ACME-Console.Example.com"})
        self.assertEqual(a["name"], "acme")
        self.assertEqual(a["hostname"], "acme-console.example.com")
        self.assertEqual(a["tunnel"], "acme-console")        # the default tunnel name
        self.assertEqual(a["page"], ".overture/page.html")
        self.assertEqual(a["adapter"], ".overture/adapter.py")

    def test_each_bad_answer_is_refused_by_its_own_name(self):
        cases = {
            "name": ["a", "1acme", "acme_", "acme-", "x" * 33, "ac me"],
            "team_domain": ["acme.example.com", "acme.cloudflareaccess.com.evil.net", ""],
            "aud": ["abc", "g" * 64, AUD + "0", AUD[:-1]],
            "hostname": ["localhost", "http://acme.example.com", "acme.example.com/x", "a b.example.com"],
            "port": [80, 70000, "x"],
            "page": ["/etc/passwd", "../outside.html", "a/../../b"],
            "adapter": ["/tmp/a.py", "..", "~/a.py"],
            "tunnel": ["Bad Tunnel", "-x"],
        }
        for key, values in cases.items():
            for v in values:
                with self.subTest(key=key, value=v):
                    with self.assertRaises(O.OnboardError) as e:
                        O.check({**GOOD, key: v})
                    self.assertTrue(str(e.exception).startswith(key + ":"), e.exception)

    def test_the_team_domain_is_not_accepted_as_the_hostname(self):
        with self.assertRaisesRegex(O.OnboardError, "^hostname: that is the team domain"):
            O.check({**GOOD, "hostname": "acme.cloudflareaccess.com"})


class WriteTests(Base):
    def test_writes_env_config_adapter_and_page(self):
        out = self.write()
        env = (self.project / ".overture/console.env").read_text()
        self.assertTrue(env.startswith(O.MARK))
        for line in ("CONSOLE_NAME=acme", f"CONSOLE_AUD={AUD}", "CONSOLE_HOSTNAME=acme-console.example.com",
                     "CONSOLE_PORT=4793", "CONSOLE_TUNNEL=acme-console"):
            self.assertIn(line + "\n", env)
        cfg = json.loads((self.project / ".overture.json").read_text())
        self.assertEqual(cfg["fold"]["adapter"], ".overture/adapter.py")
        self.assertTrue((self.project / ".overture/adapter.py").is_file())
        self.assertIn(O.MARK.lstrip("# "), (self.project / ".overture/page.html").read_text())
        # 1.6.1 added a line for appending .overture/console.env to .gitignore (so Claude Code's
        # safety check doesn't block the mid-onboard commit).
        self.assertEqual(len(out), 5, out)
        gi = (self.project / ".gitignore").read_text()
        self.assertIn(".overture/console.env", gi)

    def test_a_rerun_with_the_same_answers_changes_nothing(self):
        self.write()
        before = {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        out = self.write()
        self.assertEqual(out[0], f"unchanged {self.project.resolve() / '.overture/console.env'}")
        # The starters exist now, so a rerun names them for review rather than trusting a marker.
        # 1.6.1: a `kept .gitignore: already lists …` line also appears (idempotent gitignore append).
        bodies = [line for line in out[1:] if not line.startswith("kept")]
        self.assertEqual([line.split()[1].rsplit("/", 1)[1].rstrip(":") for line in bodies], ["adapter.py", "page.html"])
        self.assertTrue(all(line.startswith("REVIEW") for line in bodies), out)
        self.assertEqual(before, {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()})

    def test_a_rerun_with_new_answers_rewrites_its_own_file(self):
        self.write()
        self.write(hostname="other.example.com")
        self.assertIn("CONSOLE_HOSTNAME=other.example.com\n", (self.project / ".overture/console.env").read_text())

    def test_a_file_it_did_not_write_is_refused_unless_forced(self):
        env = self.project / ".overture/console.env"
        env.parent.mkdir()
        env.write_text("CONSOLE_NAME=hand-made\n")
        with self.assertRaisesRegex(O.OnboardError, "was not written by onboard.py"):
            self.write()
        self.assertEqual(env.read_text(), "CONSOLE_NAME=hand-made\n")
        O.write(self.project, GOOD, force=True, check_port=False)
        self.assertIn("CONSOLE_NAME=acme", env.read_text())

    def test_an_existing_adapter_and_page_are_left_alone(self):
        (self.project / "board.html").write_text("<p>mine</p>")
        (self.project / "tools").mkdir()
        (self.project / "tools/adapter.py").write_text("# mine\n")
        self.write(page="board.html", adapter="tools/adapter.py")
        self.assertEqual((self.project / "board.html").read_text(), "<p>mine</p>")
        self.assertEqual((self.project / "tools/adapter.py").read_text(), "# mine\n")

    def test_the_config_is_merged_never_replaced(self):
        (self.project / ".overture.json").write_text(json.dumps(
            {"keep": 1, "fold": {"locked": "custom/locked", "other": True}}))
        self.write(audit_seat="determinism", audit_brief="check replay")
        cfg = json.loads((self.project / ".overture.json").read_text())
        self.assertEqual(cfg["keep"], 1)
        self.assertEqual(cfg["fold"], {"locked": "custom/locked", "other": True,
                                       "ledger": ".overture/folded.txt", "adapter": ".overture/adapter.py"})
        self.assertEqual(cfg["audit"], {"seat": "determinism", "brief": "check replay"})

    def test_next_step_defaults_to_the_plugins_own_skills_and_never_replaces_one(self):
        # Catches: onboarding that leaves Refine and Drill refused on a fresh install (no next_step),
        # one that overwrites a project's own choice of skill, and a default the server would refuse.
        from overture import projectcfg as PC
        self.write()
        cfg = json.loads((self.project / ".overture.json").read_text())
        self.assertEqual(cfg["next_step"], {"refine": "overture:refine", "drill": "overture:drill"})
        self.assertEqual(PC.load(self.project).next_step, cfg["next_step"])
        (self.project / ".overture.json").write_text(json.dumps({"next_step": {"refine": "refine"}}))
        self.write()
        cfg = json.loads((self.project / ".overture.json").read_text())
        self.assertEqual(cfg["next_step"], {"refine": "refine", "drill": "overture:drill"})
        (self.project / ".overture.json").write_text(json.dumps({"next_step": ["refine"]}))
        with self.assertRaisesRegex(O.OnboardError, "next_step"):
            self.write()

    def test_a_broken_config_is_refused_before_anything_is_written(self):
        (self.project / ".overture.json").write_text("{not json")
        with self.assertRaisesRegex(O.OnboardError, "is not valid JSON"):
            self.write()
        self.assertFalse((self.project / ".overture").exists())

    def test_a_bad_answer_writes_nothing(self):
        with self.assertRaises(O.OnboardError):
            self.write(aud="nope")
        self.assertEqual(list(self.project.iterdir()), [])

    def test_a_port_in_use_is_refused(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            port = s.getsockname()[1]
            if port < 1024:
                self.skipTest("the OS gave a privileged port")
            with self.assertRaisesRegex(O.OnboardError, f"^port: {port} is already in use"):
                O.write(self.project, {**GOOD, "port": port})

    def test_next_steps_route_dns_with_its_own_config(self):
        steps = O.next_steps(self.project, O.check(GOOD))
        self.assertIn("register --project", steps)
        route = next(line for line in steps.splitlines() if "route dns" in line)
        self.assertIn("--config", route)
        self.assertIn("config-acme-console.yml", route)

    def test_next_steps_make_the_user_the_administrator_without_an_email_from_the_session(self):
        # Catches (1.40.0): onboarding that leaves every Access login an owner with no step to change it,
        # and a step that has the session take the user's email (operator emails never reach agents).
        steps = O.next_steps(self.project, O.check(GOOD))
        self.assertIn(" 6. Make yourself the administrator.", steps)   # a step, not an optional aside
        self.assertIn('"Make me the administrator"', steps)
        line = next(s for s in steps.splitlines() if " access " in s)
        self.assertIn("access YOU@EXAMPLE.COM owner", line)
        self.assertIn(str(O.state_dir("acme")), line)


class SymlinkTests(Base):
    """A cloned repository must not be able to steer a write outside itself (PR #1 security review, CRITICAL)."""

    TARGETS = (".overture/console.env", ".overture.json", ".overture/adapter.py", ".overture/page.html")

    def test_a_dangling_link_at_any_target_is_refused_and_nothing_is_written(self):
        for rel in self.TARGETS:
            with self.subTest(target=rel):
                shutil.rmtree(self.project)
                self.project.mkdir()
                outside = self.home / f"planted-{rel.replace('/', '_')}"
                link = self.project / rel
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(outside)                       # dangling: `outside` does not exist
                for force in (False, True):                    # --force never overrides this
                    with self.assertRaisesRegex(O.OnboardError, "is a symbolic link"):
                        O.write(self.project, GOOD, force=force, check_port=False)
                self.assertFalse(outside.exists(), f"{rel} wrote through the link")
                self.assertEqual(list(self.home.iterdir()), [], "something landed outside the project")
                self.assertFalse((self.project / ".overture/console.env").exists() and rel != ".overture/console.env")

    def test_a_linked_directory_is_refused(self):
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        (self.project / ".overture").symlink_to(elsewhere)
        with self.assertRaisesRegex(O.OnboardError, "is a symbolic link"):
            self.write()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_a_link_to_a_real_file_inside_the_project_is_refused_too(self):
        (self.project / "real.html").write_text("<p>x</p>")
        (self.project / ".overture").mkdir()
        (self.project / ".overture/page.html").symlink_to(self.project / "real.html")
        with self.assertRaisesRegex(O.OnboardError, "is a symbolic link"):
            self.write()

    def test_a_link_at_the_tunnel_config_is_refused(self):
        self.write()
        cf = self.home / ".cloudflared"
        cf.mkdir()
        (cf / f"{TID}.json").write_text("{}")
        target = self.home / "planted.yml"
        (cf / "config-acme-console.yml").symlink_to(target)
        with self.assertRaisesRegex(O.OnboardError, "is a symbolic link"):
            O.tunnel(self.project, TID, force=True)
        self.assertFalse(target.exists())


class ReviewNoticeTests(Base):
    def test_an_adapter_or_page_already_there_is_named_for_review(self):
        (self.project / ".overture").mkdir()
        (self.project / ".overture/adapter.py").write_text(f"{O.MARK}\nimport os\n")  # a marker proves nothing
        out = self.write()
        review = [line for line in out if line.startswith("REVIEW")]
        self.assertEqual(len(review), 1, out)
        self.assertIn("adapter.py", review[0])
        self.assertIn("install.sh", review[0])

    def test_files_it_just_wrote_are_not_flagged(self):
        self.assertFalse([line for line in self.write() if line.startswith("REVIEW")])


class OsErrorTests(Base):
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root writes anywhere")
    def test_a_filesystem_error_is_a_named_refusal_not_a_traceback(self):
        self.project.chmod(0o500)
        self.addCleanup(self.project.chmod, 0o700)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = O.main(["write", "--project", str(self.project), "--name", "acme", "--team-domain",
                         GOOD["team_domain"], "--aud", AUD, "--hostname", GOOD["hostname"], "--no-port-check"])
        self.assertEqual(rc, 2)
        self.assertTrue(err.getvalue().startswith("onboard: "), err.getvalue())
        self.assertIn("Permission denied", err.getvalue())


@unittest.skipUnless(shutil.which("bash"), "no bash")
class InstallGuardTests(Base):
    """install.sh refuses a path systemd or sed cannot take, BEFORE it copies, builds or writes anything."""

    def run_install(self, project):
        env = {**os.environ, "HOME": str(self.home), "XDG_DATA_HOME": str(self.home / "share"),
               "XDG_CONFIG_HOME": str(self.home / "cfg"), "XDG_STATE_HOME": str(self.home / "st"),
               "PATH": os.environ.get("PATH", "")}
        return subprocess.run(["bash", str(Path(O.__file__).parent / "deploy/install.sh"), "--project", str(project)],
                              env=env, capture_output=True, text=True, timeout=60)

    def test_unsafe_project_paths_are_refused_before_anything_happens(self):
        for name in ("pipe|dir", "amp&dir", "sp ace", "pct%dir", "back\\slash"):
            with self.subTest(name=name):
                project = self.root / name
                project.mkdir()
                O.write(project, GOOD, check_port=False)
                r = self.run_install(project)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("holds a character a systemd unit cannot take safely", r.stderr)
                for d in ("share", "cfg", "st"):
                    self.assertFalse((self.home / d).exists(), f"{d} was written before the refusal")

    def test_macos_is_refused_by_name_and_pointed_to_the_launchd_service(self):
        # Catches (1.51, D2): install.sh on a Mac copying the kit and writing systemd units that nothing runs,
        # instead of naming `server.py service install` (launchd), before anything is written.
        O.write(self.project, GOOD, check_port=False)
        fake = self.root / "fakebin"
        fake.mkdir()
        (fake / "uname").write_text("#!/bin/sh\necho Darwin\n")
        (fake / "uname").chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{fake}{os.pathsep}{os.environ.get('PATH', '')}"}):
            r = self.run_install(self.project)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("macOS", r.stderr)
        self.assertIn("server.py service install", r.stderr)
        for d in ("share", "cfg", "st"):
            self.assertFalse((self.home / d).exists(), f"{d} was written before the refusal")


class ReadEnvTests(Base):
    def test_show_returns_only_validated_keys(self):
        self.write()
        env = self.project / ".overture/console.env"
        env.write_text(env.read_text() + "EVIL=$(rm -rf ~)\nExecStartPre=/bin/sh\n")
        got = O.read_env(env)
        self.assertEqual(set(got), {"CONSOLE_NAME", "CONSOLE_TEAM_DOMAIN", "CONSOLE_AUD", "CONSOLE_HOSTNAME",
                                    "CONSOLE_PORT", "CONSOLE_TUNNEL", "CONSOLE_PAGE", "CONSOLE_ADAPTER"})

    def test_a_hand_edited_bad_value_is_refused_on_read(self):
        self.write()
        env = self.project / ".overture/console.env"
        env.write_text(env.read_text().replace("CONSOLE_NAME=acme", "CONSOLE_NAME=acme;touch /tmp/x"))
        with self.assertRaisesRegex(O.OnboardError, "^name:"):
            O.read_env(env)

    def test_show_on_a_project_never_onboarded(self):
        with self.assertRaisesRegex(O.OnboardError, "run `onboard.py write` first"):
            O.read_env(self.project / ".overture/console.env")


class TunnelTests(Base):
    def setUp(self):
        super().setUp()
        self.write()
        self.cf = self.home / ".cloudflared"
        self.cf.mkdir()

    def test_a_bad_id_is_refused(self):
        for bad in ("acme-console", "../../etc/passwd", TID + "x"):
            with self.subTest(bad=bad), self.assertRaisesRegex(O.OnboardError, "^id:"):
                O.tunnel(self.project, bad)

    def test_no_credentials_file_is_refused(self):
        with self.assertRaisesRegex(O.OnboardError, "no credentials file"):
            O.tunnel(self.project, TID)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read a mode-000 file")
    def test_the_credentials_file_is_never_opened(self):
        creds = self.cf / f"{TID}.json"
        creds.write_text('{"TunnelSecret": "SENTINEL-SECRET"}')
        creds.chmod(0)                       # any open() of it would raise PermissionError
        self.addCleanup(creds.chmod, stat.S_IRUSR | stat.S_IWUSR)
        O.tunnel(self.project, TID.upper())
        cfg = (self.cf / "config-acme-console.yml").read_text()
        self.assertNotIn("SENTINEL", cfg)
        self.assertIn(TID, cfg)
        self.assertIn(str(creds), cfg)
        self.assertIn("acme-console.example.com", cfg)
        self.assertIn("127.0.0.1:4793", cfg)

    def test_a_foreign_tunnel_config_is_not_overwritten(self):
        (self.cf / f"{TID}.json").write_text("{}")
        (self.cf / "config-acme-console.yml").write_text("tunnel: someone-else\n")
        with self.assertRaisesRegex(O.OnboardError, "was not written by onboard.py"):
            O.tunnel(self.project, TID)


class CliTests(Base):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = O.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_a_refusal_exits_2_and_names_the_value(self):
        rc, out, err = self.run_main("write", "--project", str(self.project), "--name", "Bad Name",
                                     "--team-domain", GOOD["team_domain"], "--aud", AUD,
                                     "--hostname", GOOD["hostname"], "--no-port-check")
        self.assertEqual(rc, 2)
        self.assertTrue(err.startswith("onboard: name:"), err)
        self.assertEqual(out, "")

    def test_write_then_show(self):
        rc, out, _ = self.run_main("write", "--project", str(self.project), "--name", "acme",
                                   "--team-domain", GOOD["team_domain"], "--aud", AUD,
                                   "--hostname", GOOD["hostname"], "--no-port-check")
        self.assertEqual(rc, 0)
        self.assertIn("Next, run these yourself", out)
        rc, out, _ = self.run_main("show", "--project", str(self.project))
        self.assertEqual(rc, 0)
        self.assertIn("CONSOLE_NAME=acme\n", out)

    def _write(self, *extra):
        return self.run_main("write", "--project", str(self.project), "--name", "acme",
                             "--team-domain", GOOD["team_domain"], "--aud", AUD,
                             "--hostname", GOOD["hostname"], "--no-port-check", *extra)

    def test_a_master_agent_name_lands_in_the_register_step_only(self):
        # The steward is named in the owner's own registry, never by the repository (0.8.3):
        # --steward goes into the printed `register` command and nowhere in the project's files.
        rc, out, _ = self._write("--steward", "agent-1")
        self.assertEqual(rc, 0)
        self.assertIn('register --project', out)
        self.assertIn("--steward agent-1\n", out)
        self.assertIn("/overture:as agent-1", out)
        for f in self.project.rglob("*"):
            if f.is_file():
                self.assertNotIn("agent-1", f.read_text(errors="replace"), f)

    def test_no_master_agent_prints_no_steward_flag(self):
        rc, out, _ = self._write()
        self.assertEqual(rc, 0)
        self.assertNotIn("--steward", out)
        self.assertNotIn("/overture:as", out)

    def test_a_bad_master_agent_name_is_refused_before_anything_is_written(self):
        for bad in ("Agent One", "owner", "x" * 40):
            with self.subTest(bad=bad):
                rc, out, err = self._write("--steward", bad)
                self.assertEqual(rc, 2)
                self.assertTrue(err.startswith("onboard: steward:"), err)
                self.assertFalse((self.project / ".overture/console.env").exists())


ZT = "10.147.17.10"
FAKE = [("lo", "127.0.0.1", 8, True), ("eth0", "172.23.0.5", 20, True), ("ztexample0", ZT, 16, True),
        ("docker0", "172.17.0.1", 16, True), ("br-5a1f", "10.147.0.1", 16, False),
        ("tailscale0", "100.101.102.103", 32, True)]


class LinkModeTests(Base):
    """1.47.0 (L7): onboarding a console that signs in by link: write, show, detect, verify, next steps."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(Path(O.__file__).parent))
        from overture import netif as NI
        self.NI = NI
        NI.set_fake(lambda: list(FAKE))
        self.addCleanup(NI.set_fake, None)

    def link(self, **over):
        return O.write(self.project, {"name": "acme", "auth": "link", **over}, check_port=False)

    def env(self):
        return (self.project / ".overture/console.env").read_text()

    def test_link_mode_needs_no_access_values_and_writes_its_own_keys(self):
        # Catches (L7): link mode still demanding --team-domain/--aud/--hostname/--tunnel, one of them written
        # (and forgotten) anyway, CONSOLE_AUTH/ORIGIN/LISTEN missing, an origin default other than
        # http://LISTEN:PORT (else http://127.0.0.1:PORT), and a Cloudflare console.env changed by any of it.
        self.link()
        env = self.env()
        for line in ("CONSOLE_NAME=acme", "CONSOLE_AUTH=link", "CONSOLE_ORIGIN=http://127.0.0.1:4793",
                     "CONSOLE_PORT=4793"):
            self.assertIn(line + "\n", env)
        for absent in ("CONSOLE_LISTEN", "CONSOLE_AUD", "CONSOLE_HOSTNAME", "CONSOLE_TUNNEL", "CONSOLE_TEAM"):
            self.assertNotIn(absent, env)
        self.link(listen=ZT, port=4800)
        self.assertIn(f"CONSOLE_LISTEN={ZT}\nCONSOLE_ORIGIN=http://{ZT}:4800\n", self.env())
        # Catches (1.47, S1): --listen with an https origin written, a console whose `tailscale serve` proxy would
        # get 403 on every write; it is refused by name, and without --listen the same origin is written.
        with self.assertRaisesRegex(O.OnboardError, "^origin: .*`tailscale serve` forwards to 127.0.0.1"):
            self.link(listen=ZT, origin="https://box.tailnet.ts.net/")
        self.link(origin="https://box.tailnet.ts.net/")
        self.assertIn("CONSOLE_ORIGIN=https://box.tailnet.ts.net\n", self.env())
        for key, value in (("aud", AUD), ("hostname", "acme.example.com"), ("team_domain", GOOD["team_domain"]),
                           ("tunnel", "acme-console")):
            with self.subTest(key=key), self.assertRaisesRegex(O.OnboardError, f"^{key}: is for --auth cloudflare"):
                self.link(**{key: value})
        shutil.rmtree(self.project)
        self.project.mkdir()
        self.write()
        self.assertNotIn("CONSOLE_AUTH", self.env())   # Cloudflare: 1.46's file, byte for byte
        self.assertEqual(O.env_text(O.check(GOOD)), self.env())
        with self.assertRaisesRegex(O.OnboardError, "^listen: is for --auth link"):
            O.check({**GOOD, "listen": ZT})

    def test_listen_and_origin_are_checked_by_name_before_anything_is_written(self):
        # Catches (contract 1, L15, L17): a refused --listen (0.0.0.0, public, loopback, IPv6, an address on
        # docker0) or an origin that is http on another IP, or loopback beside --listen, written; an address no
        # interface holds yet refused (the server waits for it) or left unsaid; and the overlap warning missing.
        for listen, why in (("0.0.0.0", "every interface"), ("8.8.8.8", "public"), ("127.0.0.1", "loopback"),
                            ("::1", "IPv6"), ("172.17.0.1", "it is on docker0")):
            with self.subTest(listen=listen), self.assertRaisesRegex(O.OnboardError, f"^listen: .*{why}"):
                self.link(listen=listen)
        for listen, origin in ((None, f"http://{ZT}:4793"), (ZT, "http://10.0.0.1:4793"),
                               (ZT, "http://127.0.0.1:4793")):
            with self.subTest(origin=origin), self.assertRaisesRegex(O.OnboardError, "^origin:"):
                self.link(listen=listen, origin=origin)
        self.assertEqual(list(self.project.iterdir()), [])
        out = self.link(listen="10.147.17.5")
        self.assertTrue(any(l.startswith("NOTE") and "waits up to 2 minutes" in l for l in out), out)
        out = self.link(listen=ZT)
        self.assertEqual([l for l in out if "warning" in l and "br-5a1f (down)" in l and "10.147.0.0/16" in l
                          ], [l for l in out if "warning" in l])
        self.assertEqual(len([l for l in out if "warning" in l]), 1, out)

    def test_show_carries_the_link_keys_through_and_refuses_a_hand_edit(self):
        # Catches: `show` (which install.sh reads) dropping CONSOLE_AUTH/LISTEN/ORIGIN (the unit would start
        # behind Cloudflare it does not have), an unknown CONSOLE_AUTH read as Cloudflare, an Access key left in a
        # link file passed on, and a hand-edited listen passed on unchecked.
        self.link(listen=ZT)
        env = self.project / ".overture/console.env"
        got = O.read_env(env)
        self.assertEqual(got, {"CONSOLE_NAME": "acme", "CONSOLE_AUTH": "link", "CONSOLE_LISTEN": ZT,
                               "CONSOLE_ORIGIN": f"http://{ZT}:4793", "CONSOLE_PORT": "4793",
                               "CONSOLE_PAGE": ".overture/page.html", "CONSOLE_ADAPTER": ".overture/adapter.py"})
        text = env.read_text()
        for bad, why in (("CONSOLE_AUTH=link", "CONSOLE_AUTH=Link"), (f"CONSOLE_LISTEN={ZT}", "CONSOLE_LISTEN=0.0.0.0"),
                         ("CONSOLE_NAME=acme", f"CONSOLE_NAME=acme\nCONSOLE_AUD={AUD}")):
            env.write_text(text.replace(bad, why))
            with self.subTest(why=why), self.assertRaises(O.OnboardError):
                O.read_env(env)
        env.write_text(text)
        with self.assertRaisesRegex(O.OnboardError, "no tunnel"):
            O.tunnel(self.project, TID)

    def test_detect_lists_the_overlay_addresses_and_their_overlaps(self):
        # Catches (L7, L17): detect missing an overlay (or listing eth0/docker0), the line shape the skill reads,
        # no overlap warning for a bridge on the ZeroTier range, and --json not the same facts.
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(O.main(["detect"]), 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[:2], [f"zerotier ztexample0 {ZT}/16", "tailscale tailscale0 100.101.102.103/32"])
        self.assertEqual(len(lines), 3)
        self.assertIn("br-5a1f (down)", lines[2])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            O.main(["detect", "--json"])
        doc = json.loads(out.getvalue())
        self.assertEqual([(o["kind"], o["name"], o["address"], o["prefix"]) for o in doc["overlays"]],
                         [("zerotier", "ztexample0", ZT, 16), ("tailscale", "tailscale0", "100.101.102.103", 32)])
        self.assertEqual(len(doc["warnings"]), 1)

    def test_next_steps_print_the_owners_commands_for_each_way_in(self):
        # Catches (L7): link-mode steps still sending the owner to Cloudflare, no `invite` step (or one that a
        # session would run), no `tailscale serve` line for Tailscale without --listen, no http://ADDR:PORT for
        # ZeroTier, and no "sign in once per address" note.
        for over, want in (({"listen": ZT}, f"open http://{ZT}:4793 on any device joined to this ZeroTier"),
                           ({"listen": "100.101.102.103"}, "on your tailnet"),
                           ({"origin": "https://box.tailnet.ts.net"}, "tailscale serve --bg http://127.0.0.1:4793"),
                           ({}, "open http://127.0.0.1:4793 on this machine")):
            with self.subTest(over=over):
                steps = O.next_steps(self.project, O.check({"name": "acme", "auth": "link", **over}))
                self.assertIn(want, steps)
                self.assertIn("install.sh", steps)
                self.assertIn("invite YOU@EXAMPLE.COM --origin", steps)
                self.assertIn("a Claude session is refused", steps)
                self.assertIn("Sign in once per address", steps)
                for cf in ("cloudflared", "Access application", "route dns"):
                    self.assertNotIn(cf, steps)

    def test_verify_skips_cloudflare_and_checks_the_door_and_link_mode_on_each_address(self):
        # Catches (L7): verify in link mode failing on cloudflared/the tunnel, not checking the door on its
        # addresses, reading a 403 as link mode (a Cloudflare console 403s too), and spending anything to learn
        # it (a real invite: the bogus token has the shape but no invite).
        self.link(listen=ZT)
        answers = {("127.0.0.1", "/api/view"): 403, ("127.0.0.1", f"/signin?t={O.BOGUS_TOKEN}"): 410,
                   (ZT, "/api/view"): 403, (ZT, f"/signin?t={O.BOGUS_TOKEN}"): 403}
        with mock.patch.object(O, "door_answer", lambda h, p, path: answers[(h, path)]):
            got = {step: status for step, status, _ in O.verify(self.project)}
        self.assertEqual(got, {"config": "ok", "cloudflare": "skip", "tunnel": "skip", "door": "ok",
                               "sign-in links": "ok", f"door {ZT}": "ok", f"sign-in links {ZT}": "fail"})
        with mock.patch.object(O, "door_answer", lambda h, p, path: "ConnectionRefusedError: refused"):
            got = O.verify(self.project)
        self.assertIn("nothing answers on http://127.0.0.1:4793", got[3][2])
        self.assertTrue(O.BOGUS_TOKEN.startswith("ovi_") and len(O.BOGUS_TOKEN) == 47)

    def test_verify_answers_410_from_a_real_link_mode_door(self):
        # Catches: the bogus token not the shape the server parses (a 400 or 403 instead of 410), so verify
        # could never pass against a real console.
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import threading
        from overture import server as SV
        import test_server as TS
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": td}):
            d = Path(td)
            cfg = SV.Config(root=d, page=None, state=d / "s", adapter=d / "u.py", team_domain="", aud="",
                            hostname="", port=0, auth="link", origin="http://127.0.0.1:1")
            console = SV.Console(cfg, TS.FakeAdapter())
            srv = SV.owner_server(console, SV.link_verifier(cfg), 0)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                port = srv.server_address[1]
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(O.door_answer("127.0.0.1", port, "/api/view"), 403)
                    self.assertEqual(O.door_answer("127.0.0.1", port, f"/signin?t={O.BOGUS_TOKEN}"), 410)
            finally:
                srv.shutdown()
                srv.server_close()

    def test_the_cli_takes_auth_link_without_access_flags_and_cloudflare_still_needs_them(self):
        # Catches: the parser still requiring --team-domain/--aud/--hostname with --auth link, and Cloudflare
        # (the default) no longer requiring them in argparse's own words.
        rc, out, err = CliTests.run_main(self, "write", "--project", str(self.project), "--name", "acme", "--auth",
                                         "link", "--listen", ZT, "--no-port-check")
        self.assertEqual(rc, 0, err)
        self.assertIn(f"http://{ZT}:4793", out)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as e:
            O.main(["write", "--project", str(self.project), "--name", "acme", "--aud", AUD])
        self.assertEqual(e.exception.code, 2)
        self.assertIn("the following arguments are required: --team-domain, --hostname", err.getvalue())


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "no bash")
class InstallLinkTests(Base):
    """install.sh renders a link-mode unit from `onboard.py show` (1.47.0, L7)."""

    def test_a_link_console_gets_the_link_unit_with_its_flags_and_no_tunnel(self):
        # Catches: install.sh rendering the Cloudflare unit (--team-domain ...) for a link console, dropping
        # --listen/--origin, writing a tunnel unit there is no tunnel for, and a flag the server does not define.
        O.write(self.project, {"name": "acme", "auth": "link", "origin": "https://box.tailnet.ts.net"},
                check_port=False)
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        units = self.home / "cfg" / "systemd" / "user"
        self.assertEqual(sorted(p.name for p in units.iterdir()), ["acme-console.service"])
        unit = (units / "acme-console.service").read_text()
        self.assertIn("--auth link", unit)
        self.assertIn("--project acme --origin https://box.tailnet.ts.net\n", unit)
        self.assertNotIn("--team-domain", unit)
        self.assertNotIn("@", unit.split("ExecStart=", 1)[1].split("\n[Install]")[0])

    def test_start_with_listen_says_the_server_may_still_be_waiting_rather_than_none(self):
        # Catches (1.47, C5): `install.sh --start` printing "loopback ... answers none (want 403)" while a --listen
        # server is still in its L16 wait for ZeroTier (it binds nothing until then), which reads as a fault;
        # and the control: a console that answers 403 still gets the plain check line.
        O.write(self.project, {"name": "acme", "auth": "link", "listen": "10.147.17.10"}, check_port=False)
        r = self.install("--start", curl="exit 7")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("check: no answer on loopback yet (none): the server may still be waiting for "
                      "10.147.17.10 on ZeroTier or Tailscale (up to 2 minutes)", r.stdout)
        self.assertNotIn("want 403)\n", r.stdout)
        r = self.install("--start", curl="printf 403")
        self.assertIn("check: loopback without a token answers 403 (want 403)", r.stdout)

    def install(self, *extra, curl="exit 0"):
        bindir = self.root / "bin"
        bindir.mkdir(exist_ok=True)
        for tool, body in (("systemctl", "exit 0"), ("curl", curl), ("sleep", "exit 0")):
            (bindir / tool).write_text(f"#!/bin/sh\n{body}\n")
            (bindir / tool).chmod(0o755)
        kit = Path(O.__file__).parent
        share = self.home / "share" / "overture"
        (share / "venv" / "bin").mkdir(parents=True, exist_ok=True)
        # The venv's interpreter: its one `-c` (the PyJWT version check) answered here, so no network install.
        (share / "venv" / "bin" / "python").write_text(f'#!/bin/sh\n[ "$1" = -c ] && exit 0\nexec {sys.executable} "$@"\n')
        (share / "venv" / "bin" / "python").chmod(0o755)
        (share / "venv" / "bin" / "pip").write_text("#!/bin/sh\nexit 0\n")
        (share / "venv" / "bin" / "pip").chmod(0o755)
        env = {**os.environ, "HOME": str(self.home), "XDG_DATA_HOME": str(self.home / "share"),
               "XDG_CONFIG_HOME": str(self.home / "cfg"), "XDG_STATE_HOME": str(self.home / "st"),
               "PATH": f"{bindir}:{os.environ.get('PATH', '')}"}
        return subprocess.run(["bash", str(kit / "deploy/install.sh"), "--project", str(self.project), *extra],
                              env=env, capture_output=True, text=True, timeout=120)


class InstallNoticeTests(unittest.TestCase):
    """The one-time banner after installing or upgrading the plugin (plugin/hooks/install_notice.py).

    Catches: a banner whose commands do not exist. Until this test the first-install banner told new
    users to run `~/.local/share/overture/kit/plugin/kit/agent.py register` (no such path, and
    register needs --state and --project) and `systemctl --user start overture.service` (no such
    unit), and never named /overture:console-onboard, so a fresh install left people lost.
    """

    HOOK = Path(__file__).resolve().parent / "plugin" / "hooks" / "install_notice.py"

    def banner(self, prior: str | None = None) -> str:
        with tempfile.TemporaryDirectory() as td:
            if prior:
                (Path(td) / "overture").mkdir()
                (Path(td) / "overture" / f"install-notice-seen-{prior}").write_text("x")
            env = {**os.environ, "XDG_STATE_HOME": td}
            return subprocess.run([sys.executable, str(self.HOOK)], env=env, capture_output=True,
                                  text=True, timeout=30, check=True).stdout

    def test_a_first_install_points_at_onboarding(self):
        out = self.banner()
        self.assertIn("/overture:console-onboard", out)
        skill = self.HOOK.parent.parent / "skills" / "console-onboard" / "SKILL.md"
        self.assertTrue(skill.is_file(), skill)
        for wrong in ("overture.service", "kit/plugin/kit", "agent.py register"):
            self.assertNotIn(wrong, out)

    def test_an_upgrade_names_an_install_script_that_exists(self):
        out = self.banner(prior="0.0.1")
        self.assertIn("Upgraded to Overture", out)
        line = next(l for l in out.splitlines() if "install.sh" in l and "bash" in l)
        script = Path(line.split('"')[1])
        self.assertTrue(script.is_file(), script)
        self.assertNotIn("overture.service", out)

    def test_the_upgrade_names_systemctl_restart_on_linux_and_service_install_on_a_mac(self):
        # Catches: on Linux, a restart line that drifts from `systemctl --user restart overture-console` (the
        # main server would keep the old kit); on a Mac, any systemctl or install.sh line (neither works there)
        # in place of `service install --start` from the new kit.
        import importlib.util
        spec = importlib.util.spec_from_file_location("install_notice_t", self.HOOK)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.path.insert(0, str(self.HOOK.parent.parent / "kit"))
        self.addCleanup(sys.path.remove, str(self.HOOK.parent.parent / "kit"))
        import hosting
        for plat in ("darwin", "linux"):
            with self.subTest(plat=plat), mock.patch.object(sys, "platform", plat):
                body = "\n".join(mod._upgrade_lines(["0.0.1"])) + "\n"
                if plat == "darwin":
                    # Catches (1.51): a Mac told to run deploy/install.sh, which refuses on macOS, so the upgrade
                    # never reaches the service; `service install --start` from the new kit re-points the
                    # LaunchAgent and restarts it, and the server.py it names exists.
                    line = next(l for l in body.splitlines() if "service install --start" in l)
                    self.assertTrue(Path(line.split('"')[1]).is_file(), line)
                    self.assertIn(str(Path(hosting.__file__).resolve().parent / "server.py"), line)
                    self.assertNotIn("install.sh", body)
                    self.assertNotIn("systemctl", body)
                else:                                                   # unchanged from 1.50
                    self.assertIn("    systemctl --user restart overture-console\n", body)
                    self.assertNotIn("launchctl", body)

    def test_it_shows_once_per_version(self):
        with tempfile.TemporaryDirectory() as td:
            env = {**os.environ, "XDG_STATE_HOME": td}
            run = lambda: subprocess.run([sys.executable, str(self.HOOK)], env=env, capture_output=True,
                                         text=True, timeout=30, check=True).stdout
            self.assertIn("Welcome", run())
            self.assertEqual(run(), "")


class WindowsOnboardTests(Base):
    """1.53.2: onboarding on native Windows names WSL once, instead of commands a WSL shell cannot run."""

    def test_next_steps_say_once_to_onboard_again_inside_wsl(self):
        # Catches: the POSIX steps printed there: `bash "C:\...\install.sh"` and Windows --state paths, which
        # cannot be pasted into WSL, in either way in.
        for answers in (GOOD, {"name": "acme", "auth": "link"}):
            a = O.check(answers)   # Path("...") would be a WindowsPath under "nt", which POSIX cannot make
            with self.subTest(auth=a["auth"]), mock.patch.object(O.os, "name", "nt"):
                steps = O.next_steps(self.project, a)
                self.assertIn("Run onboarding again inside\nWSL", steps)
                self.assertIn("/overture:console-onboard", steps)
                self.assertNotIn('bash "', steps)
                self.assertNotIn("--state", steps)

    def test_verify_does_not_raise_without_getuid(self):
        # Catches: `os.getuid()` in verify, an AttributeError on native Windows, where there is no uid and
        # no console socket to find.
        self.write()
        env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        real = os.getuid
        del os.getuid
        try:
            with mock.patch.dict(os.environ, env, clear=True), mock.patch("shutil.which", lambda _: None), \
                    mock.patch("subprocess.run", side_effect=OSError("no systemctl")):
                got = {step: (status, detail) for step, status, detail in O.verify(self.project)}
        finally:
            os.getuid = real
        self.assertEqual(got["agent socket"][0], "fail")
        self.assertIn("run verify inside WSL", got["agent socket"][1])


def prereqs_module():
    sys.path.insert(0, str(O.KIT))
    from overture import prereqs as PQ
    return PQ


class PrereqTests(unittest.TestCase):
    """1.53.2: what this machine still needs, with the fix for THIS platform and a link (owner, 2026-10-20)."""

    def scan(self, plat, have=(), routes=False, systemd=False):
        PQ = prereqs_module()
        which = lambda name: f"/usr/bin/{name}" if name in have else None
        with mock.patch.object(PQ.shutil, "which", which), mock.patch.object(PQ, "_systemd_user", lambda: systemd):
            return {i["name"]: i for i in PQ.scan(routes=routes, plat=plat)}

    def test_each_platform_gets_its_own_items_and_fixes(self):
        # Catches: one platform's fix printed on another (apt on a Mac, brew on Windows), WSL told nothing of
        # wsl.conf, Windows not told of WSL, Git for Windows, python3 or that Claude Code belongs in WSL, and a
        # required item marked optional (gh is the only optional one).
        linux, wsl, mac, win = (self.scan(p) for p in ("linux", "wsl", "macos", "windows"))
        self.assertEqual(set(linux), {"Python 3.11 or newer", "git", "gh, the GitHub CLI", "systemd --user"})
        self.assertTrue(linux["git"]["fix"][0].startswith("sudo apt install git"))
        self.assertEqual(wsl["systemd --user"]["link"], "https://learn.microsoft.com/en-us/windows/wsl/systemd")
        self.assertIn("/etc/wsl.conf", wsl["systemd --user"]["why"])
        self.assertNotIn("wsl.conf", linux["systemd --user"]["why"] + " ".join(linux["systemd --user"]["fix"]))
        self.assertEqual(set(mac), {"Python 3.11 or newer", "git", "gh, the GitHub CLI", "launchd"})
        self.assertEqual((mac["git"]["fix"], mac["gh, the GitHub CLI"]["fix"]), (["brew install git"], ["brew install gh"]))
        self.assertTrue(win["WSL"]["fix"][0].startswith("wsl --install"))
        self.assertEqual(win["Git for Windows (git and Git Bash)"]["fix"], ["winget install --id Git.Git -e"])
        self.assertEqual(win["python3 on PATH"]["link"], "https://apps.microsoft.com/search?query=python")
        self.assertEqual(win["gh, the GitHub CLI"]["fix"], ["winget install --id GitHub.cli -e"])
        self.assertEqual(win["Claude Code inside WSL"]["link"], "https://code.claude.com/docs/en/setup")
        for got in (linux, wsl, mac, win):
            self.assertEqual({n for n, i in got.items() if not i["required"]}, {"gh, the GitHub CLI"})
            self.assertTrue(got["Python 3.11 or newer"]["ok"])
            self.assertTrue(all(not i["ok"] for n, i in got.items() if n != "Python 3.11 or newer"))
        self.assertTrue(self.scan("linux", have=("git", "gh"), systemd=True)["systemd --user"]["ok"])
        routes = self.scan("macos", routes=True)
        self.assertEqual(routes["cloudflared"]["fix"], ["brew install cloudflared"])
        self.assertFalse(any(routes[n]["required"] for n in ("cloudflared", "tailscale", "zerotier-cli")))
        self.assertNotIn("cloudflared", self.scan("macos"))   # route tools only when asked for

    def test_gh_on_debian_and_ubuntu_is_githubs_apt_repository_not_the_distributions(self):
        # Catches (1.53.2 review F1): `sudo apt install gh` printed on Linux or WSL, which installs the
        # distribution's gh (2.4 to 2.46), one GitHub calls broken; the fix is GitHub's own apt repository.
        for plat in ("linux", "wsl"):
            gh = self.scan(plat)["gh, the GitHub CLI"]
            with self.subTest(plat=plat):
                self.assertEqual(gh["fix"], [])
                self.assertEqual(gh["link"], "https://github.com/cli/cli/blob/trunk/docs/install_linux.md")
                self.assertIn("add GitHub's apt repository first", gh["why"])
        self.assertEqual(self.scan("macos")["gh, the GitHub CLI"]["link"], "https://cli.github.com")

    def test_the_python_apt_line_says_which_releases_ship_3_11(self):
        # Catches (1.53.2 review F2): a bare `sudo apt install python3`, which gives 3.10 on Ubuntu 22.04 and
        # 3.9 on Debian 11, both too old, with nothing saying so.
        for plat in ("linux", "wsl"):
            with self.subTest(plat=plat):
                fix = self.scan(plat)["Python 3.11 or newer"]["fix"]
                self.assertEqual(fix, ["sudo apt install python3   # Ubuntu 24.04+ and Debian 12+ ship 3.11 or "
                                       "newer; else see the link"])

    def test_windows_says_how_to_get_wsl_and_python3_and_lists_wsl_first(self):
        # Catches (1.53.2 review F3, F4, F7): `wsl --install` without "PowerShell as administrator" (it fails
        # elsewhere); the out-of-date "a python.org install gives only python and py" (its install manager ships
        # python3; only the old full installer lacks it); and "Claude Code inside WSL" listed before WSL itself.
        PQ = prereqs_module()
        with mock.patch.object(PQ.shutil, "which", lambda n: None):
            names = [i["name"] for i in PQ.scan(plat="windows")]
        self.assertEqual(names[1:3], ["WSL", "Claude Code inside WSL"])
        win = self.scan("windows")
        self.assertEqual(win["WSL"]["fix"], ["wsl --install   # in PowerShell, run as administrator"])
        why = win["python3 on PATH"]["why"]
        self.assertIn("Python's install manager (from python.org or the Microsoft Store) provides it", why)
        self.assertIn("the old full installer gives only `python` and `py`", why)

    def test_wsl_systemd_is_edited_under_boot_never_appended_blind(self):
        # Catches (1.53.2 review F5): `printf '[boot]...' | sudo tee -a /etc/wsl.conf`, which adds a second
        # [boot] section to a wsl.conf that has one; Debian left without systemd-sysv; the old docs link.
        it = self.scan("wsl")["systemd --user"]
        self.assertEqual(it["fix"], [])
        self.assertNotIn("tee", it["why"])
        for words in ("add `systemd=true` under `[boot]` in /etc/wsl.conf (create the section if it isn't there)",
                      "then run `wsl --shutdown` from Windows", "Debian needs `systemd-sysv` too"):
            self.assertIn(words, it["why"])
        self.assertEqual(it["link"], "https://learn.microsoft.com/en-us/windows/wsl/systemd")

    def test_the_cloudflared_link_is_the_page_itself_not_a_redirect(self):
        # Catches (1.53.2 review F9): the old connect-networks downloads link, which only redirects.
        self.assertEqual(self.scan("linux", routes=True)["cloudflared"]["link"],
                         "https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/"
                         "downloads/")

    def test_the_scan_ends_with_one_total_line(self):
        # Catches (1.53.2 review F8): `onboard.py prereqs` and the banner block ending on the last item, with no
        # count, or a count that mixes required with optional.
        PQ = prereqs_module()
        it = lambda req, ok: {"name": "n", "required": req, "ok": ok, "why": "w", "fix": [], "link": "L"}
        self.assertEqual(PQ.total_line([it(True, True), it(False, False)]), "nothing required is missing")
        self.assertEqual(PQ.total_line([it(True, False), it(True, False), it(False, False), it(False, True)]),
                         "2 required, 1 optional missing")
        self.assertEqual(PQ.missing_block([it(True, False)])[-1], "1 required, 0 optional missing")
        everything = ("git", "gh", "cloudflared", "tailscale", "zerotier-cli")
        for have, systemd, last in ((everything, True, "nothing required is missing"),
                                    (("git", "gh"), False, "1 required, 3 optional missing"),
                                    ((), False, "2 required, 4 optional missing")):
            out = io.StringIO()
            with self.subTest(have=have), mock.patch.object(PQ, "detect", lambda: "linux"), \
                    mock.patch.object(PQ.shutil, "which", lambda n: "/usr/bin/" + n if n in have else None), \
                    mock.patch.object(PQ, "_systemd_user", lambda: systemd), contextlib.redirect_stdout(out):
                O.main(["prereqs"])
            self.assertEqual(out.getvalue().splitlines()[-1], last)

    def test_detect_tells_wsl_from_linux(self):
        # Catches: WSL taken for plain Linux (no wsl.conf fix), by either sign, or Windows and macOS misread.
        PQ = prereqs_module()
        with tempfile.TemporaryDirectory() as td:
            rel = Path(td) / "osrelease"
            for system, env, kernel, want in (("Windows", {}, "", "windows"), ("Darwin", {}, "", "macos"),
                                              ("Linux", {"WSL_DISTRO_NAME": "Ubuntu"}, "6.1.0", "wsl"),
                                              ("Linux", {}, "6.6.87.2-microsoft-standard-WSL2", "wsl"),
                                              ("Linux", {}, "6.1.0-18-amd64", "linux")):
                rel.write_text(kernel)
                plain = {k: v for k, v in os.environ.items() if k != "WSL_DISTRO_NAME"}
                with self.subTest(want=want, kernel=kernel), mock.patch.object(PQ.platform, "system", lambda: system), \
                        mock.patch.object(PQ, "OSRELEASE", rel), mock.patch.dict(os.environ, {**plain, **env}, clear=True):
                    self.assertEqual(PQ.detect(), want)

    def test_the_one_subprocess_has_a_one_second_timeout(self):
        # Catches: a `systemctl --user` call with no timeout (or a longer one), which could hold the 5 s banner
        # hook past its own limit, and more than two subprocesses in one scan.
        PQ = prereqs_module()
        calls = []
        run = lambda *a, **k: calls.append(k.get("timeout")) or subprocess.CompletedProcess(a[0], 0)
        with mock.patch.object(PQ.shutil, "which", lambda n: "/usr/bin/" + n), mock.patch.object(PQ.subprocess, "run", run):
            for plat in ("linux", "wsl", "macos", "windows"):
                PQ.scan(routes=True, plat=plat)
        self.assertEqual(calls, [1.0, 1.0])   # linux and wsl, one each

    def test_onboard_prereqs_exits_1_only_when_a_required_one_is_missing(self):
        # Catches: `onboard.py prereqs` exiting 0 with git missing (a script cannot tell), 1 for a missing
        # optional one, its --json not the scan's own items, and the route tools left out of it.
        PQ = prereqs_module()
        for have, want in ((("git", "gh"), 0), (("git",), 0), (("gh",), 1)):
            out = io.StringIO()
            which = lambda n: "/usr/bin/" + n if n in have else None
            with self.subTest(have=have), mock.patch.object(PQ, "detect", lambda: "linux"), \
                    mock.patch.object(PQ.shutil, "which", which), mock.patch.object(PQ, "_systemd_user", lambda: True), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(O.main(["prereqs", "--json"]), want)
            items = json.loads(out.getvalue())
            self.assertEqual([i["name"] for i in items][-3:], ["cloudflared", "tailscale", "zerotier-cli"])
            self.assertTrue(all(set(i) == {"name", "required", "ok", "why", "fix", "link"} for i in items))
        out = io.StringIO()
        with mock.patch.object(PQ, "detect", lambda: "linux"), mock.patch.object(PQ.shutil, "which", lambda n: None), \
                mock.patch.object(PQ, "_systemd_user", lambda: False), contextlib.redirect_stdout(out):
            self.assertEqual(O.main(["prereqs"]), 1)
        self.assertIn("  - git (required): agents use it for their own worktrees\n      sudo apt install git", out.getvalue())


class PrereqBannerTests(unittest.TestCase):
    """1.53.2: the install banner ends with what is missing, and is unchanged when nothing is."""

    def notice(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("install_notice_pq", InstallNoticeTests.HOOK)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_a_missing_one_is_listed_with_its_command_and_link_and_none_adds_nothing(self):
        # Catches: no scan on install (the owner's ask), a block printed when nothing is missing, and a block
        # without the fix command or the link, on the first-install and the upgrade banner alike.
        mod, PQ = self.notice(), prereqs_module()
        ok = [{"name": "git", "required": True, "ok": True, "why": "w", "fix": ["sudo apt install git"], "link": "L"}]
        gone = [{**ok[0], "ok": False}]
        for prior in ([], ["0.0.1"]):
            body = "\n".join(mod._upgrade_lines(prior) if prior else mod._install_lines())
            with self.subTest(prior=prior), mock.patch.object(mod, "_prior_versions", lambda: prior):
                with mock.patch.object(PQ, "scan", lambda: ok):
                    self.assertEqual(mod._instructions(), body)
                with mock.patch.object(PQ, "scan", lambda: gone):
                    self.assertEqual(mod._instructions(), body + "\n\nMissing prerequisites:\n"
                                     "  - git (required): w\n      sudo apt install git\n      L\n"
                                     "1 required, 0 optional missing")

    def test_on_windows_the_banners_say_where_the_console_runs_and_print_no_command(self):
        # Catches (1.53.2): the Windows banner telling people to run "the printed install commands" in WSL (they
        # print Windows paths), never saying Claude Code itself must run in WSL, that Desktop has no plugins in
        # its WSL sessions, or that the hooks need a python3; and the upgrade banner's `bash "C:\\...install.sh"`.
        mod = self.notice()
        with mock.patch.object(mod, "_is_windows_native", lambda: True):
            first, upgrade = "\n".join(mod._install_lines()), "\n".join(mod._upgrade_lines(["0.0.1"]))
        for words in ("the console and its agent side run inside WSL2", "Use the Claude\n  Code CLI inside WSL",
                      "Desktop has no plugins in its WSL sessions", "need a `python3` on PATH", mod.WINDOWS):
            self.assertIn(words, first)
        self.assertNotIn("printed install commands", first)
        self.assertIn("runs inside WSL. Update the plugin in the Claude\nCode CLI inside WSL too", upgrade)
        for wrong in ("install.sh", "systemctl", "server.py"):
            self.assertNotIn(wrong, upgrade)
        self.assertTrue(mod.WINDOWS.endswith("docs/features/hosting.md#windows"))

    def test_a_failing_scan_leaves_the_banner_as_before(self):
        # Catches: an error in the scan (or its import) costing the user the banner, or the session a hook
        # error: the hooks fail open.
        mod, PQ = self.notice(), prereqs_module()
        body = "\n".join(mod._install_lines())
        with mock.patch.object(mod, "_prior_versions", lambda: []), \
                mock.patch.object(PQ, "scan", side_effect=OSError("boom")):
            self.assertEqual(mod._instructions(), body)


if __name__ == "__main__":
    unittest.main()
