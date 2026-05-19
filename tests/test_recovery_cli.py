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
                elif "read-screen" in args:
                    print(os.environ.get("CMUX_FAKE_SCREEN_TEXT", ""))
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

    def test_codex_candidate_prompt_skips_agents_instructions(self) -> None:
        transcript = self.base / "codex-session-instructions.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "# AGENTS.md instructions for /Users/robertgrzesik/Development <INSTRUCTIONS> lots of rules",
                            }
                        ],
                    },
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "i want you to take over from claude code and fix the welcome sequence bug",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        recorded = self.run_cli(
            "record",
            "--tool",
            "codex",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "codex-session-instructions", "cwd": str(self.restore_cwd), "transcript_path": str(transcript)},
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        other = self.run_cli(
            "record",
            "--tool",
            "codex",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "codex-session-other", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(other.returncode, 0, other.stderr)

        recovered = self.run_cli("recover", "1", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)

        ambiguous = self.run_cli("recover", "--dry-run")
        self.assertIn("i want you to take over from claude code", ambiguous.stdout)
        self.assertNotIn("AGENTS.md instructions", ambiguous.stdout)

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
        self.assertIn("Release Notes", recovered.stdout)

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

    def test_generic_development_tab_lists_recent_untitled_codex_state(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "Development"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)

        state = self.base / "codex-state.sqlite"
        self.env["CMUX_CODEX_STATE"] = str(state)
        rollout = self.base / "rollout-cmr-memory.jsonl"
        rollout.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "Fix the cmr command and cmux memory crash recovery.",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        other_rollout = self.base / "rollout-other.jsonl"
        other_rollout.write_text(
            json.dumps({"type": "user", "message": {"content": "Review Peter H client work."}}) + "\n",
            encoding="utf-8",
        )
        with sqlite3.connect(state) as con:
            con.execute(
                "CREATE TABLE threads (id TEXT, updated_at INTEGER, cwd TEXT, rollout_path TEXT, title TEXT, model TEXT, approval_mode TEXT, sandbox_policy TEXT, archived INTEGER)"
            )
            con.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "codex-cmr-memory-fix",
                    2000000000,
                    str(self.restore_cwd),
                    str(rollout),
                    "Fix cmr command and cmux memory crash recovery",
                    "gpt",
                    "never",
                    "workspace-write",
                    0,
                ),
            )
            con.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "codex-other-recent",
                    1999999900,
                    str(self.restore_cwd),
                    str(other_rollout),
                    "Review Peter H client work",
                    "gpt",
                    "never",
                    "workspace-write",
                    0,
                ),
            )

        stale = self.run_cli(
            "record",
            "--tool",
            "codex",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "codex-stale-development", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(stale.returncode, 0, stale.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_title='Development',
                    normalized_title='development',
                    workspace_id='old-workspace',
                    workspace_ref='old-workspace-ref',
                    surface_id='old-surface',
                    surface_ref='old-surface-ref',
                    workspace_index=NULL,
                    last_seen='2026-04-29T00:00:00Z'
                WHERE session_id='codex-stale-development'
                """
            )

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 3)
        self.assertIn("multiple possible sessions", recovered.stdout)
        self.assertIn("codex recent-cwd session=codex-cmr-memory-fix", recovered.stdout)
        self.assertIn("Fix the cmr command and cmux memory crash recovery", recovered.stdout)
        self.assertIn("codex-other-recent", recovered.stdout)

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
        self.assertIn("CX - Bug: New Leads Missing How Found", recovered.stdout)
        self.assertNotIn("claude-step-seven-poison", recovered.stdout)
        self.assertNotIn("claude-step-nine-poison", recovered.stdout)

    def test_current_screen_resume_without_known_title_does_not_override_title(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "CX - Bug: New Leads Missing How Found"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)
        screen_session = "019e0d99-96a0-7800-a6ee-32d651afad79"
        self.env["CMUX_FAKE_SCREEN_TEXT"] = (
            "Resume this session with:\n"
            "claude --resume 98057358-d9ce-4d4b-a752-233a16dc147b\n"
            f"To continue this session, run codex resume {screen_session}"
        )

        poisoned = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={
                "session_id": "claude-linkedin-title-poison",
                "cwd": str(self.restore_cwd / "MarketingManager"),
                "prompt": "You are a LinkedIn outreach agent. This is Step 9: ACCEPT INCOMING CONNECTION REQUESTS.",
            },
        )
        self.assertEqual(poisoned.returncode, 0, poisoned.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 2, recovered.stderr)
        self.assertIn("no recoverable", recovered.stdout)
        self.assertIn("CX - Bug: New Leads Missing How Found", recovered.stdout)
        self.assertNotIn("claude-linkedin-title-poison", recovered.stdout)
        self.assertNotIn(f"codex -C {self.restore_cwd} resume {screen_session}", recovered.stdout)

    def test_current_screen_resume_with_matching_known_title_can_override(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "CX - Bug: New Leads Missing How Found"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)
        screen_session = "019e0d99-96a0-7800-a6ee-32d651afad79"
        self.env["CMUX_FAKE_SCREEN_TEXT"] = f"To continue this session, run codex resume {screen_session}"

        recorded = self.run_cli(
            "record",
            "--tool",
            "codex",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": screen_session, "cwd": str(self.restore_cwd), "prompt": "real bug session"},
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_title='CX - Bug: New Leads Missing How Found',
                    normalized_title='cx bug new leads missing how found'
                WHERE session_id=?
                """,
                (screen_session,),
            )

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn(f"codex -C {self.restore_cwd} resume {screen_session}", recovered.stdout)

    def test_current_screen_resume_conflicting_known_title_is_ignored(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "(CX) ⏳ 🧾 Taxes"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)
        self.env["CMUX_FAKE_SCREEN_TEXT"] = (
            "Resume this session with:\n"
            "claude --resume claude-client-christy"
        )

        stale = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "claude-client-christy", "cwd": str(self.restore_cwd / "MarketingManager")},
        )
        self.assertEqual(stale.returncode, 0, stale.stderr)
        taxes = self.run_cli(
            "record",
            "--tool",
            "codex",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "codex-taxes-session", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(taxes.returncode, 0, taxes.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_title='(CX) 💰🚀 Client - Christy',
                    normalized_title='cx client christy'
                WHERE session_id='claude-client-christy'
                """
            )
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_id='old-workspace', workspace_ref='old-workspace-ref',
                    surface_id='old-surface', surface_ref='old-surface-ref',
                    last_seen='2026-04-30T02:44:43Z'
                WHERE session_id='codex-taxes-session'
                """
            )

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("codex-taxes-session", recovered.stdout)
        self.assertNotIn("claude-client-christy", recovered.stdout)

    def test_cx_prefix_is_part_of_exact_title(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "🚀 CX - Paraxanthine"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)

        recorded = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "Stop",
            input_json={
                "session_id": "claude-paraxanthine-session",
                "cwd": str(self.restore_cwd),
                "transcript_path": str(self.base / "claude-paraxanthine-session.jsonl"),
            },
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_title='🚀 Paraxanthine', normalized_title='paraxanthine',
                    workspace_id='old-workspace', surface_id='old-surface'
                WHERE session_id='claude-paraxanthine-session'
                """
            )

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 2, recovered.stderr)
        self.assertIn("cmr: no recoverable Claude/Codex session found", recovered.stdout)
        self.assertNotIn("claude --resume claude-paraxanthine-session", recovered.stdout)

    def test_sales_and_marketing_prefixes_are_not_interchangeable(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "💰🚀 Sales - CX - Welcome Sequence"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)

        marketing = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "claude-marketing-welcome", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(marketing.returncode, 0, marketing.stderr)
        sales = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "claude-sales-welcome", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(sales.returncode, 0, sales.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_title='💰🚀 Marketing - Welcome Sequence',
                    normalized_title='marketing welcome sequence',
                    last_seen='2026-05-11T00:00:00Z'
                WHERE session_id='claude-marketing-welcome'
                """
            )
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_title='💰🚀 Sales - CX - Welcome Sequence',
                    normalized_title='sales cx welcome sequence',
                    last_seen='2026-05-10T00:00:00Z'
                WHERE session_id='claude-sales-welcome'
                """
            )

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("claude-sales-welcome", recovered.stdout)
        self.assertNotIn("claude-marketing-welcome", recovered.stdout)

    def test_current_screen_transcript_text_recovers_codex_without_resume_line(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "CX - OpenAI Credits"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)
        self.env["CMUX_FAKE_SCREEN_TEXT"] = (
            "Done. Switched BotSpot Agent to openai/gpt-5.4-mini locally and in the production workflow, "
            "fixed the Agent token aggregation bug."
        )

        state = self.base / "codex-state.sqlite"
        self.env["CMUX_CODEX_STATE"] = str(state)
        rollout = self.base / "rollout-openai-credits.jsonl"
        rollout.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "agent_message",
                        "message": (
                            "Done. Switched BotSpot Agent to openai/gpt-5.4-mini locally and in the production workflow, "
                            "fixed the Agent token aggregation bug."
                        ),
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        with sqlite3.connect(state) as con:
            con.execute(
                "CREATE TABLE threads (id TEXT, updated_at INTEGER, cwd TEXT, rollout_path TEXT, title TEXT, model TEXT, approval_mode TEXT, sandbox_policy TEXT, archived INTEGER)"
            )
            con.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "019e17db-f3aa-7cf2-972d-e0c52e1c9781",
                    2000000000,
                    str(self.restore_cwd),
                    str(rollout),
                    None,
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
                "session_id": "claude-openai-credits-poison",
                "cwd": str(self.restore_cwd / "MarketingManager"),
                "prompt": "You are a LinkedIn outreach agent. This is Step 1: CHECK MESSAGES AND NEW ACCEPTANCES.",
            },
        )
        self.assertEqual(poisoned.returncode, 0, poisoned.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("codex -C", recovered.stdout)
        self.assertIn("019e17db-f3aa-7cf2-972d-e0c52e1c9781", recovered.stdout)
        self.assertNotIn("claude-openai-credits-poison", recovered.stdout)

    def test_cmr_candidate_list_text_is_not_used_as_screen_transcript_match(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "💰🚀 Sales - CX - Welcome Sequence"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)
        self.env["CMUX_FAKE_SCREEN_TEXT"] = (
            "cmr: multiple possible sessions found. Pick one with `cmr N`:\n"
            "1. codex session=codex-current-cmr-thread score=200 title='cmr recovery bug' cwd=/Users/robertgrzesik\n"
            "   first_user='I get so many errors when I start up Codex. Is this a problem? Can you fix this?'\n"
        )

        state = self.base / "codex-state.sqlite"
        self.env["CMUX_CODEX_STATE"] = str(state)
        unrelated_rollout = self.base / "rollout-cmr-current.jsonl"
        unrelated_rollout.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "I get so many errors when I start up Codex. Is this a problem? Can you fix this?",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        with sqlite3.connect(state) as con:
            con.execute(
                "CREATE TABLE threads (id TEXT, updated_at INTEGER, cwd TEXT, rollout_path TEXT, title TEXT, model TEXT, approval_mode TEXT, sandbox_policy TEXT, archived INTEGER)"
            )
            con.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "codex-current-cmr-thread",
                    2000000000,
                    str(self.base),
                    str(unrelated_rollout),
                    "cmr recovery bug",
                    "gpt",
                    "never",
                    "workspace-write",
                    0,
                ),
            )

        intended = self.run_cli(
            "record",
            "--tool",
            "codex",
            "--event",
            "UserPromptSubmit",
            input_json={"session_id": "codex-sales-welcome", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(intended.returncode, 0, intended.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_title='💰🚀 Sales - CX - Welcome Sequence',
                    normalized_title='sales cx welcome sequence'
                WHERE session_id='codex-sales-welcome'
                """
            )

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("codex-sales-welcome", recovered.stdout)
        self.assertNotIn("codex-current-cmr-thread", recovered.stdout)

    def test_codex_state_topic_match_does_not_recover_without_exact_title(self) -> None:
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
        self.assertEqual(recovered.returncode, 2, recovered.stderr)
        self.assertIn("no recoverable", recovered.stdout)
        self.assertIn("CX - Fargate Deploy Test", recovered.stdout)
        self.assertNotIn("claude-linkedin-content-poison", recovered.stdout)
        self.assertNotIn("codex-fargate-deploy", recovered.stdout)

    def test_exact_posthog_title_beats_broad_topic_match(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "Sales - PostHog Recordings Review"
        tree["windows"][0]["workspaces"][0]["index"] = 98
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)

        state = self.base / "codex-state.sqlite"
        self.env["CMUX_CODEX_STATE"] = str(state)
        with sqlite3.connect(state) as con:
            con.execute(
                "CREATE TABLE threads (id TEXT, updated_at INTEGER, cwd TEXT, rollout_path TEXT, title TEXT, model TEXT, approval_mode TEXT, sandbox_policy TEXT, archived INTEGER)"
            )
            con.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "codex-broad-posthog",
                    2000000000,
                    str(self.restore_cwd),
                    str(self.base / "missing-rollout.jsonl"),
                    "Review PostHog funnel notes",
                    "gpt",
                    "never",
                    "workspace-write",
                    0,
                ),
            )

        exact = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "UserPromptSubmit",
            input_json={
                "session_id": "claude-posthog-recordings",
                "cwd": str(self.restore_cwd),
                "prompt": "Review the PostHog recordings and summarize sales friction.",
            },
        )
        self.assertEqual(exact.returncode, 0, exact.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET normalized_title='sales posthog recordings review'
                WHERE session_id='claude-posthog-recordings'
                """
            )

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("claude-posthog-recordings", recovered.stdout)
        self.assertNotIn("codex-broad-posthog", recovered.stdout)

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

    def test_pin_beats_current_screen_resume(self) -> None:
        tree = json.loads(json.dumps(TREE))
        tree["windows"][0]["workspaces"][0]["title"] = "CX - Paraxanthine"
        self.env["CMUX_FAKE_TREE_JSON"] = json.dumps(tree)
        self.env["CMUX_FAKE_SCREEN_TEXT"] = "Resume this session with:\nclaude --resume claude-wrong-paraxanthine\n"

        wrong = self.run_cli(
            "record",
            "--tool",
            "claude",
            "--event",
            "Stop",
            input_json={"session_id": "claude-wrong-paraxanthine", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(wrong.returncode, 0, wrong.stderr)
        intended = self.run_cli(
            "record",
            "--tool",
            "codex",
            "--event",
            "Stop",
            input_json={"session_id": "codex-right-paraxanthine", "cwd": str(self.restore_cwd)},
        )
        self.assertEqual(intended.returncode, 0, intended.stderr)
        with sqlite3.connect(self.db) as con:
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_title='Paraxanthine', normalized_title='paraxanthine'
                WHERE session_id='claude-wrong-paraxanthine'
                """
            )
            con.execute(
                """
                UPDATE session_bindings
                SET workspace_title='CX - Paraxanthine', normalized_title='cx paraxanthine'
                WHERE session_id='codex-right-paraxanthine'
                """
            )

        pinned = self.run_cli(
            "pin",
            "--title",
            "CX - Paraxanthine",
            "--tool",
            "codex",
            "--session-id",
            "codex-right-paraxanthine",
        )
        self.assertEqual(pinned.returncode, 0, pinned.stderr)

        recovered = self.run_cli("recover", "--dry-run")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("codex-right-paraxanthine", recovered.stdout)
        self.assertNotIn("claude-wrong-paraxanthine", recovered.stdout)

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
        self.assertIn("Release Notes", recovered.stdout)
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
