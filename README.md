# cmux-agent-recovery

Local crash recovery for Claude Code and Codex sessions running inside CMUX.

The goal is simple:

- Save session metadata automatically on every agent turn.
- After CMUX restarts, recover one workspace at a time with `cmr`.
- Never start a fresh `claude` or `codex` session when a resume ID is missing.
- Never bulk-start every old agent after a crash.

## Commands

```sh
cmr
```

Recover the current CMUX workspace. If there is one safe match, it starts:

```sh
cd "$HOME/Development" && claude --resume <session-id>
cd "$HOME/Development" && codex -C "$HOME/Development" resume <session-id>
```

If multiple sessions match, `cmr` prints choices:

```text
cmr: multiple possible sessions found. Pick one with `cmr N`:
1. codex score=100 last=2026-04-30T01:00:00Z title='Release Notes'
2. codex score=90 last=2026-04-27T10:00:00Z title='Release Notes'
```

Then run:

```sh
cmr 1
```

Dry run:

```sh
cmr --dry-run
```

Dry run uses the same match selection as normal recovery. It only prints the command instead of executing it.

Audit all current CMUX workspaces:

```sh
cmux-recovery verify
```

Record and inspect workspace memory usage:

```sh
cmux-recovery memory-snapshot
cmux-recovery memory-top --since 6h
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
- per-workspace memory samples: total RSS, process count, and top process names

Treat the database as private local state. Session IDs, transcript paths, and workspace titles can reveal sensitive project context.

## Safety Rules

- `cmr` never runs plain `claude`.
- `cmr` never runs plain `codex`.
- Ambiguous matches require an explicit number.
- Missing matches do nothing.
- Workspace titles are matched literally and are not parsed for tool metadata.
- Restore is one workspace at a time by default.

## Install

The hooks are wired from:

- `~/.claude/settings.json`
- `~/.codex/hooks.json`
- `~/.zshrc`

The short shell command is a zsh function:

```sh
cmr() {
  "/path/to/cmux-agent-recovery/bin/cmr" "$@"
}
```

## Notes

CMUX currently restores layout and metadata after relaunch, but it does not restore live process state. This tool fills that gap for Claude Code and Codex by storing resume metadata outside CMUX.
