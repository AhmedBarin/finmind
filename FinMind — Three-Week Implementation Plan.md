# FinMind — Implementation Plan

> **Source of truth:** `FinMind_unified_fastapi_spec.md` supplied by the project owner.
> **Planning horizon:** 3 weeks.
> **Team:** Team Member 1–5. Names, skills, and roles were not specified; assignments below are planning decisions, not project requirements.
> **Scope rule:** This plan preserves the modules, boundaries, contracts, and requirements in the source specification. It does not remove or redesign project functionality.

## 1. Project Scope Summary

FinMind is an async Python/PostgreSQL financial system exposed through FastAPI. The source specification contains five ordered modules: Investor Agent; Technical Engine and Recommendation Engine; News Agent; Explanation Agent; and Monitoring Service. The shared platform provides FastAPI routing, Pydantic contracts, authentication dependencies, database sessions, lifecycle management, scheduled jobs, logging, error handling, migrations, and tests.

The Investor Agent collects and confirms an investor profile. The Technical Engine ingests prices, validates data, calculates indicators and technical snapshots. The Recommendation Engine combines technical snapshots with the confirmed profile and produces rule-based recommendation output. The News Agent ingests permitted news, links it to EGX companies, produces evidence-backed positive/negative/neutral/unknown direction, and does not make the final recommendation or calculate an impact score. The Explanation Agent explains prepared recommendations and alerts and provides the Stock Q&A mode through read-only snapshot tools. The Monitoring Service evaluates deterministic rules against stored market and technical data, persists alerts, and provides rule/alert APIs.

The complete source scope is substantial for three weeks. Five people can establish the architecture, contracts, first working paths, and integration in that period, but full production hardening, all source adapters, complete Arabic NLP evaluation, RAG quality evaluation, and exhaustive market-data validation may require work beyond three weeks. This is a schedule risk, not a scope reduction.

## 2. README Requirements Register

