---
name: checkpoint-work
description: Work through meaningful, verified checkpoints until the requested scope is complete or a user-selected Codex or Claude Code usage reserve is reached. Use only when explicitly invoked with a remaining-usage percentage and a task.
---

# Checkpoint Work

Turn a long task into an uninterrupted sequence of independently useful checkpoints while preserving a requested percentage of account usage.

## Invocation

The host determines the command syntax:

- Codex: `$checkpoint-work <reserve-percent> <task>`
- Claude Code: `/checkpoint-work <reserve-percent> <task>`

Interpret the number after the skill name as the **remaining-usage reserve**. It must be between 0 and 100. Everything else is the task and its stopping scope. A reserve of 10 means: keep working while measured remaining usage is above 10%; leave 10% as reserve.

If the reserve or task is missing or ambiguous, ask only for the missing value. Do not substitute token budget, context-window usage, elapsed time, message count, or an estimate for the account rate-limit percentage.

## Scope and structure

- Preserve authoritative phases, tasks, milestones, numbering, and ordering already defined by the user or project.
- Treat an explicitly named terminal phase or task as a hard stop. Completing it completes the requested scope; never begin a later phase even when usage remains.
- When no authoritative structure exists, create meaningful checkpoints that each produce a coherent, verifiable result.
- A predefined phase may be subdivided for verification, but those checkpoints must not change official numbering or broaden the task.

## Workflow

1. Inspect the task and relevant workspace state. Reuse an authoritative structure when one exists; otherwise create a plan of meaningful checkpoints. Do not create artificial micro-checkpoints merely to increase the number of usage checks.
2. If a persistent goal facility is available, use it for the stated scope without assigning a token budget. The reserve is an account-rate-limit guard, not a goal token budget.
3. Before the first checkpoint, resolve the checker from the directory containing this `SKILL.md` and run it with an absolute path:
   - On Codex: `python3 scripts/check_usage.py --provider codex --reserve <percentage>`
   - On Claude Code: `python3 scripts/check_usage.py --provider claude --reserve <percentage>`
4. Start the next checkpoint only when the checker returns `may_start_next_checkpoint: true`.
5. Complete and verify the active checkpoint even if usage crosses the reserve while it is running. Never interrupt an in-progress coherent unit solely because the reserve may have been crossed.
6. Update the plan at the checkpoint boundary, run the same provider check again, and continue automatically when the scope is unfinished and another checkpoint may start.
7. Stop when the requested scope or hard boundary is complete, a required approval or user decision blocks progress, or the checker denies the next checkpoint.

Normal authorization and safety boundaries still apply. Invoking this skill authorizes persistence on the stated task, not unrelated changes, external publication, purchases, destructive operations, or bypassing approvals.

## Usage-check failures

If the checker cannot obtain a current value:

- Do not invent or estimate a percentage.
- Do not start another checkpoint.
- Preserve completed work and report the checker error concisely.
- On Codex, ask the user to run `/status` if the local app-server check is unavailable.
- On Claude Code, ask the user to verify the status-line setup and run `/usage` if the cache is missing, stale, or lacks rate-limit fields.

## Stopping handoff

When stopping before the requested scope is complete, provide a compact handoff containing:

- provider, measured remaining percentage, limiting window, and requested reserve;
- completed and verified checkpoints;
- current workspace state, changed files, and verification results;
- remaining checkpoints and the exact next action;
- a ready-to-use resume prompt using `$checkpoint-work` on Codex or `/checkpoint-work` on Claude Code.

When the requested scope is complete, report the completed outcome and verification normally.
