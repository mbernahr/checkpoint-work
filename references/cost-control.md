# Cost control

Read this reference whenever `--max-cost-usd` is present.

## Meaning of the limit

The USD amount is a soft checkpoint-start limit for this invocation. Another checkpoint may start only while:

```text
remaining usage > reserve AND run cost < maximum cost
```

Complete and verify an active checkpoint even if it crosses the monetary limit. The skill cannot guarantee a hard billing cap because future checkpoint cost is unknown and interrupting coherent work would violate the checkpoint boundary.

## Run identity and baseline

Create one unique opaque run ID before the first check and pass it as `--cost-run-id` with the same `--max-cost-usd` value at every boundary. The checker stores only the provider's cumulative-cost baseline and source metadata under `~/.checkpoint-work/cost-runs/`; it does not store prompts or source code.

Preserve the run ID in automatic resumes and handoffs. Never create a new run ID to bypass a reached cost limit. A new run ID is appropriate only for a genuinely new user invocation.

## Quality categories

- `reported`: the provider identifies the value as an actual reported monetary amount.
- `calculated`: the value was calculated from measured usage and a declared pricing version.
- `estimated`: the provider or adapter identifies the value as an estimate or API-equivalent cost.
- `unavailable`: no reliable comparable value is available; fail closed.

Never silently mix categories. The checker also fails closed if source, scope, or source identity changes, or if a cumulative total drops below its saved baseline.

## Built-in sources

### Codex

The checker uses the current `CODEX_THREAD_ID` to request the local app-server's estimated thread usage. When `estimatedUsageUsdMicros` is available, it is classified as `estimated`, scoped to the Codex thread, and requires no API key. If the current Codex billing route does not expose a USD estimate, cost control fails closed.

### Claude Code

The status-line capture reads `cost.total_cost_usd`, which Claude documents as a client-side estimated session cost that may differ from the bill. It is classified as `estimated` and scoped to the Claude session. If `/clear` starts a new session or the session identity changes, do not reuse the previous baseline.

### External adapters

A host with a trustworthy cumulative value may pass `--current-cost-usd` together with `--cost-quality`, `--cost-source`, `--cost-scope`, and `--cost-source-id`. Do not pass an invented value. API organization costs or token-derived calculations require their own authenticated adapter and attribution strategy; the generic checker does not claim that unrelated organization-wide spend belongs to this run.

## Reporting

At every stopped or completed run, distinguish the measurement explicitly. For example:

```text
Run cost: $4.87 estimated
Maximum cost: $5.00
Source: claude_statusline
Scope: session
```

Never shorten this to “billed $4.87” unless the quality is genuinely `reported` and the provider defines it as billed cost.
