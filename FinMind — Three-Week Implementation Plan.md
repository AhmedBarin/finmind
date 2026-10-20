# FinMind — Three-Week Implementation Plan

**Plan basis:** FinMind consolidated specification v0.3.0-consolidated (2026-10-17)  
**Duration:** 3 weeks / 15 working days  
**Team:** 5 members (roles below; replace labels with actual names)  
**Delivery target:** Integrated MVP demonstrating the in-scope technical engine, investor profile, rule-based recommendation engine, technical monitoring, evidence-grounded explanations, and minimal intent orchestration.

> **Scope guardrail:** The specification explicitly defers the Arabic News Agent, news ingestion/NLP/Chroma, position sizing, portfolio construction, holdings decisions, and external notification delivery. They are excluded from this 3-week commitment. The MVP uses `NEWS_ENABLED=false`, empty news evidence, and a no-op notification dispatcher. A 3-week build is aggressive; this plan assumes a usable starter EGX price dataset/provider, development credentials/LLM availability (or a fake for tests), and team members able to work in parallel. If those assumptions fail, cut LangMem and nonessential dashboard-facing APIs before cutting safety, auditability, contract tests, or reproducibility.

## 1. Delivery goals and acceptance

At the end of Week 3, a user should be able to:

1. Run the service locally using Docker Compose and PostgreSQL, with health checks and migrations.
2. Generate/read a valid, versioned technical snapshot for a stock from OHLCV data, including quality state, core indicators, family scores, regime, and setup score.
3. Complete an Arabic investor-profile interview, review and explicitly confirm a profile, and see the active version; no unconfirmed profile is persisted as active.
4. Request a single-stock recommendation that combines the active profile with the latest valid snapshot, applies deterministic gates, logs the complete reproducible output, and does not call an LLM to decide.
5. Create monitoring rules, evaluate them against fresh snapshots, persist deduplicated alerts with sufficient evidence, and read/acknowledge owned alerts.
6. Explain a stored recommendation or alert, answer read-only technical questions, and route a “should I buy?” question through the recommendation path. Stale/missing data and safety disclaimers are handled explicitly.
7. Pass unit, integration, contract, security/ownership, and end-to-end smoke tests; document known limitations and deferred features.

**Not a production investment-advice certification.** The MVP does not promise returns, execute trades, calculate portfolio sizes, or establish that any score predicts returns. All user-facing financial output carries the required disclaimer.

## 2. Team allocation

| Member | Primary ownership | Week 1 focus | Week 2 focus | Week 3 focus |
|---|---|---|---|---|
| **M1 — Platform & integration lead** | Core app, auth seam, contracts, migrations coordination, orchestration, CI/containerization, integration and release | Foundation, shared contracts, API scaffolding, CI | `/v1/chat` thin routing; integrate modules; unblock contracts | End-to-end tests, hardening, deployment/demo, fixes |
| **M2 — Data & Technical Engine** | Stock universe/price ingestion seam, EGX calendar, indicators/scoring, snapshots, scheduler | Data model, calendar, input/quality pipeline | Indicator/scoring implementation and snapshot job | Backfill/correction behavior, performance, contract tests |
| **M3 — Investor Agent** | Profile schemas/repository, Arabic interview, deterministic risk assessment, HITL, audit | Profile schema/migrations and API skeleton | Interview workflow, validation, confirmation and audit | Integration with recommendation, safety/persona tests, polish |
| **M4 — Recommendation & Explanation** | Recommendation rules/log, explanation modes/validators, read-only snapshot tools | Recommendation contract/rules design and pure-function scaffold | Decision engine and reproducible output; explanation recommendation mode | Alert/follow-up/Stock Q&A modes; explanation validators and integration |
| **M5 — Monitoring & Quality** | Monitoring models/rules/job/API, test strategy, security/ownership and operational checks | Rule schema/evaluator design; test harness and cross-contract review | Monitoring repositories/evaluators/job and integration tests | API, scheduling/dedupe, ownership/security tests, acceptance verification |

**Shared ownership rules:** M1 owns merge/release decisions and keeps the integration branch green. Each module owner owns its code, unit tests, migration, and module-level docs. All shared Pydantic contracts are reviewed by M1 plus producer and consumer owners. One Alembic history is maintained: each owner prepares a migration proposal; M1 coordinates merge order and resolves revision conflicts. No member edits another module’s repository internals to bypass its contract.

## 3. Work breakdown and traceability

Each task has an implementation ID (`IMP-xx`). User stories live in [finmind_user_stories.md](./finmind_user_stories.md), where each story has a unique `US-xx` and references these task IDs. The story file also lists acceptance criteria and inter-story dependencies.

### Week 1 — Foundation, contracts, and parallel module scaffolds

