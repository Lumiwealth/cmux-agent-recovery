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


if __name__ == "__main__":
    unittest.main()