| Requirement ID | Source requirement/module | Requirement statement | User-facing? |
|---|---|---|---|
| REQ-001 | Project-wide FastAPI setup | Use FastAPI as the project HTTP boundary with modular routers and business logic outside route handlers. | No |
| REQ-002 | Project-wide runtime | Use Python 3.11+, async SQLAlchemy/asyncpg, PostgreSQL 15+, Pydantic v2, Alembic, Uvicorn, APScheduler, tests, and structured logging as specified. | No |
| REQ-003 | Shared application | Provide application creation, configuration loading, router registration, lifespan startup/shutdown, health endpoints, and dependency cleanup. | No |
| REQ-004 | Shared API/security | Use typed schemas, authentication dependencies, database dependencies, ownership checks, UTC timestamps, request IDs, consistent errors, structured logs, and protected internal routes. | Partly |
| REQ-005 | Shared data contracts | Use PostgreSQL as canonical storage; use ChromaDB only as a retrieval index; preserve stable IDs, dates, versions, status, provenance, and explicit missing/stale states. | No |
| REQ-006 | Investor Agent | Conduct the Arabic conversational investor interview using a stateful LangGraph workflow. | Yes |
| REQ-007 | Investor Agent | Extract risk, horizon, goal, experience, sector preferences, ticker exclusions, and constraints into validated structured data. | Yes |
| REQ-008 | Investor Agent | Validate consistency, resolve contradictions, and continue the interview until required information is complete. | Yes |
| REQ-009 | Investor Agent | Present an Arabic profile summary and require explicit human confirmation before activation. | Yes |
| REQ-010 | Investor Agent | Persist confirmed profiles, audit changes, checkpoints, and learned preferences in PostgreSQL/LangMem as specified. | Partly |
| REQ-011 | Investor Agent boundary | Do not calculate indicators, make recommendations, execute orders, or bypass confirmation in the Investor Agent. | No |
| REQ-012 | Technical data | Ingest daily OHLCV prices after the market session and maintain the consistent price series and history. | No |
| REQ-013 | Technical data quality | Detect insufficient history, gaps, zero volume, stale data, unexplained jumps, duplicate dates, and out-of-order dates; do not silently interpolate. | No |
| REQ-014 | Technical indicators | Calculate the specified trend, momentum, volume, volatility, support/resistance, regime, liquidity, and context indicators deterministically. | No |
| REQ-015 | Technical scoring | Normalize indicators to bounded 0–100 scores and calculate Trend, Momentum, Volume, and Support/Resistance family scores using the specified rules. | No |
| REQ-016 | Regime/risk | Calculate ADX regime and volatility/risk metrics separately from the setup score. | No |
| REQ-017 | Technical snapshots | Store reproducible technical snapshots containing raw inputs, indicators, scores, regime, risk, prices, and configuration version. | No |
| REQ-018 | Recommendation filters | Apply data-quality, liquidity, exclusions, and other specified filters before a recommendation. | No |
| REQ-019 | Recommendation gates | Apply profile-specific minimums and technical family rules; use setup score for ranking/display only, not as the sole decision. | No |
| REQ-020 | Recommendation output | Produce direction, confidence, blockers/reasons, family results, user fit, data quality, and the documented recommendation payload. | Yes |
| REQ-021 | Recommendation audit | Persist recommendation logs with the specified user, ticker, date, snapshot, configuration, decision, blockers, confidence, and timestamp fields. | No |
| REQ-022 | News ingestion | Collect permitted financial news and disclosures through configured sources, schedules, retries, rate limits, and backfill support. | No |
| REQ-023 | News normalization | Preserve original content, normalize Arabic/multilingual text, validate metadata, deduplicate, and preserve provenance. | No |
| REQ-024 | Company linking | Link articles to canonical EGX companies/tickers using aliases, confidence, ambiguity handling, and abstention when necessary. | No |
| REQ-025 | News direction/evidence | Classify event type and evidence-backed direction as positive, negative, neutral, or unknown with confidence, relevance, novelty, freshness, and source reliability; do not expose an impact level/score. | Partly |
| REQ-026 | News persistence/retrieval | Store articles, analyses, links, and news signals in PostgreSQL; index permitted chunks in ChromaDB with stable references; expose typed tools. | Partly |
| REQ-027 | News API | Expose the specified News Agent FastAPI routes, internal routes, validation, security, observability, and error semantics. | Yes |
| REQ-028 | News integration | Send news evidence/direction to Recommendation, Monitoring, and Explanation contracts without making a final recommendation in News Agent. | No |
| REQ-029 | Explanation inputs | Explain validated Recommendation Engine outputs and Monitoring Service alerts without changing decisions or inventing evidence. | Yes |
| REQ-030 | Explanation evidence | Retrieve and cite authorized financial evidence, preserve source metadata, distinguish facts from interpretation, and state uncertainty. | Yes |
| REQ-031 | Explanation modes | Support recommendation explanation, alert explanation, follow-up, and Stock Q&A modes in one Explanation Agent. | Yes |
| REQ-032 | Stock Q&A tools | In Stock Q&A, use only the read-only snapshot tools: technical snapshot, snapshot history, price history, snapshot comparison, and indicator glossary. | Yes |
| REQ-033 | Stock Q&A safety | Answer only from tool output, include data date/freshness, verify numeric claims, reject recommendation language, retry once, and use a safe fallback when needed. | Yes |
| REQ-034 | Arabic explanation | Preserve Arabic output style, disclaimer, source attribution, uncertainty, and no-guarantee behavior. | Yes |
| REQ-035 | Monitoring rules | Load and validate active rules and evaluate RSI, moving-average cross, volatility, and score-change rules deterministically. | Yes |
| REQ-036 | Monitoring data safety | Read shared market/technical tables only, validate freshness, and skip stale tickers without creating user alerts. | No |
| REQ-037 | Monitoring persistence | Own and persist monitoring rules, rule states, runs, alerts, evidence, cooldown/deduplication, and optional notification attempts as specified. | Partly |
| REQ-038 | Monitoring execution | Run scheduled monitoring cycles with PostgreSQL advisory-lock overlap prevention, per-rule/per-ticker error handling, and run status. | No |
| REQ-039 | Monitoring API | Expose authenticated rule, alert, acknowledgement, run, and health APIs with user ownership checks. | Yes |
| REQ-040 | Cross-module integration | Align Investor→Recommendation, Technical→Recommendation/Monitoring, News→Recommendation/Monitoring/Explanation, Monitoring→Explanation, and all FastAPI schemas. | No |
| REQ-041 | Testing/acceptance | Provide unit, integration, API, contract, security, evaluation, and end-to-end validation for the specified modules and contracts. | No |
| REQ-042 | Active News Agent | Implement News Agent as active scope; do not defer, disable, or replace it with an unimplemented placeholder. | No |