| ID | Days | Owner(s) | Deliverable / done condition | Story links |
|---|---:|---|---|---|
| **IMP-01** | D1–D2 | M1, all | Agree MVP scope, decisions, interfaces, Definition of Done; record open assumptions (price source, auth provider seam, LLM provider/model, EGX calendar/source). Freeze API/error envelope and module ownership. | US-01–US-08 |
| **IMP-02** | D1–D3 | M1 | Modular-monolith repo scaffold matching spec; FastAPI app factory/lifespan, settings, structured logging, request ID, common errors, auth `CurrentUser` seam, health endpoints, `.env.example`, lint/type/test CI. | US-01 |
| **IMP-03** | D1–D4 | M1 + module owners | Shared Pydantic contracts: `StockUniverseRow`, `TechnicalSnapshot`, `InvestorProfile`, `RecommendationOutput`, `AlertRecord`; define stable interfaces/Protocols and contract fixtures. | US-02–US-08 |
| **IMP-04** | D2–D5 | M1 + M2 | PostgreSQL/Alembic baseline, stock universe and OHLCV table/import seam, UTC/trading-date conventions, EGX calendar interface, test DB strategy, Docker Compose with healthy DB and migration job. Seed deterministic fixtures. | US-01, US-02 |
| **IMP-05** | D2–D5 | M2 | Technical ingestion and quality-check scaffold: input OHLCV contract; dedupe/order checks, session gaps, minimum 200 sessions, stale status, zero-volume reliability, correction logging. No silent interpolation. | US-02 |
| **IMP-06** | D2–D5 | M3 | Investor profile schema/repository/API skeleton and migration: partial unique active-profile index, versions, exclusions by canonical sector code, audit log, auth-derived user ID. Define draft/checkpoint persistence seam. | US-03 |
| **IMP-07** | D2–D5 | M4 | Recommendation pure-function scaffold/config tables; formalize gate/blocker/output JSON and log schema including `profile_version`, `config_version`, `snapshot_id`, full `output_json`. Unit test fixtures. | US-04 |
| **IMP-08** | D2–D5 | M5 | Monitoring schema/evaluator interfaces and test plan; rule parameter schemas, alert evidence contract, UTC-day unique-index migration proposal, ownership query patterns. | US-05 |
| **IMP-09** | D4–D5 | M1 + M2/M4/M5 | Integration checkpoint: first app boots, migrations run, typed contracts import, mock snapshot flows through a contract test; confirm config version and freshness semantics. Blocker list reviewed by all. | US-01, US-02, US-04, US-05 |

**Week 1 exit gate:** CI passes; app boots with PostgreSQL; migrations are reproducible; contracts and protocol boundaries are approved; sample data can be loaded; no direct cross-module repository dependencies. If this gate is missed, Week 2 feature work should remain behind module interfaces until the foundation is stable.

### Week 2 — Core capabilities and first integrated paths

| ID | Days | Owner(s) | Deliverable / done condition | Story links |
|---|---:|---|---|---|
| **IMP-10** | D6–D9 | M2 | Indicators and scoring: SMA20/50/200, RSI14, MACD, volume ratio/SMA, ATR14/ATR%, Bollinger width, ADX regime, support/resistance, family scores and regime-weighted setup score. Formula/config versioned; deterministic fixtures cover edge cases. | US-02 |
| **IMP-11** | D8–D10 | M2 + M1 | `technical_snapshots` migration/repository and scheduled/manual technical run seam; one row per ticker/date/config version; active config and freshness reader; corrected historical data triggers controlled recompute/versioning. | US-02 |
| **IMP-12** | D6–D10 | M3 | LangGraph (or specification-compatible stateful workflow) interview: Arabic questions for goal, horizon, capacity/tolerance, experience/knowledge, constraints; completeness and contradictions; safety cap for low capacity; resumable checkpoint. Use FakeLLM in tests. | US-03 |
| **IMP-13** | D9–D10 | M3 + M1 | HITL summary/confirm flow and transactional persistence: explicit confirmation only; deactivate old active version, insert new version, audit immutable change; profile GET/PATCH and user ownership checks. | US-03 |
| **IMP-14** | D6–D10 | M4 | Rule-based recommendation engine: data quality, liquidity percentile formula, exclusions, profile/horizon thresholds, blockers, AVOID/WATCH/BUY/EXCLUDED/NO_RECOMMENDATION, confidence and candidate selection. No LLM in decision path. | US-04 |
| **IMP-15** | D9–D10 | M4 + M2/M3 | Recommendation endpoint/log: load active valid snapshot and confirmed profile via Protocols, produce full required output, store reproducible versions and output JSON; tests cover no profile/no snapshot/stale/profile exclusion. | US-02, US-03, US-04 |
| **IMP-16** | D6–D10 | M5 | Deterministic monitoring evaluators for RSI threshold, price/MA crossing, volatility threshold, setup-score change; first-evaluation rules, missing-input errors, session freshness behavior. Pure unit tests. | US-05 |
| **IMP-17** | D9–D10 | M5 + M2 | Snapshot/state/run repositories and cycle skeleton; reads active config + valid snapshots through snapshot interface, writes run counts and evidence fields, advisory lock design reviewed. | US-02, US-05 |
| **IMP-18** | D10 | All | Week 2 integration demo: generate snapshot → save/confirm profile → request and persist recommendation; run evaluator against fixture snapshot. Resolve any contract mismatches before Week 3. | US-02–US-05 |

