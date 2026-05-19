# CMUX Memory Crash Recovery Handoff - 2026-05-19

## Why this exists

Rob asked to resume the recent unnamed `Development` Codex tab after another CMUX/Codex memory crash. The tab was about fixing `cmr` recovery failures, understanding the memory crash that caused the problem, and deciding whether CMUX should get an upstream GitHub feature.

## Recovered conversations

- Current recovered Codex session: `019e4163-62d1-7a31-8a67-90978ec13351`
- Prior `cmr` repair session: `019e4138-5173-7ca2-af4e-ca96ea591212`
- Broader Chrome and memory crash investigation: `019e221a-7d58-7832-86d9-c93ca2667346`

Important tab pins already written to the local recovery DB:

- `💰🚀 Sales - CX - Marketplace Returns` -> Codex `019ddf5f-9cae-7ab3-8528-fc05806cf79c`
- `CX - Improving Gen/Refine System Prompts` -> Codex `019e27c7-07ef-7703-a1c9-76d01e6a134c`

## What was fixed today

- `cmr` now names the workspace in missing, ambiguous, and invalid-choice messages.
- Poisoned exact-title matches from generic LinkedIn workflow transcripts are suppressed instead of offered as choices.
- Generic restored tabs named `Development` now include recent untitled Codex state rows from `~/.codex/state_5.sqlite` as `recent-cwd` candidates.
- The newest recent-cwd candidate can auto-select when it is less than two hours old and at least ten minutes newer than the next recent-cwd candidate.
- Specific restored tabs can now recover recent untitled Codex state rows when the same cwd and Codex thread title/payload strongly match the workspace title. This fixes `(CX) Client - Peter H`, where Codex state had `Peter H` in the thread title but the recovery binding had no workspace title.
- Codex hooks were installed in `/Users/robertgrzesik/.codex/hooks.json` but disabled by `/Users/robertgrzesik/.codex/config.toml` (`[features] hooks = false`). The local config has been changed to `hooks = true` so new Codex sessions should record `SessionStart`, `UserPromptSubmit`, and `Stop` bindings again.
- A local recovery pin was written for `(CX) 💰🚀 Client - Peter H` -> Codex `019e4113-4909-7991-8909-b85a9a2593e5`.
- Memory pressure alerts now use plain language: warning starts at about `40 GB` of live CMUX agent memory, critical starts at about `50 GB`, and `60 GB` is treated as the approximate crash danger zone.
- Alert dialogs now show current CMUX agent memory, approximate headroom before the danger zone, swap cushion, disk free space, and live recoverable tabs. Swap/disk pressure is shown as context but does not by itself make the alert critical.
- `/Users/robertgrzesik/.codex/hooks.json` also had stale native CMUX hook commands using `cmux codex-hook ...`. The installed CMUX CLI no longer exposes that command; the current interface is `cmux hooks codex <event>`. The Codex hook config was updated on 2026-05-19 to use `cmux hooks codex session-start`, `cmux hooks codex prompt-submit`, and `cmux hooks codex stop`, and duplicate stale native-hook blocks were removed.

Commits:

- `791bf90 Improve cmr exact-title recovery fallback`
- `bd6d314 Suppress generic workflow cmr matches`
- `c620936 Handle unnamed Development Codex recovery` - pushed to `origin/main`
- `f72d7a5 Auto-select clear newest Development recovery` - local only as of this handoff
- Pending after this handoff update: specific untitled Codex topic fallback for Peter H.
- Later pushed fixes include `0c66071`, `8474e9c`, `4d50a00`, `acd5977`, `79635f5`, and `05e38e1`.

## Current memory pressure

Fresh sampled total from `cmux-recovery pressure --no-snapshot --limit 6` on 2026-05-19 16:44 America/Toronto:

- Status: `ok`
- Live CMUX agent memory: `36916.2 MB`
- Physical RAM: `48.0 GB`
- Crash danger zone: about `60.0 GB`
- Headroom before danger zone: about `23.9 GB`
- Swap free: `1183 MB`
- Disk free: `157.9 GB`
- Dry-run trim plan would reduce to `24706.5 MB`
- No stops were executed.

Top dry-run stop candidates:

- `(CX) Odoo Data Migration` - `2993.8 MB`
- `CX - Improving Gen/Refine System Prompts` - `2993.8 MB`
- `💰🚀 Sales - CX - Courses` - `2993.8 MB`
- `💰🚀 Sales - CX - Newsletter` - `2109.2 MB`
- `CX - Bug: Chrome Crashing` - `661.6 MB`
- `(CX) Stacey Bug` - `457.4 MB`

Do not execute `trim --execute` without Rob's explicit approval naming the target behavior, because it respawns panes and stops live agents while leaving tabs recoverable.

## CMUX running badge investigation

Rob reported that `(CX) 💰🚀 Client - Peter H` shows CMUX's running indicator while `(CX) 💰🚀 Client - Christy` is actually running but does not reliably show the same indicator.

Findings on 2026-05-19:

- Top Christy workspace `workspace:1` uses tty `ttys005` and has a live Codex process for session `019db8e6-d7ed-7920-8fd2-1ee234a23066`.
- Peter workspace `workspace:2` uses tty `ttys006` and has a live Codex process for session `019e4113-4909-7991-8909-b85a9a2593e5`.
- Peter has a current marker at `/Users/robertgrzesik/.codex/cmux-markers/01E8B0E9-0340-4171-9EAE-D060276B5CA5` and live `cmux hooks codex monitor` processes, so CMUX has native state to show the running indicator.
- Top Christy had no marker at `/Users/robertgrzesik/.codex/cmux-markers/8D1680A3-F9A9-48A9-9105-75838A2B524A` and no `cmux hooks codex monitor` process, even though the Codex process is live.
- The likely cause is the stale `cmux codex-hook ...` command in the Codex hook config plus the earlier disabled hooks setting. Sessions started while that config was broken could run without creating the native CMUX monitor state.
- The hook config fix applies to future Codex hook events. Existing sessions that missed `SessionStart` may not retroactively get the native running badge until they emit a fresh hook event or are restarted/resumed after the hook fix.

## Chrome/memory crash context

The broader Chrome crash investigation concluded:

- Chrome MCP is not required for crashes. One captured crash had `devtools=0`.
- MCP and many attached agents can still amplify memory pressure.
- Evidence points to Chrome plus this macOS environment plus heavy session pressure, not a single extension, current Chrome version, or profile.
- Better rolling log capture and a careful profile-preserving Chrome reinstall were proposed before blaming MCP.

Relevant docs:

- `/Users/robertgrzesik/Development/chrome-crash-investigation/SUMMARY.md`
- `/Users/robertgrzesik/Development/chrome-crash-investigation/2026-05-18-no-extension-profile-isolation.md`

## CMUX upstream feature direction

The recovery repo links three upstream CMUX issues:

- `manaflow-ai/cmux#3342` - stable agent session recovery after CMUX crash or relaunch
- `manaflow-ai/cmux#3322` - persist session manifest and reattach live agent processes after daemon/app restart
- `manaflow-ai/cmux#3130` - show per-workspace/session memory and CPU usage in sidebar

The local recovery tool already prototypes pieces of this:

- External session binding database for Claude/Codex resume IDs
- Per-workspace RSS, CPU, and top-process samples
- Sidebar metrics via workspace descriptions
- Safe dry-run trim planning
- Respawn-pane based stop behavior so tabs remain recoverable

Recommended next feature to upstream or build locally:

- A native CMUX agent manifest per workspace with tool, session ID, cwd, transcript path, title history, and last prompt summary.
- Native workspace memory pressure UI showing RSS, CPU, process count, and top process names.
- A first-class "park old agent" action that stops the process, keeps the tab, and shows the exact resume command.
- A crash-recovery chooser that ranks by title history, current cwd, screen text, and agent manifest, not just live process state.

## Immediate next steps

1. Push the local `main` commits to `origin/main` when Rob wants these recovery fixes on GitHub.
2. Run `cmr --dry-run` in the unnamed `Development` tab and confirm it prints the direct resume command for `019e4163-62d1-7a31-8a67-90978ec13351`.
3. Run `cmr --dry-run` in `(CX) 💰🚀 Client - Peter H`; it should recover Codex `019e4113-4909-7991-8909-b85a9a2593e5`.
4. Use `cmux-recovery trim` as the non-destructive way to plan memory relief.
5. Ask Rob before any `trim --execute`, because stopping active agents is externally visible and may interrupt work.
6. Open or update upstream CMUX GitHub issues with this concrete repro: restored generic `Development` tab, many agent sessions, memory-pressure crash, stale workspace titles, and need for native agent manifests.