## 3. Implementation Plan

Effort is a planning estimate in person-days. Assignments are organizational decisions because the source does not specify team roles.

| Plan ID | Requirement ID(s) | Module/Feature | Task description | Subtasks | Dependencies | Priority | Assigned member | Effort | Week/days | Definition of Done | Notes / clarification needed |
|---|---|---|---|---|---|---|---|---:|---|---|---|
| PLAN-001 | REQ-001–REQ-005 | Platform foundation | Create the shared FastAPI application skeleton and cross-module contracts. | Create package layout; settings; app factory; common schemas; error envelope; router registry. | None | P0 | Team Member 1 | 3 | W1 D1–3 | App starts; routers load; health route responds; contracts compile. | Authentication provider and deployment environment are **NEEDS CLARIFICATION**. |
| PLAN-002 | REQ-002–REQ-005 | Persistence foundation | Configure async PostgreSQL, SQLAlchemy, Alembic, logging, request IDs, and lifecycle cleanup. | Engine/session factory; base models; migration config; structured logs; lifespan cleanup. | PLAN-001 | P0 | Team Member 1 | 3 | W1 D3–5 | Database connects; migration runs; sessions close; logs contain request IDs. | Actual shared `users` table contract is **NEEDS CLARIFICATION**. |
| PLAN-003 | REQ-004 | Security/API boundary | Implement shared authentication, authorization dependencies, ownership checks, rate limiting boundary, and internal service authentication. | Auth dependency; current-user dependency; internal-route guard; safe exceptions; route tests. | PLAN-001 | P0 | Team Member 5 | 3 | W1 D3–5 | Protected routes reject unauthorized requests and do not leak data. | Identity provider and exact JWT policy are **NEEDS CLARIFICATION**. |
| PLAN-004 | REQ-006–REQ-011 | Investor Agent workflow | Implement profile interview state and deterministic validation. | LangGraph state; question sequencing; structured extraction; contradiction handling; completeness checks. | PLAN-001, PLAN-002, PLAN-003 | P0 | Team Member 2 | 5 | W1 D2–5, W2 D1 | Interview progresses and rejects incomplete/conflicting state. | Exact LLM/provider and LangMem deployment are **NEEDS CLARIFICATION**. |
| PLAN-005 | REQ-009–REQ-011 | Investor Agent confirmation | Implement summary, HITL confirmation, edits, persistence, audit, and API routes. | Summary schema; confirm endpoint; edit endpoint; profile repository; audit records; tests. | PLAN-004 | P0 | Team Member 2 | 4 | W2 D1–4 | Unconfirmed profile cannot be used as active profile; confirmed state is persisted and audited. | Dashboard implementation is outside the supplied backend details; **NEEDS CLARIFICATION** if required here. |
| PLAN-006 | REQ-010 | Investor memory | Integrate LangMem tiers and preference drift/reprofiling handling from the source. | Memory adapter; validated preference writes; drift event handling; PII minimization. | PLAN-004, PLAN-005 | P1 | Team Member 2 | 3 | W2 D4–5, W3 D1 | Preferences are versioned, validated, and never change foundational risk without confirmation. | Exact LangMem storage backend is **NEEDS CLARIFICATION**. |
| PLAN-007 | REQ-012–REQ-013 | Price ingestion | Implement daily price ingestion and data-quality validation. | Source adapter boundary; OHLCV persistence; exchange calendar hook; history checks; stale/gap flags. | PLAN-001, PLAN-002 | P0 | Team Member 3 | 5 | W1 D1–5 | Valid data is persisted; each specified invalid condition is flagged and tested. | Provider, exchange-calendar source, and corporate-action policy are **NEEDS CLARIFICATION**. |
| PLAN-008 | REQ-014–REQ-017 | Technical Engine | Implement deterministic indicators, normalization, family scores, regime, risk, setup score, and snapshots. | Indicator functions; scoring tables; support/resistance; ADX; snapshot model/repository; config version. | PLAN-007 | P0 | Team Member 3 | 8 | W2 D1–5, W3 D1–3 | Fixed inputs produce reproducible snapshots matching source formulas and bounds. | Threshold validation/backtest dataset is **NEEDS CLARIFICATION**. |
| PLAN-009 | REQ-018–REQ-021 | Recommendation Engine | Implement profile/technical filters, gates, direction, confidence, candidate selection, payload, and log. | Input adapters; filters; profile minimums; decision logic; confidence; recommendation repository. | PLAN-005, PLAN-008 | P0 | Team Member 3 | 6 | W3 D1–5 | Valid profile plus snapshot yields documented payload; invalid/stale data yields no recommendation with reason. | News contribution policy and exact handling of missing news are **NEEDS CLARIFICATION**. |
| PLAN-010 | REQ-022–REQ-024 | News ingestion | Implement active source configuration, fetching, normalization, persistence, deduplication, and ticker linking. | Adapter envelope; fetch runs; retries; Arabic normalization; URL/title/content dedupe; alias resolver. | PLAN-001, PLAN-002, PLAN-003 | P0 | Team Member 4 | 7 | W1 D2–5, W2 D1–3 | At least one configured source can be ingested idempotently with provenance and ticker-link confidence. | Approved providers, licensing, and storage permissions are **NEEDS CLARIFICATION**. |
| PLAN-011 | REQ-025–REQ-028, REQ-042 | News direction and retrieval | Implement evidence-backed direction-only analysis, PostgreSQL signals, Chroma references, tools, and downstream contracts. | Direction schema; evidence spans; positive/negative/neutral/unknown validation; chunk indexing; search/retrieval tools; recommendation/monitoring/explanation envelopes. | PLAN-010 | P0 | Team Member 4 | 7 | W2 D3–5, W3 D1–4 | News output contains direction/evidence and never an impact field or final recommendation; all tools are typed and tested. | Model choice, taxonomy, score policy, and lookback windows are **NEEDS CLARIFICATION**. |
| PLAN-012 | REQ-027 | News API | Implement News Agent public and internal FastAPI routes. | Search; recent/company news; signal; analysis; recompute; validation; error/status mapping. | PLAN-003, PLAN-010, PLAN-011 | P0 | Team Member 4 | 3 | W3 D2–4 | OpenAPI routes validate requests, enforce auth, and return documented statuses. | Exact route versioning follows the source; deployment exposure is **NEEDS CLARIFICATION**. |
| PLAN-013 | REQ-029–REQ-031, REQ-034 | Explanation Agent core | Implement recommendation, alert, follow-up, adapters, context builder, Arabic structured output, and evidence validation. | Input schemas; mode router; RAG adapter; source checks; output schema; disclaimer; fallback/error handling. | PLAN-001, PLAN-003, PLAN-009, PLAN-011, PLAN-014 | P0 | Team Member 5 | 6 | W2 D1–5, W3 D1 | Each prepared input produces schema-valid Arabic output without changing the source decision. | LLM, RAG store, and document availability are **NEEDS CLARIFICATION**. |
| PLAN-014 | REQ-032–REQ-033 | Stock Q&A | Implement read-only snapshot tools and the fourth Explanation Agent mode. | Tool repository queries; orchestrator intent split; date/freshness; number grounding; language rejection; retry/fallback. | PLAN-008, PLAN-013 | P0 | Team Member 5 | 5 | W3 D1–4 | Q&A answers only from tool output; recommendation questions route separately; stale/missing data is explicit. | Exact Arabic recommendation-language lexicon is **NEEDS CLARIFICATION**. |
| PLAN-015 | REQ-035–REQ-038 | Monitoring core | Implement deterministic rule engine, freshness, state, runs, alerts, cooldowns, and scheduler lock. | Rule schemas; repositories; evaluators; advisory lock; run lifecycle; dedupe; evidence JSONB; no-op dispatcher. | PLAN-002, PLAN-008 | P0 | Team Member 1 | 7 | W2 D1–5, W3 D1–2 | Scheduled cycle evaluates valid fresh data, persists runs/states/alerts, and prevents overlap. | Actual technical table names/columns are **NEEDS CLARIFICATION**. |
| PLAN-016 | REQ-039 | Monitoring API | Implement authenticated monitoring rule, alert, acknowledgement, run, and health routes. | CRUD/list routes; owner filtering; acknowledge route; admin run route; schemas/tests. | PLAN-003, PLAN-015 | P0 | Team Member 1 | 3 | W3 D2–4 | Ownership and status codes match source specification; unauthorized records are not visible. | Admin role definition is **NEEDS CLARIFICATION**. |
| PLAN-017 | REQ-040 | Integration contracts | Connect module service interfaces and reconcile all shared payloads. | Investor→Recommendation; Technical→Recommendation/Monitoring; News→Recommendation/Monitoring/Explanation; Monitoring→Explanation; date/status/version fields. | PLAN-005, PLAN-008, PLAN-009, PLAN-011, PLAN-013, PLAN-015 | P0 | Team Member 1 + all | 5 | W3 D2–5 | Contract tests pass for every documented direction and no module violates ownership boundaries. | Final schemas must be approved by module owners. |
| PLAN-018 | REQ-041 | Testing | Implement unit, integration, API, contract, security, evaluation, and end-to-end tests. | Deterministic formula tests; API TestClient/httpx; DB integration; prompt-injection/SSRF; stale/missing cases; Q&A grounding. | PLAN-001–PLAN-017 incrementally | P0 | Team Member 5 + all | 7 | W1 D4–5, W2 D4–5, W3 D1–5 | Test suite runs in CI/local environment and all critical acceptance tests pass or are recorded as blockers. | CI environment and representative data set are **NEEDS CLARIFICATION**. |
| PLAN-019 | REQ-003, REQ-041 | Final validation | Run integrated acceptance, bug fixing, migration review, and release validation. | Full smoke test; API/OpenAPI review; migration dry run; security review; fix critical bugs; document known limitations. | PLAN-017, PLAN-018 | P0 | All, coordinated by Team Member 1 | 5 | W3 D4–5 | Scope coverage is signed off; unresolved blockers are explicit; no silent scope reduction occurs. | Production deployment target is **NEEDS CLARIFICATION**. |

