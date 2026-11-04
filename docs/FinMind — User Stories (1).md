# FinMind — User Stories

> **Source of truth:** `FinMind_unified_fastapi_spec.md`.
> **Connected document:** [FinMind Implementation Plan](./FinMind_Implementation_Plan.md).
> **Traceability convention:** Every story references one or more `REQ-*` requirements and one or more `PLAN-*` tasks. Technical requirements without a valid actor are retained in the coverage matrix and remain in the Implementation Plan; they are not turned into invented user stories.

## 1. Project Scope Summary

These stories describe only user-facing or actor-facing behavior explicitly present in the source specification. The source does not define names or job titles for actors beyond concepts such as user/investor, authenticated user, Dashboard, Orchestration Layer, Scheduler, Monitoring administrator, and downstream services. Where a specific human actor is not explicit, the story states `NEEDS CLARIFICATION` rather than guessing.

The stories connect to the implementation plan through stable IDs. For example:

`REQ-006 → PLAN-004 → US-001`

## 2. User Stories

### US-001 — Conduct the Arabic investor interview

- **Requirement ID:** REQ-006
- **Related Implementation Plan ID(s):** PLAN-004
- **User/Actor:** Investor/user
- **Title:** Complete a guided Arabic investor interview
- **User Story:** As an investor/user, I want to answer a guided Arabic profiling interview so that the system can collect my investment profile.
- **Acceptance Criteria:**
  1. A stateful interview workflow presents the next required question.
  2. User responses are processed as structured profile information.
  3. The workflow preserves session state and can continue from a checkpoint.
  4. The agent does not calculate indicators or issue a recommendation.
- **Priority:** P0
- **Dependencies:** PLAN-001–PLAN-004; exact LLM/LangGraph deployment is **NEEDS CLARIFICATION**.
- **Planned Week:** Week 1–2
- **Assigned Team Member:** Team Member 2 (planning decision)
- **Definition of Done:** Interview path, state tests, and API contract tests pass.

### US-002 — Review and confirm an investor profile

- **Requirement ID:** REQ-007–REQ-009
- **Related Implementation Plan ID(s):** PLAN-004, PLAN-005
- **User/Actor:** Investor/user
- **Title:** Review and explicitly confirm the profile
- **User Story:** As an investor/user, I want to review and edit the extracted profile before confirmation so that only an approved profile becomes active.
- **Acceptance Criteria:**
  1. The profile includes the specified risk, horizon, goal, experience, preferences, exclusions, and constraints.
  2. Contradictory or incomplete information causes clarification rather than silent acceptance.
  3. An Arabic summary is presented for review.
  4. The profile remains inactive until explicit confirmation.
  5. Edits are validated before confirmation.
- **Priority:** P0
- **Dependencies:** US-001; profile persistence and user identity contract.
- **Planned Week:** Week 2
- **Assigned Team Member:** Team Member 2 (planning decision)
- **Definition of Done:** Confirm/edit flow persists only a valid confirmed profile and has API/integration tests.

### US-003 — Maintain profile history and preferences

- **Requirement ID:** REQ-010
- **Related Implementation Plan ID(s):** PLAN-005, PLAN-006
- **User/Actor:** Investor/user; system preference-memory component
- **Title:** Keep an auditable profile and preference history
- **User Story:** As an investor/user, I want confirmed profile changes and learned preferences to be versioned so that my profile history remains auditable.
- **Acceptance Criteria:**
  1. Confirmed changes create an audit record.
  2. Learned preferences include source, confidence, validation status, and timestamps as specified.
  3. Foundational risk values cannot be silently changed by memory extraction.
  4. Sensitive raw financial disclosures are not sent to external tracing logs.
- **Priority:** P1
- **Dependencies:** US-002; LangMem storage details are **NEEDS CLARIFICATION**.
- **Planned Week:** Week 2–3
- **Assigned Team Member:** Team Member 2 (planning decision)
- **Definition of Done:** Audit and memory repository tests pass and unconfirmed changes cannot become active.

### US-004 — View technical stock information

