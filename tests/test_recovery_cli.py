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
                elif "respawn-pane" in args:
                    print("OK Respawned pane")
                elif "send-key" in args:
                    print("OK Sent key")
                elif "workspace-action" in args:
                    print("OK Workspace action")
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
            "CMUX_RECOVERY_DEBUG_DIR": str(self.base / "logs"),
            "CMUX_RECOVERY_DISABLE_MEMORY": "1",
            "CMUX_RECOVERY_DISABLE_SAVED_SESSION": "1",
            "CMUX_CODEX_STATE": str(self.base / "missing-codex-state.sqlite"),
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

    def test_recovers_claude_from_recorded_project_cwd(self) -> None:
        project_cwd = self.restore_cwd / "MarketingManager"
        project_cwd.mkdir()
        recorded = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "claude-project-session", "cwd": str(project_cwd)},
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn(f"cd {project_cwd}", recovered.stdout)
        self.assertIn("claude --resume claude-project-session", recovered.stdout)

    def test_claude_resume_prefers_transcript_project_cwd(self) -> None:
        child_cwd = self.restore_cwd / "botspot_node"
        child_cwd.mkdir()
        slug = "-" + "-".join(self.restore_cwd.parts[1:])
        transcript = self.base / ".claude" / "projects" / slug / "claude-root-project-session.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text(
            json.dumps({"type": "user", "message": {"content": "newsletter work in the root project"}}) + "\n",
            encoding="utf-8",
        )
        recorded = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={
                "session_id": "claude-root-project-session",
                "cwd": str(child_cwd),
                "transcript_path": str(transcript),
            },
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn(f"cd {self.restore_cwd}", recovered.stdout)
        self.assertNotIn(f"cd {child_cwd}", recovered.stdout)
        self.assertIn("claude --resume claude-root-project-session", recovered.stdout)

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

    def test_title_only_recency_gap_does_not_auto_select(self) -> None:
        for session_id in ["claude-old-title-only", "claude-new-title-only"]:
            recorded = self.run_cli(
                "record",
                "--tool",
                "claude",
                "--event",
                "UserPromptSubmit",
                input_json={"session_id": session_id, "cwd": str(self.base / session_id)},
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_id='old-workspace', workspace_ref='old-workspace-ref',
                    surface_id='old-surface', surface_ref='old-surface-ref',
                    workspace_index=NULL, last_seen='2026-05-01T00:00:00Z'
                WHERE session_id='claude-old-title-only'
                """
            )
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_id='old-workspace', workspace_ref='old-workspace-ref',
                    surface_id='old-surface', surface_ref='old-surface-ref',
                    workspace_index=NULL, last_seen='2026-05-01T00:10:00Z'
                WHERE session_id='claude-new-title-only'
                """
            )

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 3)
        self.assertIn("multiple possible sessions", recovered.stdout)
        self.assertIn("claude-new-title-only", recovered.stdout)

    def test_title_only_recency_gap_still_requires_choice(self) -> None:
        shared_cwd = self.base / "shared-title-work"
        shared_cwd.mkdir()
        for session_id in ["claude-old-title-gap", "claude-new-title-gap"]:
            recorded = self.run_cli(
                "record",
                "--tool",
                "claude",
                "--event",
                "UserPromptSubmit",
                input_json={"session_id": session_id, "cwd": str(shared_cwd)},
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_id='old-workspace', workspace_ref='old-workspace-ref',
                    surface_id='old-surface', surface_ref='old-surface-ref',
                    workspace_index=NULL, last_seen='2026-05-01T00:00:00Z'
                WHERE session_id='claude-old-title-gap'
                """
            )
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_id='old-workspace', workspace_ref='old-workspace-ref',
                    surface_id='old-surface', surface_ref='old-surface-ref',
                    workspace_index=NULL, last_seen='2026-05-01T00:20:00Z'
                WHERE session_id='claude-new-title-gap'
                """
            )

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 3)
        self.assertIn("multiple possible sessions", recovered.stdout)
        self.assertIn("claude-new-title-gap", recovered.stdout)
        self.assertIn("claude-old-title-gap", recovered.stdout)

    def test_old_matching_title_is_not_lost_behind_recent_global_limit(self) -> None:
        old = self.run_cli(
            "record",
            "--tool",
            "codex",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "codex-old-release-notes", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(old.returncode, 0, old.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_id='old-workspace', workspace_ref='old-workspace-ref',
                    surface_id='old-surface', surface_ref='old-surface-ref',
                    workspace_index=NULL, last_seen='2026-04-01T00:00:00Z'
                WHERE session_id='codex-old-release-notes'
                """
            )
            for index in range(600):
                con.execute(
                    """
                    INSERT INTO session_bindings (
                      tool, session_id, first_seen, last_seen, last_event, last_source,
                      cwd, workspace_title, normalized_title
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "claude",
                        f"unrelated-{index}",
                        "2026-05-01T00:00:00Z",
                        f"2026-05-01T00:{index % 60:02d}:00Z",
                        "UserPromptSubmit",
                        "test",
                        str(self.base / "unrelated"),
                        f"Unrelated {index}",
                        f"unrelated {index}",
                    ),
                )

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("codex-old-release-notes", recovered.stdout)

    def test_topic_relevance_beats_generic_outreach_poison(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "Sales - CX - Trading Agents 54k Stars Could Be Lumibot"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)

        codex = self.run_cli(
            "record",
            "--tool",
            "codex",
            "--event",
            "UserPromptSubmit",
            input_json={
                "session_id": "codex-trading-agents",
                "cwd": str(self.restore_cwd),
                "last_assistant_message": "TradingAgents and Lumibot plan for a 54k stars GitHub launch.",
            },
        )
        self.assertEqual(codex.returncode, 0, codex.stderr)
        linkedin = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={
                "session_id": "claude-linkedin-poison",
                "cwd": str(self.restore_cwd / "MarketingManager"),
                "prompt": "You are a LinkedIn outreach agent. This is Step 3a: REPLY TO ACTIVE CONVERSATIONS for proprietary trading contacts.",
            },
        )
        self.assertEqual(linkedin.returncode, 0, linkedin.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET last_seen='2026-05-01T00:00:00Z',
                    workspace_id='old-workspace', surface_id='old-surface'
                WHERE session_id='codex-trading-agents'
                """
            )
            con.execute(
                """
                UPDATE session_bindings
                SET last_seen='2026-05-11T00:00:00Z'
                WHERE session_id='claude-linkedin-poison'
                """
            )

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("codex-trading-agents", recovered.stdout)
        self.assertNotIn("claude-linkedin-poison", recovered.stdout)

    def test_bug_title_does_not_treat_leads_as_generic_outreach(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "CX - Bug: New Leads Missing How Found"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)

        for session_id, prompt in [
            (
                "claude-step-seven-poison",
                "You are a LinkedIn engagement agent. This is Step 7: TARGETED PROSPECT ENGAGEMENT AND COMMENT MANAGEMENT.",
            ),
            (
                "claude-step-nine-poison",
                "You are a LinkedIn outreach agent. This is Step 9: ACCEPT INCOMING CONNECTION REQUESTS.",
            ),
        ]:
            recorded = self.run_cli(
                "record",
                "--tool",
                "claude",
                "--event",
                "UserPromptSubmit",
                input_json={"session_id": session_id, "cwd": str(self.restore_cwd / "MarketingManager"), "prompt": prompt},
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 2)
        self.assertIn("no recoverable", recovered.stdout)

    def test_codex_state_topic_match_beats_linkedin_content_poison(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "CX - Fargate Deploy Test"
        tree["windows"][0]["workspaces"][0]["index"] = 99
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)

        state = self.base / "codex-state.sqlite"
        self.env["CMUX_CODEX_STATE"] = str(state)
        rollout = self.base / "rollout-fargate.jsonl"
        rollout.write_text(
            json.dumps({"type": "user", "message": {"content": "Research Fargate deployment runners."}}) + "\n",
            encoding="utf-8",
        )
        with sqlite3.connect(state) as con:
            con.execute(
                "CREATE TABLE threads (id TEXT, updated_at INTEGER, cwd TEXT, rollout_path TEXT, title TEXT, model TEXT, approval_mode TEXT, sandbox_policy TEXT, archived INTEGER)"
            )
            con.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "codex-fargate-deploy",
                    2000000000,
                    str(self.restore_cwd),
                    str(rollout),
                    "Plan the Fargate deployment runner",
                    "gpt",
                    "never",
                    "workspace-write",
                    0,
                ),
            )

        poisoned = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={
                "session_id": "claude-linkedin-content-poison",
                "cwd": str(self.restore_cwd / "MarketingManager"),
                "prompt": "You are a LinkedIn content creation agent. This is Step 6: POST CONTENT TO LINKEDIN.",
            },
        )
        self.assertEqual(poisoned.returncode, 0, poisoned.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("codex-fargate-deploy", recovered.stdout)
        self.assertNotIn("claude-linkedin-content-poison", recovered.stdout)

    def test_pin_overrides_poisoned_current_workspace_match(self) -> None:
        poisoned = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "claude-poisoned-current", "cwd": str(self.base / "MarketingManager")},
        )
        self.assertEqual(poisoned.returncode, 0, poisoned.stderr)
        intended = self.run_cli(
            "record",
            "--tool",
            "codex",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "codex-intended", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(intended.returncode, 0, intended.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_id='old-workspace', workspace_ref='old-ref',
                    surface_id='old-surface', surface_ref='old-surface',
                    last_seen='2026-05-01T00:00:00Z'
                WHERE session_id='codex-intended'
                """
            )

        pinned = self.run_cli("pin", "--title", "Release Notes", "--tool", "codex", "--session-id", "codex-intended")
        self.assertEqual(pinned.returncode, 0, pinned.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("codex-intended", recovered.stdout)
        self.assertNotIn("claude-poisoned-current", recovered.stdout)

    def test_ignore_removes_session_from_candidates(self) -> None:
        for session_id in ["claude-ignore-me", "claude-keep-me"]:
            recorded = self.run_cli(
                "record",
                "--tool",
                "claude",
                "--event",
                "UserPromptSubmit",
                input_json={"session_id": session_id, "cwd": str(self.restore_cwd)},
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
        ignored = self.run_cli("ignore", "--tool", "claude", "--session-id", "claude-ignore-me", "--reason", "test")
        self.assertEqual(ignored.returncode, 0, ignored.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("claude-keep-me", recovered.stdout)
        self.assertNotIn("claude-ignore-me", recovered.stdout)

    def test_session_start_does_not_rebind_existing_session(self) -> None:
        recorded = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "claude-stable-binding", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "Taxes"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)
        started = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "SessionStart",
            input_json={"session_id": "claude-stable-binding", "cwd": str(self.restore_cwd), "source": "resume"},
        )
        self.assertEqual(started.returncode, 0, started.stderr)

        with sqlite3.connect(self.db) as con:
            row = con.execute(
                """
                SELECT workspace_title, normalized_title, last_event
                FROM session_bindings
                WHERE tool='claude' AND session_id='claude-stable-binding'
                """
            ).fetchone()
        self.assertEqual(row[0], "Release Notes")
        self.assertEqual(row[1], "release notes")
        self.assertEqual(row[2], "UserPromptSubmit")

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

    def test_sidebar_metrics_updates_workspace_descriptions_when_executed(self) -> None:
        self.env.pop("CMUX_RECOVERY_DISABLE_MEMORY", None)
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["description"] = "Keep this note"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)
        self.env["CMUX_RECOVERY_PS_JSON"] = json.dumps(
            [
                {"pid": 10, "ppid": 1, "pgid": 10, "tty": "ttys999", "rss_kb": 2048, "pmem": 0.2, "pcpu": 1.5, "command_name": "zsh"},
            ]
        )

        dry = self.run_cli("sidebar-metrics")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("dry-run", dry.stdout)
        self.assertIn("cmux: rss=2MB cpu=1.5% procs=1", dry.stdout)

        executed = self.run_cli("sidebar-metrics", "--execute")
        self.assertEqual(executed.returncode, 0, executed.stderr)
        self.assertIn("executed", executed.stdout)

        cleared = self.run_cli("sidebar-metrics", "--clear", "--execute")
        self.assertEqual(cleared.returncode, 0, cleared.stderr)
        self.assertIn("cleared", cleared.stdout)

    def test_trim_only_stops_recoverable_sessions_when_executed(self) -> None:
        self.env.pop("CMUX_RECOVERY_DISABLE_MEMORY", None)
        self.env["CMUX_RECOVERY_PS_JSON"] = json.dumps(
            [
                {"pid": 10, "ppid": 1, "pgid": 10, "tty": "ttys999", "rss_kb": 1000, "pmem": 0.1, "pcpu": 0.1, "command_name": "zsh"},
                {"pid": 11, "ppid": 10, "pgid": 10, "tty": "ttys999", "rss_kb": 5000, "pmem": 0.5, "pcpu": 3.0, "command_name": "claude"},
            ]
        )
        recorded = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "claude-trim-session", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)

        guarded = self.run_cli("trim", "--min-mb", "1", "--min-age", "0s", "--target-gb", "0.001")
        self.assertEqual(guarded.returncode, 0, guarded.stderr)
        self.assertIn("planned=0", guarded.stdout)

        dry = self.run_cli("trim", "--include-active", "--min-mb", "1", "--min-age", "0s", "--target-gb", "0.001")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("would stop", dry.stdout)
        self.assertIn("claude-trim-session", dry.stdout)

        executed = self.run_cli(
            "trim",
            "--include-active",
            "--min-mb",
            "1",
            "--min-age",
            "0s",
            "--target-gb",
            "0.001",
            "--execute",
        )
        self.assertEqual(executed.returncode, 0, executed.stderr)
        self.assertIn("stopped", executed.stdout)

        with sqlite3.connect(self.db) as con:
            row = con.execute(
                "SELECT status, method, stopped_count FROM trim_events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(row[0], "executed")
            self.assertEqual(row[1], "respawn")
            self.assertEqual(row[2], 1)


if __name__ == "__main__":
    unittest.main()
