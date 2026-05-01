# Stern Reasoning Backbone

> **Source:** Stern, Cifu & Altkorn — *Symptoms to Diagnosis: An Evidence-Based Guide to Clinical Decision Making* (4th ed., 2020). User-provided personal copy at `knowledge/_local/stern/raw/`. License posture per ADR 0003 (research-demo, IAP-gated, never shipped verbatim).
>
> **Status:** Phase 0 backbone work — text corpus ingested (33 chapters / 1,837 chunks); Reasoner system prompt extracted; Stern-faithful template schema landed; per-chapter templates extracted by `scripts/extract_stern_to_templates.py` (vision-augmented, runs on-demand).
>
> **Audience:** anyone touching the agents, prompts, schemas, or eval harness.

---

## 1. Why Stern is the backbone

The kickoff plan and `docs/ARCHITECTURE.md` both name Stern as the cognitive backbone. Of every textbook on the build list (Robbins, Harrison's, Goodman & Gilman, Wagner, Felson, Fitzpatrick), Stern is the one that **teaches a procedure** rather than a body of facts. Other texts answer "what disease is this?"; Stern answers "*how do I work out* what disease this is, while staying honest about uncertainty." That procedural content is exactly what an agent needs in order to produce a reasoning trace that downstream agents (Devil's Advocate, Must-Not-Miss Sweeper, Safety Reviewer) can audit structurally.

Concretely, Stern gives us four reusable artefacts:

1. **A 9-step diagnostic procedure** (Ch. 1) → Reasoner system prompt.
2. **A 4-bucket differential taxonomy** (Ch. 1) → `HypothesisRole` enum on every diagnosis.
3. **A Bayesian threshold model** with explicit LR+ / LR- arithmetic (Ch. 1) → `TestCharacteristic` schema; reasoner reasons with numbers, not vibes.
4. **A consistent per-complaint chapter shape** (Ch. 3 onward, ×31 chapters) → one `Template` YAML per chief complaint, all using the same fields.

Decision E (research-demo posture) means we extract Stern's structure into our own schema, mark every template `reviewed_by: pending`, attach the research-demo disclaimer to every output that consumes a template, and never ship Stern's text verbatim in API responses. That posture must be revisited before any access widening.

---

## 2. Stern's 9-step diagnostic procedure (Ch. 1)

These are Stern's named steps, in order. Page citations are PDF pages of the user's 4th-edition copy.

| # | Stern's name | What the agent does |
|---|---|---|
| 1 | **Identify the Problem** (p. 14–15) | Build the complete problem list: chief complaint, other acute symptoms, exam abnormalities, lab abnormalities, chronic active problems, important past problems. Group items likely related (e.g., dyspnea + chest pain together). |
| 2 | **Frame the Differential Diagnosis** (p. 15) | Apply a structuring framework — anatomic / physiologic / categorical — appropriate to the chief complaint. The chosen framework comes from the loaded template's `framework_type`. |
| 3 | **Organize the Differential Diagnosis** (p. 15) | Enumerate plausible diagnoses against the framework's categories. Inclusivity now prevents premature closure later. |
| 4 | **Limit the Differential Diagnosis** (p. 15) | Extract pivotal points — pairs of opposing descriptors (e.g., "old vs. new headache," "exertional vs. pleuritic chest pain"). Use them to narrow to a focused candidate set. |
| 5 | **Explore Possible Diagnoses Using H&P Findings** (p. 15–16) | For each retained candidate, identify supporting and refuting features. Flag fingerprint findings — very specific findings that strongly suggest one diagnosis (Stern: "rarely seen in patients without the disease, just as fingerprints point to a specific person"). |
| 6 | **Rank the Differential Diagnosis** (p. 16) | Assign every candidate to exactly one bucket: Leading Hypothesis, Active Alternative — Most Common, Active Alternative — Must Not Miss, Other Hypotheses, Excluded Hypotheses. |
| 7 | **Test Your Hypotheses** (p. 17–21) | Apply the threshold model + likelihood ratios. Choose tests whose result will move pretest probability across either the test threshold (rule out) or the treatment threshold (commit to treatment). |
| 8 | **Re-rank the Differential Based on New Data** (p. 16) | Apply test results / new history / new exam findings; update bucket assignments and make the changes explicit. |
| 9 | **Test the New Hypotheses** (p. 16) | If new candidates emerge, repeat step 7. Loop until commit or escalate. |

