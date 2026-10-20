# FinMind — MVP User Stories and Dependencies

**Companion plan:** [FinMind Three-Week Implementation Plan](./finmind_implementation_plan.md)  
**Specification basis:** FinMind consolidated specification v0.3.0-consolidated (2026-10-17)  
**MVP scope:** Three-week implementation of the in-scope modules. News Agent and other deferred capabilities are excluded as documented in the implementation plan.

## How to read this file

- Each story has a stable **`US-xx`** identifier.
- **Implementation links** point to `IMP-xx` task IDs in `finmind_implementation_plan.md`; those task entries reciprocally list their story IDs.
- **Depends on** means the story’s acceptance should not be considered complete until those prerequisite stories/capabilities are available. Some dependencies can be developed in parallel, but the integration contract must exist.
- Each story includes acceptance criteria in observable Given/When/Then form.

## Story map — how the parts work together

```text
US-01 Platform foundation
  └── US-02 Price data + technical snapshots
        ├── US-04 Profile-aware recommendations ← US-03 Confirmed investor profile
        ├── US-05 Monitoring rules + alerts
        └── US-07 Read-only stock Q&A
              └── US-06 Explanation modes consume US-04 recommendations / US-05 alerts

US-08 Security, auditability, and safe behavior applies across all stories.
```

The technical engine computes snapshots once per stock/trading day, independent of the user. The Investor Agent collects and persists a confirmed profile but does not calculate or recommend. The Recommendation Engine is the only component that combines user profile with technical data and makes the deterministic BUY/WATCH/AVOID/EXCLUDED/NO_RECOMMENDATION decision. Monitoring evaluates user rules against snapshots and creates structured alerts without calling the Recommendation Engine. Explanation interprets already-computed recommendations or alerts; Stock Q&A reads snapshots only and must not recommend. Orchestration routes the question to the appropriate path.

---

## US-01 — Run the FinMind MVP service

**As a** developer/operator, **I want** to start FinMind with its database, migrations, health checks, and required configuration, **so that** the team has a repeatable environment for development, tests, and demonstration.

**Priority:** Must  
**Primary owner:** M1 — Platform & integration lead  
**Depends on:** None  
**Implementation links:** [IMP-01](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-02](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-04](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-09](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-24](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-25](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-26](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-27](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening).

### Acceptance criteria

1. **Given** a clean checkout and configured environment variables, **when** the developer runs the documented Docker Compose command, **then** PostgreSQL becomes healthy, migrations run once, and the API starts.
2. **Given** a running service, **when** `/health/live` and readiness/health endpoints are requested, **then** they return the documented status without exposing secrets or stack traces.
3. **Given** an invalid/missing secret configuration, **when** startup or a protected request needs it, **then** FinMind fails safely with a clear operational error and does not print secret values.
4. **Given** the MVP configuration, **when** the service starts, **then** only one scheduler instance is enabled and News/Chroma routes/jobs remain disabled.
5. **Given** the documented test command, **when** run in CI, **then** lint and automated tests execute against deterministic fixtures.

**Collaborates with:** US-02 provides the technical scheduler workload; US-05 provides monitoring scheduler workload; all modules depend on the foundation and common error/config conventions.

---

## US-02 — Produce versioned technical snapshots from market data

**As a** FinMind user and downstream service, **I want** a quality-checked technical snapshot for a ticker and EGX trading date, **so that** recommendations, monitoring, and explanations use the same reproducible analysis.

**Priority:** Must  
**Primary owner:** M2 — Data & Technical Engine  
**Depends on:** US-01  
**Implementation links:** [IMP-03](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-04](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-05](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-09](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-10](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-11](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-15](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-17](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-24](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-25](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening).

### Acceptance criteria

