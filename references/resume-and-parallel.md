# Resume and parallel execution

Read this reference when `--auto-resume` is requested, when the host can schedule a wake or resume, or when a checkpoint contains parallel work.

## Automatic resume

Automatic resume is opt-in. Do not create a scheduled task, wakeup, watcher, or background wait unless the user supplied `--auto-resume` or explicitly requested equivalent behavior.

When the usage reserve prevents another checkpoint and the cost guard still allows work:

1. Use `limiting_resets_at` and `limiting_window_id` from the checker. Do not estimate missing values.
2. If the host provides a wake or resume facility and a reset timestamp is available, arrange one re-check at or just after that timestamp. Respect host delay limits; use bounded chained wakeups only when the host cannot represent the full delay, and avoid short-interval polling.
3. Keep at most one pending automatic resume for the current run. Update an existing wakeup instead of creating duplicates when the host supports updates.
4. Make the resume payload self-contained: include the authoritative plan source, completed work, remaining scope, hard stop, reserve, provider, previous window identity, changed files, verification state, exact usage command, and next checkpoint. When cost control is active, also include the maximum cost, run cost, quality, source, scope, and unchanged cost run ID.
5. On wake, run the real usage checker before doing any work. A passed timestamp is not proof that the account window reset.
6. If the measured window is still at or below the reserve, schedule one later re-check only when the same opt-in remains active and a current reset timestamp is available. Otherwise stop with a handoff.
7. If the scope is already complete or the wakeup is stale, do nothing except report that no work remains.

If the host has no suitable wake/resume facility, provide the ordinary manual handoff. Auto-resume permission does not authorize external publication, bypassed approvals, or a new task outside the original scope.

Do not schedule an automatic resume when the monetary limit is the blocking condition. A usage window can reset; the accumulated cost of this run cannot. Continuing requires a new explicit user decision, not a new run ID created by the agent.

## Bounded parallel work

Parallelism is optional and must remain inside one coherent checkpoint.

- Apply the explicit `--max-parallel N` value when present. It must be a positive integer.
- Otherwise use at most 2 simultaneous workers, and prefer sequential work when tasks share files, ordering, state, or design decisions.
- Assign independent, bounded scopes with their own verification and stop conditions.
- Launch at most one worker wave per checkpoint. Wait for every in-flight worker, integrate the results, resolve conflicts, and verify the whole checkpoint before the next usage check.
- Do not interrupt in-flight workers solely to preserve the reserve. Do not launch replacements or additional work after the boundary check denies another checkpoint.
- Normal host concurrency limits and user instructions override this default maximum.