- **Requirement ID:** REQ-012–REQ-017
- **Related Implementation Plan ID(s):** PLAN-007, PLAN-008
- **User/Actor:** `NEEDS CLARIFICATION — actor not specified in source for direct technical snapshot access`
- **Title:** Access a reproducible technical snapshot
- **User Story:** As a `NEEDS CLARIFICATION` actor, I want to access a technical snapshot so that I can view the stored indicators, family scores, regime, risk metrics, prices, and data status.
- **Acceptance Criteria:**
  1. A snapshot is generated from the consistent OHLCV series.
  2. Data-quality failures are explicit and do not produce a valid recommendation.
  3. Indicators and family scores follow the source formulas and 0–100 bounds.
  4. The snapshot includes trading/as-of date, configuration version, and provenance.
- **Priority:** P0
- **Dependencies:** PLAN-007–PLAN-008; direct actor/API exposure is **NEEDS CLARIFICATION**.
- **Planned Week:** Week 2–3
- **Assigned Team Member:** Team Member 3 (planning decision)
- **Definition of Done:** Formula, persistence, and read API/contract tests pass.

### US-005 — Receive a rule-based recommendation

- **Requirement ID:** REQ-018–REQ-021
- **Related Implementation Plan ID(s):** PLAN-005, PLAN-008, PLAN-009
- **User/Actor:** Investor/user
- **Title:** Receive a profile-aware recommendation result
- **User Story:** As an investor/user, I want the system to evaluate a stock against my confirmed profile and technical data so that I receive the documented recommendation result and reasons.
- **Acceptance Criteria:**
  1. Only a confirmed active profile is used.
  2. Data-quality, liquidity, exclusion, profile, and technical gates are applied.
  3. Setup score is not used as the sole decision.
  4. The response includes direction, confidence, blockers/reasons, family results, user fit, and data quality.
  5. Stale/invalid data produces no recommendation and explains why.
  6. The result is logged with the required audit fields.
- **Priority:** P0
- **Dependencies:** US-002, US-004; missing-news handling and news scoring policy are **NEEDS CLARIFICATION**.
- **Planned Week:** Week 3
- **Assigned Team Member:** Team Member 3 (planning decision)
- **Definition of Done:** Recommendation contract, decision-rule tests, audit-log tests, and API tests pass.

### US-006 — Search and retrieve permitted financial news

- **Requirement ID:** REQ-022–REQ-024, REQ-026–REQ-027, REQ-042
- **Related Implementation Plan ID(s):** PLAN-010, PLAN-011, PLAN-012
- **User/Actor:** `NEEDS CLARIFICATION — actor not specified in source for direct News Agent API access`
- **Title:** Search company and market news
- **User Story:** As a `NEEDS CLARIFICATION` actor, I want to search and retrieve permitted company/disclosure news so that I can access traceable information connected to EGX tickers.
- **Acceptance Criteria:**
  1. Requests use the typed News Agent FastAPI contracts.
  2. Results preserve source IDs, URLs, publication dates, article IDs, and ticker links.
  3. Ambiguous ticker matches are marked or omitted rather than guessed.
  4. Missing, stale, partial, and unavailable statuses are distinct.
  5. News Agent remains active and is not replaced by a placeholder.
- **Priority:** P0
- **Dependencies:** Approved sources and content permissions are **NEEDS CLARIFICATION**.
- **Planned Week:** Week 2–3
- **Assigned Team Member:** Team Member 4 (planning decision)
- **Definition of Done:** At least one source works end to end with idempotent persistence, retrieval, and API tests.

### US-007 — Understand the positive or negative direction of news

- **Requirement ID:** REQ-025, REQ-028
- **Related Implementation Plan ID(s):** PLAN-011
- **User/Actor:** `NEEDS CLARIFICATION — actor not specified in source for consuming news direction`
- **Title:** Receive evidence-backed news direction
- **User Story:** As a `NEEDS CLARIFICATION` consumer, I want news direction to be positive, negative, neutral, or unknown with evidence so that downstream modules can use the news information without the News Agent making a final recommendation.
- **Acceptance Criteria:**
  1. Direction is one of `positive`, `negative`, `neutral`, or `unknown`.
  2. Each material direction has evidence and source metadata.
  3. Confidence, relevance, novelty, freshness, and source reliability remain distinguishable.
  4. No impact level/impact score is emitted.
  5. The News Agent never returns a final buy/sell decision.
- **Priority:** P0
- **Dependencies:** US-006; final taxonomy and aggregation policy are **NEEDS CLARIFICATION**.
- **Planned Week:** Week 3
- **Assigned Team Member:** Team Member 4 (planning decision)
- **Definition of Done:** Direction schema, evidence validation, downstream contract, and negative/unknown cases are tested.