1. **Given** OHLCV rows for a known ticker, **when** the technical run executes for a trading date, **then** it validates and orders/deduplicates input and records quality problems rather than silently interpolating gaps.
2. **Given** fewer than 200 sessions or stale/missing/flagged input, **when** a snapshot is requested by a consumer, **then** the snapshot marks the correct `data_quality` and no downstream recommendation treats it as valid.
3. **Given** at least 200 valid sessions, **when** calculations run, **then** required MVP indicators and technical families are calculated deterministically from the configured consistent price series; the output includes ADX regime, risk metrics, family scores, and ranking-only `setup_score`.
4. **Given** a ticker/date/config version, **when** a snapshot is stored, **then** it is uniquely identified by `(ticker, trading_date, config_version)` and prior versions are not silently overwritten.
5. **Given** a consumer calls the snapshot reader, **when** it requests latest data, **then** the reader selects the active `config_version` and returns valid data with trading-session freshness metadata.
6. **Given** a user asks for current stock information, **when** the snapshot is missing/stale/invalid, **then** the returned status states why and does not invent a current value.

**Collaborates with:** US-04 consumes snapshot contracts; US-05 reads the same snapshots for rules; US-06 alert explanations may fetch old/new snapshots; US-07 uses read-only snapshot tools. Technical Engine must not depend on profiles or user queries.

---

## US-03 — Create, review, and confirm an investor profile

**As an** investor, **I want** an Arabic guided interview that captures my goal, horizon, risk capacity/tolerance, experience, and restrictions, **so that** later recommendations can apply my confirmed preferences transparently.

**Priority:** Must  
**Primary owner:** M3 — Investor Agent  
**Depends on:** US-01  
**Implementation links:** [IMP-03](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-06](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-12](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-13](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-15](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-23](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-25](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-26](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-27](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening).

### Acceptance criteria

1. **Given** an authenticated user starts an interview, **when** they answer questions, **then** the workflow collects required dimensions, asks follow-ups for missing/contradictory answers, and can resume an abandoned session.
2. **Given** a low financial capacity signal (e.g. emergency funds needed soon or high debt), **when** the requested risk profile is Aggressive, **then** the system applies the Moderate cap, explains the trade-off, and gives the user a clear review/override path consistent with the specification.
3. **Given** the profile is complete, **when** the agent presents the summary card, **then** the summary clearly shows extracted profile values and requires explicit user confirmation.
4. **Given** a user has not confirmed the card, **when** any service requests the active profile, **then** no draft is returned as active or used for recommendations.
5. **Given** the user confirms or updates the profile, **when** persistence occurs, **then** the old active profile is deactivated, a new `profile_version` is created, and an audit record is written atomically.
6. **Given** any profile endpoint is called, **when** the authenticated identity is resolved, **then** `user_id` comes from the token/session and a user cannot read or mutate another user’s profile.
7. **Given** the user asks for a stock recommendation during the interview, **when** the request is processed, **then** the interview agent does not make the recommendation and directs the request to the recommendation flow.

**Collaborates with:** US-04 reads only the active, confirmed profile through `ProfileReader`; it owns no technical calculations or recommendations. US-08 governs PII minimization and audit behavior.

---

## US-04 — Receive a reproducible, profile-aware stock recommendation

**As an** investor with an active confirmed profile, **I want** a deterministic recommendation for a ticker or a ranked scan, **so that** I can see whether technical gates fit my profile and understand what blocks or could change the result.

**Priority:** Must (single-ticker); Should (universe scan if time allows)  
**Primary owner:** M4 — Recommendation & Explanation  
**Depends on:** US-02 and US-03  
**Implementation links:** [IMP-03](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-07](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-09](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-14](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-15](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-21](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-22](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-23](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-25](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-26](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-27](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening).

### Acceptance criteria

