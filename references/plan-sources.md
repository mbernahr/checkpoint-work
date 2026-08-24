# Plan sources

Use an existing approved plan as the checkpoint map. Checkpoint Work controls when execution may continue; it does not replace the project's planning system.

## Precedence

Use the first applicable source:

1. The user's explicit scope, ordering, and hard stop.
2. The plan approved in the current host session or a plan file explicitly named by the user.
3. Project-owned phases, milestones, specifications, or implementation tickets.
4. Newly created meaningful checkpoints when none of the above exists.

Never choose a plan solely because it is the newest file in a global plans directory. If two plausible plans conflict and the current session does not identify the approved one, ask the user which plan controls execution.

## Claude Code

Claude Code Plan Mode is read-only. While it is active, inspect and refine the plan but do not begin implementation. After the user approves the plan and execution is permitted:

- preserve its task order, identifiers, dependencies, and completion criteria;
- treat each coherent plan item, or a justified group of small adjacent items, as a checkpoint;
- update the plan artifact or host-visible plan state at checkpoint boundaries when that workflow expects updates;
- honor `plansDirectory` when configured. Claude Code defaults this setting to `~/.claude/plans`, but a project-relative directory may be used;
- prefer the plan attached to the current session or an explicitly named path over scanning the directory.

The status-line helper and a Claude plan file serve different purposes: the former supplies usage data, while the latter supplies work structure.

## Codex

When Codex exposes an active plan or persistent goal for the task, preserve it as the authoritative structure. Reflect checkpoint completion in that plan instead of creating a parallel checklist. If no plan exists and execution is authorized, create coherent checkpoints normally.

## Wayfinder and other decision maps

Wayfinder is a planning and decision-discovery workflow, not an implementation plan by default. An unresolved map may contain research questions, human-in-the-loop decisions, or ambiguous branches that must not be treated as executable checkpoints.

- Do not implement unresolved decision tickets.
- Preserve human-in-the-loop boundaries and any one-ticket-per-session constraint declared by the planning workflow.
- Once Wayfinder produces an approved specification or build tickets, use those downstream artifacts as the authoritative checkpoint structure.
- Keep Checkpoint Work's reserve checks at boundaries between executable tickets or coherent groups of small adjacent tickets.