### US-008 — Receive an Arabic explanation of a recommendation

- **Requirement ID:** REQ-029–REQ-030, REQ-034
- **Related Implementation Plan ID(s):** PLAN-009, PLAN-011, PLAN-013
- **User/Actor:** Investor/user
- **Title:** Understand why a recommendation was produced
- **User Story:** As an investor/user, I want an Arabic explanation of the prepared recommendation so that I can understand its factors, risks, evidence, and limitations.
- **Acceptance Criteria:**
  1. The explanation preserves the Recommendation Engine decision.
  2. Numeric and financial claims come from supplied data or authorized evidence.
  3. Sources are attributable and not invented.
  4. Uncertainty and limitations are explicit.
  5. Arabic style and the financial disclaimer are included.
  6. The explanation does not guarantee outcomes.
- **Priority:** P0
- **Dependencies:** US-005; evidence/RAG availability is **NEEDS CLARIFICATION**.
- **Planned Week:** Week 2–3
- **Assigned Team Member:** Team Member 5 (planning decision)
- **Definition of Done:** Recommendation input produces validated structured Arabic output and evidence checks pass.

### US-009 — Receive an Arabic explanation of a monitoring alert

- **Requirement ID:** REQ-029–REQ-030, REQ-034, REQ-037
- **Related Implementation Plan ID(s):** PLAN-013, PLAN-015
- **User/Actor:** Investor/user
- **Title:** Understand why an alert triggered
- **User Story:** As an investor/user, I want an Arabic explanation of a structured monitoring alert so that I can understand the triggering rule, observed values, evidence, and limitations.
- **Acceptance Criteria:**
  1. Alert input is validated before generation.
  2. Triggered rule, observed value, threshold, timestamp, and related snapshot are preserved when available.
  3. The Explanation Agent does not modify the alert or create a recommendation.
  4. Missing evidence is clearly stated.
- **Priority:** P0
- **Dependencies:** PLAN-015; actual alert-to-explanation schema must be approved.
- **Planned Week:** Week 3
- **Assigned Team Member:** Team Member 5 (planning decision)
- **Definition of Done:** Alert explanation schema and tests match the actual Monitoring Service output.

### US-010 — Ask a follow-up question

- **Requirement ID:** REQ-031, REQ-034
- **Related Implementation Plan ID(s):** PLAN-013
- **User/Actor:** Investor/user
- **Title:** Ask follow-up questions about an existing result
- **User Story:** As an investor/user, I want to ask a follow-up question about an existing recommendation or alert so that I can understand the supplied result without it being silently changed.
- **Acceptance Criteria:**
  1. The question is associated with the relevant stock, result, or alert.
  2. Existing context is reused where available.
  3. New evidence is distinguished from previously supplied evidence.
  4. The original decision remains unchanged.
  5. Arabic style and disclaimer remain present.
- **Priority:** P1
- **Dependencies:** US-008 or US-009; conversation-state implementation details are **NEEDS CLARIFICATION**.
- **Planned Week:** Week 3
- **Assigned Team Member:** Team Member 5 (planning decision)
- **Definition of Done:** Follow-up context and validation tests pass.

### US-011 — Ask a Stock Q&A question

- **Requirement ID:** REQ-031–REQ-034
- **Related Implementation Plan ID(s):** PLAN-008, PLAN-013, PLAN-014
- **User/Actor:** Investor/user
- **Title:** Ask descriptive questions about a stock
- **User Story:** As an investor/user, I want to ask a descriptive question about one or more stocks so that I can understand stored technical data without receiving an unrequested recommendation.
- **Acceptance Criteria:**
  1. The mode is selected as `stock_qa` by the orchestrator.
  2. Only the specified read-only snapshot tools are callable.
  3. The answer uses only tool output and includes `data_date`/freshness.
  4. Every numeric claim is traceable to a tool result.
  5. Missing or stale data is stated explicitly.
  6. Recommendation language is rejected, retried once, and replaced by a safe fallback if necessary.
  7. Mixed questions are split so the descriptive part uses Stock Q&A and the recommendation part uses Recommendation Engine.
- **Priority:** P0
- **Dependencies:** US-004; exact Arabic recommendation-language lexicon is **NEEDS CLARIFICATION**.
- **Planned Week:** Week 3
- **Assigned Team Member:** Team Member 5 (planning decision)
- **Definition of Done:** All five read-only tools, mode routing, grounding validation, stale-data behavior, and fallback tests pass.