## 4. 3-Week Schedule

### Week 1 — Foundation and first vertical slices

| Tasks | Subtasks | Dependencies | Assignments | Expected deliverables |
|---|---|---|---|---|
| PLAN-001–PLAN-003 | FastAPI skeleton, settings, DB, migrations, auth, errors, health | None | TM1, TM5 | Running app, common schemas, protected route examples, database migration baseline |
| PLAN-004 | Investor state/extraction skeleton | PLAN-001–003 | TM2 | Interview graph and validation path |
| PLAN-007 | Price ingestion/data-quality skeleton | PLAN-001–002 | TM3 | OHLCV contract, quality flags, repository boundary |
| PLAN-010 | News source envelope/ingestion skeleton | PLAN-001–003 | TM4 | Active source adapter boundary, normalized article schema, idempotency design |
| PLAN-018 (partial) | Foundation unit/API tests | In parallel | TM5 + all | Health/auth/session tests |

**Week 1 dependencies:** Common schemas and database sessions must exist before module repositories. Authentication must exist before protected route testing. The actual shared table names remain a clarification item.

### Week 2 — Core module implementation

| Tasks | Subtasks | Dependencies | Assignments | Expected deliverables |
|---|---|---|---|---|
| PLAN-005–PLAN-006 | Investor confirmation, audit, and memory | PLAN-004 | TM2 | Confirmed profile API, audit trail, memory adapter boundary |
| PLAN-008 | Indicators, scoring, regime, snapshots | PLAN-007 | TM3 | Deterministic technical snapshot pipeline |
| PLAN-009 (start) | Recommendation filters/gates | PLAN-005, PLAN-008 | TM3 | Recommendation service skeleton and payload contract |
| PLAN-010 (finish) | News normalization, dedupe, ticker linking | PLAN-010 start | TM4 | Persisted article/link records and tests |
| PLAN-011 (start) | Direction/evidence and retrieval | PLAN-010 | TM4 | Direction-only analysis contract and retrieval skeleton |
| PLAN-013 (start) | Explanation prepared-input modes | PLAN-009/011 contracts | TM5 | Recommendation/alert explanation schemas and validator |
| PLAN-015 (start) | Monitoring repositories/rule engine | PLAN-002, PLAN-008 | TM1 | Rule schemas and deterministic evaluator skeleton |
| PLAN-018 (partial) | Module unit/integration tests | In parallel | All | Formula, schema, and repository tests |

