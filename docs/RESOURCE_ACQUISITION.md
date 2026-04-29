# Resource acquisition

Sources used by the system, how they are acquired, and the policy for using them. See [`KICKOFF_PLAN.md` §9](KICKOFF_PLAN.md#9-resource-acquisition-plan) and [`adrs/0003-research-demo-tos-posture.md`](adrs/0003-research-demo-tos-posture.md) for the underlying decision.

## Posture

> Retrieve all data, save locally, structure for retrieval, cite sources in every claim. Treat as a private research corpus accessed only by the developer and IAP-gated testers. Premium databases use individual subscriptions where available. AI-use ToS violations on premium subs are accepted with eyes open.

> **This posture must be revisited before any access widening or production deployment.** When the demo opens beyond the named tester group, premium-source ingestion paths must be re-evaluated against enterprise-tier terms.

## Source tiers

### Tier A — Free / open access

Download Day 1, no friction.

| Resource | Channel | Format |
|---|---|---|
| StatPearls | NCBI Bookshelf bulk download | XML |
| NICE guidelines | NICE API | HTML/PDF |
| USPSTF | direct download | HTML/PDF |
| WHO guidelines | WHO API | PDF |
| AHA/ACC, ESC, ATS, GOLD, GINA, IDSA, ADA, ACG, AGA, AASLD, KDIGO, ACR, EULAR, ASH | per-society | PDF |
| LITFL ECG Library | scrape (CC-BY-NC for many) | HTML + images |
| OpenStax (Anatomy & Physiology) | direct | PDF/HTML |
| DailyMed | NLM bulk | XML |
| RxNorm | NLM monthly release | RRF |
| ICD-10-CM | CMS | XML/CSV |
| LOINC | direct download (free with registration) | CSV |
| UMLS Metathesaurus | NLM (free research license) | RRF |
| PMC Open Access subset | NCBI bulk | XML |
| BMJ Case Reports OA | direct | XML |
| ARUP Consult, Mayo Clinic Labs catalog | scrape (check ToS) | HTML |

### Tier B — Personal-research textbook access

User-provided digital copies; extract concepts in structured schema; store locally; cite. Personal-research fair-use posture for a private demo. Re-evaluate before any access widening.

- Stern, Cifu, Altkorn — *Symptoms to Diagnosis* (cognitive backbone — chapter 1 + per-complaint).
- Robbins / Harrison's / Goodman & Gilman / Wagner / Felson / Fitzpatrick / Braunwald / Murray & Nadel / Sleisenger / Mandell / Williams / Brenner / Kelley / Hoffman / Katzung / Wallach / Boron / Guyton / West / Pappano / Dubin.

### Tier C — Premium individual subscriptions

Individual-tier subscriptions used as personal research data sources with citation. **Each source has ToS prohibiting AI/RAG use even on paid individual subscriptions.** That risk is explicitly accepted for this private, IAP-gated demo. Caching and rate-limiting reduce cost and detection surface.

| Resource | Channel | Estimate |
|---|---|---|
| UpToDate | Individual sub (Wolters Kluwer) | ~$0.6K/yr |
| DynaMed | Individual sub (EBSCO) where available | ~$0.4K/yr |
| BMJ Best Practice | Individual sub | ~$0.5K/yr |
| Lexicomp | Individual sub | ~$0.3K/yr |
| DrugBank | Academic/research tier | $0–$2K/yr |
| VisualDx | Individual sub | ~$0.3K/yr |
| Micromedex | Institutional only — substitute with DrugBank Academic + DailyMed if no path | $0–$60K/yr |
| MKSAP | ACP individual | ~$0.5K/yr |
| SNOMED CT | IHTSDO research-tier affiliate license (Qatar status TBD) | $0–$5K |

**Demo-period total estimate**: ~$2K–$10K/yr for premium subs, plus model + GCP costs.

## Caching + rate-limiting

For Tier C subscriptions queried programmatically:

- Local content-hashed cache with **90-day TTL**. Re-queries hit cache, not source.
- Rate-limit at human-equivalent pace: **≤ 30 requests / hour per source**.
- Per-source query log retained for audit.
- Graceful degradation if access is revoked → next-best (DailyMed, NICE, specialty society guidelines) without breaking the diagnostic loop.

## Citation requirement

Every retrieved chunk carries a `citation` string and an `authority_tier` (1 = guideline, 2 = clinical reference, 3 = textbook). The Reasoner is required to cite by tier in its reasoning trace, and the user-facing output must include a citation list. The `CitationScorer` in eval enforces "every claim has a citation."

## Phase 0 status

The scaffold ships:

- No corpus downloads yet.
- `scripts/ingest_statpearls.py` (placeholder; runs once GCP project is decided — open item 21).
- No premium-sub clients (placeholders deferred until item 22 confirms which subs are in hand).

Tier A ingestion is the first concrete Phase 0 work after this scaffold lands.

## Substitution path

The demo is viable on Tier A alone (StatPearls + NICE + USPSTF + specialty societies + DailyMed + Wallach if licensed for research) with degraded prescribing capability. Plan can shrink to a scope-restricted demo while licensing resolves.