1. **Given** an authenticated user with a confirmed active profile and a valid, fresh snapshot, **when** a recommendation is requested, **then** the engine combines only that user’s profile with the shared technical snapshot and returns one of `BUY`, `WATCH`, `AVOID`, `EXCLUDED`, or `NO_RECOMMENDATION`.
2. **Given** the snapshot is invalid/stale or the user has no confirmed profile, **when** a recommendation is requested, **then** it returns an explicit safe status/reason and does not infer missing data or proceed with another user’s profile.
3. **Given** liquidity rank, restrictions, horizon, risk and technical family scores, **when** gates are evaluated, **then** the engine applies the specified liquidity percentile semantics (`rank >= 100 - top_share`), sector/ticker exclusions, family minimums, volatility limits, blockers, and AVOID conditions.
4. **Given** a preferred sector, **when** eligible candidates are ranked, **then** preference is only a tie-break, not an exclusion rule.
5. **Given** the output is generated, **when** it is persisted, **then** the recommendation log records ticker/date, snapshot ID, `config_version`, `profile_version`, decision, blockers, confidence, and the complete output JSON needed for later explanation.
6. **Given** the same versioned snapshot, profile and configuration are supplied again, **when** the pure decision function runs, **then** the decision and reasons are reproducible; an LLM is not used to decide.
7. **Given** the result is shown to a user, **when** the setup score appears, **then** it is described as a ranking/display score, never as probability of profit, and the standard disclaimer is present.

**Collaborates with:** US-02 supplies shared snapshot data; US-03 supplies profile. US-06 explains the stored full output but cannot alter the decision. US-07 routes “should I buy?” into this story’s recommendation flow rather than answering from Q&A.

---

## US-05 — Configure monitoring rules and review technical alerts

**As an** investor, **I want** to create personal technical monitoring rules and receive stored alerts when the configured condition triggers, **so that** I can track stocks without the monitoring service making investment decisions.

**Priority:** Must (rules, deterministic evaluation, alert persistence/API); Could (external delivery, deferred)  
**Primary owner:** M5 — Monitoring & Quality  
**Depends on:** US-01 and US-02  
**Implementation links:** [IMP-03](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-08](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-09](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-16](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-17](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-19](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-20](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-21](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-24](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-25](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-26](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-27](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening).

### Acceptance criteria

1. **Given** an authenticated user, **when** they create a supported rule (`rsi_threshold`, `price_ma_cross`, `volatility_threshold`, or `score_change`), **then** parameters and ticker are validated and the rule is owned by that authenticated user.
2. **Given** a crossing or change rule is first evaluated, **when** there is no prior state, **then** current state is stored but no alert is generated on that first evaluation.
3. **Given** the ticker has no valid fresh snapshot within configured EGX trading-session staleness, **when** the cycle runs, **then** the ticker is skipped and logged; no alert is fabricated.
4. **Given** a rule triggers, **when** the alert is persisted, **then** it records current/threshold values, rule identity, reason, and evidence containing `snapshot_id`, `trading_date`, `previous_trading_date`, and `config_version` where applicable.
5. **Given** the same rule triggers repeatedly within cooldown or daily backstop, **when** monitoring evaluates it, **then** duplicate alerts are suppressed while rule state and run counts are updated appropriately.
6. **Given** two monitoring cycles overlap, **when** the advisory lock is unavailable, **then** the overlapping cycle skips safely instead of duplicating writes.
7. **Given** an alert or rule belongs to another user, **when** a user attempts to read/change/acknowledge it, **then** the API does not disclose it and returns the documented not-found/authorization outcome.
8. **Given** an alert is explained, **when** the Explanation Agent processes it, **then** monitoring itself has not called the Recommendation Engine or LLM; explanations state the technical trigger and do not claim it is a recommendation.
9. **Given** the MVP is running, **when** an alert is created, **then** it is persisted and retrievable; external email/push/SMS delivery is not implied.

**Collaborates with:** US-02 is the sole technical snapshot source. US-06 consumes stored alerts and evidence. Monitoring owns its tables and never writes technical tables or calls recommendation logic.

---

## US-06 — Understand a stored recommendation or alert

**As an** investor, **I want** an explanation tied to a recommendation or alert already stored for me, **so that** I can understand the decision, its evidence, limitations, and what might change it.

**Priority:** Must for recommendation and alert explanations; Should for follow-up  
**Primary owner:** M4 — Recommendation & Explanation  
**Depends on:** US-02, US-04; US-05 for alert mode  
**Implementation links:** [IMP-19](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-20](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-21](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-22](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-23](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-25](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-26](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-27](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening).

### Acceptance criteria