### Week 3 — Integration, Q&A, APIs, testing, and hardening

| Tasks | Subtasks | Dependencies | Assignments | Expected deliverables |
|---|---|---|---|---|
| PLAN-009 (finish) | Recommendation confidence/logging | PLAN-008, profile contract | TM3 | Complete recommendation payload and audit log |
| PLAN-011–PLAN-012 | News direction, retrieval, FastAPI routes, downstream contracts | PLAN-010 | TM4 | Active News Agent API and integration envelopes |
| PLAN-013–PLAN-014 | Explanation integration and Stock Q&A | PLAN-008, PLAN-009, PLAN-011 | TM5 | Four modes, read-only tools, date/number/recommendation-language validation |
| PLAN-015–PLAN-016 | Monitoring scheduler, lock, alerts, API | PLAN-008, PLAN-003 | TM1 | Complete monitoring cycle and authenticated APIs |
| PLAN-017 | Cross-module integration | All core tasks | TM1 + all | Contract tests and end-to-end service path |
| PLAN-018 | Full testing/security/evaluation | All available modules | TM5 + all | Test report, defect list, security findings |
| PLAN-019 | Integration, bug fixing, final validation | PLAN-017–018 | All | Release candidate, migration review, explicit blockers and known limitations |

The schedule does not remove scope to fit three weeks. If the team cannot complete all work, incomplete capabilities must remain visible in the risk/blocker list rather than being silently deferred or redesigned.