### US-012 — Create and manage a monitoring rule

- **Requirement ID:** REQ-035, REQ-039
- **Related Implementation Plan ID(s):** PLAN-015, PLAN-016
- **User/Actor:** Authenticated user
- **Title:** Manage monitoring rules
- **User Story:** As an authenticated user, I want to create, view, update, activate/deactivate, and delete my monitoring rules so that the service can evaluate conditions I configure.
- **Acceptance Criteria:**
  1. Rule parameters validate against the supported discriminated rule types.
  2. A user can view only owned rules.
  3. Updates are limited to the fields specified by the source.
  4. Rules are evaluated deterministically and never through an LLM.
  5. Protected routes enforce authentication and ownership.
- **Priority:** P0
- **Dependencies:** PLAN-003, PLAN-015; exact admin role is **NEEDS CLARIFICATION**.
- **Planned Week:** Week 3
- **Assigned Team Member:** Team Member 1 (planning decision)
- **Definition of Done:** Rule API, validation, ownership, and evaluator tests pass.

### US-013 — Receive and acknowledge a monitoring alert

- **Requirement ID:** REQ-036–REQ-039
- **Related Implementation Plan ID(s):** PLAN-015, PLAN-016
- **User/Actor:** Authenticated user
- **Title:** Review and acknowledge alerts
- **User Story:** As an authenticated user, I want to view and acknowledge my alerts so that I can track the monitoring events generated for my rules.
- **Acceptance Criteria:**
  1. Only fresh market/technical data is evaluated.
  2. Stale tickers are skipped without a user alert.
  3. Alerts contain the triggering evidence and related run/rule information.
  4. Cooldown and database constraints prevent duplicate active alerts.
  5. A user can view and acknowledge only owned alerts.
- **Priority:** P0
- **Dependencies:** US-012; technical table names and columns are **NEEDS CLARIFICATION**.
- **Planned Week:** Week 3
- **Assigned Team Member:** Team Member 1 (planning decision)
- **Definition of Done:** Monitoring cycle, deduplication, alert API, ownership, and acknowledgement tests pass.

## 3. User Story Acceptance Criteria

The detailed acceptance criteria are recorded under each story. The following cross-story checks apply without creating new requirements:

| Check | Applicable stories | Pass condition |
|---|---|---|
| Source traceability | US-001–US-013 | Each story has at least one REQ and PLAN ID. |
| API validation | US-002, US-005–US-007, US-012–US-013 | Requests/responses use typed schemas and protected dependencies. |
| Data freshness | US-004, US-005, US-011, US-013 | Stale/missing data remains explicit and follows the source behavior. |
| Evidence grounding | US-006–US-011 | Evidence/source IDs are traceable and never fabricated. |
| Ownership/safety | US-002, US-005, US-012–US-013 | Users cannot access another user’s protected profile/rules/alerts. |
| Scope preservation | All stories | No story changes, merges, or removes a source requirement. |

## 4. Requirement → Plan → User Story Traceability Matrix

