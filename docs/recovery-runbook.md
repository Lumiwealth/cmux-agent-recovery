# Recovery Runbook

## Normal Use

After CMUX restarts, open a workspace and run:

```sh
cmr
```

If the match is exact, the agent resumes immediately.

If multiple matches are possible, pick one:

```sh
cmr 1
```

If no match is found, leave the workspace alone and inspect:

```sh
cmux-recovery verify
```

## Why Recovery Is Manual

Starting every recovered Claude/Codex session at once can recreate the same memory pressure that caused the crash. `cmr` restores one workspace at a time.

## Matching Strategy

The resolver scores candidates with several signals:

- current surface ID
- current workspace ID
- workspace title
- current directory
- workspace order/index
- last-used timestamp

Surface/workspace IDs are useful inside one CMUX lifecycle but may change after a crash or relaunch, so title plus recency is the main fallback. Workspace titles are matched literally and are not parsed for Claude/Codex metadata. Ambiguous matches still require `cmr N`.

## Legacy Imports

After a crash, import the historical reports and local agent state before recovering tabs:

```sh
cmux-recovery import-legacy
```

By default this imports the session ledger and Codex state if they exist. Import CMUX report folders explicitly:

```sh
cmux-recovery import-legacy --report-dir /path/to/cmux/reports
```

Multiple report directories can be passed with repeated `--report-dir` flags. You can also set `CMUX_RECOVERY_REPORT_DIRS` to a colon-separated list.

## Hook Events

Claude and Codex write on:

- `SessionStart`
- `UserPromptSubmit`
- `Stop`
- explicit resume commands caught by the zsh wrappers

This means renames and directory changes get refreshed during normal use.

## Memory Telemetry

Every hook-triggered record also samples workspace memory usage. The sampler maps CMUX workspace ttys to their attached process trees, sums RSS, and stores top process names. It does not store full command lines by default because those can include secrets.

Manual snapshot:

```sh
cmux-recovery memory-snapshot
```

Largest workspaces in a recent window:

```sh
cmux-recovery memory-top --since 6h
```

Disable automatic sampling:

```sh
export CMUX_RECOVERY_DISABLE_MEMORY=1
```

## Database

Default database:

```text
/path/to/cmux-agent-recovery/state/cmux-recovery.sqlite
```

Override:

```sh
export CMUX_RECOVERY_DB=/path/to/cmux-recovery.sqlite
```

Restore cwd:

```sh
export CMUX_RESTORE_CWD="$HOME/Development"
```