1. **Given** a user requests an explanation by recommendation/alert ID, **when** the endpoint loads the record, **then** the server fetches the stored record and checks ownership instead of trusting user-supplied financial payloads.
2. **Given** a recommendation output, **when** it is explained, **then** the response accounts for decision, blockers, confidence, family scores and minima, indicators, profile fit, rules, `what_would_change_it`, data quality, `config_version`, and `profile_version` as applicable.
3. **Given** an alert and its evidence, **when** it is explained, **then** the explanation identifies the configured trigger, observed and threshold values, and relevant old/new snapshot dates; it does not invent a news/market cause.
4. **Given** no News Agent is enabled, **when** explanation is generated, **then** it states that no news/disclosure evidence was available rather than inventing or implying evidence.
5. **Given** LLM output contains unsupported numbers/claims or fails schema validation, **when** validators run, **then** output is retried at most once and then replaced by a template grounded in the supplied structured data.
6. **Given** any user-facing explanation is returned, **when** rendered, **then** uncertainty/limitations and the standard no-guarantee disclaimer are present and the original deterministic decision is unchanged.

**Collaborates with:** US-04 is the recommendation evidence source; US-05 is the alert/evidence source; US-02 supplies snapshots for the alert explanation. Explanations interpret decisions; they do not recalculate indicators or revise decisions.

---

## US-07 — Ask technical stock questions without receiving an unintended recommendation

**As a** user, **I want** to ask what a ticker’s technical readings mean or compare stocks, **so that** I can understand the system’s data without confusing descriptive analysis with a personalized recommendation.

**Priority:** Should (core safety behavior is Must)  
**Primary owner:** M4 — Recommendation & Explanation, with M1 orchestration  
**Depends on:** US-01 and US-02; US-04 is needed only when the question asks whether to buy/sell  
**Implementation links:** [IMP-03](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-11](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-21](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-22](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-23](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-25](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-26](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-27](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening).

### Acceptance criteria

1. **Given** a question about a stock indicator or trend, **when** it is routed to Stock Q&A, **then** the agent uses only allowlisted, read-only tools backed by stored snapshots/history/glossary and has no access to profiles, holdings, or write operations.
2. **Given** a number is included in the answer, **when** the response is validated, **then** the number appears in tool output and the answer includes the snapshot/data date.
3. **Given** a user asks “should I buy/sell?” or equivalent, **when** the intent is classified, **then** the question is routed to the profile-aware recommendation path and not answered as a Q&A decision.
4. **Given** a user asks a mixed question (e.g. trend plus whether to buy), **when** orchestration can identify both parts, **then** it separates descriptive Q&A from the recommendation request and presents both with their proper boundaries.
5. **Given** ticker identity is ambiguous or data is stale/missing/invalid, **when** the question is handled, **then** the system asks for clarification or states the data status/age in trading sessions instead of guessing or presenting it as current.
6. **Given** a Q&A answer is returned, **when** its language is validated, **then** it contains no BUY/WATCH/AVOID recommendation language (including Arabic equivalents), follows the required Arabic output style, and includes the standard disclaimer.
7. **Given** the user asks a concept question, **when** the glossary tool is used, **then** definitions and system-specific thresholds come from the fixed glossary rather than model memory.

**Collaborates with:** US-02 owns the snapshot and history. US-04 handles suitability/recommendation decisions. US-08 supplies validation, privacy, input guard, and least-privilege expectations.

---

## US-08 — Preserve privacy, ownership, reproducibility, and safe financial boundaries

**As a** user and project stakeholder, **I want** each service to enforce access boundaries and retain traceable versions/evidence, **so that** personal data stays private and system outputs can be audited and reproduced.

