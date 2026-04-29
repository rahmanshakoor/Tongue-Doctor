# ADR 0004 — GCP region and model-availability fallback

- Status: accepted
- Date: 2026-04-29
- Deciders: Rahman Shakoor
- Source decision: `KICKOFF_PLAN.md` Decisions Log row D.

## Context

The user is in Doha. The natural primary region is `me-central1` for proximity. But model availability via Vertex Model Garden lags us-central / europe regions, and not every model in our stack is reliably available in `me-central1`:

- Gemini 3.1 Pro: typically available in `me-central1`.
- Claude Opus 4.7 / Sonnet via Model Garden: rolling regional availability; often lags `us-central1` / `europe-west4`.
- Cohere Rerank in Model Garden: limited regional availability.
- Vertex Vector Search: regional with cost/perf tradeoffs.

A research demo can absorb cross-region latency more readily than a production system can.

## Decision

- **Primary region**: `me-central1`. Used for Vertex Vector Search, Firestore, GCS, Cloud Run, Gemini calls.
- **Fallback region**: `europe-west4` for Anthropic via Vertex Model Garden and for Cohere Rerank when `me-central1` lacks the model.
- **Second fallback**: direct Anthropic API (`api.anthropic.com`) for Claude calls when Vertex Model Garden returns `UNAVAILABLE` in both regions. Triggered automatically by the `models/vertex_anthropic.py` client; uses `ANTHROPIC_API_KEY` from Secret Manager.
- Cross-region calls accepted as a research-demo trade-off. Cost and latency of these calls are tracked in observability so the trade-off remains visible.

## Consequences

- Routing logic is centralized in the LLM client layer (`models/`), not scattered through agents.
- A single env var (`GOOGLE_CLOUD_REGION`, `GOOGLE_CLOUD_FALLBACK_REGION`) controls both. Switching regions is a config change.
- Direct Anthropic API requires its own rate-limit and auth handling (separate from GCP IAM). This is documented in `models/anthropic_direct.py`.
- The `infra/terraform/` modules (when authored) will need to deploy resources to the primary region only; fallback region usage is read-only.

## Alternatives considered

- **Strict single-region (`me-central1` only)**. Rejected: blocks Claude usage during periods of regional unavailability. Devil's Advocate is a hard component of the architecture; losing it silently is worse than a cross-region call.
- **Primary in `us-central1` for maximum availability**. Rejected: meaningful latency penalty for Doha-based users on every call, with no offsetting benefit during the demo.
- **Self-host Cohere Rerank.** Possible later if cost or availability warrants; not worth the operational overhead at demo scale.

## Revisit triggers

- Production deployment.
- Any scenario requiring cross-region data residency guarantees (compliance ask, partner ask).
- Major change in Vertex Model Garden regional coverage.
