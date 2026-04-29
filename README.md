# Tongue-Doctor

> **Research demonstration. Not a clinical tool. Not validated. Outputs must not be used to make medical decisions.**

A multi-agent clinical reasoning system emulating physician diagnostic reasoning across adult internal medicine. Built as a research demonstration to evaluate whether structured multi-agent clinical reasoning is viable. Access is gated by Identity-Aware Proxy to a small group of named testers.

## Status

**Phase 0 — foundation scaffolded.** No clinical functionality yet. The repo currently contains:

- Architectural plan (`docs/KICKOFF_PLAN.md`) — authoritative spec.
- Foundation: settings, structured logging, OTel tracing, pydantic schemas, LLM-client + agent protocols, prompt loader, eval-harness skeleton, safety taint guard.
- No agent implementations, no prompts, no eval cases, no ingestion code, no GCP infra. Those land in follow-up phases as kickoff open items 21–25 resolve.

See `docs/ARCHITECTURE.md` for the system shape and `docs/KICKOFF_PLAN.md` §13 for what's still blocking Phase 0 execution.

## Disclaimer (carried in every output the system will eventually generate)

> This is a research demonstration of clinical reasoning. It is **not** a medical device, **not** clinically validated, and **not** a substitute for a qualified physician. Do not use any output to make medical decisions for yourself or others. If you are experiencing a medical emergency, contact emergency services.

## Architecture (one-liner per tier)

- **Tier 1** — Router (scope/red-flag), Case State Manager (Firestore), Multimodal Processor.
- **Tier 2** — Reasoner (Gemini), Retriever (hybrid BM25 + dense + rerank, authority-aware), Devil's Advocate (Claude Opus, cross-family for blind-spot diversity), Must-Not-Miss Sweeper.
- **Tier 3** — Research Prescriber (internal-only, hard-isolated from user output), Safety Reviewer (Claude Sonnet), Synthesizer (Gemini Flash-Lite).

Cognitive backbone: Stern, Cifu, Altkorn — *Symptoms to Diagnosis*.

## Dev quickstart

Requirements:

- macOS or Linux. Python 3.12 (auto-managed by uv).
- [uv](https://github.com/astral-sh/uv) ≥ 0.10 (`brew install uv`).
- `libmagic` for `python-magic` (`brew install libmagic` on macOS).

Setup:

```bash
uv sync                  # creates .venv, installs runtime + dev deps
uv run pre-commit install
make test                # pytest, ruff, mypy via Makefile targets
```

Useful targets:

```bash
make lint    # ruff check
make format  # ruff format
make type    # mypy on src/
make test    # pytest with coverage
make eval    # eval harness (raises until Phase 1)
```

Copy `.env.example` to `.env` and fill in values as they become available. The repo is designed so that empty values fail loudly at boot rather than silently degrading.

## Repository layout

```
tongue-doctor/
├── pyproject.toml                # uv-managed
├── Makefile                      # common tasks
├── docs/                         # plan, architecture, ADRs, processes
├── config/                       # layered YAML config + model assignments
├── prompts/                      # versioned Jinja2 prompts (loader in src/)
├── src/tongue_doctor/            # main package
├── tests/                        # unit + integration
├── eval/                         # eval harness + cases + scoring
└── scripts/                      # offline tools (extract, ingest, replay)
```

`infra/` (Terraform / Cloud Build) is intentionally absent until a GCP project is decided (kickoff open item 21).

## License + posture

This is a private research repository. Source materials (textbooks, premium clinical references) are accessed under personal-research and individual-subscription terms; AI/RAG use of premium subscriptions accepts ToS-violation risk explicitly limited to this private, IAP-gated demo. The posture must be revisited before any access widening or production deployment. See `docs/RESOURCE_ACQUISITION.md` and `docs/adrs/0003-research-demo-tos-posture.md`.
