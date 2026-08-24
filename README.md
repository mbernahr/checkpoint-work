# Checkpoint Work

**Autonomous checkpoint-based work with protected usage reserves for Codex and Claude Code.**

[![Tests](https://github.com/mbernahr/checkpoint-work/actions/workflows/test.yml/badge.svg)](https://github.com/mbernahr/checkpoint-work/actions/workflows/test.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-22c55e.svg)](LICENSE)
[![Codex + Claude Code](https://img.shields.io/badge/Codex%20%2B%20Claude%20Code-supported-7c3aed.svg)](#platform-support)

![Checkpoint Work workflow](assets/checkpoint-workflow-excalidraw.png)

_The core loop: select or create a plan, check usage at a boundary, finish one coherent checkpoint, verify it, and decide whether another checkpoint may start._

Checkpoint Work lets an AI coding agent continue through long tasks without waiting for repeated “continue” prompts. It divides unstructured work into meaningful checkpoints, respects existing project phases, verifies each completed unit, and stops before starting another checkpoint when a configurable usage reserve is reached.

**No API key is required. Usage is read locally from the active Codex or Claude Code session.**

[Quick start](#quick-start) · [Execution model](#how-it-works) · [Installation](#installation) · [Command reference](#command-reference) · [Examples](#examples) · [Safety](#safety-and-privacy)

## Capabilities

| Capability | Behavior |
| --- | --- |
| Configurable reserve | Preserves a user-selected percentage of remaining account usage. |
| Plan-aware execution | Reuses the approved host plan, an explicitly named plan file, or project phases and tickets. |
| Automatic planning | Creates meaningful checkpoints when no authoritative plan exists. |
| Atomic checkpoints | Completes, integrates, and verifies active work before stopping. |
| Hard scope boundaries | Stops at an explicitly named phase or task even when usage remains. |
| Optional auto-resume | Schedules one host-supported re-check after a limiting window resets. |
| Bounded parallelism | Allows a controlled worker wave inside a checkpoint. |
| Resumable handoff | Records the plan, completed work, verification state, usage window, and exact next action. |
| Fail-closed measurement | Never invents a percentage or starts more work without a current measurement. |

## Quick start

After [installing the skill](#installation), invoke it with the percentage of account usage to preserve and the work to complete:

```text
$checkpoint-work 10 Complete the approved implementation plan through Phase 8.
```

In Claude Code, use the slash form:

```text
/checkpoint-work 10 Complete the approved implementation plan through Phase 8.
```

The agent continues checkpoint by checkpoint until the requested scope is complete, a hard stop is reached, approval is required, or remaining usage reaches the protected reserve.

### When to use it

Checkpoint Work is designed for multi-step implementation, refactoring, migration, testing, documentation, and research work that should continue without repeated “continue” prompts. For a small one-shot edit, a usage check and checkpoint plan usually add unnecessary ceremony.

## How it works

Invoke the skill with a reserve percentage and a task. Before every new checkpoint, it reads the most constrained active usage window.

### Execution lifecycle

1. Resolve the requested scope and any hard stop.
2. Select the authoritative plan source, or create meaningful checkpoints when none exists.
3. Measure the most constrained available usage window.
4. Start one checkpoint only when remaining usage is above the reserve.
5. Finish, integrate, and verify the entire active checkpoint.
6. Update the authoritative plan and measure usage again.
7. Continue, stop with a handoff, or arrange an opt-in automatic resume.

```text
usage remaining > reserve  →  start and finish the next checkpoint
usage remaining ≤ reserve  →  stop and provide a resumable handoff
requested scope complete   →  stop normally
hard-stop phase complete   →  stop without starting the next phase
```

The reserve is checked only at checkpoint boundaries. If usage falls below the reserve while a checkpoint is active, that checkpoint is still completed and verified. This avoids leaving edits, migrations, or tests half-finished.

### Plan selection

Checkpoint Work uses the first applicable source instead of maintaining a competing checklist:

| Priority | Plan source |
| --- | --- |
| 1 | The user's explicit scope, order, and hard stop |
| 2 | The plan approved in the current host session or a plan file explicitly named by the user |
| 3 | Project phases, milestones, specifications, or implementation tickets |
| 4 | Newly created coherent checkpoints |

It never selects a global plan merely because that file is the newest one.

### Stopping behavior

| Condition at a checkpoint boundary | Result |
| --- | --- |
| Requested scope is complete | Stop normally and report verification. |
| Explicit hard-stop phase is complete | Stop without starting the next phase. |
| Remaining usage is above the reserve | Start the next checkpoint. |
| Remaining usage equals or falls below the reserve | Stop and create a handoff. |
| Current usage cannot be measured | Fail closed and do not start more work. |
| Approval or a user decision is required | Preserve state and ask for the missing decision. |

### Example

With a `10%` reserve:

- At `11%` remaining, the next checkpoint may start.
- The active checkpoint finishes even if usage drops below `10%`.
- At `10%` or less, no additional checkpoint starts.

Unlike a simple usage guard, Checkpoint Work also decides which approved work unit comes next, what must be verified before that unit is complete, and where the requested scope ends. Usage protection is part of the execution protocol rather than a standalone alarm.

## Platform support

| | Codex | Claude Code |
| --- | --- | --- |
| Invocation | `$checkpoint-work 10 …` | `/checkpoint-work 10 …` |
| Skill format | `SKILL.md` | `SKILL.md` |
| Usage source | Local Codex app server | Status-line `rate_limits` data |
| Measured windows | Active Codex rate-limit windows | 5-hour and 7-day windows |
| Existing plans | Active host plan or project plan | Approved Plan Mode file or project plan |
| API key required | No | No |

Claude.ai web chat is not supported by the local usage checker.

## Requirements

- Python 3.10 or newer
- Git
- One supported host:
  - Codex desktop or CLI authenticated with a ChatGPT account
  - Claude Code with rate-limit data available to its status line

## Installation

### Codex

Install the repository as a personal Codex skill:

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/mbernahr/checkpoint-work.git ~/.codex/skills/checkpoint-work
```

Restart Codex if the skill does not appear immediately.

Verify the local usage adapter:

```bash
python3 ~/.codex/skills/checkpoint-work/scripts/check_usage.py \
  --provider codex \
  --reserve 10
```

### Claude Code

Install the repository as a personal Claude Code skill:

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/mbernahr/checkpoint-work.git ~/.claude/skills/checkpoint-work
```

Configure the local usage capture:

```bash
python3 ~/.claude/skills/checkpoint-work/scripts/setup_claude_statusline.py
```

Restart Claude Code and send one message so its official 5-hour and 7-day rate-limit fields can populate the local cache. Then verify the adapter:

```bash
python3 ~/.claude/skills/checkpoint-work/scripts/check_usage.py \
  --provider claude \
  --reserve 10
```

The setup helper preserves unrelated Claude settings, creates a timestamped backup of an existing settings file, and refuses to replace an existing custom status line.

#### Why Claude uses a helper script

[Claude Code already sends](https://code.claude.com/docs/en/statusline) the official `rate_limits` fields to its status-line command. The small capture helper stores only that transient usage snapshot so Checkpoint Work can read it at the next checkpoint boundary. It does not install a usage package, call a third-party service, or use an API key, and the normal status-line display may still render icons and context information.

If a custom status line is already configured, keep it. The installer refuses to overwrite it; follow the [manual integration note](#troubleshooting) to pass the same input through the capture helper.

<details>
<summary><strong>Install once for both Codex and Claude Code</strong></summary>

Clone the repository into a permanent location and link it into both skill directories:

```bash
git clone https://github.com/mbernahr/checkpoint-work.git checkpoint-work
mkdir -p ~/.codex/skills ~/.claude/skills
ln -s "$(pwd)/checkpoint-work" ~/.codex/skills/checkpoint-work
ln -s "$(pwd)/checkpoint-work" ~/.claude/skills/checkpoint-work
python3 checkpoint-work/scripts/setup_claude_statusline.py
```

On Windows, copy the repository into both skill directories instead of creating symbolic links.

</details>

## Command reference

The number after the skill name is the percentage of usage to keep in reserve.

```text
$checkpoint-work <reserve-percent> [--auto-resume] [--max-parallel N] <task>
/checkpoint-work <reserve-percent> [--auto-resume] [--max-parallel N] <task>
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `<reserve-percent>` | Yes | Remaining account usage to preserve, from `0` to `100`. |
| `<task>` | Yes | Work scope, completion criteria, and optional hard stop. |
| `--auto-resume` | No | Authorizes one host-supported wakeup and a mandatory fresh usage check. |
| `--max-parallel N` | No | Sets a positive limit for simultaneous workers inside one checkpoint. |

Without `--max-parallel`, the skill uses at most 2 workers and may remain fully sequential when work is coupled.

## Examples

### Codex

```text
$checkpoint-work 10 Finish the remaining implementation, tests, and documentation.
```

### Claude Code

```text
/checkpoint-work 10 Finish the remaining implementation, tests, and documentation.
```

### Optional automatic resume

Add `--auto-resume` when the host should arrange a later re-check after the limiting usage window resets:

```text
$checkpoint-work 10 --auto-resume Complete the approved implementation plan.
```

Auto-resume is deliberately opt-in. It schedules at most one host-supported wakeup for the current run. The wakeup carries a self-contained handoff and checks the real account usage again before starting work; elapsed time or a passed reset timestamp is never treated as proof that capacity is available. If the host cannot schedule a suitable resume, the skill falls back to a manual resume prompt.

### Optional bounded parallelism

Parallel workers may be used inside one checkpoint when their scopes are independent:

```text
/checkpoint-work 20 --max-parallel 3 Complete the approved migration plan.
```

Without this option, the maximum is 2 simultaneous workers, and the agent may choose fewer or remain sequential. A checkpoint launches at most one worker wave, waits for all in-flight work, integrates the results, and verifies the complete checkpoint before checking usage again.

### Stop after a specific phase

```text
$checkpoint-work 50 Complete all unfinished work through Phase 9 of 14.
Phase 9 is a hard stop. Do not begin Phase 10.
```

Claude Code uses the same task with `/checkpoint-work`.

The run ends when the first of these conditions is met:

1. Phase 9 is complete.
2. Remaining usage is `50%` or lower at the next checkpoint boundary.

### Work without a predefined plan

```text
$checkpoint-work 20 Build and verify the requested feature end to end.
```

When no authoritative structure exists, the skill creates coherent checkpoints automatically. When a project already defines phases or tasks, that structure is preserved.

### Work from an approved plan

Checkpoint Work does not need to invent another plan. It uses the first authoritative source available: the user's hard stop, the plan approved in the current Codex or Claude session, an explicitly named plan file, or the project's own phases and implementation tickets.

```text
/checkpoint-work 20 Execute the approved plan through task 6.
Task 6 is a hard stop.
```

In Claude Code, [Plan Mode remains read-only](https://code.claude.com/docs/en/permission-modes). Checkpoint Work can help structure the plan there, but implementation starts only after the plan is approved and Claude Code returns to an execution-capable mode. Claude's [`plansDirectory` setting](https://code.claude.com/docs/en/configuration) defaults to `~/.claude/plans` and can point to a project-relative directory. The skill uses the current session's approved plan or a path you explicitly name; it does not guess by selecting the newest global plan.

[Wayfinder-style maps](https://github.com/mattpocock/skills/blob/main/skills/engineering/wayfinder/SKILL.md) are supported as an upstream planning source. Unresolved decision or research tickets remain planning work. Once the map produces an approved specification or executable build tickets, those artifacts become Checkpoint Work's checkpoints.

## Usage decisions

The checker emits machine-readable JSON so the agent can make a deterministic decision:

```json
{
  "ok": true,
  "provider": "claude",
  "remaining_percent": 18,
  "limiting_window": "seven_day",
  "limiting_resets_at": 1787755644,
  "limiting_window_id": "claude:seven_day:1787755644",
  "reserve_percent": 10,
  "may_start_next_checkpoint": true
}
```

When multiple rate-limit windows are present, the window with the least remaining usage controls the decision.

## Handoff and resume

When work stops before the requested scope is complete, the handoff records:

- the provider, remaining usage, protected reserve, limiting window, reset time, and window identity;
- the authoritative plan source and its current state;
- completed checkpoints, changed files, and verification results;
- remaining checkpoints and the exact next action;
- a self-contained `$checkpoint-work` or `/checkpoint-work` resume prompt.

Every manual or automatic resume measures the real account window again. A reset timestamp or elapsed delay alone never authorizes more work. Auto-resume remains limited to the original task and falls back to a manual handoff when the host cannot schedule a suitable wakeup.

## Current scope and limitations

- Checkpoint Work currently protects account usage percentages; it does not enforce a monetary budget or estimate dollar cost.
- Auto-resume depends on a compatible host wake or scheduling facility.
- Usage is checked at coherent checkpoint boundaries, so a checkpoint may finish after the reserve has been crossed.
- Claude.ai web chat is not supported by the local checker.
- Provider fields may change; unavailable or stale measurements always fail closed.

## Safety and privacy

Checkpoint Work is deliberately fail-closed: if it cannot obtain a current usage value, it does not estimate one and does not begin another checkpoint.

- The Codex adapter starts a local `codex app-server` process and reads the signed-in account's rate-limit snapshot.
- The Claude adapter receives status-line JSON and stores only rate-limit percentages, reset timestamps, and a local capture timestamp.
- Authentication tokens, prompts, source files, and conversation content are not stored.
- Invoking the skill does not authorize unrelated edits, destructive operations, purchases, publication, or bypassing normal approvals.
- Scheduled wakeups are created only when `--auto-resume` is explicitly requested and remain limited to the original task.

## Troubleshooting

<details>
<summary><strong>Codex usage cannot be read</strong></summary>

Confirm that Codex is installed and authenticated, then inspect `/status`. To select a non-standard executable:

```bash
CHECKPOINT_WORK_CODEX_BIN=/path/to/codex \
  ./scripts/check_usage.py --provider codex --reserve 10
```

The Codex `account/rateLimits/read` method is experimental and may change in a future Codex release.

The executable is discovered through `PATH` on Linux, macOS, and Windows. `/Applications/Codex.app/Contents/Resources/codex` is used only as a macOS fallback; it is not required on other platforms. The app-server reader uses a portable background pipe reader rather than Unix-only pipe selectors.

</details>

<details>
<summary><strong>Claude usage cache is missing or stale</strong></summary>

Restart Claude Code, send one message, and inspect `/usage`. The checker rejects cache snapshots older than 15 minutes by default.

```bash
./scripts/check_usage.py \
  --provider claude \
  --reserve 10 \
  --max-cache-age 900
```

Claude rate-limit fields may be unavailable before the first response or for authentication plans that do not expose them.

</details>

<details>
<summary><strong>Claude Code already has a custom status line</strong></summary>

Claude Code supports one `statusLine.command`, so the setup helper will not overwrite an existing configuration. Integrate manually by making the existing status-line script read stdin once, pass the same JSON to `scripts/capture_claude_usage.py` with its output hidden, and then render the existing status text from that JSON.

</details>

## Project structure

```text
checkpoint-work/
├── SKILL.md                         # Shared agent workflow
├── agents/openai.yaml               # Codex UI metadata
├── assets/                          # README graphics
├── references/
│   ├── plan-sources.md              # Codex, Claude, and Wayfinder plan precedence
│   └── resume-and-parallel.md       # Optional wakeups and bounded concurrency
├── scripts/
│   ├── check_usage.py               # Provider-independent decision CLI
│   ├── capture_claude_usage.py      # Claude status-line capture
│   └── setup_claude_statusline.py   # Safe Claude setup helper
├── tests/                            # Deterministic unit tests
└── .github/workflows/test.yml        # Linux, macOS, and Windows CI
```

## Development

Run the test suite without contacting Codex or Claude:

```bash
python3 -m unittest discover -s tests -v
```

The GitHub Actions workflow tests Python 3.10 and 3.13 on Linux, macOS, and Windows.

## Contributing

Issues and pull requests are welcome. For compatibility reports, include:

- Codex or Claude Code version
- operating system
- authentication type or plan, without account details
- sanitized checker output
- steps needed to reproduce the problem

Please do not include credentials, authentication tokens, private prompts, or proprietary source code.

## License

Released under the [MIT License](LICENSE).
