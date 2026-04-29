# ADR 0003 — Research-demo posture for textbook + premium-database access

- Status: accepted
- Date: 2026-04-29
- Deciders: Rahman Shakoor
- Source decision: `KICKOFF_PLAN.md` Decisions Log rows A and B.

## Context

The Reasoner depends on textbook concepts (Stern, Robbins, Harrison's, Goodman & Gilman, Wagner, Felson, Fitzpatrick, ...) and the Research Prescriber depends on drug-database content (UpToDate, Lexicomp, DynaMed, BMJ Best Practice, DrugBank, ...). Most textbook publishers and **all** of the premium clinical databases prohibit AI/RAG/redistribution use of their content even on paid individual subscriptions. Their commercial AI/enterprise license tiers exist precisely to license this kind of usage.

Three options were on the table:

1. **Procure enterprise/AI-licensed access** before building anything. Strict ToS-compliance, high cost ($5K–$50K+/yr), multi-month procurement, blocks all Phase 0 progress.
2. **Substitute permissively-licensed sources only.** Demo viable on free corpora alone (StatPearls + NICE + USPSTF + specialty guidelines + DailyMed) but with materially degraded prescribing capability.
3. **Download personal copies + hold individual subscriptions, save locally for retrieval, cite sources.** Non-compliant with most premium-DB ToS even on paid individual subs. Acceptable risk for a private demo behind IAP; **not** acceptable at production breadth.

## Decision

Adopt option 3 for the duration of the IAP-gated research demo, with explicit escape conditions.

Concretely:

- Textbooks (Tier B in `RESOURCE_ACQUISITION.md`): user-provided digital copies; concept extraction in our own structured schema; stored locally; cited per chunk.
- Premium databases (Tier C): **individual** subscriptions where available (UpToDate, BMJ Best Practice, DynaMed, Lexicomp, DrugBank academic, VisualDx, MKSAP). Programmatic queries with local content-hashed cache (90-day TTL) and human-equivalent rate limiting (≤ 30 req/hr/source).
- Every chunk carries `citation` and `authority_tier`. Every claim in user-facing output is grounded by a citation.
- No legal counsel engagement for the demo. Risk is account termination if discovered, not legal liability for citation alone.

**Escape conditions — this posture is revisited and likely retired before any of:**
- Demo widening beyond the named tester group.
- Public deployment.
- Use by any external organization (research collaborator, hospital, vendor).
- Any commercial intent.

When any of those triggers, the project must move to option 1 (or hybrid 1+2) before content widens. Failure to do so is a hard block on shipping.

## Consequences

- Phase 0 ingestion can start immediately — no procurement bottleneck.
- The system is **not** legally clean to widen access. This is recorded prominently in `README.md`, `RESOURCE_ACQUISITION.md`, and the project memory file.
- Caching reduces both cost and detection surface; the rate limit is set so traffic patterns look like human use.
- Eval reports and audit logs do not exfiltrate premium content (citations only).

## Alternatives considered

- **Option 1 (compliant procurement first)**. Rejected: blocks 6+ months of Phase 0 work. The demo's purpose is to evaluate viability before committing to full procurement.
- **Option 2 (free sources only)**. Acceptable as a fallback if premium sub access is denied or revoked, but degrades prescribing quality below what the architecture is designed to demonstrate.
