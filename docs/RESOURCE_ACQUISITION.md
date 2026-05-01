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

GCP is deferred (Decision 2026-04-30). All current work runs in **direct-API / local-disk
mode**: ingesters write `chunks.jsonl` under `knowledge/_local/<source>/` keyed by a
deterministic chunk id, and the runtime reads them locally. The same files become
the input to Vertex Vector Search later.

Each chunk carries a `source_location` field that points back to the exact part of
the source artefact (page range for PDFs, NBK + section anchor for StatPearls,
SetID + LOINC code for DailyMed, ICD code for ICD-10-CM, PMC + section for PMC OA,
canonical URL + anchor for HTML scrapes). Citations remain reproducible without
re-fetching.

### Implemented ingesters

| Source | Status | CLI | Chunks (current) |
|---|---|---|---|
| ICD-10-CM | full corpus | `make ingest-icd10cm` | 97,584 (97,584 codes) |
| USPSTF | all current recommendations | `make ingest-uspstf` | 1,763 (74 topics) |
| OpenStax Anatomy & Physiology 2e | full book | `make ingest-openstax` | 2,195 (30 chapters) |
| DailyMed (FDA SPL) | smoke (200 labels) | `make ingest-dailymed` | 4,026 (192 labels) |
| StatPearls (NCBI Bookshelf) | smoke (30 articles) | `make ingest-statpearls` | 702 (30 articles) |
| PMC Open Access | query-driven; smoke | `make ingest-pmc-oa QUERY=…` | 1,138 (30 case reports) |

`make acquire-corpus-status` reads `knowledge/_local/MANIFEST.json` for live counts.
`make acquire-quick` runs a small smoke of every ingester end-to-end.

### Not yet implemented (next session)

- WHO IRIS — DSpace OAI-PMH harvester. Curated by collection (Guidelines, Technical
  Reports) rather than full-corpus to control disk + crawl.
- Specialty society guidelines (AHA/ACC, ESC, ATS, GOLD, GINA, IDSA, ADA, ACG, AGA,
  AASLD, KDIGO, ACR, EULAR, ASH) — per-society downloaders; URLs need cataloguing.
- NICE guidelines — UK; no public bulk download. Per-topic fetch.
- LITFL ECG library — CC-BY-NC for many entries; conservative scrape pending.
- BMJ Case Reports OA — covered indirectly by `pmc_oa` (BMJ Case Reports is in PMC OA).

### Long-running full-corpus ingest

The smoke runs above prove the pipeline. To pull full corpora:

- DailyMed full (~80K labels, multi-GB, many hours): `make ingest-dailymed`
- StatPearls full (~9.6K articles, hours): `make ingest-statpearls`
- PMC OA: incremental by query. Each query writes to the same store; chunk ids
  deduplicate. Example queries in `scripts/ingest_pmc_oa.py` docstring.

Each ingester is **resumable**: cached raw artefacts skip re-download on the next
run, so an interrupted long ingest just resumes.

### License-required free corpora — user actions needed

These need a one-time application from you; once the credentials/data files are in
hand, ingester scaffolding will pick them up under `knowledge/_local/<source>/raw/`.

| Source | What to do | Approx. turnaround | Why we need it |
|---|---|---|---|
| **UMLS Metathesaurus** | Apply for a UTS account and accept the Metathesaurus licence at https://uts.nlm.nih.gov/uts/signup-login. After approval, download the latest Metathesaurus full release. | 1–3 business days | Ontology query expansion (SNOMED ↔ ICD ↔ LOINC ↔ RxNorm crosswalks) feeding the retriever. |
| **LOINC** | Register at https://loinc.org/downloads/ (free, immediate) and download the latest LOINC table CSV. | immediate | Lab / observation code resolution in the diagnostic_tests index. |
| **DrugBank Academic** | Apply at https://go.drugbank.com/releases/academic for the academic / non-commercial tier. | 1–2 weeks | Structured drug data (mechanisms, interactions, targets) for the prescriber tools without hitting commercial API ToS. |
| **SNOMED CT** | Confirm Qatar IHTSDO member status at https://www.snomed.org/our-members; if not a member, apply for a research-tier affiliate licence directly with SNOMED International. Until cleared, retrieval falls back to ICD-10-CM + LOINC + RxNorm + UMLS-derived mappings. | weeks | Canonical clinical terminology for the ontology layer. |
| **MKSAP** (optional) | Confirm whether you already have an ACP membership/MKSAP licence; if so, drop the digital release into `knowledge/_local/mksap/raw/`. Skip otherwise — the demo runs without it. | n/a | Adversarial eval cases sourced with citation. |

### User-provided digital copies — Tier B textbooks

Drop digital copies into the matching directory under `knowledge/_local/`. The
ingester for each book reads the file in place (no upload, no re-encoding). All
gitignored.

| Book | Drop at | Format preference | Status |
|---|---|---|---|
| Stern, *Symptoms to Diagnosis* (4th ed., 2020) | `knowledge/_local/stern/raw/` | PDF or EPUB | **ingested** (33 chapters, 1,837 chunks; per-page `source_location`) |
| Robbins & Cotran, *Pathologic Basis of Disease* | `knowledge/_local/robbins/raw/` | PDF | pending user upload |
| Harrison's *Principles of Internal Medicine* | `knowledge/_local/harrisons/raw/` | PDF | pending user upload |
| Goodman & Gilman, *Pharmacological Basis of Therapeutics* | `knowledge/_local/goodman_gilman/raw/` | PDF | pending user upload |
| Wagner, *Marriott's Practical Electrocardiography* | `knowledge/_local/wagner/raw/` | PDF | pending user upload |
| Felson's *Principles of Chest Roentgenology* | `knowledge/_local/felson/raw/` | PDF | pending user upload |
| Fitzpatrick's *Color Atlas of Clinical Dermatology* | `knowledge/_local/fitzpatrick/raw/` | PDF | pending user upload |

Phase 1 (chest pain end-to-end) only strictly needs Stern + Wagner + a pharmacology
source; the rest can land per-complaint as the breadth expands. **Stern is the
cognitive backbone**: Ch. 1 became the Reasoner system prompt
(`prompts/reasoner/system_v1.j2`); the 31 complaint chapters (3-33) feed
per-complaint templates at `src/tongue_doctor/templates/data/<slug>.yaml`. See
`docs/STERN_REASONING_BACKBONE.md` for the mapping.

Per-chapter template extraction status: `chest_pain.yaml` landed (16 diagnoses
across all 4 buckets, 10-step algorithm distilled from Figure 9-1 + Figure 9-2).
Remaining 30 chapters extract on demand via the Read-tool path (see backbone
report) or via `scripts/extract_stern_to_templates.py` if Anthropic API access
is configured.

### Tier C premium subscriptions — deferred per user direction

Per the 2026-04-30 decision, premium subscriptions (UpToDate, DynaMed, BMJ Best
Practice, Lexicomp, VisualDx, Micromedex, DrugBank commercial) are **not in scope
for this acquisition pass**. Clients are stubs; the demo runs on the Tier A free
corpus + license-required free corpus + user-provided textbooks until that
posture changes.

## Substitution path

The demo is viable on Tier A alone (StatPearls + NICE + USPSTF + specialty societies + DailyMed + Wallach if licensed for research) with degraded prescribing capability. Plan can shrink to a scope-restricted demo while licensing resolves.
