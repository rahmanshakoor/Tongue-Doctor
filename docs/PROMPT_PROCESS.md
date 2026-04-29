# Prompt management

Prompts are versioned artifacts, edited like code, tested by snapshot, and tied to eval regression. See [`KICKOFF_PLAN.md` §5](KICKOFF_PLAN.md#5-prompt-management) for the spec.

## Layout

```
prompts/
├── reasoner/
│   └── system_v1.j2
├── router/
│   └── classify_v1.j2
├── devils_advocate/
├── safety_reviewer/
├── synthesizer/
├── must_not_miss_sweeper/
├── research_prescriber/
└── multimodal/
    └── ecg_interpret_v1.j2
```

One file per `(agent, purpose, version)`. Filename pattern: `<purpose>_v<N>.j2`. **Old versions are kept** — agent config (in `config/models.yaml` and `config/default.yaml`) pins the active version.

## Front matter

Every prompt starts with a Jinja comment containing YAML metadata:

```jinja2
{# ---
name: reasoner_system
version: 1
created: 2026-04-29
author: Rahman Shakoor
notes: "Stern ch.1 diagnostic procedure, paraphrased. Cross-validated against Harrison's ch.1."
inputs: [loaded_templates, case_state]
--- #}

You are a clinical reasoning agent operating in a research demonstration...
```

The loader (`src/tongue_doctor/prompts/loader.py`) parses the front matter into a `PromptMetadata` model and renders the body with the supplied context.

## Versioning rule

Bump filename version (`system_v1.j2` → `system_v2.j2`) on any **substantive** change — wording that changes behavior, instructions, output shape, or examples. Whitespace fixes and typo corrections do **not** require a version bump but **do** require a snapshot test update.

## Tests

Every prompt has at least one snapshot test in `tests/unit/prompts/test_<agent>.py`:

```python
def test_reasoner_system_renders_stable():
    rendered, meta = load_prompt("reasoner/system", version=1, **fixture_context)
    assert meta.name == "reasoner_system"
    assert "Stern" in rendered  # canary substring
    snapshot.assert_match(rendered, "reasoner_system_v1.txt")
```

Catches accidental whitespace, indent, or template-variable changes during refactors.

## Eval coupling

A prompt change triggers a regression run on the relevant eval slice before merge. CI gates the merge on no-regression (or an explicit waiver with a note recorded in the PR body). See [`EVAL_PROCESS.md`](EVAL_PROCESS.md#regression-detection).

## No prompt content in code

Code references prompts by `(agent_dir, name, version)` and renders via the prompt loader. There are **no string literals containing prompt text in `src/tongue_doctor/`** outside the loader — agents request the active version from config and call `load_prompt(...)`. This keeps prompt diffs reviewable independently and lets non-engineers iterate prompts without touching Python.

## The two `prompts/` directories

There are intentionally two:

- `prompts/` at repo root — Jinja files (the artifacts).
- `src/tongue_doctor/prompts/` — the loader subpackage (Python code).

The loader resolves the artifact directory from `Settings.prompts_dir` (default: repo-root `prompts/`). This split is recorded in [`adrs/0001-record-architecture-decisions.md`](adrs/0001-record-architecture-decisions.md).

## Phase 0 status

The scaffold ships **no production prompts** — only `prompts/_fixtures/echo_v1.j2` for the loader unit test. Concrete prompts land alongside their agents in Phase 1.
