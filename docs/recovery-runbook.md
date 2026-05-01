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

## Memory And CPU Telemetry

Every hook-triggered record also samples workspace resource usage. The sampler maps CMUX workspace ttys to their attached process trees, sums RSS, `%MEM`, and `%CPU`, and stores top process names. It does not store full command lines by default because those can include secrets.

Manual snapshot:

```sh
cmux-recovery memory-snapshot
```

Largest workspaces in a recent window:

```sh
cmux-recovery memory-list
cmux-recovery memory-top --since 6h
```

## Sidebar Metrics

CMUX renders workspace descriptions in the sidebar and exposes them through the CLI. The recovery tool can use that as a lightweight, no-fork display surface for memory metrics:

```sh
cmux-recovery sidebar-metrics
```

Default mode is a dry run. To write the metrics into each workspace description:

```sh
cmux-recovery sidebar-metrics --execute
```

The managed line looks like:

```text
cmux: rss=1.2GB cpu=3.4% procs=18
```

This command does not rename workspaces, so it does not interfere with recovery title matching. It preserves existing description text and only replaces prior managed `cmux:` metric lines. Clear managed metrics:

```sh
cmux-recovery sidebar-metrics --clear --execute
```

## Reducing Memory Pressure

Use `trim` when too many recovered agents are running at once:

```sh
cmux-recovery trim
```

The default mode is a dry run. It takes a fresh memory snapshot, looks for older workspaces that have a safe resume ID, skips the active workspace, and shows the agents it would stop to get under the target memory level.

To actually stop those agents and keep the CMUX tabs available:

```sh
cmux-recovery trim --execute
```

Default target:

```text
30 GB total sampled workspace RSS
```

Useful options:

```sh
cmux-recovery trim --target-gb 24
cmux-recovery trim --min-age 2h
cmux-recovery trim --limit 5
cmux-recovery trim --force
```

The default stop method is `respawn-pane`, which restarts the terminal surface instead of closing the workspace. Run `cmr` in that tab later to resume the saved Claude/Codex session.

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
