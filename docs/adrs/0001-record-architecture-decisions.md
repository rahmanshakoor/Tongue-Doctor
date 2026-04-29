# ADR 0001 — Record architecture decisions

- Status: accepted
- Date: 2026-04-29
- Deciders: Rahman Shakoor

## Context

Architectural decisions made over the lifetime of this repository need a durable, reviewable home. Conversations and chat logs decay; commit messages capture the *what* but not the *why*. Without a written record, future contributors (and future-me) re-litigate decided questions or, worse, silently reverse them in refactors.

## Decision

Record significant architectural decisions as ADRs in `docs/adrs/`. Format: a lightly-modified MADR template — title, status, date, deciders, context, decision, consequences, alternatives.

Numbering is sequential, four-digit, zero-padded (`0001`, `0002`, …). Filename slug is short and stable: `<NNNN>-<slug>.md`.

An ADR is required when a decision:
- changes a hard invariant or a guarantee given to testers / users,
- changes the model family / region / authority of a Tier 1 or Tier 2 component,
- imposes or removes a development-process requirement (testing, prompt management, eval gating),
- creates or removes a directory / module that other modules depend on by convention.

Bug fixes, refactors that preserve invariants, and prompt iterations within a single agent do **not** require ADRs.

## Consequences

- New decisions get one short ADR each. The PR introducing the decision references it.
- Reversing a decision is a new ADR that supersedes the old one (status: superseded; link both ways).
- The ADR set is the canonical answer to "why does the codebase look like this?" — `KICKOFF_PLAN.md` is the up-front design; ADRs are the trail of changes after.

## Alternatives considered

- **No ADRs, rely on PR descriptions.** Rejected: PR descriptions are tied to the merge commit and are not browsable as a corpus. Future contributors don't read PR archaeology.
- **Notion / Confluence pages.** Rejected: external systems decay and are not version-controlled with the code they describe.
- **Inline comments.** Rejected: comments rot, fragment across files, and are read only by people already inside the affected file.
