# ADR 0005 — No third-party orchestration framework

- Status: accepted
- Date: 2026-04-29
- Deciders: Rahman Shakoor
- Source: `KICKOFF_PLAN.md` §2 "Deliberately NOT including".

## Context

Several frameworks aim at the multi-agent orchestration problem this project has: LangChain / LangGraph, CrewAI, llama-index agent abstractions, AutoGen. They offer pre-built abstractions for tools, message routing, retries, and streaming.

The problem domain here has properties that make those abstractions cost more than they save:

- **The agent set is small, fixed, and opinionated.** Six concrete agents in Phase 1; no plans to dynamically spawn more. The kickoff plan §1 pins each one's responsibility.
- **The loop logic is the product.** Gather → hypothesize → retrieve → critique → must-not-miss audit → safety review → commit-or-iterate is the system. It must be debuggable line-by-line, not hidden inside a framework's loop.
- **Hard invariants live at orchestration level.** I-3 (prescriber isolation), I-5 (must-not-miss audit), I-2 (scope refusal). Frameworks that abstract orchestration tend to make these guards either non-trivial to insert or invisible to readers.
- **Custom failure modes need custom telemetry.** Iteration-count pathologies, cross-family verifier mismatches, prompt-vs-output drift — diagnosing these requires a trace shape we control.

The cost of a bespoke orchestrator is roughly 200 lines of Python. The cost of fighting an opinionated framework when an invariant changes is open-ended.

## Decision

Build the orchestrator in-tree, in `src/tongue_doctor/orchestrator/`. No LangChain, LangGraph, CrewAI, or llama-index agent abstractions.

Specifically:

- The `Agent` protocol (`agents/base.py`) is ours: `name`, `model_assignment_key`, `prompt_name`, `async run(case_state, **kwargs) -> AgentResult`.
- The `LLMClient` protocol (`models/base.py`) is ours: a thin `async generate(messages, *, system, tools, response_schema, thinking) -> LLMResponse`.
- Retry, backoff, circuit-breaking handled with `tenacity` directly, not framework wrappers.
- Streaming, when needed for the frontend, comes from FastAPI + SSE / async iterators, not a framework.

Where a third-party SDK is the right answer (Vertex AI SDK, Anthropic SDK, Cohere SDK), we use it directly.

## Consequences

- Orchestrator code is short, readable, and ours to refactor without coordinating with a framework's API surface.
- Guards (I-3 leak detector, I-5 must-not-miss audit) sit visibly in the loop body, not buried in callbacks or middleware.
- We don't get framework-provided patterns "for free" — retry policies, prompt templating, tool routing are written once in our shape.
- New contributors must read our orchestrator; no transferable framework knowledge applies. For a solo / small-team research demo, that is a feature, not a bug.

## Alternatives considered

- **LangGraph for the diagnostic loop**. Strong DAG model, but the loop's structure is essentially linear with conditional iteration; LangGraph's node-and-edge formalism would force re-expressing it without adding leverage.
- **CrewAI for agent collaboration**. Forces a "crew + role" abstraction that doesn't match Tier 1/2/3 functional split.
- **llama-index agents**. Useful for ingestion experiments (chunkers, query engines), kept available there but explicitly out of the runtime path.

## Revisit triggers

- Cross-team contribution at scale (multiple full-time engineers wanting onboarding leverage from a known framework).
- Adoption of a multi-agent reasoning pattern that genuinely needs a graph/DAG model rather than a loop.
- Migration to a managed agent runtime (Vertex AI Agent Engine, Bedrock Agents, etc.) as the deployment target.
