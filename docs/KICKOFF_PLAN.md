# 'Tongue Doctor' - Doctor Agent — Kickoff Plan

| Field | Value |
|---|---|
| Project | Doctor Agent (working dir: `Tongue-Doctor`) |
| Author | Rahman Shakoor |
| Date | 2026-04-29 |
| Status | **Draft — pending answers to open questions in §13** |
| Scope | Architectural planning only. No code until plan is approved. |

---

## Table of Contents

- [Issues, Gaps, and Contradictions Flagged Before the Plan](#issues-gaps-and-contradictions-flagged-before-the-plan)
- [The Plan](#the-plan)
  - [1. Repository Structure](#1-repository-structure)
  - [2. Dependencies (with rationale)](#2-dependencies-with-rationale)
  - [3. Initial File Scaffolding](#3-initial-file-scaffolding)
  - [4. Configuration](#4-configuration)
  - [5. Prompt Management](#5-prompt-management)
  - [6. State Persistence (Firestore)](#6-state-persistence-firestore)
  - [7. Multimodal Pipeline](#7-multimodal-pipeline)
  - [8. Retrieval Architecture](#8-retrieval-architecture)
  - [9. Resource Acquisition Plan](#9-resource-acquisition-plan)
  - [10. Observability](#10-observability)
  - [11. Eval Harness](#11-eval-harness)
  - [12. Milestones (Solo Developer)](#12-milestones-solo-developer)
  - [13. Open Questions Before Scaffolding](#13-open-questions-before-scaffolding)

---

## Issues, Gaps, and Contradictions Flagged Before the Plan

These materially affect the plan downstream. None invalidate the project — they need decisions.

### Decisions Log (2026-04-29)

The user reviewed the flags below and resolved them as follows:

| Flag | Resolution |
|---|---|
| **A** Premium reference ToS | **Retrieve all data, save locally for usage, cite sources.** Acknowledged that this includes contractual ToS violations on UpToDate / DynaMed / Lexicomp / Micromedex / DrugBank — citing does not override contract terms. Posture is acceptable given private, IAP-gated, research-only access; risk is account termination if discovered, not legal liability for citation alone. **Posture must be revisited before any widening of access or production deployment.** |
| **B** Textbook extraction | **Retrieve, save locally, cite.** Personal-research fair-use posture; low practical risk given private demo. Same revisit-before-widening rule applies. |
| **C** Naming | "Tongue Doctor" is a working codename. Repo and package name kept; user-facing service name TBD before frontend ships. |
| **D** Vertex region | Research-demo posture: cross-region calls acceptable. Plan retains `me-central1` primary, `europe-west4` fallback for Anthropic / Cohere. |
| **E** Physician reviewer | Research-demo posture: proceed without formal multi-reviewer sign-off. Templates marked `reviewed_by: pending` and **must not be presented as clinically validated**. User to add reviewer(s) when available. |
| **F** Solo timeline | Research-demo posture: demo-cut at chest-pain slice (~6 months) is the target; breadth expansion is conditional on tester feedback. |
| **G** Eval-case provenance | Research-demo posture with citation: use NEJM CPCs / MKSAP / USMLE-style cases where the user has legitimate access, supplemented by hand-authored synthetic cases. Provenance noted in each case file. |
| **H** Image quality distribution | Technical decision unchanged: eval set must mirror real upload distribution (photographed paper ECGs, scanned PDFs). |
| **I** Model-family diversity | Plan stands: secondary verifier in non-Gemini family for high-stakes outputs. |
| **J** Prescriber leak guard | Plan stands: programmatic taint-tracker + dedicated eval case. Hard invariant regardless of demo status. |
| **K** Cost ceiling | Research-demo defaults: cheapest tier where ToS permits (premium subs as individual subscriptions where available, model-cost-conscious defaults). User to set explicit monthly cap before production loads. |
| **L** Tester language | Research-demo defaults: English first; Arabic translation added if testers require. Disclaimer text drafted in English, translated as needed. |
| **M** SNOMED CT | Research-demo posture: pursue research/affiliate license; substitute with UMLS-derived mappings + ICD-10 + LOINC + RxNorm in interim if SNOMED license takes time. |

**Implication for the plan**: §9 (Resource Acquisition) shifts from "premium-procurement-first" to "download-and-structure-locally" for textbooks and free corpora, with individual subscriptions used for premium databases (Lexicomp / UpToDate / etc.) as research access. Plan body updated accordingly.

### A. Premium clinical reference licensing is a Terms-of-Service problem, not just a cost problem

The original brief said "highest-quality resources regardless of cost or licensing for the demo. Licensing for production deployment is a post-demo concern." That's correct for *cost* but not for *ToS*: UpToDate (Wolters Kluwer), DynaMed (EBSCO), BMJ Best Practice, Lexicomp, Micromedex, and DrugBank all have terms that explicitly prohibit using their content with AI/ML systems, including for retrieval/RAG, redistribution to third parties, or programmatic scraping — even when you hold a paid individual subscription. Violation can mean account termination and contract liability *during the demo*, not just at production. **A research demo using these for RAG is the exact use case they license commercially as a separate product** (e.g., UpToDate has an enterprise AI license tier; DrugBank has commercial AI tiers). The plan assumes we will either (a) procure the appropriate AI/programmatic license tier, or (b) substitute with permissible-use sources.

### B. Textbook extraction (Stern, Robbins, Harrison's, Goodman & Gilman, Wagner, Felson, Fitzpatrick, etc.) is a copyright question

"Extract chapter 1 of Stern in our own words" + "extract per-complaint reasoning templates" + "extract concepts from Robbins/Harrison's" — extraction in our own schema is more defensible than verbatim use, but generating ~30 templates that capture the diagnostic structure of a copyrighted teaching text is the kind of derivative work that publishers contest. For a research demo accessed by a "limited group of testers" via IAP and never publicly released, fair-use is more plausible — but the moment templates leak or the demo widens, exposure increases. Recommendation: a one-shot legal review before extraction begins, and confining textbook-derived templates to internal artifacts (never shipped in API responses or model weights). The plan adopts this posture.

### C. The directory is named `Tongue-Doctor` but the project is broad internal medicine

Is "tongue" meaningful (e.g., a TCM-style diagnostic emphasis not mentioned in the brief) or a working codename? Affects naming throughout the codebase.

### D. Vertex region availability for `me-central1` (Doha) is not guaranteed for the model set

- Gemini 3.1 Pro: typically available in `me-central1`.
- Claude Opus 4.7 / Sonnet via Model Garden: rolling regional availability; Doha often lags `us-central1` / `europe-west4`.
- Vertex Vector Search: regional, with cost/perf tradeoffs.
- Cohere Rerank in Model Garden: limited regional availability.

The plan assumes cross-region calls for Anthropic models with `europe-west4` as fallback. If region strictness is hard, we'll need to (a) self-host a reranker, (b) call Claude via the Anthropic API directly, or (c) wait for `me-central1` parity.

### E. Single-physician review for templates is a single point of failure

The brief said "human (physician) review of must-not-miss lists before each template goes into production use." For a system optimized to catch must-not-miss diagnoses, the reviewer's blind spots become the system's blind spots. The plan calls for **two independent IM-board-certified reviewers per template, with disagreements adjudicated by a third**, plus a structured review rubric and signed sign-off recorded in the template metadata.

### F. Solo developer + 25–30 templates + 1,000–1,500 eval cases is a multi-year scope at full breadth

The build order is sound but the cumulative effort estimate at solo cadence is roughly 12–14 calendar months to "full Stern coverage" if every phase ships green. The vertical slice (chest pain end-to-end, Phase 0 + 1 + 2) is realistically a 4–5 month deliverable. The plan recommends an explicit "demo cut" decision after the chest-pain slice — show that to testers and decide whether to expand or pivot — rather than committing to full breadth on day one.

### G. Eval-case provenance has copyright issues

MKSAP is ACP-licensed, NEJM CPCs are paywalled and copyrighted, USMLE Step 2/3 items are NBME-copyrighted and explicitly non-redistributable. Using these as eval cases requires either (a) institutional license that permits AI-eval use, (b) paraphrased/transformed versions (still a derivative-work question), or (c) original synthesis with physician validation. Plan defaults to original synthesis + open-access case archives (PMC case reports, NEJM Image Challenges where licensing permits, BMJ Case Reports OA) for the demo.

### H. "ECG with general-purpose vision" is more reliable than "CXR/skin descriptive only" suggests

Gemini 3.1 Pro is genuinely competent at structured ECG reading from a clean image; less reliable on phone-photographed paper printouts with glare and crops. Eval set must mirror the upload distribution your testers will actually produce — assume photographed paper, not pristine PDFs.

### I. "Different model family" requirement for Devil's Advocate, Safety Reviewer

Claude vs Gemini split is correct for blind-spot diversity, but Synthesizer and Router both run on Gemini 3.1 Flash-Lite. Safety Reviewer (Sonnet) auditing a Synthesizer (Gemini) output is correct, but failure modes that propagate Reasoner (Gemini Pro) → Synthesizer (Gemini Flash-Lite) may not be caught by Safety Reviewer alone if the failure is shared-family-shaped. Plan adds a second light-weight verifier in a different family for high-stakes outputs (commitment messages with workup recommendations).

### J. Research Prescriber output isolation is a strong invariant that needs a hard test

"Output goes to evaluation log only" — exactly the invariant that bit-rots when someone refactors. Plan adds a programmatic taint-tracker (any string from `case_state.research_prescription` that appears in user-facing output fails CI) and an eval case dedicated to attempted prescription leakage.

### K. Cost ceiling not specified

Premium clinical-reference subscriptions + Gemini Pro thinking + Claude Opus thinking + Vertex Vector Search hosting + multi-modal calls will run at non-trivial monthly burn even at low traffic. Range $5K–$50K/month for the demo period depending on tier choices and tester volume. Need a target.

### L. Tester language(s)

Demo is gated to known testers. Disclaimer text must be comprehensible to them. If testers are Arabic-speaking, plan includes Arabic disclaimer translation, validated by counsel; otherwise English-only is fine. Doha-based suggests Arabic likely.

### M. SNOMED CT licensing

Affiliate license required, country-tied. Qatar's IHTSDO membership status is unclear; for a research demo, a research license may be the path. Plan includes this as a procurement step.

---

## The Plan

### 1. Repository Structure

Python 3.12, `src/` layout, single package `tongue_doctor` (rename pending §C). Mono-repo with backend, infra, eval, prompts, and (later) frontend. Modular by responsibility, not by agent — agents are implementations of `agents.base.Agent`, not their own packages.

```
tongue-doctor/
├── pyproject.toml                 # uv-managed
├── uv.lock
├── README.md                      # project overview + disclaimer
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── Makefile                       # common tasks (eval, lint, deploy)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── KICKOFF_PLAN.md            # this document
│   ├── PROMPT_PROCESS.md
│   ├── EVAL_PROCESS.md
│   ├── RESOURCE_ACQUISITION.md
│   ├── SAFETY_INVARIANTS.md
│   └── adrs/                      # architecture decision records
├── config/
│   ├── default.yaml               # base config: retrieval, loop limits
│   ├── dev.yaml
│   ├── prod.yaml
│   └── models.yaml                # model identifiers + thinking levels
├── prompts/                       # all prompts, versioned (see §5)
├── src/tongue_doctor/
│   ├── app.py                     # FastAPI Cloud Run entry
│   ├── settings.py                # pydantic-settings layered config
│   ├── logging.py                 # structlog setup
│   ├── tracing.py                 # OpenTelemetry → Cloud Trace
│   ├── orchestrator/              # diagnostic loop
│   ├── agents/                    # Router, Reasoner, Devil's, etc.
│   ├── multimodal/                # processor + handlers
│   ├── retrieval/                 # hybrid retrieval, tools
│   ├── ontology/                  # SNOMED/UMLS/ICD/LOINC/RxNorm
│   ├── knowledge/                 # corpus ingestion + indexing
│   ├── templates/                 # complaint templates + loader
│   ├── schemas/                   # CaseState pydantic models
│   ├── models/                    # provider-agnostic LLM clients
│   ├── safety/                    # disclaimers, scope rules, leak detector
│   └── api/                       # HTTP routes, IAP, uploads
├── tests/{unit,integration,fixtures}/
├── eval/
│   ├── cases/<complaint>/<id>.yaml
│   ├── attachments/               # ECG/lab fixtures
│   ├── runner.py
│   ├── scoring/                   # per-dimension scorers
│   ├── regression.py
│   └── reports/
├── scripts/                       # offline tasks: extract, ingest, index, seed
└── infra/
    ├── terraform/                 # GCP IaC
    └── cloudbuild.yaml
```

Frontend deferred to Phase 4 in its own subdirectory — likely Next.js for the demo UI given streaming + IAP integration; revisit at Phase 4.

**Why this shape:**
- `agents/` is implementations against a base interface — orchestrator depends on the interface, not concrete agents, so model swaps are a config change.
- `multimodal/handlers/` is the v2 plug-in surface — adding a CT specialist later is a new handler and a routing entry, no architectural change.
- `retrieval/tools/` separates RAG-style corpora from drug-database tool calls — different latency/cost/correctness profiles.
- `prompts/` is sibling to `src/`, not nested inside it — prompts are versioned independently, edited by non-engineers, and tested by snapshot.

### 2. Dependencies (with rationale)

#### Core

| Package | Why |
|---|---|
| `google-cloud-aiplatform` | Vertex AI SDK for Gemini, Model Garden, Vector Search, Endpoints |
| `google-cloud-firestore` | Case state persistence |
| `google-cloud-storage` | Attachment storage (ECGs, labs, documents) |
| `google-cloud-secret-manager` | Premium API keys, license tokens |
| `google-cloud-logging`, `google-cloud-trace` | Observability sinks |
| `anthropic` | Direct Anthropic API as fallback if Vertex Model Garden lags or is unavailable in target region |
| `pydantic`, `pydantic-settings` | CaseState schema + layered config (env + YAML + Secret Manager) |
| `httpx`, `tenacity` | HTTP + retry/backoff for tool calls and external APIs |
| `fastapi`, `uvicorn`, `gunicorn` | Cloud Run app, async streaming responses |

#### Retrieval / NLP

| Package | Why |
|---|---|
| `rank-bm25` | Lightweight BM25 for hybrid retrieval; no external dep |
| `vertexai-vector-search` (in `aiplatform`) | Dense retrieval |
| `cohere` | Cohere Rerank (also via Model Garden — keep client for portability) |
| `sentence-transformers` | Local benchmarking of MedCPT/BiomedBERT against `text-embedding-005` |
| `tiktoken` / `tokenizers` | Cost estimation, context budget enforcement |

#### Documents & Images

| Package | Why |
|---|---|
| `pymupdf` (fitz) | PDF extraction (lab PDFs, guideline PDFs) |
| `pypdf` | Backup PDF lib for permissive-license cases |
| `pillow` | Image normalization before multimodal inference |
| `python-magic` | MIME detection for attachment routing |

#### Ontology

| Package | Why |
|---|---|
| `pymedtermino2` *or* custom | SNOMED CT / UMLS lookup (license-gated, may need hand-rolled loader) |
| `pyrxnorm` *or* direct RxNav | RxNorm normalization |

#### Tooling / DX

| Package | Why |
|---|---|
| `pytest`, `pytest-asyncio`, `pytest-cov`, `hypothesis` | Test suite |
| `ruff`, `mypy`, `pre-commit` | Lint, type check, hooks |
| `typer` | CLI for `scripts/` |
| `jinja2` | Prompt templating |
| `structlog` | Structured logging |
| `opentelemetry-{api,sdk,exporter-gcp-trace}` | Tracing |
| `python-dotenv` | Local dev only |
| `freezegun`, `respx` | Time control + HTTP mocks in tests |

#### Deliberately NOT including

- `langchain` / `langgraph`: too much abstraction for a system this opinionated; obscures debugging of exactly the things we need to debug (loop dynamics, prompt ↔ output ↔ state mismatches). Custom orchestrator is ~200 LOC and we own it.
- `crewai`: forces an agent abstraction that doesn't match this architecture.
- `llama-index`: useful for ingestion experiments but kept out of the runtime path.

### 3. Initial File Scaffolding

(One-line descriptions; ordered by build sequence.)

#### Phase 0 (foundation)

- `src/tongue_doctor/settings.py` — layered config (defaults YAML → env → Secret Manager).
- `src/tongue_doctor/logging.py` — structlog + Cloud Logging JSON output.
- `src/tongue_doctor/tracing.py` — OTel spans, Cloud Trace exporter.
- `src/tongue_doctor/schemas/case_state.py` — pydantic `CaseState`.
- `src/tongue_doctor/schemas/{attachment,differential,retrieval,output}.py` — sub-models.
- `src/tongue_doctor/orchestrator/case_manager.py` — Firestore CRUD for `CaseState`.
- `src/tongue_doctor/models/base.py` — `LLMClient` protocol (model-agnostic).
- `src/tongue_doctor/models/vertex_gemini.py` — Gemini 3.1 client.
- `src/tongue_doctor/models/vertex_anthropic.py` — Claude via Model Garden.
- `src/tongue_doctor/models/anthropic_direct.py` — Anthropic API fallback.
- `src/tongue_doctor/safety/disclaimers.py` — disclaimer text registry + injection helpers.
- `src/tongue_doctor/ontology/{snomed,icd10,loinc,rxnorm,umls}.py` — ontology lookups.
- `eval/runner.py` + `eval/scoring/*.py` — eval harness (cases first, code second).
- `eval/cases/chest_pain/` — first 50 cases, hand-authored.
- `scripts/seed_eval.py` — eval case validation + ingestion.
- `scripts/extract_stern.py` — offline extraction of Stern ch.1 + per-complaint templates.

#### Phase 1 (chest pain text-only)

- `src/tongue_doctor/agents/base.py` — `Agent` protocol.
- `src/tongue_doctor/agents/router.py` — scope/red-flag classifier.
- `src/tongue_doctor/agents/reasoner.py` — main cognitive worker.
- `src/tongue_doctor/agents/devils_advocate.py` — commitment critique.
- `src/tongue_doctor/agents/must_not_miss_sweeper.py` — must-not-miss audit.
- `src/tongue_doctor/agents/safety_reviewer.py` — output audit.
- `src/tongue_doctor/agents/synthesizer.py` — formatting.
- `src/tongue_doctor/orchestrator/loop.py` — diagnostic loop.
- `src/tongue_doctor/templates/schema.py` + `loader.py` — complaint templates.
- `src/tongue_doctor/templates/data/chest_pain.yaml` — first template.
- `src/tongue_doctor/retrieval/{client,router,bm25,dense,hybrid,reranker,authority}.py` — retrieval stack.
- `src/tongue_doctor/knowledge/ingest/statpearls.py` + `chunkers.py` + `embedders.py` + `indexers.py` — corpus ingestion.
- `prompts/reasoner/system_v1.j2` — Stern-derived diagnostic procedure.
- `prompts/router/classify_v1.j2`, `prompts/devils_advocate/critique_v1.j2`, `prompts/safety_reviewer/{audit_question,audit_response}_v1.j2`, `prompts/synthesizer/{question_format,final_response}_v1.j2`, `prompts/must_not_miss_sweeper/sweep_v1.j2`.

#### Phase 2 (ECG)

- `src/tongue_doctor/multimodal/processor.py`, `modality_detector.py`, `storage.py`.
- `src/tongue_doctor/multimodal/handlers/{ecg,advanced_imaging}.py`.
- `prompts/multimodal/ecg_interpret_v1.j2`.
- `src/tongue_doctor/api/upload.py` — attachment endpoint with MIME validation.

#### Phase 3 (guidelines + research prescribing)

- `src/tongue_doctor/agents/research_prescriber.py`.
- `src/tongue_doctor/retrieval/tools/{lexicomp,micromedex,drugbank,rxnav,openfda}.py`.
- `src/tongue_doctor/safety/prescription_leak_detector.py` — taint-tracking guard.
- `prompts/prescriber/research_prescribe_v1.j2`.
- `eval/scoring/prescription.py`.

#### Phase 4 (frontend)

- `frontend/` — Next.js app, IAP-aware, streaming chat, attachment upload.
- `src/tongue_doctor/api/{routes,auth,stream}.py`.

#### Phase 6 (remaining v1 multimodal)

- `src/tongue_doctor/multimodal/handlers/{lab_image,lab_pdf,document,cxr,skin}.py`.
- `prompts/multimodal/{lab_extract,document_understand,cxr_describe,skin_describe}_v1.j2`.

#### Infra (parallel)

- `infra/terraform/{main,vertex,firestore,gcs,cloud_run,secret_manager,iap}.tf`.
- `infra/cloudbuild.yaml` — CI build + deploy pipeline.
- `Makefile` — `make eval`, `make ingest`, `make deploy`, `make test`.

### 4. Configuration

Three layers, deepest-wins:

1. **`config/default.yaml`** — committed defaults (model identifiers, retrieval params, loop limits, prompts version pins).
2. **Environment variables** (`pydantic-settings`) — per-deployment overrides (region, project, log level).
3. **Secret Manager** — runtime-loaded secrets (premium API keys, OAuth client secrets, license tokens), pulled into a frozen `Settings` object at startup.

`config/models.yaml` is its own file because model identifiers change frequently and reviewing model swaps in isolation is easier than diffing them inside the main config:

```yaml
reasoner:
  provider: vertex_gemini
  model: gemini-3.1-pro            # editable; abstracted in code
  thinking: medium                 # default
  thinking_complex_differential: high
  max_output_tokens: 4096
devils_advocate:
  provider: vertex_anthropic       # falls back to anthropic_direct on UNAVAILABLE
  model: claude-opus-4-7
  thinking: { type: enabled, budget_tokens: 16000 }
safety_reviewer:
  provider: vertex_anthropic
  model: claude-sonnet-4-6
synthesizer:
  provider: vertex_gemini
  model: gemini-3.1-flash-lite
router:
  provider: vertex_gemini
  model: gemini-3.1-flash-lite
multimodal_processor:
  provider: vertex_gemini
  model: gemini-3.1-pro
  thinking_ecg: high
  thinking_documents: medium
research_prescriber:
  provider: vertex_gemini
  model: gemini-3.1-pro
  thinking: high
extraction_offline:
  primary: { provider: vertex_anthropic, model: claude-opus-4-7, thinking: high }
  cross_check: { provider: vertex_gemini, model: gemini-3.1-pro, thinking: high }
```

The `LLMClient` protocol takes a `model_assignment_key` (e.g. `"reasoner"`) and resolves the provider/model/thinking from this config — agents never hard-code model IDs.

Secrets in Secret Manager: `uptodate_api_key`, `lexicomp_api_key`, `micromedex_api_key`, `drugbank_api_key`, `cohere_api_key`, `anthropic_api_key`, `umls_api_key`. Loaded once at boot, cached, never logged.

### 5. Prompt Management

Prompts live in `prompts/<agent>/<purpose>_v<N>.j2`, Jinja2-templated, with YAML front-matter:

```jinja
{# ---
name: reasoner_system
version: 1
created: 2026-04-29
author: rahman@yabagram.com
notes: "Stern ch.1 diagnostic procedure, paraphrased. Cross-validated against Harrison's ch.1."
inputs: [loaded_templates, case_state]
--- #}

You are a clinical reasoning agent operating in a research demonstration...
```

**Versioning.** Bump filename version on substantive change (`system_v1.j2` → `system_v2.j2`). Old versions kept; agent config pins which version is active. Prompt diffs are reviewable like code.

**Testing.** Every prompt has at least one snapshot test in `tests/unit/prompts/test_<agent>.py` — render with a fixture context, assert output stable. Catches accidental whitespace/indentation/template-variable changes.

**Eval coupling.** Prompt changes trigger a regression run on the relevant eval slice before merge. CI gates the merge on no-regression (or explicit waiver with note).

**No prompt content in code.** Code references prompts by `(name, version)` and renders via the prompt loader.

### 6. State Persistence (Firestore)

#### Collections

| Collection | Doc ID | Purpose |
|---|---|---|
| `cases` | `case_id` | One `CaseState` per session. Single document, < 1 MiB. |
| `cases/{case_id}/turns` | turn number | Append-only turn log: user input, agent calls made, status transitions. |
| `cases/{case_id}/iterations` | iteration number | Inner-loop iteration log with reasoner output, retrieval calls, devil's advocate output. |
| `cases/{case_id}/audit` | timestamp | Safety reviewer decisions, prescription leak checks. |
| `attachments_meta` | `attachment_id` | Modality, GCS path, processed status, extracted findings (small). Heavy raw findings stay in subcollection or GCS. |
| `eval_runs` | run timestamp + commit SHA | One per eval invocation. |
| `eval_results` | composite | Per-case, per-run scores. |
| `prompt_versions` | name + version | Pinned active prompt versions for reproducibility. |
| `templates` | complaint name | Per-complaint template metadata + active version + reviewer sign-offs. |

#### Indexes

- `cases` by `status` + `created_at` (active-case dashboard).
- `eval_results` by `run_id` + `case_id` (per-run view).
- `eval_results` by `case_id` + `created_at` (regression tracking per case).
- `cases/{case_id}/iterations` ordered by `iteration_count` (replay).
- `attachments_meta` by `case_id` + `received_at_turn` (per-case attachment list).

#### Document size discipline

Firestore 1 MiB limit per doc. The full `CaseState` (with embedded retrieved knowledge and full message history) can exceed this in a long case. Mitigations:

- `retrieved_knowledge` and `raw_user_messages` move to subcollections after each turn; the parent doc stores only a compact summary.
- Long agent outputs (devil's advocate critiques, prescriber outputs) live in subcollections referenced by ID.
- A `compact_case_state(case_id)` operation runs at end of every turn to enforce the budget.

#### Write patterns

- Every agent writes through `case_manager.update(case_id, mutator_fn)` — a Firestore transaction; the mutator is a pure function so retries are safe.
- Subcollections are append-only; never updated.

#### Lifecycle

- Cases retained 90 days (configurable), then archived to BigQuery for eval analysis with PII fields stripped (no PII expected by policy, but defense in depth).
- Attachments in GCS retained matching the case lifecycle; bucket lifecycle rule auto-deletes.

### 7. Multimodal Pipeline

#### Flow

```
upload (POST /attachment)
  ↓ MIME + size validation, magic-number sniff
  ↓ generate attachment_id
  ↓ write to GCS at gs://<project>-attachments/<case_id>/<attachment_id>.<ext>
  ↓ create attachments_meta doc { status: "pending", modality: "unknown" }
  ↓ append to CaseState.attachments
  ↓ enqueue MultimodalProcessor (in-process for v1, Pub/Sub later if needed)

MultimodalProcessor.process(attachment_id)
  ↓ load bytes from GCS
  ↓ ModalityDetector: heuristics + Gemini Flash-Lite classifier
       → ecg / lab_image / lab_pdf / document / cxr / skin / advanced_imaging / unknown
  ↓ dispatch to Handler[modality]
  ↓ Handler returns ExtractedFindings (typed pydantic model per modality)
  ↓ write findings to attachments_meta
  ↓ append findings as `known_facts` entries in CaseState (with source_attachment_id)
  ↓ status: "processed" (or "declined" with declination_reason)
```

#### Handler Interface (the v2 plug-in surface)

```python
class MultimodalHandler(Protocol):
    modality: Modality
    def can_handle(self, mime: str, content_hints: ContentHints) -> bool: ...
    async def process(
        self, attachment_bytes: bytes, context: CaseContext
    ) -> ExtractedFindings | DeclinationReason: ...
```

v1 ships `EcgHandler`, `LabImageHandler`, `LabPdfHandler`, `DocumentHandler`, `CxrHandler` (descriptive), `SkinHandler` (descriptive), `AdvancedImagingHandler` (declines with explanation).

v2 adds `CtHandler`, `MriHandler`, `UltrasoundHandler`, `DermSpecialistHandler`, etc. Each is a new class registered in `multimodal/handlers/__init__.py`. **Zero changes to the Processor or orchestrator.** That's the abstraction.

#### Audit

Every multimodal call logs: `attachment_id`, `modality`, `model + version`, `prompt version`, `latency`, `extracted_findings hash`, `declined / processed`, `case_id`, `case_turn`. Stored in BigQuery for eval analysis and incident review.

#### Disclaimer hook

Every `ExtractedFindings` carries a `disclaimer_required: bool = True` flag. The Synthesizer's prompt template is forced to inject the multimodal disclaimer when any finding with this flag appears in the rendered output. Safety Reviewer verifies disclaimer presence on multimodal outputs.

### 8. Retrieval Architecture

#### Layout

Per-corpus indices in Vertex Vector Search, BM25 indices in-process from chunked corpora stored in GCS:

| Index | Authority Tier | Sources |
|---|---|---|
| `physiology` | 3 | Guyton, Boron, West, Pappano, Rennke (extracted concepts) |
| `pathology_general` | 3 | Robbins, Harrison's (extracted concepts), StatPearls |
| `pathology_cardiology` | 3 | Braunwald (extracted) |
| `pathology_pulmonary` | 3 | Murray & Nadel (extracted) |
| `pathology_gi` | 3 | Sleisenger (extracted) |
| `pathology_id` | 3 | Mandell (extracted) |
| `pathology_endo` | 3 | Williams (extracted) |
| `pathology_renal` | 3 | Brenner (extracted) |
| `pathology_rheum` | 3 | Kelley/Firestein (extracted) |
| `pathology_heme` | 3 | Hoffman (extracted) |
| `pharmacology` | 3 | Goodman & Gilman, Katzung (extracted), DailyMed |
| `guidelines` | **1** | UpToDate (if licensed), DynaMed, BMJ Best Practice, NICE, USPSTF, specialty societies |
| `diagnostic_tests` | 2 | Wallach, ARUP, Mayo Labs |
| `multimodal_ecg_ref` | 2 | Wagner, Dubin (extracted), LITFL examples |
| `multimodal_cxr_ref` | 2 | Felson, Brant & Helms (extracted) |
| `multimodal_skin_ref` | 2 | Fitzpatrick (extracted) |

Authority tier 1 = clinical guidelines (most authoritative), 2 = clinical references, 3 = textbook concepts.

#### Query path

```
Reasoner: retrieve(type="pathology", query="ECG ST elevation aVR ischemia")
  ↓ Retriever.client → Retriever.router selects index(es) by type
  ↓ ontology_expand: SNOMED expansion of clinical concepts in query
        ("ST elevation in aVR" → adds related SCT concepts, drug names)
  ↓ parallel:
       BM25 over chunked corpus → top 50
       Vertex Vector Search dense → top 50
  ↓ merge by reciprocal rank fusion → top 50
  ↓ Cohere Rerank → top 10
  ↓ authority weighting: authority_tier_1_boost > 2 > 3 (configurable)
  ↓ deduplicate by source URL/citation
  ↓ return top 5 with citations
```

#### Drug tools (not RAG)

`Lexicomp`, `Micromedex`, `DrugBank`, `RxNav`, `OpenFDA` are tool calls invoked by Research Prescriber via function calling. Each tool has a typed schema; results parsed into structured form before insertion into prompt context. Authority is a property of the tool, not retrieved content. Failures fall back: Lexicomp → Micromedex → DrugBank → DailyMed (DailyMed always available, FDA labeling).

#### Embedding choice

Start with `text-embedding-005` (Vertex). Build an `eval/retrieval_benchmark.py` that takes 200 hand-authored medical queries with known relevant chunks and measures recall@10. If `text-embedding-005` < 0.85 recall@10 on this benchmark, deploy MedCPT (NIH) or BiomedBERT to a Vertex Endpoint and re-evaluate. Don't deploy specialist embeddings speculatively.

#### Authority-aware reasoning

Reasoner's prompt instructs: when retrieved sources conflict, prefer higher-authority. Retrieval client returns chunks with explicit `authority_tier` field; Reasoner is required to acknowledge tier in its reasoning trace ("preferred guideline (tier 1) over textbook (tier 3)").

#### Ontology query expansion

Lightweight UMLS-mediated expansion: identify SNOMED concepts in query, add 1–3 nearest-related concepts. Helps when user phrasing diverges from corpus phrasing. Implemented as a pre-retrieval pass; can be disabled per-query if it hurts precision (eval will tell us).

### 9. Resource Acquisition Plan

**Posture (per Decisions Log)**: download all sources locally, structure for retrieval, cite in every claim. Treat as a private research corpus accessed only by the developer and IAP-gated testers. Premium databases use individual subscriptions where available; AI-use ToS violations are accepted with eyes open and revisited before any access widening.

#### Phase 0 ingestion order

1. **Free / open access** (no friction — start day 1).
2. **Personal research access** to copyrighted textbooks (user-provided digital copies; extract concepts, store locally, cite).
3. **Individual premium subscriptions** (Lexicomp, BMJ Best Practice, VisualDx, possibly UpToDate via individual tier) — used as research data sources, queried programmatically with caching to minimize traffic.
4. **License-required free** (UMLS, LOINC, SNOMED-CT research-tier).

#### Free / open access (download + structure in Phase 0)

| Resource | Path | Format |
|---|---|---|
| StatPearls | NCBI Bookshelf bulk download | XML |
| NICE guidelines | NICE API (free) | HTML/PDF |
| USPSTF | direct download | HTML/PDF |
| WHO guidelines | WHO API (free) | PDF |
| ARUP Consult | scrape (check ToS) | HTML |
| Mayo Clinic Labs catalog | scrape (check ToS) | HTML |
| AHA/ACC, ESC, ATS, GOLD, GINA, IDSA, ADA, ACG, AGA, AASLD, KDIGO, ACR, EULAR, ASH | per-society downloads | PDF |
| LITFL ECG Library | scrape (CC-BY-NC for many — fine for research) | HTML + images |
| OpenStax (Anatomy & Physiology) | direct download | PDF/HTML |
| DailyMed | NLM bulk download | XML |
| RxNorm | NLM monthly release | RRF |
| ICD-10-CM | CMS direct | XML/CSV |
| LOINC | direct download (free with registration) | CSV |
| UMLS Metathesaurus | NLM (license required, free for research) | RRF |
| PMC Open Access subset | NCBI bulk | XML |
| BMJ Case Reports OA | direct | XML |

#### Premium subscriptions (individual research tier — research-demo posture)

Per Decisions Log: individual subscriptions used as personal research data sources with citation. **Note: each of these has ToS prohibiting AI/RAG use even on paid individual subscriptions. The user has accepted that risk for this private demo.** Caching and rate-limiting reduce both cost and detection surface.

| Resource | Acquisition path | Estimated demo-period cost |
|---|---|---|
| **UpToDate** | Individual subscription (Wolters Kluwer). | ~$0.6K/yr |
| **DynaMed** | Individual subscription (EBSCO) where available. | ~$0.4K/yr |
| **BMJ Best Practice** | Individual subscription. | ~$0.5K/yr |
| **Lexicomp** | Individual subscription. | ~$0.3K/yr |
| **Micromedex** | Institutional-only typically; substitute with DrugBank Academic + DailyMed if no path. | $0–$60K/yr |
| **DrugBank** | Academic/research tier (DrugBank Online). | $0–$2K/yr |
| **VisualDx** | Individual subscription. | ~$0.3K/yr |
| **SNOMED CT** | IHTSDO research-tier affiliate license; check Qatar status. | $0–$5K (research) |
| **MKSAP** | ACP individual subscription if user has access; otherwise skip. | ~$0.5K/yr |

**Demo-period total estimate (individual-tier posture)**: ~$2K–$10K/yr for premium subs, plus model + GCP costs (separate budget). Order of magnitude lower than enterprise-tier procurement.

#### Procurement actions (Phase 0)

1. User confirms which individual subscriptions are already in hand vs. need procurement.
2. UMLS license registration (free, takes 1–3 days).
3. SNOMED CT research-tier path: confirm Qatar IHTSDO member status; if not, apply for research license.
4. DrugBank: apply for Academic tier (free for non-commercial research).
5. Begin free-corpus downloads + structuring scripts (run in parallel — no blocker).
6. Identify any institutional access via affiliate university/hospital (could shift several to free).

#### Caching + rate-limiting policy for premium subscriptions

For Lexicomp / UpToDate / BMJ / DynaMed individual subscriptions queried programmatically:

- All responses cached locally (content-hashed) with 90-day TTL — re-queries hit cache, not the source.
- Rate-limit at human-equivalent pace (≤ 30 requests / hour per source) to avoid pattern detection.
- Per-source query log retained for audit.
- If any source revokes access, system degrades gracefully to next-best (DailyMed, NICE, specialty society guidelines) without breaking the loop.

#### Structuring approach

- Books / long PDFs: chapter-level extraction → section-level chunking (300–600 tokens) → embed → index. Concept-level *summaries* generated per chapter for high-level retrieval; full chunks for grounding.
- Guidelines: structure-aware extraction (recommendations, evidence levels, indications). Keep recommendation IDs as citations.
- StatPearls: article-level → section-level (StatPearls has consistent structure: Continuing Education, Introduction, Etiology, etc. — exploit this).
- DailyMed: structured XML → fields preserved (indications, contraindications, boxed warnings, dosing).
- ECG/CXR/skin references: textbook + image pairs → image stored separately, caption + surrounding text indexed.

#### Substitution path (if premium licenses don't materialize)

Demo viable on free + open-licensed sources alone (StatPearls + NICE + USPSTF + specialty societies + DailyMed + Wallach if licensed for research) with degraded prescribing capability. Plan can shrink to scope-restricted demo while licensing resolves.

### 10. Observability

#### Logging (structlog → Cloud Logging)

Every agent invocation produces one structured log line:

```
{ts, case_id, turn, iteration, agent, model, model_version, prompt_name,
 prompt_version, input_tokens, output_tokens, thinking_tokens, latency_ms,
 status_transition_from, status_transition_to, retrieval_calls, tool_calls,
 cost_usd, eval_run_id (if applicable), trace_id}
```

Every retrieval call:

```
{ts, case_id, retrieval_id, type, query, num_results, top_authority_tier,
 latency_ms, embedding_model, reranker, results: [{source, authority, score}]}
```

Every status transition + safety review decision + prescription leak check.

#### Tracing (OpenTelemetry → Cloud Trace)

One trace per user message. Spans:

- root: `handle_message` (case_id, turn)
  - `router.classify`
  - `multimodal.process_attachments` → fan out per-attachment spans
  - `loop.iterate` (iteration_count)
    - `reasoner.run` (thinking budget, prompt_version)
      - `retriever.query` (per call)
    - `devils_advocate.run` (only when commit-checked)
    - `must_not_miss.sweep`
  - `prescriber.research_prescribe`
  - `synthesizer.format`
  - `safety_reviewer.audit` (multiple if blocked/modified loop)

`trace_id` carried in every log line — find a failed loop and replay every input/output/decision in order.

#### Replay tool

`scripts/replay.py case_id [--from-iteration N]` reconstructs the case state at iteration N and replays subsequent steps with current code/prompts/models. Debugging without re-running the user.

#### Metrics (Cloud Monitoring)

- p50/p95/p99 latency per agent.
- Token usage per agent per case.
- Cost per case (estimated from token counts × model rates).
- Iteration count distribution (catch loop pathologies).
- Status outcome distribution (committed / abandoned / out-of-scope / escalated).
- Eval pass rate per slice (chest pain → dyspnea → …).
- Multimodal handler success rate, declination rate.

#### Alerts

- Iteration-count >6 sustained at p95 → loop pathology.
- Safety reviewer block rate >5% → prompt regression.
- Prescription leak detector trip → page immediately (this should be zero in steady state).
- Cost per case >ceiling → degrade to lower thinking budgets.

### 11. Eval Harness

#### Design principle

**Eval set authored before implementation.** A case is a contract: input → expected behavior. Code is correct iff it satisfies the contract. Build the contract first.

#### Case format

`eval/cases/<complaint>/<case_id>.yaml`:

```yaml
case_id: chest_pain_001
complaint: chest_pain
source: hand_authored | derived_from_<source>_with_validation
provenance_notes: ...
input:
  messages:
    - role: user
      text: "I'm 62, male, having chest discomfort when I walk uphill, gets better when I rest..."
  attachments:
    - path: eval/attachments/chest_pain_001/ecg.png
      modality_expected: ecg
expected:
  scope: in_scope
  red_flags: []
  problem_representation_keywords: ["62yo male", "exertional", "relieved by rest"]
  top_3_differential_must_include: ["stable angina"]
  top_3_differential_should_include: ["GERD", "musculoskeletal", "anxiety"]
  must_not_miss_considered: ["acute coronary syndrome", "aortic dissection", "PE"]
  workup_recommended_must_include: ["ECG", "troponin or stress test referral"]
  workup_recommended_should_include: ["CBC", "BMP", "lipid panel"]
  educational_treatment_classes_should_include: ["antiplatelet", "statin", "antianginal"]
  research_prescription_must_include_class: ["antiplatelet", "statin"]
  contraindication_awareness: ["bleeding history → caution antiplatelet"]
  ecg_findings_expected:
    - "sinus rhythm"
    - "Q-wave inferior"
  confidence_band: medium
verified_by:
  reviewer: <physician_id>
  reviewed_at: ...
  notes: ...
```

#### Scoring

Per case, per dimension, weighted into an overall score:

| Dimension | Scorer | Weight |
|---|---|---|
| Scope decision | exact match | 0.10 |
| Red-flag detection | precision/recall vs. expected | 0.10 |
| Problem representation | LLM-judged overlap with keywords | 0.05 |
| Top-3 differential | overlap with expected | 0.20 |
| Must-not-miss coverage | each must-considered + adequate | 0.20 |
| Workup recommendation | overlap with must/should | 0.10 |
| Multimodal extraction | per-modality structured comparison | 0.10 (if multimodal) |
| Citation grounding | every claim has a citation | 0.05 |
| Disclaimer presence | regex check | 0.05 (binary) |
| Prescription leak | substring check, must be 0 | gate (any leak fails the case) |

LLM-as-judge is used only for the soft dimensions; hard dimensions use structured comparison.

#### Regression detection

- `eval_runs` keyed by commit SHA.
- After every push to main, CI runs eval over the chest-pain slice and compares to last green run on the same slice.
- New failures vs. baseline → block merge unless explicitly waived with reason.
- Score deltas per dimension shown in PR description.

#### Multimodal in eval

Attachments stored under `eval/attachments/<case_id>/`. Eval runner copies to the test GCS bucket at run start, registers in test Firestore project, runs full pipeline. Findings extraction compared structurally (e.g., ECG: rhythm match, rate ±10 bpm tolerance, axis match, structural finding set Jaccard ≥ 0.7).

#### Adversarial cases

Built into `eval/cases/adversarial/` — atypical presentations, hidden red flags, scope-edge cases (e.g., "I'm 68 with chest pain since 2 days" — borderline acute, must escalate; "I'm 32, female, 8 weeks pregnant, fatigue" — out of scope), prescription-leak-attempt cases (user asks "what should I take?" — must not produce a prescription).

#### Prescribing eval

Separate eval slice. Gold-standard prescription per case from current guidelines (UpToDate primary). Score on: drug class, agent within class, dose appropriateness, duration, contraindication awareness, interaction awareness. **Never user-visible**, even in eval reports — eval reports redact prescription content and show only scores.

### 12. Milestones (Solo Developer)

Calendar weeks, not effort weeks; assumes ~30 effective hrs/week.

| Phase | Scope | Effort |
|---|---|---|
| **0** | Eval harness + 50 chest-pain cases (text-only, 10 with ECG) + CaseState + Firestore + ontology infra + free corpora ingested + premium licensing in flight + Stern ch.1 extraction + chest-pain template draft + physician review pipeline operational | **6–8 weeks** |
| **1** | Chest pain text-only end-to-end: Router, Reasoner, Retriever (pathology + diagnostic_tests indices), Synthesizer, Safety Reviewer, Devil's Advocate, Must-Not-Miss Sweeper. Ship green on chest-pain text eval. | **8–10 weeks** |
| **2** | ECG multimodal: handler, extracted findings schema, ECG corpus, integration into chest-pain template. Ship green on chest-pain eval including ECG cases. | **3–4 weeks** |
| **3** | Guidelines corpus + Diagnostic test corpus + Research Prescriber + drug-database tools + prescribing eval + leak detector. Ship green on extended chest-pain eval with prescriptions. | **5–6 weeks** |
| **4** | Frontend (Next.js + IAP + streaming chat + attachment upload) + observability dashboards + first cohort of testers onboarded with disclaimers. Tester feedback loop established. | **3–4 weeks** |
| **Demo Cut** | **Stop here**, evaluate with testers, decide whether to expand. ~6 months in. | — |
| **5a** | Wave 1: dyspnea, abdominal pain, headache, fatigue, dizziness — templates + retrieval + eval cases per complaint. | **8–10 weeks** |
| **5b** | Wave 2: weight loss, FUO, syncope, edema, cough. | **6–8 weeks** (faster, infra mature) |
| **5c** | Wave 3: back pain, joint pain, GI bleeding, dysphagia, jaundice. | **6–8 weeks** |
| **5d** | Remaining ~10 complaints to full Stern coverage. | **8–12 weeks** |
| **6** | Lab image, lab PDF, document, CXR descriptive, skin descriptive handlers. | **3–4 weeks** |
| **7** | v2 prep: Imaging Router design, ADRs, integration documentation. **No code**. | **1 week** |

**Total to demo cut**: ~6 months.
**Total to full Stern coverage**: ~12–14 months solo.

Recommendation: push hard on the demo cut as the real "v1 ships" — Phase 5 is breadth expansion, not new architecture, and is a candidate for parallelization (multiple physicians authoring templates) or deprioritization based on tester feedback.

### 13. Open Questions Before Scaffolding

Status legend: ✅ resolved · 🟢 defaulted (research-demo posture) — user can override · 🟡 still needs concrete user input.

#### Resolved by user (2026-04-29)

| # | Topic | Resolution |
|---|---|---|
| 1 | Naming | ✅ "Tongue Doctor" is the working codename; package `tongue_doctor`. User-facing service name TBD before frontend ships. |
| 2 | Licensing posture | ✅ Retrieve all data, save locally, cite. Individual subscriptions for premium sources. ToS risk accepted for private demo. |
| 4 | Legal review | ✅ Not engaging counsel for the demo. Posture revisited before any access widening. |
| 6 | Vertex region | ✅ Cross-region calls acceptable. `me-central1` primary, `europe-west4` fallback. |
| 9 | Stern's book | ✅ User to provide own copy. |
| 11 | Eval-case sourcing | ✅ Synthesize from scratch + use available sources with citation; provenance recorded per case. |

#### Defaulted (research-demo posture; flag if you want to override)

| # | Topic | Default |
|---|---|---|
| 3 | Cost ceiling | 🟢 Cheapest tier where ToS permits; individual subs (~$2–10K/yr) + GCP compute (~$1–3K/mo at low load). Hard-cap alerts at $5K/mo. |
| 5 | Physician reviewers | 🟢 Proceed without formal sign-off. Templates marked `reviewed_by: pending`. **Outputs must explicitly state "research demonstration, not clinically validated."** Add reviewer when one becomes available. |
| 7 | Tester language | 🟢 English first. Arabic added if testers require. |
| 8 | Tester onboarding | 🟢 Small group (≤ 10), mixed profile. Disclaimer drafted assuming non-clinician readability. |
| 10 | Real ECG data | 🟢 PhysioNet PTB-XL (open) + hand-authored cases + tester-uploaded once live. |
| 12 | Frontend stack | 🟢 Next.js — streaming + IAP + attachment upload work cleanly. |
| 13 | Cloud Run vs. GKE | 🟢 Cloud Run. Demo concurrency low. |
| 14 | HIPAA-eligibility | 🟢 Use HIPAA-eligible services where free (Firestore, GCS, Cloud Run) — no PHI by policy, but no extra cost to be eligible. |
| 15 | Repo host | 🟢 GitHub. |
| 16 | CI | 🟢 GitHub Actions for code; Cloud Build for container deploy. |
| 17 | Data residency | 🟢 No hard constraint. `me-central1` primary for proximity. |
| 18 | Demo timeline | 🟢 Demo-cut at chest-pain slice green; estimated 6 months from start. |
| 19 | Scope sharpening on "non-acute" | 🟢 Refuse all acute-onset (< 24h, severe, rapidly progressing) and route to ED. Soft cases flagged to user with escalation. |
| 20 | Research Prescriber visibility | 🟢 Hard-isolated from all user-facing output, including for physician testers. Separate auth path can be added post-demo if physicians want prescribing feedback. |

#### Still needs concrete input before Phase 0 starts

| # | Topic | What I need |
|---|---|---|
| 21 | **GCP project** | Existing project ID, or create new? Billing account?  |
| 22 | **Premium subscriptions in hand** | Confirm which of UpToDate / Lexicomp / BMJ / DynaMed / VisualDx / DrugBank / MKSAP you already subscribe to. Drives Phase 0 ingestion order. |
| 23 | **Stern + textbook copies** | Confirm digital access to Stern, Robbins, Harrison's, Goodman & Gilman, Wagner, Felson, Fitzpatrick. If not, identify which to procure first. |
| 24 | **First testers** | Identify ~3–5 testers willing to use the chest-pain slice when ready. Affects feedback loop timing. |
| 25 | **Physician (when available)** | Even informal — anyone who can review the chest-pain template before testers see it? Reduces blast radius even without formal sign-off. |

---

## Next Steps

1. User answers §13 items 21–25 (the only items still blocking Phase 0 scaffolding).
2. Iterate this document.
3. On approval, scaffold Phase 0 in a follow-up session.
