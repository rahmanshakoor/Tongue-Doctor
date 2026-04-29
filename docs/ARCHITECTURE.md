# Architecture

One-page overview. The authoritative spec is [`KICKOFF_PLAN.md`](KICKOFF_PLAN.md). This file is for fast orientation.

## What this system does

Emulates physician diagnostic reasoning across adult internal medicine. The user describes a complaint, the system gathers structured information (history, exam findings, attachments), retrieves authoritative knowledge, generates and tests a differential, and produces a research-demonstration commitment with workup recommendations and explicit confidence framing. **No prescriptions or therapeutic advice are delivered to the user.**

## Three tiers

```
┌─────────────────────────────────────────────────────────────────────┐
│ Tier 1 — Intake                                                     │
│   Router (scope + red flags)                                        │
│   Case State Manager (Firestore — single source of truth per case)  │
│   Multimodal Processor (modality detection + per-modality handlers) │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Tier 2 — Reasoning                                                  │
│   Reasoner (Gemini 3.1 Pro)                                         │
│   Retriever (hybrid BM25 + dense + rerank, authority-aware)         │
│   Devil's Advocate (Claude Opus 4.7 — cross-family blind-spot div.) │
│   Must-Not-Miss Sweeper                                             │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Tier 3 — Output                                                     │
│   Research Prescriber  ── ISOLATED, NEVER USER-VISIBLE              │
│   Safety Reviewer (Claude Sonnet)                                   │
│   Synthesizer (Gemini Flash-Lite)                                   │
└─────────────────────────────────────────────────────────────────────┘
```

The orchestrator owns the diagnostic loop: gather → hypothesize → retrieve → critique → audit → commit-or-iterate. It depends on `agents.base.Agent` (a protocol), not on concrete agent classes. Model swaps are config changes, not code changes.

## Hard invariants

- **Research-demo disclaimer** on every user-facing output.
- **Scope refusal** for acute presentations (< 24h, severe, or rapidly progressing) — route to ED.
- **Prescriber isolation** (kickoff §J): the `research_prescription` field of `CaseState` is taint-tracked; any substring appearing in `UserFacingOutput.body` raises `PrescriptionLeakError`. CI gates on a dedicated leak eval case.
- **Multimodal disclaimer** when any extracted finding feeds the synthesizer.
- **Must-not-miss audit** before any commitment.
- **Authority-aware retrieval** — guideline > clinical reference > textbook. The Reasoner cites authority tier in its reasoning trace.

See [`SAFETY_INVARIANTS.md`](SAFETY_INVARIANTS.md) for the canonical list and how each is enforced.

## Cognitive backbone

Stern, Cifu, Altkorn — *Symptoms to Diagnosis*. Chapter 1 (the diagnostic procedure) goes into the Reasoner system prompt. Per-complaint chapters are extracted into structured templates with must-not-miss lists, red-flag patterns, pivotal features, and default workup. Templates are cross-validated against Harrison's, UpToDate, and specialty guidelines.

## Storage shape

- **Firestore** — `cases/{case_id}` plus subcollections (`turns`, `iterations`, `audit`). One `CaseState` per session, < 1 MiB per document; long agent outputs spill to subcollections.
- **GCS** — `gs://<project>-attachments/<case_id>/<attachment_id>.<ext>` for raw uploads.
- **Vertex Vector Search** — per-corpus dense indices, BM25 in-process from chunked corpora.
- **BigQuery** — eval results and audit log for analysis (post-90-day archive of Firestore cases with PII stripped — none expected, defense-in-depth).

## Region posture

`me-central1` (Doha) primary. `europe-west4` fallback for Anthropic via Model Garden / Cohere. Direct Anthropic API as the second fallback. See [`adrs/0004-region-and-fallback.md`](adrs/0004-region-and-fallback.md).

## What this scaffold ships

The current commit lands the foundation only:

- Settings, logging, tracing, FastAPI shell.
- Pydantic schemas (`CaseState`, `Attachment`, `Differential`, `RetrievalResult`, `UserFacingOutput`).
- LLM client protocol + per-provider class skeletons.
- `Agent` protocol, orchestrator skeleton (raises until Phase 1).
- Prompt loader (Jinja2 + YAML front-matter) — tested.
- Template loader.
- Safety: disclaimer registry, **prescription leak detector (tested)**, scope rule placeholder.
- Eval harness (runner, scorers) — operational shape, no cases yet.

Concrete agents, prompts, ingestion, eval cases, frontend, and Terraform follow in subsequent phases per [`KICKOFF_PLAN.md` §12](KICKOFF_PLAN.md#12-milestones-solo-developer).