**Priority:** Must  
**Primary owner:** M1 (platform/security integration), with all module owners  
**Depends on:** US-01; acceptance is cross-cutting across US-02–US-07  
**Implementation links:** [IMP-02](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-03](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-04](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-06](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-07](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-08](./finmind_implementation_plan.md#week-1--foundation-contracts-and-parallel-module-scaffolds), [IMP-11](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-13](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-14](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-15](./finmind_implementation_plan.md#week-2--core-capabilities-and-first-integrated-paths), [IMP-19](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-20](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-22](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-23](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-25](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-26](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening), [IMP-27](./finmind_implementation_plan.md#week-3--monitoring-apis-explanations-orchestration-hardening).

### Acceptance criteria

1. **Given** a user-scoped request, **when** identity is established, **then** `user_id` comes from the authenticated principal, not request input; tests verify ownership isolation for profiles, recommendations, rules, alerts, and explanations.
2. **Given** an output depends on calculations or model-generated explanation, **when** it is stored or returned, **then** required configuration/profile/prompt/model versions and source record IDs are retained for reproducibility as specified.
3. **Given** the Technical Engine runs for multiple users, **when** it calculates a ticker/day, **then** it calculates user-independent snapshots once per trading date/config version; user-specific suitability remains in Recommendation Engine.
4. **Given** profile financial capacity data is supplied, **when** it is stored or logged, **then** sensitive salary/net-worth details are represented as bands and raw values are not sent to external tracing or logged.
5. **Given** natural-language or untrusted text is supplied, **when** guarded routes process it, **then** body size, prompt-injection handling, schema validation, timeouts, rate limits, and safe error responses apply; untrusted text cannot call tools or alter module policy.
6. **Given** any generated output is financial in nature, **when** returned, **then** it makes no profit guarantee, does not execute or claim to execute trades, and includes the system disclaimer.
7. **Given** missing data, uncertain ticker links, stale snapshots, or unavailable services occur, **when** a result is generated, **then** the system exposes an explicit missing/unknown/partial state rather than substituting fabricated or neutral facts.
8. **Given** News Agent is deferred, **when** the MVP handles a news-related query or explanation, **then** it reports news unavailability/empty evidence and does not create a false neutral signal.

**Collaborates with:** This is a quality and policy story spanning all modules. M1 coordinates test coverage; each owner is accountable for their module’s data ownership, validation, safe failures, and audit/version fields.

---

## Dependency and collaboration detail

| Story | Upstream dependency | Data/contract consumed | Data/contract produced | Downstream stories |
|---|---|---|---|---|
| US-01 | — | Environment/config | Running API, DB, migrations, shared conventions | US-02–US-08 |
| US-02 | US-01 | OHLCV, calendar, stock universe | `TechnicalSnapshot`, `SnapshotReader` | US-04, US-05, US-06, US-07 |
| US-03 | US-01 | Authenticated user, interview answers | Confirmed/versioned `InvestorProfile`, `ProfileReader`, audit trail | US-04 |
| US-04 | US-02 + US-03 | Snapshot + active profile + config | Logged `RecommendationOutput` and reproducibility metadata | US-06; US-07 recommendation routing |
| US-05 | US-01 + US-02 | Rules + valid snapshots + prior rule state | Alert with structured evidence + run/state | US-06 |
| US-06 | US-04; US-05 for alert mode; US-02 for snapshot context | Stored recommendation/alert and evidence | Validated explanation with limitations/disclaimer | User-facing outcome |
| US-07 | US-01 + US-02; US-04 for buy/sell intent | Read-only snapshot/history/glossary; recommendation route when required | Descriptive answer or safely routed recommendation request | User-facing outcome |
| US-08 | US-01 | Identity, module contracts, logs and persisted data | Cross-cutting security, traceability, safe behavior | All stories |

## MVP story sequencing recommendation

1. Complete the minimal foundation in **US-01**.
2. Build **US-02** snapshots and **US-03** confirmed profiles in parallel using shared contracts.
3. Integrate them in **US-04** and create monitoring evaluators for **US-05** in parallel; monitoring’s end-to-end cycle waits for snapshots.
4. Deliver explanation modes in **US-06** and safe Q&A/routing in **US-07** after their source records/tools exist.
5. Verify **US-08** continuously, with full cross-module security and contract checks in Week 3.

**Scope reminder:** News sentiment, articles, Chroma, recommendations using news, portfolio construction, position sizing, holdings decisions, and external alert delivery are deferred from this MVP.