## 5. Team of 5 Work Allocation

| Team member | Planned primary allocation | Supporting allocation | Basis |
|---|---|---|---|
| Team Member 1 | Platform foundation and Monitoring Service | Integration coordination and final validation | Planning decision based on dependency centrality; not specified by source |
| Team Member 2 | Investor Agent | Profile contract integration and memory | Planning decision; not specified by source |
| Team Member 3 | Technical Engine and Recommendation Engine | Technical contract tests | Planning decision; not specified by source |
| Team Member 4 | Active News Agent | News downstream contracts and API | Planning decision; not specified by source |
| Team Member 5 | Explanation Agent and testing | Security/API tests and final QA | Planning decision; not specified by source |

All five members participate in PLAN-017–PLAN-019. No skill, seniority, or role is assumed from the member labels.

## 6. Dependencies

1. PLAN-001 must precede all FastAPI route work.
2. PLAN-002 must precede repository, migration, and persistence work.
3. PLAN-003 must precede protected API acceptance tests.
4. Investor confirmation (PLAN-005) must precede Recommendation Engine profile consumption (PLAN-009).
5. Price ingestion and quality validation (PLAN-007) must precede Technical Engine snapshots (PLAN-008).
6. Technical snapshots (PLAN-008) must precede Recommendation, Stock Q&A, and Monitoring work.
7. News ingestion/linking (PLAN-010) must precede direction/retrieval (PLAN-011).
8. Recommendation and News contracts must be available before complete Explanation integration.
9. Monitoring contract alignment requires confirmation of Technical Engine table names and columns.
10. Contract tests and final validation depend on all participating module schemas being stable.