**Week 2 exit gate:** A deterministic vertical slice works from fixture OHLCV through a stored snapshot and logged recommendation for a confirmed profile. Monitoring evaluator unit tests pass. Investor profile cannot become active without confirmation. No unresolved breaking contract changes.

### Week 3 — Monitoring APIs, explanations, orchestration, hardening

| ID | Days | Owner(s) | Deliverable / done condition | Story links |
|---|---:|---|---|---|
| **IMP-19** | D11–D12 | M5 | Complete monitoring cycle: advisory lock, freshness skip, rule evaluation, state upsert, cooldown + unique-index dedupe, alert evidence with snapshot/date/config fields, run status/counts, startup stuck-run sweep. | US-05 |
| **IMP-20** | D11–D12 | M5 + M1 | Monitoring rules/alerts API with auth-derived ownership, create/list/get/update allowed fields/soft-delete, acknowledge alert, admin run view and health status; real PostgreSQL integration tests. | US-05 |
| **IMP-21** | D11–D13 | M4 | Explanation modes: recommendation first (full engine output), alert (alert + old/new snapshots), follow-up on stored IDs, stock Q&A using allowlisted read-only tools and bounded queries; no profile access in Q&A. | US-04, US-05, US-06, US-07 |
| **IMP-22** | D12–D13 | M4 + M1 | Explanation output validation: structured schema, every figure grounded in supplied tool/output data, data date stated for Q&A, no recommendation language in Q&A (English/Arabic), disclaimer, missing/stale handling, one bounded retry then template fallback. | US-06, US-07 |
| **IMP-23** | D11–D13 | M1 + M3/M4 | Minimal orchestrator `/v1/chat`: intent routing for profile, recommendation, follow-up, alert explanation, stock Q&A and concept questions; ambiguous ticker asks clarification; “should I buy?” routes to recommendation; mixed message splits into Q&A + recommendation when feasible. | US-03, US-04, US-06, US-07 |
| **IMP-24** | D13 | M1 + M2 | Scheduler and runtime integration: configured EGX-local schedule, calendar gate, one scheduler instance in MVP, technical and monitoring jobs; safe shutdown, health/readiness, retries/locks as specified. | US-01, US-02, US-05 |
| **IMP-25** | D13–D14 | M5 + all | Cross-module contract/security test pass: technical→recommendation, profile→recommendation, recommendation→explanation, snapshot→monitoring→alert→explanation, mixed intent, stale/missing data, ownership isolation, prompt injection, no secrets in logs. | US-01–US-08 |
| **IMP-26** | D14 | M1 + all | Docker acceptance: clean checkout → Compose build/up → Alembic upgrade → health 200; seed/demo command; install/test docs, API OpenAPI review, known limitations and deferred News documented. | US-01–US-08 |
| **IMP-27** | D15 | All | Stabilization and demo; close P0 defects, validate story acceptance, freeze release branch, handover/runbook, final scope and risk review. | US-01–US-08 |

**Week 3 exit gate:** All committed stories pass acceptance or are explicitly marked as a release-blocking gap; app runs from clean setup; data/recommendation outputs are reproducible and versioned; monitoring alerts are deduped; Q&A is read-only and non-recommending; all user-facing financial explanations include disclaimer and limitations.

## 4. Dependency map and collaboration

```text
IMP-01/02/03/04 (foundation + contracts + database)
       ├── IMP-05 → IMP-10 → IMP-11 ───────────────┐
       ├── IMP-06 → IMP-12 → IMP-13 ───────┐       │
       ├── IMP-07 → IMP-14 → IMP-15 ←──────┴───────┘
       └── IMP-08 → IMP-16 → IMP-17 → IMP-19 → IMP-20
                                              │             │
                         IMP-15 ──────────────┴→ IMP-21 → IMP-22
                         IMP-20/alerts ─────────→ IMP-21
                         IMP-02/03 + module APIs → IMP-23
                         all modules → IMP-24/25/26/27
```

**Key handoffs:**

