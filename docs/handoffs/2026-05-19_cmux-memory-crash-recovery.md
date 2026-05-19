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

Commits:

- `791bf90 Improve cmr exact-title recovery fallback`
- `bd6d314 Suppress generic workflow cmr matches`
- `c620936 Handle unnamed Development Codex recovery` - pushed to `origin/main`
- `f72d7a5 Auto-select clear newest Development recovery` - local only as of this handoff

## Current memory pressure

Fresh sampled total from `cmux-recovery trim --target-gb 24 --limit 10`:

- Total sampled workspace RSS: `47246.0 MB`
- Target: `24576.0 MB`
- Dry-run plan would reduce to `22200.7 MB`
- No stops were executed.

Top dry-run stop candidates:

- `(CX) 💰🚀 Client - Christy` - `5538.5 MB`
- `💰🚀 Sales - CX - Marketplace Returns` - `2618.8 MB`
- `💰🚀 Sales - CX - Tradier Traderfest` - `2618.8 MB`
- Multiple older tabs around `2378 MB` each

Do not execute `trim --execute` without Rob's explicit approval naming the target behavior, because it respawns panes and stops live agents while leaving tabs recoverable.

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

1. Push `f72d7a5` to `origin/main` if Rob wants the newest auto-select fix on GitHub.
2. Run `cmr --dry-run` in the unnamed `Development` tab and confirm it prints the direct resume command for `019e4163-62d1-7a31-8a67-90978ec13351`.
3. Use `cmux-recovery trim` as the non-destructive way to plan memory relief.
4. Ask Rob before any `trim --execute`, because stopping active agents is externally visible and may interrupt work.
5. Open or update upstream CMUX GitHub issues with this concrete repro: restored generic `Development` tab, many agent sessions, memory-pressure crash, stale workspace titles, and need for native agent manifests.