## 7. Risks and Blockers

| ID | Risk/blocker | Effect | Mitigation | Status |
|---|---|---|---|---|
| RISK-001 | Three-week window versus full scope | Full production readiness may exceed capacity. | Build vertical slices; report incomplete work explicitly; do not reduce scope silently. | Open |
| RISK-002 | News providers, permissions, and licensing unspecified | Ingestion and storage may be blocked. | Confirm approved sources and storage rights before production ingestion. | NEEDS CLARIFICATION |
| RISK-003 | Actual shared database table names/columns unspecified | Monitoring and integration queries may not compile. | Isolate repositories; confirm OD-01/OD-02 before final implementation. | NEEDS CLARIFICATION |
| RISK-004 | LLM, LangGraph/LangMem, RAG, embedding, and Chroma deployment choices unspecified | Agent features cannot be validated end to end. | Keep provider adapters; use contract tests; record unavailable dependencies explicitly. | NEEDS CLARIFICATION |
| RISK-005 | Authentication/identity provider unspecified | Protected APIs cannot be finalized. | Implement dependency boundary; confirm JWT/identity policy. | NEEDS CLARIFICATION |
| RISK-006 | News direction aggregation policy/lookback unspecified | Recommendation integration may be ambiguous. | Do not invent coefficients; obtain policy decision. | NEEDS CLARIFICATION |
| RISK-007 | Representative EGX data/evaluation set unspecified | Thresholds and Arabic classification quality cannot be validated. | Require a reviewed dataset and document limitations. | NEEDS CLARIFICATION |
| RISK-008 | Source contains illustrative alert/recommendation fields | Contract mismatch may occur. | Replace illustrative payloads with approved shared schemas during PLAN-017. | Open |

## 8. Assumptions and Clarifications

### A. Explicitly stated in the source specification

- FastAPI is the project backend boundary.
- PostgreSQL is the canonical persistent store.
- ChromaDB is a retrieval index, not the source of truth.
- The five modules and their boundaries are retained.
- News Agent is active and direction-only; it does not make final recommendations.
- Explanation Agent has four modes, including Stock Q&A with read-only tools.
- Monitoring is deterministic and does not use an LLM.
- The project uses async Python components and the specified FastAPI/PostgreSQL stack.
- Missing, stale, partial, and unavailable data must remain distinguishable.

### B. Planning decisions

- The five generic team members are assigned according to dependencies and workload.
- PLAN-001–PLAN-003 are scheduled first because all modules use them.
- Technical and news implementation run in parallel after their shared contracts exist.
- Team Member 1 coordinates integration because the source does not specify a coordinator.
- Efforts, priorities, week/day allocations, and vertical-slice sequencing are estimates, not requirements.

### C. NEEDS CLARIFICATION

- Names, skills, and availability of the five team members.
- Authentication provider, JWT claims, roles, and deployment environment.
- Actual `users` table and ownership contract.
- Approved news providers, source permissions, APIs/RSS, and full-text storage rights.
- Exchange calendar and corporate-action policy.
- Actual `stock_prices`, `technical_indicators`, `technical_scores`, and snapshot table names/columns.
- LLM provider/model, LangGraph/LangMem versions and deployment, embedding model, Chroma mode, and RAG corpus availability.
- Final news taxonomy, lookback windows, direction aggregation policy, missingness behavior in Recommendation Engine, and validation thresholds.
- Exact Arabic recommendation-language lexicon for Stock Q&A.
- Whether Dashboard/UI work is part of this backend implementation.
- CI, test database, representative market dataset, and production deployment target.

## 9. Recommended Changes — NOT PART OF THE BASE PLAN

The following are not requirements and are not applied to the plan:

1. Add a formal product owner or technical lead role.
2. Add a delivery milestone after week 3 for production hardening and model/data evaluation.
3. Freeze cross-module schemas before parallel implementation.
4. Decide a single deployment and authentication target before API hardening.
5. Create a reviewed Arabic/English evaluation dataset before relying on news direction or Stock Q&A in production.

These recommendations do not change the base scope or remove any source requirement.