- M2 publishes `TechnicalSnapshot` and `SnapshotReader`; consumers must use active `config_version`, valid data, and EGX-session freshness rules.
- M3 publishes only confirmed `InvestorProfile` versions. Derived recommendation thresholds remain owned by the Recommendation Engine config, not stored profile values.
- M4 consumes profile/snapshot contracts and publishes the complete `RecommendationOutput`, including profile/config versions and `what_would_change_it`.
- M5 consumes snapshot contracts only; alerts include `snapshot_id`, `trading_date`, `previous_trading_date`, and `config_version` in evidence.
- M4 Explanation consumes stored recommendation/alert IDs and checks ownership server-side. Q&A receives no investor profile and can only call bounded read-only snapshot tools.
- M1 owns orchestration and integration; modules call in-process services via interfaces, not each other’s repositories.

## 5. Ceremony and operating rhythm

- **Daily (15 min):** each member reports yesterday/today/blockers; M1 updates dependency board and identifies contract changes.
- **D1 planning (60–90 min):** confirm scope, assignment, branches, code style, Definition of Done, data/API assumptions.
- **D5 and D10 integration demos (30 min):** demonstrate only merged, running code; agree whether scope needs trimming.
- **D14 release candidate:** feature freeze; only bug fixes and acceptance gaps after this point.
- **Pull requests:** small, reviewed by module owner plus one other member; migration and contract changes require M1 plus affected producer/consumer review; CI required.
- **Shared fixtures:** deterministic price histories and test users in `tests/fixtures`; never use fabricated live-market results in user-facing demo without labeling them test data.

## 6. Risks, assumptions, and mitigations

| Risk / assumption | Impact | Mitigation / decision needed |
|---|---|---|
| Full breadth in three weeks is ambitious for five people | High | Ship vertical slice in Week 2; defer LangMem, profile drift, universe-wide scan, advanced backfill, production auth/provider integration if needed. Keep interfaces. |
| Reliable EGX OHLCV source and historical data may not be ready | High | Decide source and licensing on D1; use a clearly labeled local fixture for tests/demo; isolate provider adapter; never imply fixture data is live. |
| Auth and LLM provider/model are open in spec | High | Implement `verify_token` and `LLMClient` seams with FakeLLM; choose real provider early only if credentials are available. No secrets in repo/logs. |
| EGX calendar, session close, and schedule require verified config | High | Implement calendar abstraction and configurable schedule; validate exchange holidays/closing time before enabling live scheduled run. |
| Cross-module migrations can conflict | Medium | Single Alembic history coordinated by M1; module owners submit revisions early; avoid parallel edits to migration head. |
| Indicator edge cases and formula correctness | High | Pure functions, hand-checkable fixtures, independent code review; preserve raw inputs, config versions, and quality flags. |
| LLM-generated financial text can introduce unsupported claims | High | Structured schemas, evidence-grounding validators, tool allowlist, bounded retry/template fallback, disclaimer and no-decision-changing policy. |
| Production deployment/security not fully specified (e.g. auth provider) | Medium | MVP auth seam/stub only, clearly documented; do not market as production-ready; enforce ownership tests and safe error handling. |

## 7. Deferred work (not a hidden commitment)

- Arabic News Agent, source permissions, ingestion/classification, signals, Chroma/vector search, and news-driven monitoring/recommendations.
- Portfolio construction, position sizing, capital/max-loss calculations, holdings-based HOLD/REDUCE.
- Email, push, SMS delivery; monitoring dispatcher remains no-op.
- Production multi-worker split, Redis shared rate limiting, external identity-provider integration, and operational SLOs.
- Full LangMem preference/drift tracking and dashboard/frontend, unless a working UI already exists.

## 8. Traceability index

| Story | Summary | Implementation tasks |
|---|---|---|
| US-01 | Run FinMind reliably | IMP-01–04, IMP-09, IMP-24–27 |
| US-02 | Ingest prices and generate technical snapshots | IMP-03–05, IMP-09–11, IMP-15, IMP-17, IMP-24–25 |
| US-03 | Create and confirm investor profile | IMP-03, IMP-06, IMP-12–13, IMP-15, IMP-23, IMP-25–27 |
| US-04 | Generate reproducible recommendation | IMP-03, IMP-07, IMP-09, IMP-14–15, IMP-21–23, IMP-25–27 |
| US-05 | Monitor technical conditions and manage alerts | IMP-03, IMP-08–09, IMP-16–20, IMP-21, IMP-24–27 |
| US-06 | Explain a recommendation or alert | IMP-03, IMP-19–23, IMP-25–27 |
| US-07 | Ask stock/concept questions safely | IMP-03, IMP-11, IMP-21–23, IMP-25–27 |
| US-08 | Protect data and preserve traceability | IMP-02–04, IMP-06–08, IMP-11, IMP-13–15, IMP-19–27 |

**Companion file:** [FinMind User Stories](./finmind_user_stories.md).