These map 1:1 onto the section headers the Reasoner is required to emit (`# Step 1 — Problem List` … `# Step 9 — New Hypotheses`). The Synthesizer reads those sections by name; the Devil's Advocate audits Step 6 specifically; the Must-Not-Miss Sweeper audits the Active Alternative — Must Not Miss bucket.

---

## 3. The differential taxonomy

Stern (Table 1-2, p. 16) defines five buckets. We model four (the fifth — *Excluded Hypotheses* — is recorded inline in the reasoner's trace, not in the template, because exclusion is patient-specific):

| Stern term | `HypothesisRole` | Stern's role criteria | Testing implication |
|---|---|---|---|
| **Leading Hypothesis** | `LEADING` | Most likely based on prevalence, demographics, risk factors, symptoms, signs. | Confirm with **high specificity / high LR+** test. LR+ > 10 strongly rules in. |
| **Active Alternative — Most Common** | `ACTIVE_MOST_COMMON` | High prevalence and reasonably likely for this patient. | Investigate alongside the leading hypothesis when workup overlaps. |
| **Active Alternative — Must Not Miss** | `ACTIVE_MUST_NOT_MISS` | Life-threatening — cannot afford to miss. | Exclude with **high sensitivity / very low LR-** test. LR- < 0.1 strongly rules out. Even low pretest probability earns testing if consequence of missing is catastrophic. |
| **Other Hypotheses** | `OTHER` | Not excluded, not serious or likely enough to test for initially. | Defer testing. |
| Excluded Hypotheses | (in trace only) | Disproved by demographics, risk factors, symptoms, signs, or prior tests. | List with reason so a reviewer can audit. |

Every `DiagnosisHypothesis` in a `Template.differential` carries one role. The computed `Template.must_not_miss` projection filters by `role == ACTIVE_MUST_NOT_MISS`, preserving the Phase 0 caller surface while letting the underlying data be richer.

---

## 4. The Bayesian framework

Stern teaches Bayesian reasoning explicitly (p. 17–21):

- **Pretest probability** — probability of disease before further testing (estimated from prevalence, demographics, history, exam, prior tests).
- **Posttest probability** — probability after the test is done.
- **Likelihood ratio** — `LR+ = sens / (1 - spec)`, `LR- = (1 - sens) / spec`.
  - `posttest odds = pretest odds × LR`.
  - LR+ > 10 → strong rule-in. LR- < 0.1 → strong rule-out. LR ≈ 1 → uninformative.
- **Treatment threshold** — pretest probability above which you would treat without further testing.
- **Test threshold** — pretest probability below which you would exclude without testing.
- **The order test only when between thresholds** rule — use tests whose result will move you across one of the thresholds. Sensitivity and specificity alone don't tell you whether you'll cross one; that depends on the interaction with pretest probability.

We surface this through `TestCharacteristic`:

```python
class TestCharacteristic(BaseModel):
    test_name: str
    sensitivity: float | None    # 0.0-1.0
    specificity: float | None
    lr_positive: float | None
    lr_negative: float | None
    note: str = ""
    citation: str                # "Stern p.171"
```

The Reasoner is **required** to cite which LR it applied and which diagnosis it shifted, in Step 7. Eval will score this in the citation and differential dimensions.

---

## 5. Pivotal points & fingerprint findings

Stern's **pivotal point** (p. 15) is "one of a pair of opposing descriptors that compare and contrast clinical characteristics." Examples Stern gives: "old versus new headache, unilateral versus bilateral edema, and right lower quadrant pain versus epigastric pain." Pivotal points are the workhorse of Step 4 — they are how the agent narrows from a complete differential to a *patient-specific* one.

Stern's **fingerprint findings** (p. 16) are "very specific findings [that] strongly suggest a specific diagnosis because they are rarely seen in patients without the disease, just as fingerprints point to a specific person." Stern marks these with **FP** in the chapter prose; the extractor copies them into `DiagnosisHypothesis.fingerprint_findings` so the Reasoner surfaces them in Step 5 with full visibility.

These two constructs are what make Stern's reasoning *teachable*: a clinician (or an agent) walks the same procedure on every case, anchored by the same vocabulary.

---

## 6. Cognitive biases → agent duties

Stern Table 1-1 (p. 15) lists the cognitive biases that produce diagnostic error. Each is mapped to a structural safeguard in our agent system, so the bias has somewhere to fail loudly rather than silently.

| Bias | Stern's gloss | Owning agent / mechanism |
|---|---|---|
| **Premature closure** | "Stopping the diagnostic process too soon ... one of the most common diagnostic errors" (p. 16) | **Devil's Advocate** runs at every commit, asks "what would have to be true for the leading hypothesis to be wrong?" **Must-Not-Miss Sweeper** forces enumeration of `ACTIVE_MUST_NOT_MISS` even when the leading hypothesis feels secure. |
| **Anchoring** | Over-weighting the initial impression and not updating with new data. | Reasoner is required to recompute role assignments in Step 8 explicitly. Eval scorer checks for bucket changes when new evidence is supplied. |
| **Confirmation bias** | "Seeking data to confirm, rather than refute the initial hypothesis" (p. 15). | Reasoner Step 5 must list refuting findings per candidate; Devil's Advocate is structurally adversarial in a different model family (Decision I). |
| **Availability bias** | Over-weighting recent / memorable diagnoses. | Templates carry prevalence figures for the chief complaint; the prompt instructs the reasoner to anchor on those, not gestalt. |
| **Base-rate neglect** | Ignoring how common a disease is in this demographic. | Same — pretest probability comes from the template's prevalence table, not the model's instinct. |

---

## 7. Per-chapter implementation map

Stern has 33 numbered chapters: Ch. 1 (Diagnostic Process), Ch. 2 (Screening and Health Maintenance), Ch. 3–33 (chief complaints). Ch. 1 became the Reasoner system prompt; Ch. 2 is meta and is **not** templated. Chapters 3–33 each produce one `Template` YAML at `src/tongue_doctor/templates/data/<complaint>.yaml`.

Slug rule: lowercase the Stern title, replace non-alphanumerics with `_`, collapse repeats, strip leading/trailing `_`. Examples: "Chest Pain" → `chest_pain`; "Kidney Injury, Acute" → `kidney_injury_acute`; "AIDS/HIV Infection" → `aids_hiv_infection`.

| Ch. | Stern title | Slug | Pages |
|---|---|---|---|
| 3 | Abdominal Pain | `abdominal_pain` | 40–67 |
| 4 | Acid-Base Abnormalities | `acid_base_abnormalities` | 68–85 |
| 5 | AIDS/HIV Infection | `aids_hiv_infection` | 86–117 |
| 6 | Anemia | `anemia` | 118–133 |
| 7 | Back Pain | `back_pain` | 134–151 |
| 8 | Bleeding Disorders | `bleeding_disorders` | 152–163 |
| 9 | **Chest Pain** *(flagship)* | `chest_pain` | 164–185 |
| 10 | Cough, Fever, and Respiratory Infections | `cough_fever_and_respiratory_infections` | 186–213 |
| 11 | Delirium and Dementia | `delirium_and_dementia` | 214–227 |
| 12 | Diabetes | `diabetes` | 228–245 |
| 13 | Diarrhea, Acute | `diarrhea_acute` | 246–259 |
| 14 | Dizziness | `dizziness` | 260–285 |
| 15 | Dyspnea | `dyspnea` | 286–311 |
| 16 | Dysuria | `dysuria` | 312–321 |
| 17 | Edema | `edema` | 322–341 |
| 18 | Fatigue | `fatigue` | 342–351 |
| 19 | GI Bleeding | `gi_bleeding` | 352–363 |
| 20 | Headache | `headache` | 364–383 |
| 21 | Hematuria | `hematuria` | 384–393 |
| 22 | Hypercalcemia | `hypercalcemia` | 394–403 |
| 23 | Hypertension | `hypertension` | 404–417 |
| 24 | Hyponatremia and Hypernatremia | `hyponatremia_and_hypernatremia` | 418–441 |
| 25 | Hypotension | `hypotension` | 442–455 |
| 26 | Jaundice and Abnormal Liver Enzymes | `jaundice_and_abnormal_liver_enzymes` | 456–475 |
| 27 | Joint Pain | `joint_pain` | 476–497 |
| 28 | Kidney Injury, Acute | `kidney_injury_acute` | 498–513 |
| 29 | Rash | `rash` | 514–533 |
| 30 | Sore Throat | `sore_throat` | 534–543 |
| 31 | Syncope | `syncope` | 544–573 |
| 32 | Unintentional Weight Loss | `unintentional_weight_loss` | 574–599 |
| 33 | Wheezing and Stridor | `wheezing_and_stridor` | 600–617 |

The extractor populates each YAML with `framework_type`, `framework_categories`, `pivotal_points`, `decision_rules` (HEART, POUNDing, Wells, Centor, etc., where present), the role-tagged `differential[]`, and the diagram-derived `algorithm[]`. Until the extractor runs (pending API key), the slugs are reserved and the `data/` directory is empty.

---

## 8. How Stern's flowcharts shape the algorithms

Per project direction, **diagrams are not persisted as runtime data** — they inform extraction. Each chapter has 1–3 diagnostic-algorithm flowcharts (Figure N-1, N-2, often labeled "Diagnostic approach to chronic [complaint]" / "Diagnostic approach to acute [complaint]") plus 1–4 evidence-based tables (test characteristics, prevalence, exposure history). The flowcharts are the densest distillation of clinical decision logic in the book; pure pymupdf text extraction gets jumbled cell text and no edge structure.

The extractor solves this in two passes:

1. **Detection pass (text-only).** Walk the chapter chunks, regex-match `^Figure (\d+-\d+)\.\s*` and `^Table (\d+-\d+)\.\s*` lines, record `(kind, id, caption, page)` for each. The page comes from the chunk's `source_location = "p.<n>"`.

2. **Extraction pass (multimodal).** For each detected page, render at 2× scale via `page.get_pixmap(matrix=fitz.Matrix(2, 2))` and send the PNG bytes alongside the chapter text in a single Claude request. The model is force-tool-called with the `Template` JSON Schema as the input schema, so it must produce one structured object that passes Pydantic validation.

The model is instructed to:

- Read the flowchart as the source of truth for the procedural shape.
- Reconcile against the chapter prose; when prose and flowchart disagree, prefer prose and note the discrepancy.
- Emit `algorithm[]` as a flat ordered list of `AlgorithmStep` entries, with `derived_from_figure: "Stern Fig N-N"` provenance.

The PNG is **not** kept by default. With `--save-debug-images`, we drop the rendered pages under `knowledge/_local/stern/_debug/ch<N>/` (gitignored under the existing `knowledge/_local/` rule) so the user can spot-check what the model saw. Templates carry only the figure ID as a string — no pointers, no paths, no runtime decoding.

This keeps the runtime simple: the Reasoner sees an `algorithm[]` of plain decision steps with branches, walks them as a checklist, cites which step fired, and reports. There is no `open_image()` in the inference path.

---

## 9. Mapping Stern → our agents

| Stern step | Owning agent | Prompt | Notes |
|---|---|---|---|
| 1 — Identify the Problem | Reasoner (with Router triage) | `prompts/reasoner/system_v1.j2` (Step 1 section) | Router classifies chief complaint and selects the template. |
| 2 — Frame the Differential | Reasoner | same | Framework type comes from `Template.framework_type`. |
| 3 — Organize the Differential | Reasoner | same | Initial enumeration. |
| 4 — Limit the Differential | Reasoner | same | Pivotal points from `Template.pivotal_points`. |
| 5 — Explore via H&P | Reasoner + Retrieval | same | Retrieval grounds claims with citations. |
| 6 — Rank the Differential | Reasoner | same | Role assignments per `HypothesisRole`. |
| 6 — Audit the ranking | **Devil's Advocate** | `prompts/devils_advocate/critique_v1.j2` (Phase 1) | Different model family (Decision I). Asks: what would the leading hypothesis being wrong require? |
| 6 — Audit must-not-miss coverage | **Must-Not-Miss Sweeper** | `prompts/must_not_miss_sweeper/sweep_v1.j2` (Phase 1) | Iterates `Template.must_not_miss`; demands a test rationale per item. |
| 7 — Test Your Hypotheses | Reasoner + Retrieval | same | Uses `TestCharacteristic` LR values + threshold model. |
| 8 — Re-rank | Reasoner | same | Bucket changes are explicit. |
| 9 — Test New Hypotheses | Reasoner | same | Loop until commit / escalate. |
| Bias audit (cross-cutting) | Reasoner self-audit + Safety Reviewer | `prompts/safety_reviewer/audit_response_v1.j2` (Phase 1) | Reasoner self-reports; Safety Reviewer signs off (or blocks) on commitment. |
| User-facing format | **Synthesizer** | `prompts/synthesizer/final_response_v1.j2` (Phase 1) | Reads the Reasoner trace by section header; drops bucket vocabulary in user-facing copy unless explicitly requested. |
| Educational treatment classes | Synthesizer | same | Emits class names only ("antiplatelet", "statin"); never specific drugs/doses. Prescription-leak detector enforces this as a CI gate (`tests/unit/test_prescription_leak_detector.py`). |

---

## 10. Mapping Stern → our schemas

| Stern construct | Schema field | File |
|---|---|---|
| Chief complaint | `Template.complaint` (slug), `Template.chapter_title` | `templates/schema.py` |
| Framework type | `Template.framework_type` | same |
| Framework categories | `Template.framework_categories` | same |
| Pivotal points | `Template.pivotal_points` | same |
| Decision rules (HEART, etc.) | `Template.decision_rules: list[DecisionRule]` | same |
| Differential bucketing | `Template.differential: list[DiagnosisHypothesis]`, `DiagnosisHypothesis.role: HypothesisRole` | same |
| Per-diagnosis test characteristics | `DiagnosisHypothesis.evidence_based_diagnosis: list[TestCharacteristic]` | same |
| Disease highlights (lettered A–Z) | `DiagnosisHypothesis.disease_highlights: list[str]` | same |
| Fingerprint (FP) findings | `DiagnosisHypothesis.fingerprint_findings: list[str]` | same |
| Educational treatment classes | `DiagnosisHypothesis.treatment_classes: list[str]` (computed view: `Template.educational_treatment_classes`) | same |
| Diagnostic-algorithm flowchart (procedure) | `Template.algorithm: list[AlgorithmStep]` | same |
| Branch action / target | `AlgorithmBranch.action: AlgorithmAction`, `target_step`, `target_diagnosis`, `test_to_order`, `escalation_reason` | same |
| Figure provenance | `AlgorithmStep.derived_from_figure: str \| None` (e.g., `"Stern Fig 9-2"`) | same |
| Source pages | `Template.source_pages: tuple[int, int]` | same |
| Review status | `Template.reviewed_by`, `Template.reviewed_at` | same |
| Per-chunk page citation | `Chunk.source_location = "p.<n>"` | `knowledge/schema.py` |
| Per-chapter citation | `Chunk.citation = "Stern, Cifu, Altkorn ... pp. X-Y."` | same (set by ingester) |

---

## 11. Divergences from the kickoff plan

The kickoff plan (`docs/KICKOFF_PLAN.md` §3, §11) sketched a thinner Template than what landed:

| Kickoff sketch | Now | Why |
|---|---|---|
| `must_not_miss: list[str]` (top-level) | computed projection from `differential[]` | Single source of truth; can't drift from the role-tagged differential. |
| `red_flags: list[RedFlagPattern]` (top-level) | retained for back-compat; primary signal lives in `ACTIVE_MUST_NOT_MISS` differential entries | Stern expresses red flags inline as must-not-miss diagnoses; a separate list double-counts. |
| `pivotal_features: list[str]` | renamed to `pivotal_points` | Matches Stern's vocabulary exactly (Ch. 1 p. 15). |
| `default_workup: list[str]` | replaced by per-diagnosis `evidence_based_diagnosis` + `algorithm[]` | A flat list can't express "test A only if step 2 yields no STEMI." Stern's flowcharts encode order. |
| `educational_treatment_classes: list[str]` | computed projection, deduplicated, from `differential[*].treatment_classes` | Same single-source-of-truth principle as `must_not_miss`. |
| (no algorithm field) | `algorithm: list[AlgorithmStep]` with `derived_from_figure` provenance | Per user direction — diagrams shape the algorithm content; figures themselves are not persisted. |
| Anthropic Direct = Phase 1 stub | implemented now (vision + structured outputs) | Extraction needs it. The Phase 1 agent loop will reuse the same client. |

These are net additions, not breaking changes — `must_not_miss` and `educational_treatment_classes` keep their string-list shape via `@computed_field`. The `Template` `extra="forbid"` config keeps the schema strict, so extractor outputs that emit unknown keys fail loudly rather than silently.

---

## 12. Recommended kickoff revisions

Worth folding into `docs/KICKOFF_PLAN.md` in a follow-up edit:

- **§5 (Prompt Management).** Add: every extraction-time prompt gets snapshot tests too, not just runtime prompts.
- **§8 (Retrieval Architecture).** Add a short "Algorithm-as-context" subsection: when the Router selects a chapter, the Reasoner gets the full `Template` (including `algorithm[]`) injected before the first retrieval call. Retrieval supplements; the algorithm orients.
- **§11 (Eval Harness).** Add a citation rule: Reasoner traces must cite both Stern page (template's `source_pages`) *and* the algorithm step number that fired. The `CitationScorer` should accept `{Template path, source_pages range, algorithm step_num}` as a triple.
- **§11 (Eval).** Add a `differential_role_match` sub-scorer: did the agent assign the gold-standard diagnosis to the same role bucket as the eval case expects? This catches drift even when the diagnosis name matches.
- **§9 (Resource Acquisition).** Mark Stern as ingested; flag the diagram-extraction posture (vision-LLM informs, does not persist).
- **§13 (Open Questions).** Item 23 (textbook copies) is partially resolved — Stern's in. Robbins / Harrison's / Goodman & Gilman / Wagner / Felson / Fitzpatrick still pending.

---

## 13. Open risks

- **Vision-LLM hallucination on flowchart node labels.** Mitigation: extractor prompt instructs the model to reconcile flowchart against prose and prefer prose on conflict. User spot-checks the chest_pain template before broad extraction. Re-extraction per chapter is cheap (~$3–4 with Opus, ~$0.50 with Sonnet) so a bad extraction is reversible.
- **Schema strictness vs. extractor output.** `Template` has `extra="forbid"` and `algorithm[].target_step` is validated. If the model emits something off-schema, extraction fails loudly and the user sees the validation error in the CLI output. Acceptable failure mode.
- **Copyright posture (ADR 0003).** Stern templates are internal artefacts, never shipped verbatim, watermarked with `reviewed_by: pending` to force the research-demo disclaimer. Posture must be revisited before any access widening.
- **No physician sign-off.** Decision E. Templates are an intermediate authority — better than nothing, worse than reviewed. Eval cases must be authored knowing this; the Safety Reviewer treats `reviewed_by == "pending"` as an explicit lower-confidence signal.
- **Stern is opinionated.** Where Stern disagrees with NICE / USPSTF / specialty-society guidelines, the template will reflect Stern. Phase 1 retrieval mediates this — when guideline retrieval lands (tier 1) and conflicts with the template (tier 3), the Reasoner is required to acknowledge the tier and prefer guideline. Without that retrieval pass, templates carry the full weight.
- **Page numbering fidelity.** PDF rendered page numbers ≠ printed Stern page numbers. We use rendered numbers consistently; the extractor cites them; eval expectations should also use rendered numbers.

---

## 14. What's next

Immediate (gated only on the API key):
1. Run `scripts/extract_stern_to_templates.py --chapter 9 --save-debug-images` for the chest-pain smoke run.
2. User reviews `chest_pain.yaml` — focus on `differential` role assignments, `algorithm` step structure, `evidence_based_diagnosis` LR values.
3. Run `--all` for the remaining 30 chapters. ~30–60 minutes runtime, ~$80–120 spend at Opus.
4. Final lint / type / test green.

Phase 0b (next session):
5. BM25 + dense indexing of the Stern corpus (1,837 chunks → searchable).
6. First eval cases authored against the chest-pain template; eval harness wires up `Template` loading.

Phase 1:
7. Implement Router (chief-complaint classifier + scope refusal), Reasoner (system prompt v1 already written), Devil's Advocate, Must-Not-Miss Sweeper, Safety Reviewer, Synthesizer.
8. Eval the chest-pain slice end-to-end. Demo cut after Phase 4 per kickoff §12.