| Requirement ID | README Requirement | Implementation Plan ID | User Story ID | Week | Team Member |
|---|---|---|---|---|---|
| REQ-001 | FastAPI HTTP boundary | PLAN-001 | — | W1 | TM1 |
| REQ-002 | Runtime/dependency baseline | PLAN-001–002 | — | W1 | TM1 |
| REQ-003 | App factory/lifecycle/health | PLAN-001–002 | — | W1 | TM1 |
| REQ-004 | API/security rules | PLAN-003 | US-002, US-005, US-012, US-013 | W1–3 | TM5/TM3/TM1 |
| REQ-005 | Canonical storage/provenance | PLAN-002, PLAN-017 | — | W1/W3 | TM1/all |
| REQ-006 | Arabic interview | PLAN-004 | US-001 | W1–2 | TM2 |
| REQ-007 | Profile extraction | PLAN-004–005 | US-002 | W1–2 | TM2 |
| REQ-008 | Validation/contradictions | PLAN-004 | US-001, US-002 | W1–2 | TM2 |
| REQ-009 | Summary/HITL confirmation | PLAN-005 | US-002 | W2 | TM2 |
| REQ-010 | Persistence/audit/memory | PLAN-005–006 | US-003 | W2–3 | TM2 |
| REQ-011 | Investor boundary | PLAN-004–006 | US-001, US-002 | W1–3 | TM2 |
| REQ-012 | OHLCV ingestion | PLAN-007 | US-004 | W1–2 | TM3 |
| REQ-013 | Data quality | PLAN-007 | US-004, US-005 | W1–2 | TM3 |
| REQ-014 | Indicators | PLAN-008 | US-004 | W2–3 | TM3 |
| REQ-015 | Scoring | PLAN-008 | US-004 | W2–3 | TM3 |
| REQ-016 | Regime/risk | PLAN-008 | US-004 | W2–3 | TM3 |
| REQ-017 | Snapshots | PLAN-008 | US-004, US-011 | W2–3 | TM3/TM5 |
| REQ-018 | Recommendation filters | PLAN-009 | US-005 | W3 | TM3 |
| REQ-019 | Recommendation gates | PLAN-009 | US-005 | W3 | TM3 |
| REQ-020 | Recommendation payload | PLAN-009 | US-005, US-008 | W3 | TM3/TM5 |
| REQ-021 | Recommendation log | PLAN-009 | US-005 | W3 | TM3 |
| REQ-022 | News ingestion | PLAN-010 | US-006 | W1–2 | TM4 |
| REQ-023 | News normalization/dedupe | PLAN-010 | US-006 | W2 | TM4 |
| REQ-024 | Company/ticker linking | PLAN-010 | US-006 | W2 | TM4 |
| REQ-025 | Direction/evidence only | PLAN-011 | US-007 | W3 | TM4 |
| REQ-026 | News persistence/retrieval | PLAN-011 | US-006, US-007 | W2–3 | TM4 |
| REQ-027 | News API | PLAN-012 | US-006 | W3 | TM4 |
| REQ-028 | News downstream integration | PLAN-011, PLAN-017 | US-007, US-008 | W3 | TM4/all |
| REQ-029 | Explanation inputs | PLAN-013 | US-008, US-009 | W2–3 | TM5 |
| REQ-030 | Evidence grounding | PLAN-013 | US-008–US-011 | W2–3 | TM5 |
| REQ-031 | Four explanation modes | PLAN-013–014 | US-008–US-011 | W2–3 | TM5 |
| REQ-032 | Read-only Q&A tools | PLAN-014 | US-011 | W3 | TM5 |
| REQ-033 | Q&A validation/safety | PLAN-014 | US-011 | W3 | TM5 |
| REQ-034 | Arabic/disclaimer | PLAN-013–014 | US-008–US-011 | W2–3 | TM5 |
| REQ-035 | Deterministic monitoring rules | PLAN-015 | US-012 | W2–3 | TM1 |
| REQ-036 | Freshness/read-only data | PLAN-015 | US-013 | W3 | TM1 |
| REQ-037 | Monitoring persistence/dedup | PLAN-015 | US-013 | W3 | TM1 |
| REQ-038 | Scheduler/advisory lock | PLAN-015 | — | W2–3 | TM1 |
| REQ-039 | Monitoring API | PLAN-016 | US-012, US-013 | W3 | TM1 |
| REQ-040 | Cross-module integration | PLAN-017 | US-002, US-005, US-007–US-011, US-013 | W3 | All |
| REQ-041 | Testing/acceptance | PLAN-018–019 | All applicable stories | W1–3 | All |
| REQ-042 | Active News Agent | PLAN-010–012 | US-006, US-007 | W1–3 | TM4 |

`—` means the requirement is technical/infrastructure-only and intentionally has no invented user story.

## 5. Coverage Check

