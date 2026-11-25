"""Live smoke test for Explanation Agent routes against a running local API.

This test does not call the Investor Agent. It uses the Technical Engine to
build a snapshot from saved prices when one is missing or behind the latest
price, calls the real Recommendation Engine route, creates a temporary alert
fixture, and then exercises the Explanation Agent endpoints. It removes its
temporary recommendation/alert records afterward; existing market data is
never modified.

The API server needs GROQ_API_KEY and EXPLANATION_MODEL configured. The script
uses the repository's DATABASE_URL to locate a saved technical snapshot.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, time
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.market_data.fetcher import FetchedPriceHistory
from app.market_data.ingestion import ingest_price_history
from app.monitoring.models.alert import Alert
from app.monitoring.models.monitoring_rule import MonitoringRule
from app.monitoring.schemas.alerts import AlertResponse
from app.recommendation.models import RecommendationLog
from app.technical_analysis.snapshot_service import calculate_and_persist_snapshot
from app.technical_analysis.models import TechnicalSnapshot
from app.technical_analysis.schemas import TechnicalSnapshotRead
from app.market_data.models import StockPrice


BASE_URL = os.getenv("EXPLANATION_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TICKER = os.getenv("EXPLANATION_TICKER", "COMI").strip().upper()
if TICKER and not TICKER.endswith(".CA"):
    TICKER = f"{TICKER}.CA"
TIMEOUT = float(os.getenv("EXPLANATION_LIVE_TIMEOUT_SECONDS", "90"))
USER_ID = UUID(os.environ["EXPLANATION_USER_ID"]) if os.getenv("EXPLANATION_USER_ID") else uuid4()
_CAIRO = ZoneInfo("Africa/Cairo")
_CSV_PATH = Path(__file__).resolve().parents[1] / "EGX30_all_stocks.csv"
_CSV_SOURCE = "explanation_smoke_csv"


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def _check_response(response: httpx.Response, mode: str) -> dict:
    if response.status_code == 503:
        fail(
            f"{mode} returned 503. Check that the server has GROQ_API_KEY and "
            "EXPLANATION_MODEL configured, then restart it. "
            f"Details: {response.text[:500]}"
        )
    if response.status_code >= 400:
        fail(f"{mode} returned HTTP {response.status_code}: {response.text[:700]}")
    try:
        payload = response.json()
    except ValueError:
        fail(f"{mode} did not return JSON")
    if not isinstance(payload, dict):
        fail(f"{mode} returned an unexpected response shape")
    return payload


def _check_disclaimer(payload: dict, mode: str) -> None:
    if not payload.get("disclaimer"):
        fail(f"{mode} response has no disclaimer")


async def _create_fixtures(ticker: str) -> dict:
    imported_dates: list = []
    created_snapshot_id = None
    async with SessionLocal() as session:
        latest_price = await session.scalar(
            select(StockPrice.date)
            .where(StockPrice.ticker == ticker)
            .order_by(StockPrice.date.desc())
            .limit(1)
        )
        snapshot = await session.scalar(
            select(TechnicalSnapshot)
            .where(TechnicalSnapshot.ticker == ticker)
            .order_by(TechnicalSnapshot.date.desc(), TechnicalSnapshot.calculated_at.desc())
            .limit(1)
        )
        if latest_price is None:
            if not _CSV_PATH.exists():
                fail(f"No saved prices for {ticker}, and local CSV is missing: {_CSV_PATH}")
            frame = pd.read_csv(_CSV_PATH)
            required = {"Ticker", "Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"}
            if not required.issubset(frame.columns):
                fail(f"Local CSV is missing required columns: {sorted(required - set(frame.columns))}")
            ticker_rows = frame.loc[frame["Ticker"].astype(str).str.upper() == ticker].copy()
            if ticker_rows.empty:
                fail(f"Local CSV contains no rows for {ticker}.")
            ticker_rows["Date"] = pd.to_datetime(ticker_rows["Date"], errors="raise")
            ticker_rows = ticker_rows.drop_duplicates(subset=["Date"], keep="last")
            price_frame = ticker_rows.set_index("Date").drop(columns=["Ticker"])
            if "Dividends" not in price_frame:
                price_frame["Dividends"] = 0
            if "Stock Splits" not in price_frame:
                price_frame["Stock Splits"] = 0
            report = await ingest_price_history(
                session,
                FetchedPriceHistory(
                    ticker=ticker,
                    source=_CSV_SOURCE,
                    prices=price_frame,
                ),
            )
            imported_dates = list(report.changed_dates)
            await session.flush()
            latest_price = await session.scalar(
                select(StockPrice.date)
                .where(StockPrice.ticker == ticker)
                .order_by(StockPrice.date.desc())
                .limit(1)
            )
            print(f"Loaded {report.inserted} historical price rows from the local CSV for {ticker}.")
        if snapshot is None or snapshot.date < latest_price:
            prior_snapshot_id = snapshot.id if snapshot is not None else None
            snapshot = await calculate_and_persist_snapshot(
                session,
                ticker,
                datetime.now(_CAIRO).date(),
            )
            if snapshot.id != prior_snapshot_id:
                created_snapshot_id = snapshot.id

        user_id = USER_ID
        rule = MonitoringRule(
            id=uuid4(),
            user_id=user_id,
            name="Temporary Explanation Agent smoke-test rule",
            ticker=ticker,
            rule_type="rsi_threshold",
            parameters={"rule_type": "rsi_threshold", "threshold": 30, "direction": "below"},
            is_active=True,
            cooldown_minutes=60,
        )
        alert = Alert(
            id=uuid4(),
            rule_id=rule.id,
            user_id=user_id,
            ticker=ticker,
            alert_type="rsi_threshold",
            severity="WARNING",
            reason="Temporary historical alert fixture for Explanation Agent smoke testing.",
            evidence={"test_fixture": True, "snapshot_date": snapshot.date.isoformat()},
            current_value=snapshot.rsi,
            threshold_value=30.0,
            created_at=datetime.combine(snapshot.date, time(12), tzinfo=_CAIRO),
        )
        # The alert has a foreign key to the rule; flush its parent first.
        session.add(rule)
        await session.flush()
        session.add(alert)
        await session.commit()

        return {
            "user_id": user_id,
            "recommendation_id": None,
            "rule_id": rule.id,
            "alert_id": alert.id,
            "imported_dates": imported_dates,
            "created_snapshot_id": created_snapshot_id,
            "snapshot_date": snapshot.date,
            "alert": AlertResponse.model_validate(alert).model_dump(mode="json"),
            "snapshot": TechnicalSnapshotRead.model_validate(snapshot).model_dump(mode="json"),
        }


async def _remove_fixtures(fixtures: dict) -> None:
    async with SessionLocal() as session:
        for model, key in (
            (Alert, "alert_id"),
            (MonitoringRule, "rule_id"),
        ):
            if fixtures.get(key) is None:
                continue
            row = await session.get(model, fixtures[key])
            if row is not None:
                await session.delete(row)
        recommendation_ids = [fixtures.get("recommendation_id"), *fixtures.get("additional_recommendation_ids", [])]
        for recommendation_id in recommendation_ids:
            if recommendation_id is None:
                continue
            row = await session.get(RecommendationLog, recommendation_id)
            if row is not None:
                await session.delete(row)
        if fixtures.get("created_snapshot_id") is not None:
            snapshot = await session.get(TechnicalSnapshot, fixtures["created_snapshot_id"])
            if snapshot is not None:
                await session.delete(snapshot)
        if fixtures.get("imported_dates"):
            await session.execute(
                delete(StockPrice).where(
                    StockPrice.ticker == TICKER,
                    StockPrice.source == _CSV_SOURCE,
                    StockPrice.date.in_(fixtures["imported_dates"]),
                )
            )
        await session.commit()


def _run_api_checks(fixtures: dict, ticker: str) -> None:
    headers = {"X-User-ID": str(fixtures["user_id"])}
    snapshot_date = fixtures["snapshot_date"].isoformat()
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=TIMEOUT) as client:
        routed_response = client.post(
            "/api/v1/explanations/question",
            json={
                "question": f"What RSI14 value was stored on {snapshot_date}?",
                "tickers": [ticker],
                "language": "en",
            },
        )
        routed = _check_response(routed_response, "descriptive question routing")
        if routed.get("intent") != "descriptive" or not routed.get("stock_qa"):
            fail(f"Descriptive question was not routed to Stock Q&A: {routed}")
        _check_disclaimer(routed["stock_qa"], "descriptive question routing")
        print(f"PASS question router: descriptive -> Stock Q&A ({routed['stock_qa'].get('status')})")

        engine_response = client.post(
            "/api/v1/recommendations",
            json={"ticker": ticker},
        )
        engine_result = _check_response(engine_response, "Recommendation Engine")
        recommendation_id = engine_result.get("recommendation_id")
        recommendation_payload = engine_result.get("result")
        if not recommendation_id or not recommendation_payload:
            fail("Recommendation Engine did not return its audit ID and result")
        fixtures["recommendation_id"] = UUID(recommendation_id)
        print(
            "PASS Recommendation Engine: "
            f"decision={recommendation_payload.get('decision')}, "
            f"price_status={recommendation_payload.get('data_quality', {}).get('price_status')}"
        )

        recommendation_response = client.post(
            "/api/v1/explanations/recommendation",
            json={
                "recommendation": recommendation_payload,
                "language": "en",
                "thread_id": "live-explanation-chat",
            },
        )
        recommendation = _check_response(recommendation_response, "recommendation explanation")
        if recommendation.get("decision") != recommendation_payload.get("decision"):
            fail("Recommendation explanation changed the recorded fixture decision")
        _check_disclaimer(recommendation, "recommendation explanation")
        print(f"PASS recommendation explanation: {recommendation.get('status')}")

        follow_up_response = client.post(
            "/api/v1/explanations/follow-up",
            json={
                "question": "Why was that result recorded?",
                "subject_type": "recommendation",
                "subject_id": str(fixtures["recommendation_id"]),
                "thread_id": "live-explanation-chat",
                "language": "en",
            },
        )
        follow_up = _check_response(follow_up_response, "follow-up")
        _check_disclaimer(follow_up, "follow-up")
        print(f"PASS follow-up: {follow_up.get('status')}")

        stock_response = client.post(
            "/api/v1/explanations/stock-qa",
            json={
                "question": (
                    f"Use get_technical_snapshot for ticker {ticker} with snapshot_date "
                    f"{snapshot_date}. Return JSON. What exact RSI14 value was stored? "
                    f"Copy its full precision, use the fact label exactly RSI14, state "
                    f"the date {snapshot_date}, and say the data is stale."
                ),
                "tickers": [ticker],
                "language": "en",
            },
        )
        stock = _check_response(stock_response, "Stock Q&A")
        _check_disclaimer(stock, "Stock Q&A")
        if stock.get("explanation_type") != "stock_qa":
            fail("Stock Q&A returned the wrong explanation type")
        if stock.get("data_date") != snapshot_date:
            fail(
                "Stock Q&A did not return the explicitly requested snapshot date: "
                f"expected {snapshot_date}, got {stock.get('data_date')}; "
                f"limitations={json.dumps(stock.get('limitations', []), ensure_ascii=True)}"
            )
        stock_facts = stock.get("facts") or []
        snapshot_payload = fixtures["snapshot"]
        indicator_values = snapshot_payload.get("indicators") or {}
        market_context = {
            "ticker": ticker,
            "snapshot_date": stock.get("data_date"),
            "data_status": stock.get("status"),
            "technical_values": {
                key: snapshot_payload.get(key)
                for key in (
                    "rsi", "sma_20", "sma_50", "atr", "setup_score",
                    "regime", "risk_label", "data_quality_status",
                )
                if snapshot_payload.get(key) is not None
            },
            "indicators": dict(list(indicator_values.items())[:16]),
            "verified_calendar_and_data_limitations": (stock.get("limitations") or [])[:5],
        }
        market_context_json = json.dumps(
            market_context, ensure_ascii=False, separators=(",", ":")
        )
        print(
            f"{'PASS' if stock_facts else 'WARN'} Stock Q&A exact-date lookup: "
            f"status={stock.get('status')}, data_date={stock.get('data_date')}, "
            f"facts={json.dumps(stock_facts, ensure_ascii=True)}, "
            f"limitations={json.dumps(stock.get('limitations') or [], ensure_ascii=True)}"
        )
        if not stock_facts:
            print("WARN Stock Q&A returned its safe fallback; no grounded fact was generated.")

        def ask_stock_question(question: str) -> dict:
            language = "ar" if re.search(r"[\u0600-\u06ff]", question) else "en"
            language_instruction = (
                "أجب باللغة العربية." if language == "ar" else "Answer in English."
            )
            prompt_prefix = (
                f"Use the stored snapshot for {ticker} on {snapshot_date}. "
                f"Use the snapshot tool for values and the glossary for definitions. "
                f"Return JSON. {language_instruction} Context: {market_context_json}. "
                f"Answer from retrieved facts, include freshness limitations, and "
                f"say if a requested value is missing. Question: "
            )
            prompt = prompt_prefix + question[: max(1, 3900 - len(prompt_prefix))]
            result = _check_response(
                client.post(
                    "/api/v1/explanations/stock-qa",
                    json={
                        "question": prompt,
                        "tickers": [ticker],
                        "language": language,
                        "max_tool_calls": 5,
                    },
                ),
                "TMG Stock Q&A scenario",
            )
            print(f"Agent ({result.get('status')}): {result.get('answer')}")
            if result.get("facts"):
                print("Verified facts: " + json.dumps(result["facts"], ensure_ascii=False))
            if result.get("limitations"):
                print("Data notes: " + "; ".join(result["limitations"]))
            return result

        alert_response = client.post(
            "/api/v1/explanations/alert",
            json={
                "alert": fixtures["alert"],
                "language": "en",
            },
        )
        alert = _check_response(alert_response, "alert explanation")
        _check_disclaimer(alert, "alert explanation")
        print(f"PASS alert explanation: {alert.get('status')}")

        print(
            "\nInteractive Explanation Agent chat is ready. "
                "Type 'demo' to run the three TMG questions, 'stock' to ask about CSV-backed technical data, "
            "'rec' to ask about the saved recommendation, or 'quit' to finish."
        )
        while True:
            try:
                mode = input("\nChoose stock / rec / quit: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if mode in {"quit", "q", "exit"}:
                break
            if mode not in {"stock", "rec", "demo"}:
                print("Enter demo, stock, rec, or quit.")
                continue
            if mode == "demo":
                if ticker != "TMGH.CA":
                    print("The TMG demo needs EXPLANATION_TICKER=TMGH; restart the script with that setting.")
                    continue
                print("\nQuestion 1: Give me an overview about the stock.")
                ask_stock_question("Give me an overview about the stock.")
                print(
                    "\nQuestion 2: What is the meaning of RSI and momentum, and "
                    "what is volume? Are they important for this stock?"
                )
                ask_stock_question(
                    "What is the meaning of RSI and momentum, and what is volume? "
                    "Are they important for this stock?"
                )
                question_three = (
                    "How does the stock's technical behavior look, and can I enter now?"
                )
                print(f"\nQuestion 3: {question_three}")
                routed = _check_response(
                    client.post(
                        "/api/v1/explanations/question",
                        json={"question": question_three, "tickers": [ticker], "language": "en"},
                    ),
                    "TMG entry question routing",
                )
                fixtures.setdefault("additional_recommendation_ids", []).extend(
                    UUID(item["recommendation_id"])
                    for item in routed.get("recommendations", [])
                    if item.get("recommendation_id")
                )
                if routed.get("stock_qa"):
                    stock_part = routed["stock_qa"]
                    print(
                        f"Technical answer ({stock_part.get('status')}): "
                        f"{stock_part.get('answer')}"
                    )
                    if stock_part.get("limitations"):
                        print("Technical data notes: " + "; ".join(stock_part["limitations"]))
                recommendations = routed.get("recommendations") or []
                if not recommendations:
                    print(
                        "The router returned no Recommendation Engine result. "
                        f"intent={routed.get('intent')}, clarification={routed.get('clarification')}"
                    )
                    continue
                recommendation_payload = recommendations[0]["result"]
                print(
                    "Recommendation Engine: "
                    f"decision={recommendation_payload.get('decision')}, "
                    f"reasons={json.dumps(recommendation_payload.get('reasons', []), ensure_ascii=False)}"
                )
                rec_explanation = _check_response(
                    client.post(
                        "/api/v1/explanations/recommendation",
                        json={
                            "recommendation": recommendation_payload,
                            "language": "en",
                            "thread_id": "tmg-three-question-demo",
                        },
                    ),
                    "TMG recommendation explanation",
                )
                print(
                    "Explanation Agent: "
                    f"{rec_explanation.get('summary')} {rec_explanation.get('explanation')}"
                )
                if rec_explanation.get("limitations"):
                    print("Recommendation notes: " + "; ".join(rec_explanation["limitations"]))
                continue
            question = input("Your question: ").strip()
            if not question:
                continue
            language = "ar" if re.search(r"[\u0600-\u06ff]", question) else "en"
            if mode == "stock":
                language_instruction = (
                    "أجب باللغة العربية." if language == "ar" else "Answer in English."
                )
                asks_definition = bool(
                    re.search(
                        r"\b(meaning|define|definition|what does)\b|يعني|معنى|عرّف|اشرح",
                        question,
                        re.IGNORECASE,
                    )
                )
                tool_instruction = (
                    "Use get_technical_snapshot for current stock state and indicator "
                    "values. Do not call the glossary unless the user asks for a "
                    "definition. For a trend question, read the stored regime field "
                    "and state whether it says trending, ranging, or transition. "
                    if not asks_definition
                    else "Use get_indicator_glossary for the requested definition. "
                    "If a current value is also requested, use get_technical_snapshot. "
                )
                prompt_prefix = (
                    f"{tool_instruction} Ticker {ticker}, snapshot date {snapshot_date}. "
                    f"Return JSON. {language_instruction} Snapshot context: "
                    f"{market_context_json}. Answer the user's question directly "
                    f"using only retrieved fields; say if a field is unavailable. "
                    f"Question: "
                )
                max_question_chars = max(1, 3900 - len(prompt_prefix))
                if len(question) > max_question_chars:
                    print(f"Question shortened to {max_question_chars} characters to fit the API limit.")
                prompt = prompt_prefix + question[:max_question_chars]
                response = client.post(
                    "/api/v1/explanations/stock-qa",
                    json={
                        "question": prompt,
                        "tickers": [ticker],
                        "language": language,
                        "max_tool_calls": 1 if not asks_definition else 2,
                    },
                )
                answer = _check_response(response, "interactive Stock Q&A")
                print(f"Agent ({answer.get('status')}): {answer.get('answer')}")
                if answer.get("facts"):
                    print("Verified facts: " + json.dumps(answer["facts"], ensure_ascii=False))
                elif answer.get("status") == "unavailable" or "reliable answer could not be formed" in answer.get("answer", "").lower():
                    print("The agent could not validate a grounded answer for this question.")
                if answer.get("limitations"):
                    print("Data notes: " + "; ".join(answer["limitations"]))
            else:
                language_instruction = (
                    "أجب باللغة العربية." if language == "ar" else "Answer in English."
                )
                context_sentence = (
                    f"بيانات اللقطة الفنية بتاريخ {snapshot_date} وحالة الحداثة وملاحظات "
                    f"تقويم العطلات: {market_context_json}. "
                    if language == "ar"
                    else f"Technical snapshot dated {snapshot_date}, freshness, and "
                    f"holiday-calendar notes: {market_context_json}. "
                )
                follow_up_prefix = f"{language_instruction} {context_sentence}"
                max_question_chars = max(1, 3900 - len(follow_up_prefix))
                if len(question) > max_question_chars:
                    print(f"Question shortened to {max_question_chars} characters to fit the API limit.")
                response = client.post(
                    "/api/v1/explanations/follow-up",
                    json={
                        "question": follow_up_prefix + question[:max_question_chars],
                        "subject_type": "recommendation",
                        "subject_id": str(fixtures["recommendation_id"]),
                        "thread_id": "live-explanation-chat",
                        "language": "en",
                    },
                )
                answer = _check_response(response, "interactive recommendation follow-up")
                print(f"Agent ({answer.get('status')}): {answer.get('explanation')}")
                if answer.get("limitations"):
                    print("Data notes: " + "; ".join(answer["limitations"]))


async def _main() -> None:
    if not TICKER:
        fail("EXPLANATION_TICKER must not be blank")
    fixtures = await _create_fixtures(TICKER)
    print(
        f"Using temporary test identity {fixtures['user_id']} and Technical Engine "
        f"snapshot {TICKER} on {fixtures['snapshot_date']} (no Investor Agent call)."
    )
    try:
        await asyncio.to_thread(_run_api_checks, fixtures, TICKER)
    finally:
        await _remove_fixtures(fixtures)
        print("Removed temporary CSV prices, snapshot, recommendation, alert, and rule rows.")
    print("All Explanation Agent live checks finished.")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    asyncio.run(_main())


if __name__ == "__main__":
    main()
