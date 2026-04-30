#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "cmux-recovery"


TREE = {
    "windows": [
        {
            "id": "window-1",
            "ref": "window:1",
            "workspaces": [
                {
                    "id": "workspace-1",
                    "ref": "workspace:1",
                    "index": 0,
                    "title": "Release Notes",
                    "selected": True,
                    "active": True,
                    "pinned": False,
                    "panes": [
                        {
                            "id": "pane-1",
                            "ref": "pane:1",
                            "focused": True,
                            "active": True,
                            "selected_surface_id": "surface-1",
                            "selected_surface_ref": "surface:1",
                            "surfaces": [
                                {
                                    "id": "surface-1",
                                    "ref": "surface:1",
                                    "title": "Shell",
                                    "selected": True,
                                    "focused": True,
                                    "type": "terminal",
                                    "index": 0,
                                    "tty": "ttys999",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]
}


IDENTIFY = {
    "caller": {
        "workspace_id": "workspace-1",
        "workspace_ref": "workspace:1",
        "surface_id": "surface-1",
        "surface_ref": "surface:1",
        "tab_id": "surface-1",
        "pane_id": "pane-1",
        "pane_ref": "pane:1",
    },
    "focused": None,
}


class RecoveryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="cmux-agent-recovery-test-")
        self.base = Path(self.tmp.name)
        self.db = self.base / "state.sqlite"
        self.restore_cwd = self.base / "Development"
        self.restore_cwd.mkdir()
        self.fake_cmux = self.base / "fake-cmux"
        self.fake_cmux.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import json
                import os
                import sys

                identify_json = {json.dumps(json.dumps(IDENTIFY))}
                tree_json = {json.dumps(json.dumps(TREE))}
                args = sys.argv[1:]
                if "identify" in args:
                    print(identify_json)
                elif "tree" in args:
                    print(os.environ.get("CMUX_FAKE_TREE_JSON", tree_json))
                elif "reload-config" in args:
                    print("OK Reloaded config")
                else:
                    print("unknown fake cmux command", args, file=sys.stderr)
                    raise SystemExit(1)
                """
            ),
            encoding="utf-8",
        )
        self.fake_cmux.chmod(0o755)
        self.env = {
            **os.environ,
            "CMUX_BIN": str(self.fake_cmux),
            "CMUX_RECOVERY_DB": str(self.db),
            "CMUX_RESTORE_CWD": str(self.restore_cwd),
            "CMUX_RECOVERY_DISABLE_MEMORY": "1",
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str, input_json: dict | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI), *args],
            input=json.dumps(input_json or {}),
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )

    def test_records_and_recovers_claude_with_restore_cwd(self) -> None:
        recorded = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "claude-session-1", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn(f"cd {self.restore_cwd}", recovered.stdout)
        self.assertIn("claude --resume claude-session-1", recovered.stdout)

    def test_records_and_recovers_codex_with_restore_cwd_and_dash_c(self) -> None:
        recorded = self.run_cli(
            "record",
            "--tool",
            "codex",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "codex-session-1", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn(f"cd {self.restore_cwd}", recovered.stdout)
        self.assertIn(f"codex -C {self.restore_cwd} resume codex-session-1", recovered.stdout)

    def test_ambiguous_matches_require_choice(self) -> None:
        for session_id in ["claude-old", "claude-new"]:
            recorded = self.run_cli(
                "record",
                "--tool",
                "claude",
                "--event",
                "UserPromptSubmit",
                input_json={"session_id": session_id, "cwd": str(self.restore_cwd)},
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 3)
        self.assertIn("multiple possible sessions", recovered.stdout)

        selected = self.run_cli("recover", "1", "--dry-run")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertIn("claude --resume", selected.stdout)

    def test_missing_match_does_not_start_plain_agent(self) -> None:
        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 2)
        self.assertIn("no recoverable", recovered.stdout)
        self.assertNotIn("claude\n", recovered.stdout)
        self.assertNotIn("codex\n", recovered.stdout)

    def test_title_text_does_not_imply_tool(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "Codex Research"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)

        state = self.base / "codex-state.sqlite"
        with sqlite3.connect(state) as con:
            con.execute(
                "CREATE TABLE threads (id TEXT, updated_at INTEGER, cwd TEXT, rollout_path TEXT, title TEXT, model TEXT, approval_mode TEXT, sandbox_policy TEXT, archived INTEGER)"
            )
            con.execute(
                "INSERT INTO threads VALUES ('codex-generic-1', 2000000000, '/tmp/generic', '/tmp/rollout.jsonl', NULL, 'gpt', 'never', 'workspace-write', 0)"
            )
        imported = self.run_cli(
            "import-legacy",
            "--ledger",
            str(self.base / "missing-ledger.tsv"),
            "--report-dir",
            str(self.base / "missing-reports"),
            "--codex-state",
            str(state),
        )
        self.assertEqual(imported.returncode, 0, imported.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 2)
        self.assertIn("no recoverable", recovered.stdout)

    def test_literal_title_can_recover_any_tool(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "Codex Research"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)

        reports = self.base / "reports"
        reports.mkdir()
        (reports / "cmux-restore-armed.latest.tsv").write_text(
            "\t".join(["index", "title", "current_surface_id", "current_directory", "best_tool", "best_session_id", "best_resume_command"])
            + "\n"
            + "\t".join(["0", "Codex Research", "old-surface", str(self.restore_cwd), "claude", "claude-research-session", "claude --resume claude-research-session"])
            + "\n",
            encoding="utf-8",
        )
        imported = self.run_cli(
            "import-legacy",
            "--ledger",
            str(self.base / "missing-ledger.tsv"),
            "--report-dir",
            str(reports),
            "--codex-state",
            str(self.base / "missing-codex-state.sqlite"),
        )
        self.assertEqual(imported.returncode, 0, imported.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("claude --resume claude-research-session", recovered.stdout)
        self.assertNotIn("codex", recovered.stdout)

    def test_imports_restore_manifest_title_binding(self) -> None:
        reports = self.base / "reports"
        reports.mkdir()
        (reports / "cmux-restore-armed.latest.tsv").write_text(
            "\t".join(["index", "title", "current_surface_id", "current_directory", "best_tool", "best_session_id", "best_resume_command"])
            + "\n"
            + "\t".join(["0", "Release Notes", "old-surface", str(self.restore_cwd), "codex", "codex-release-session", "codex resume codex-release-session"])
            + "\n",
            encoding="utf-8",
        )

        imported = self.run_cli(
            "import-legacy",
            "--ledger",
            str(self.base / "missing-ledger.tsv"),
            "--report-dir",
            str(reports),
            "--codex-state",
            str(self.base / "missing-codex-state.sqlite"),
        )
        self.assertEqual(imported.returncode, 0, imported.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("codex -C", recovered.stdout)
        self.assertIn("codex-release-session", recovered.stdout)

    def test_memory_snapshot_aggregates_tty_process_tree(self) -> None:
        self.env.pop("CMUX_RECOVERY_DISABLE_MEMORY", None)
        self.env["CMUX_RECOVERY_PS_JSON"] = json.dumps(
            [
                {"pid": 10, "ppid": 1, "pgid": 10, "tty": "ttys999", "rss_kb": 1000, "pmem": 0.1, "command_name": "zsh"},
                {"pid": 11, "ppid": 10, "pgid": 10, "tty": "ttys999", "rss_kb": 2000, "pmem": 0.2, "pcpu": 1.5, "command_name": "codex"},
                {"pid": 12, "ppid": 11, "pgid": 10, "tty": None, "rss_kb": 3000, "pmem": 0.3, "pcpu": 2.5, "command_name": "mcp-server"},
                {"pid": 20, "ppid": 1, "pgid": 20, "tty": "ttys123", "rss_kb": 5000, "pmem": 0.5, "pcpu": 9.0, "command_name": "other"},
            ]
        )

        snap = self.run_cli("memory-snapshot", "--quiet")
        self.assertEqual(snap.returncode, 0, snap.stderr)

        with sqlite3.connect(self.db) as con:
            row = con.execute(
                "SELECT process_count, total_rss_kb, total_pmem, total_pcpu, top_processes_json FROM memory_workspace_samples"
            ).fetchone()
            self.assertEqual(row[0], 3)
            self.assertEqual(row[1], 6000)
            self.assertAlmostEqual(row[2], 0.6)
            self.assertAlmostEqual(row[3], 4.0)
            self.assertIn("mcp-server", row[4])

        listed = self.run_cli("memory-list", "--quiet")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("Release Notes", listed.stdout)
        self.assertIn("5.9 MB", listed.stdout)
        self.assertIn("cpu=4.0%", listed.stdout)


if __name__ == "__main__":
    unittest.main()