| README Requirement | Included in Implementation Plan? | Included in User Stories? | Status |
|---|---|---|---|
| REQ-001 FastAPI boundary | Yes: PLAN-001 | No — infrastructure | Covered |
| REQ-002 Runtime baseline | Yes: PLAN-001–002 | No — infrastructure | Covered |
| REQ-003 Application lifecycle | Yes: PLAN-001–002 | No — infrastructure | Covered |
| REQ-004 API/security | Yes: PLAN-003 | Yes: US-002, US-005, US-012, US-013 | Covered |
| REQ-005 Data contracts | Yes: PLAN-002, PLAN-017 | No — infrastructure | Covered |
| REQ-006–REQ-011 Investor Agent | Yes: PLAN-004–006 | Yes: US-001–US-003 | Covered |
| REQ-012–REQ-017 Technical Engine | Yes: PLAN-007–008 | Yes: US-004 | Covered |
| REQ-018–REQ-021 Recommendation Engine | Yes: PLAN-009 | Yes: US-005 | Covered |
| REQ-022–REQ-028 News Agent | Yes: PLAN-010–012, PLAN-017 | Yes: US-006–US-007 | Covered |
| REQ-029–REQ-034 Explanation Agent | Yes: PLAN-013–014 | Yes: US-008–US-011 | Covered |
| REQ-035–REQ-039 Monitoring Service | Yes: PLAN-015–016 | Yes: US-012–US-013 | Covered |
| REQ-040 Cross-module integration | Yes: PLAN-017 | Yes where user-facing | Covered |
| REQ-041 Testing/acceptance | Yes: PLAN-018–019 | Yes through story acceptance checks | Covered |
| REQ-042 Active News Agent | Yes: PLAN-010–012 | Yes: US-006–US-007 | Covered |

No source requirement is intentionally removed, postponed, merged, renamed, or changed to fit the schedule.

## 6. Dependencies

- US-001 and US-002 depend on the shared FastAPI, database, and authentication foundations.
- US-005 depends on a confirmed profile and a valid technical snapshot.
- US-006 and US-007 depend on approved sources and content permissions.
- US-008–US-011 depend on stable Recommendation, Monitoring, News, and snapshot contracts.
- US-011 depends on technical snapshot storage and the five read-only tool contracts.
- US-012–US-013 depend on authenticated ownership and confirmed technical table contracts.
- All stories depend on the final cross-module schema review in PLAN-017 before release.

## 7. Risks and Blockers

| ID | Risk/blocker | Stories affected | Required action |
|---|---|---|---|
| BLOCKER-001 | Authentication and actor roles are not fully specified. | US-002, US-005, US-006, US-012, US-013 | Confirm identity provider, JWT claims, and ownership rules. |
| BLOCKER-002 | Direct actor for technical/news APIs is not specified. | US-004, US-006, US-007 | Confirm whether these are user APIs, internal tools, or both. |
| BLOCKER-003 | News sources and permissions are not specified. | US-006, US-007, US-008 | Confirm approved sources and storage rights. |
| BLOCKER-004 | Actual technical/market table contracts are open. | US-004, US-005, US-011, US-013 | Confirm table names and columns. |
| BLOCKER-005 | LLM/RAG/embedding choices are open. | US-001, US-003, US-008–US-011 | Confirm providers and deployment boundaries. |
| BLOCKER-006 | Three-week capacity may not support full production readiness. | All | Keep all scope; mark incomplete work and limitations explicitly. |

## 8. Assumptions and Clarifications

### A. Explicitly stated in the source specification

- The source specification is the sole project source for these stories.
- The project has five modules in the specified order.
- FastAPI and the listed async PostgreSQL stack are part of the implementation.
- The News Agent is active and direction-only.
- The Explanation Agent has recommendation, alert, follow-up, and Stock Q&A modes.
- Monitoring rules and technical calculations are deterministic.
- Protected APIs use authentication and ownership checks where specified.

### B. Planning decisions

- Team Member 1–5 labels are used exactly as provided.
- Team assignments and planned weeks follow the Implementation Plan and do not imply actual skills.
- User stories are limited to explicit actor-facing functionality; technical requirements remain in the plan and matrix.
- A dash in the traceability matrix means no actor was specified or the requirement is infrastructure-only.

### C. NEEDS CLARIFICATION

- Exact names and roles of team members.
- Exact human actors for technical snapshot and News Agent direct access.
- Authentication provider, roles, and deployment environment.
- Dashboard/UI scope.
- News providers, permissions, taxonomy, and aggregation policy.
- Actual database table contracts.
- LLM, LangMem, RAG, embedding, ChromaDB, and evaluation dataset choices.
- Exact Arabic lexicon for blocked recommendation language in Stock Q&A.

## 9. Recommended Changes — NOT PART OF THE BASE PLAN

These are optional recommendations only and are not requirements:

1. Confirm actors and authentication before finalizing public route permissions.
2. Approve cross-module schemas before parallel implementation reaches integration.
3. Add a post-week-3 hardening milestone for production data, Arabic evaluation, and RAG quality.
4. Provide a reviewed test dataset and representative fixtures before accepting financial outputs.

The base stories and traceability matrix remain unchanged by these recommendations.
