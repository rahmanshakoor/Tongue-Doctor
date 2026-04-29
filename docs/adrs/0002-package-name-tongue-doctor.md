# ADR 0002 — Package name `tongue_doctor`

- Status: accepted
- Date: 2026-04-29
- Deciders: Rahman Shakoor
- Source decision: `KICKOFF_PLAN.md` Decisions Log row C.

## Context

The working directory is `Tongue-Doctor`, but the project's actual scope is broad adult internal medicine — not anything tongue-specific. "Tongue Doctor" is a working codename, not the eventual user-facing name.

We had to decide whether to: (a) keep the codename throughout the scaffold, (b) pick a more architectural name now (`doctor_agent`), or (c) pick a final user-facing name and lock it in.

## Decision

Use `tongue_doctor` (snake_case for the Python package; PyPI-style hyphenated `tongue-doctor` for the project name) consistently across:

- `pyproject.toml` `name = "tongue-doctor"`
- `src/tongue_doctor/` package
- Working directory `Tongue-Doctor/`
- Internal documentation references

The user-facing service name is **TBD** and will be decided before the frontend ships in Phase 4. At that point, the public-facing strings (page titles, OpenAPI title, IAP-protected URL prefix) get the user-facing name; the Python package keeps `tongue_doctor` as a stable internal identifier.

## Consequences

- All imports look like `from tongue_doctor.X import Y` from Day 1 and don't move when the user-facing name lands.
- The repo's GitHub URL will likely match the user-facing name (a future rename), but the package stays.
- One global rename of `tongue_doctor` → `<final_name>` is possible later if desired; it would touch every file but is a mechanical change.

## Alternatives considered

- **`doctor_agent`** — more accurate to architectural scope, but introduces a name divergence between working dir (`Tongue-Doctor`) and package (`doctor_agent`) on day one. Mild cognitive overhead with no offsetting benefit before the frontend ships.
- **Pick the user-facing name now.** Rejected: requires a marketing-style decision the project isn't ready to make. Codenames decouple the engineering surface from the brand.
