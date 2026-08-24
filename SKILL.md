---
name: checkpoint-work
description: Work through an approved plan or meaningful verified checkpoints until the requested scope is complete or a user-selected Codex or Claude Code usage reserve is reached. Use only when explicitly invoked with a remaining-usage percentage and a task.
---

# Checkpoint Work

Turn a long task into an uninterrupted sequence of independently useful checkpoints while preserving a requested percentage of account usage.

## Invocation

The host determines the command syntax:

- Codex: `$checkpoint-work <reserve-percent> [--auto-resume] [--max-parallel N] <task>`
- Claude Code: `/checkpoint-work <reserve-percent> [--auto-resume] [--max-parallel N] <task>`

Interpret the number after the skill name as the **remaining-usage reserve**. It must be between 0 and 100. Everything else is the task and its stopping scope. A reserve of 10 means: keep working while measured remaining usage is above 10%; leave 10% as reserve.

Both modifiers are optional. `--auto-resume` explicitly authorizes one host-supported wake or resume for this run when usage reaches the reserve. `--max-parallel N` sets a positive upper bound on simultaneous workers inside a checkpoint; when omitted, use at most 2 and use fewer whenever parallel work would add risk or overhead. Read `references/resume-and-parallel.md` when either behavior is relevant.

If the reserve or task is missing or ambiguous, ask only for the missing value. Do not substitute token budget, context-window usage, elapsed time, message count, or an estimate for the account rate-limit percentage.

## Scope and structure

- Resolve the checkpoint source in this order: the user's explicit scope and hard stop; an approved host plan or explicitly named plan file; project phases, milestones, or implementation tickets; newly created checkpoints.
- When an approved host plan or plan file exists, read `references/plan-sources.md`. Use that plan as the checkpoint structure instead of creating a competing plan.
- Preserve authoritative phases, tasks, milestones, numbering, and ordering already defined by the user or project.
- Treat an explicitly named terminal phase or task as a hard stop. Completing it completes the requested scope; never begin a later phase even when usage remains.
- When no authoritative structure exists, create meaningful checkpoints that each produce a coherent, verifiable result.
- A predefined phase may be subdivided for verification, but those checkpoints must not change official numbering or broaden the task.

## Workflow

1. Inspect the task, relevant workspace state, and any approved plan exposed by the host or explicitly named by the user. Reuse an authoritative structure when one exists; otherwise create a plan of meaningful checkpoints. Do not select an unrelated plan merely because it is the newest file, and do not create artificial micro-checkpoints merely to increase the number of usage checks.
2. If a persistent goal facility is available, use it for the stated scope without assigning a token budget. The reserve is an account-rate-limit guard, not a goal token budget.
3. If the host is currently in a read-only planning mode, finish or update the plan and wait for approval or execution mode before making implementation changes. Planning mode does not waive the usage reserve for later execution.
4. Before the first implementation checkpoint, resolve the checker from the directory containing this `SKILL.md` and run it with an absolute path:
   - On Codex: `python3 scripts/check_usage.py --provider codex --reserve <percentage>`
   - On Claude Code: `python3 scripts/check_usage.py --provider claude --reserve <percentage>`
5. Start the next checkpoint only when the checker returns `may_start_next_checkpoint: true`.
6. A checkpoint may contain bounded independent parallel work, but all in-flight workers belong to that checkpoint. Do not launch a second wave before its boundary. Complete, integrate, and verify the active checkpoint even if usage crosses the reserve while it is running; never interrupt in-flight work solely because the reserve may have been crossed.
7. Update the authoritative plan at the checkpoint boundary when the host or project workflow supports updates, run the same provider check again, and continue automatically when the scope is unfinished and another checkpoint may start.
8. Stop when the requested scope or hard boundary is complete, a required approval or user decision blocks progress, or the checker denies the next checkpoint. If and only if `--auto-resume` was requested, follow `references/resume-and-parallel.md` to arrange a safe re-check.

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
- limiting reset timestamp and window identity when the checker provides them;
- completed and verified checkpoints;
- current workspace state, changed files, and verification results;
- remaining checkpoints and the exact next action;
- the authoritative plan source or path and its current status, when applicable;
- a ready-to-use resume prompt using `$checkpoint-work` on Codex or `/checkpoint-work` on Claude Code.

On every manual or automatic resume, run the checker again. Never infer that a window reset merely because the reported reset time or a scheduled delay has passed.

When the requested scope is complete, report the completed outcome and verification normally.
