# cmux-agent-recovery

Local crash recovery for Claude Code and Codex sessions running inside [CMUX](https://github.com/manaflow-ai/cmux).

CMUX can restore workspace layout after a relaunch, app update, macOS reboot, or crash, but the live Claude Code/Codex processes are gone. This tool records enough local metadata to resume the right agent session in the right restored workspace.

## What It Does

- Save session metadata automatically on every agent turn.
- After CMUX restarts, recover one workspace at a time with `cmr`.
- Never start a fresh `claude` or `codex` session when a resume ID is missing.
- Never bulk-start every old agent after a crash.
- Ask before resuming when a restored title points at several title-only matches.
- Log per-workspace memory and CPU telemetry so runaway sessions are easier to find.
- Safely stop older/heavy agents while keeping the CMUX tabs ready to recover later.

This is a stopgap, not a replacement for native CMUX session persistence. It does not keep killed processes alive. It makes Claude Code/Codex recovery fast and explicit using their own resume mechanisms.

## Quick Start

```sh
git clone https://github.com/Lumiwealth/cmux-agent-recovery.git
cd cmux-agent-recovery
```

Add the repo's `bin/` directory to your `PATH`, then wire `hooks/agent-record.sh` into Claude Code and Codex hook events.

The important hook command shape is:

```sh
/path/to/cmux-agent-recovery/hooks/agent-record.sh claude UserPromptSubmit
/path/to/cmux-agent-recovery/hooks/agent-record.sh codex UserPromptSubmit
```

Optional short command:

```sh
cmr() {
  "/path/to/cmux-agent-recovery/bin/cmr" "$@"
}
```

Then, inside a restored CMUX workspace:

```sh
cmr
```

## Commands

```sh
cmr
```

Recover the current CMUX workspace. If there is one safe match, it starts:

```sh
cd "$HOME/Development" && claude --resume <session-id>
cd "$HOME/Development" && codex -C "$HOME/Development" resume <session-id>
```

If multiple plausible sessions match, `cmr` prints choices with the workspace name:

```text
cmr: multiple possible sessions found for workspace 'Release Notes'. Pick one with `cmr N`:
1. codex score=100 last=2026-04-30T01:00:00Z title='Release Notes' cwd=/work/repo resume_cwd=/work/repo transcript=12.4MB
2. codex score=90 last=2026-04-27T10:00:00Z title='Release Notes' cwd=/work/old resume_cwd=/work/old transcript=1.1MB
```

Then run:

```sh
cmr 1
```

If a tab title was reused or the DB got polluted by a wrong resume, pin the title to the known-good session:

```sh
cmux-recovery pin --title "Release Notes" --tool codex --session-id <session-id> --cwd "$HOME/Development"
```

Bad matches can be hidden:

```sh
cmux-recovery ignore --tool claude --session-id <wrong-session-id> --reason "wrong workspace"
```

Dry run:

```sh
cmr --dry-run
```

Dry run uses the same match selection as normal recovery. It only prints the command instead of executing it.

Exact-title matches can still be rejected when the transcript clearly belongs to a generic workflow and has no independent match to the requested tab topic, screen, workspace id, or cwd. This prevents renamed tabs from offering stale LinkedIn workflow sessions as recoverable choices.

When a crash happens before a Codex tab gets a real CMUX title, the restored tab may only be named `Development`. In that case `cmr` also lists recent untitled Codex state entries with the same cwd as `recent-cwd` candidates. A clearly newest recent-cwd candidate auto-selects when it is less than two hours old and at least ten minutes newer than the next recent-cwd candidate; otherwise `cmr` still requires an explicit choice.

For Claude Code, `cmr` prefers the project directory that owns the Claude transcript when it can prove that path. That matters when a session used `cd` during the conversation: Claude may store the resumable session under the original project even if the latest hook saw a child folder.

Audit all current CMUX workspaces:

```sh
cmux-recovery verify
```

Record and inspect workspace memory and CPU usage:

```sh
cmux-recovery memory-snapshot
cmux-recovery memory-list
cmux-recovery memory-top --since 6h
```

Show memory and CPU directly in the CMUX sidebar by writing a managed line to each workspace description:

```sh
cmux-recovery sidebar-metrics
cmux-recovery sidebar-metrics --execute
cmux-recovery sidebar-metrics --clear --execute
```

This does not change workspace titles. It preserves any existing description text except prior managed `cmux:` metric lines.

Plan a safe memory trim:

```sh
cmux-recovery trim
```

`trim` samples current workspace memory, finds older workspaces with a safe Claude/Codex resume ID, skips the active workspace by default, and prints what it would stop. To actually stop those agents while leaving the CMUX tabs in place:

```sh
cmux-recovery trim --execute
```

After a tab is stopped, run `cmr` inside that tab to resume it.

Check total pressure before macOS gets into swap collapse:

```sh
cmux-recovery pressure
```

`pressure` combines CMUX workspace RSS, physical RAM, swap usage, and free disk space. It returns non-zero when pressure is warning or critical and includes the same dry-run trim plan as `trim`.

Install a per-minute local LaunchAgent that sends a macOS notification on warning or critical pressure:

```sh
bin/install-pressure-monitor
```

Notifications are throttled to once every 15 minutes while the pressure level stays the same. Defaults are intentionally early: warning starts at about 18 GB sampled workspace RSS, 45% of physical RAM, less than 8 GB swap free, or less than 150 GB disk free. Critical starts at about 30 GB sampled workspace RSS, 65% of physical RAM, less than 4 GB swap free, or less than 80 GB disk free.

Remove it:

```sh
bin/uninstall-pressure-monitor
```

Import old recovery reports and local agent state:

```sh
cmux-recovery import-legacy
cmux-recovery import-legacy --report-dir /path/to/cmux/reports
```

## Data

The live database and runtime exports are ignored by git:

```text
state/cmux-recovery.sqlite
state/latest.json
logs/
reports/
exports/
```

The database stores:

- CMUX workspace title and normalized title
- workspace/surface IDs and refs when available
- workspace order/index
- current directory and terminal/process title
- Claude/Codex session ID
- transcript or rollout path
- tool, model, permission/sandbox mode where available
- first seen, last seen, and restore attempts
- per-workspace telemetry samples: total RSS, `%MEM`, `%CPU`, process count, and top process names

Treat the database as private local state. Session IDs, transcript paths, and workspace titles can reveal sensitive project context.

## Safety Rules

- `cmr` never runs plain `claude`.
- `cmr` never runs plain `codex`.
- Ambiguous matches require an explicit number.
- Missing matches do nothing.
- Workspace titles are matched literally and are not parsed for tool metadata.
- Restore is one workspace at a time by default.
- `trim` only stops workspaces with a recoverable session ID, skips the active workspace by default, and runs as a dry run unless `--execute` is passed.

## Hook Locations

Typical local hook wiring lives in:

- `~/.claude/settings.json`
- `~/.codex/hooks.json`
- `~/.zshrc`

Hook formats change over time, so keep the installed hook small: pass the tool name and event into `hooks/agent-record.sh`, and keep hook stdout silent.

## Notes

CMUX currently restores layout and metadata after relaunch, but it does not restore live process state. This tool fills that gap for Claude Code and Codex by storing resume metadata outside CMUX.

## Related CMUX Issues

- [Stable agent session recovery after CMUX crash or relaunch](https://github.com/manaflow-ai/cmux/issues/3342)
- [Persist session manifest and re-attach live agent processes after daemon/app restart](https://github.com/manaflow-ai/cmux/issues/3322)
- [Show per-workspace/session memory and CPU usage in sidebar](https://github.com/manaflow-ai/cmux/issues/3130)
- [Native memory telemetry CLI and trim recoverable agent command](https://github.com/manaflow-ai/cmux/issues/4059)
- [Fix 80GB memory growth from retained WebKit and cmux monitor helpers](https://github.com/manaflow-ai/cmux/issues/4188)
