"""Step 3 – Schema validation tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.monitoring.schemas import (
    AlertAcknowledgeResponse,
    AlertResponse,
    AlertSeverity,
    Direction,
    EvaluationResult,
    MarketDataPoint,
    PriceMACrossParams,
    RSIThresholdParams,
    RuleCreateRequest,
    RuleResponse,
    RuleType,
    RuleUpdateRequest,
    ScoreChangeParams,
    TechnicalSignals,
    VolatilityThresholdParams,
)

# ── RSIThresholdParams ─────────────────────────────────────────────────


class TestRSIThresholdParams:
    def test_valid(self):
        p = RSIThresholdParams(threshold=70, direction=Direction.above)
        assert p.rule_type == RuleType.rsi_threshold
        assert p.threshold == 70
        assert p.direction == Direction.above

    def test_threshold_above_100_rejected(self):
        with pytest.raises(ValidationError):
            RSIThresholdParams(threshold=100, direction=Direction.above)

    def test_threshold_zero_rejected(self):
        with pytest.raises(ValidationError):
            RSIThresholdParams(threshold=0, direction=Direction.below)

    def test_threshold_negative_rejected(self):
        with pytest.raises(ValidationError):
            RSIThresholdParams(threshold=-5, direction=Direction.below)


# ── PriceMACrossParams ─────────────────────────────────────────────────


class TestPriceMACrossParams:
    def test_valid_20(self):
        p = PriceMACrossParams(ma_period=20, direction=Direction.above)
        assert p.rule_type == RuleType.price_ma_cross
        assert p.ma_period == 20

    def test_valid_50(self):
        p = PriceMACrossParams(ma_period=50, direction=Direction.below)
        assert p.ma_period == 50


# ── VolatilityThresholdParams ──────────────────────────────────────────


class TestVolatilityThresholdParams:
    def test_valid(self):
        p = VolatilityThresholdParams(atr_pct_threshold=2.5)
        assert p.rule_type == RuleType.volatility_threshold
        assert p.atr_pct_threshold == 2.5

    def test_zero_rejected(self):
        with pytest.raises(ValidationError):
            VolatilityThresholdParams(atr_pct_threshold=0)

    def test_negative_rejected(self):
        with pytest.raises(ValidationError):
            VolatilityThresholdParams(atr_pct_threshold=-1)


# ── ScoreChangeParams ─────────────────────────────────────────────────


class TestScoreChangeParams:
    def test_valid_with_direction(self):
        p = ScoreChangeParams(delta_threshold=5, direction=Direction.below)
        assert p.rule_type == RuleType.score_change
        assert p.direction == Direction.below

    def test_valid_without_direction(self):
        p = ScoreChangeParams(delta_threshold=3)
        assert p.direction is None

    def test_negative_delta_rejected(self):
        with pytest.raises(ValidationError):
            ScoreChangeParams(delta_threshold=-1)


# ── Discriminated Union via RuleCreateRequest ──────────────────────────


class TestRuleCreateRequest:
    def test_rsi_discriminator(self):
        req = RuleCreateRequest(
            name="High RSI",
            ticker="AAPL",
            parameters={
                "rule_type": "rsi_threshold",
                "threshold": 70,
                "direction": "above",
            },
        )
        assert isinstance(req.parameters, RSIThresholdParams)

    def test_price_ma_discriminator(self):
        req = RuleCreateRequest(
            name="SMA Cross",
            ticker="MSFT",
            parameters={
                "rule_type": "price_ma_cross",
                "ma_period": 50,
                "direction": "below",
            },
        )
        assert isinstance(req.parameters, PriceMACrossParams)

    def test_volatility_discriminator(self):
        req = RuleCreateRequest(
            name="Vol Spike",
            ticker="TSLA",
            parameters={
                "rule_type": "volatility_threshold",
                "atr_pct_threshold": 3.0,
            },
        )
        assert isinstance(req.parameters, VolatilityThresholdParams)

    def test_score_discriminator(self):
        req = RuleCreateRequest(
            name="Score Drop",
            ticker="GOOG",
            parameters={
                "rule_type": "score_change",
                "delta_threshold": 10,
            },
        )
        assert isinstance(req.parameters, ScoreChangeParams)

    def test_invalid_rule_type_rejected(self):
        with pytest.raises(ValidationError):
            RuleCreateRequest(
                name="Bad",
                ticker="X",
                parameters={
                    "rule_type": "unknown",
                    "threshold": 50,
                },
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            RuleCreateRequest(
                name="",
                ticker="AAPL",
                parameters={
                    "rule_type": "rsi_threshold",
                    "threshold": 50,
                    "direction": "above",
                },
            )


# ── RuleUpdateRequest ──────────────────────────────────────────────────


class TestRuleUpdateRequest:
    def test_partial_update(self):
        req = RuleUpdateRequest(name="Renamed")
        assert req.name == "Renamed"
        assert req.parameters is None
        assert req.is_active is None

    def test_update_parameters(self):
        req = RuleUpdateRequest(
            parameters={
                "rule_type": "rsi_threshold",
                "threshold": 30,
                "direction": "below",
            },
        )
        assert isinstance(req.parameters, RSIThresholdParams)


# ── RuleResponse ───────────────────────────────────────────────────────


class TestRuleResponse:
    def test_round_trip(self):
        now = datetime.now(tz=UTC)
        uid = uuid4()
        rid = uuid4()
        resp = RuleResponse(
            id=rid,
            user_id=uid,
            name="Test",
            ticker="AAPL",
            rule_type=RuleType.rsi_threshold,
            parameters={
                "rule_type": "rsi_threshold",
                "threshold": 70,
                "direction": "above",
            },
            is_active=True,
            cooldown_minutes=60,
            created_at=now,
            updated_at=now,
        )
        data = resp.model_dump()
        assert data["id"] == rid
        assert data["deactivated_at"] is None

    def test_json_round_trip(self):
        now = datetime.now(tz=UTC)
        resp = RuleResponse(
            id=uuid4(),
            user_id=uuid4(),
            name="Test",
            ticker="AAPL",
            rule_type=RuleType.rsi_threshold,
            parameters={"threshold": 70},
            is_active=True,
            cooldown_minutes=60,
            created_at=now,
            updated_at=now,
        )
        json_str = resp.model_dump_json()
        rebuilt = RuleResponse.model_validate_json(json_str)
        assert rebuilt.name == "Test"


# ── AlertResponse & AlertAcknowledgeResponse ───────────────────────────


class TestAlertSchemas:
    def test_alert_response(self):
        now = datetime.now(tz=UTC)
        resp = AlertResponse(
            id=uuid4(),
            rule_id=uuid4(),
            user_id=uuid4(),
            ticker="AAPL",
            alert_type="rsi_threshold",
            severity=AlertSeverity.WARNING,
            reason="RSI crossed 70",
            evidence={"rsi": 72.3},
            current_value=72.3,
            threshold_value=70.0,
            created_at=now,
        )
        assert resp.severity == AlertSeverity.WARNING
        assert resp.acknowledged_at is None

    def test_alert_acknowledge_response(self):
        now = datetime.now(tz=UTC)
        resp = AlertAcknowledgeResponse(id=uuid4(), acknowledged_at=now)
        assert resp.acknowledged_at == now

    def test_severity_enum_values(self):
        assert AlertSeverity.INFO.value == "INFO"
        assert AlertSeverity.WARNING.value == "WARNING"
        assert AlertSeverity.CRITICAL.value == "CRITICAL"


# ── MarketDataPoint ───────────────────────────────────────────────────


class TestMarketDataPoint:
    def test_valid(self):
        mdp = MarketDataPoint(
            ticker="AAPL",
            date=date(2024, 1, 15),
            open=150.0,
            high=155.0,
            low=149.0,
            close=154.0,
            volume=1_000_000,
            updated_at=datetime.now(tz=UTC),
        )
        assert mdp.ticker == "AAPL"
        assert mdp.volume == 1_000_000


# ── TechnicalSignals ──────────────────────────────────────────────────


class TestTechnicalSignals:
    def test_all_fields(self):
        ts = TechnicalSignals(
            ticker="AAPL",
            date=date(2024, 1, 15),
            rsi=65.3,
            sma_20=150.0,
            sma_50=148.0,
            atr=3.2,
            composite_score=72.0,
            calculated_at=datetime.now(tz=UTC),
        )
        assert ts.rsi == 65.3
        assert ts.sma_20 == 150.0
        assert ts.composite_score == 72.0

    def test_optional_fields_default_none(self):
        ts = TechnicalSignals(
            ticker="AAPL",
            date=date(2024, 1, 15),
            calculated_at=datetime.now(tz=UTC),
        )
        assert ts.rsi is None
        assert ts.sma_20 is None
        assert ts.sma_50 is None
        assert ts.atr is None
        assert ts.composite_score is None


# ── EvaluationResult ──────────────────────────────────────────────────


class TestEvaluationResult:
    def test_triggered_result(self):
        er = EvaluationResult(
            triggered=True,
            reason="RSI crossed threshold",
            current_value=72.3,
            threshold_value=70.0,
            evidence={"rsi": 72.3, "direction": "above"},
        )
        assert er.triggered is True
        assert er.error is False
        assert er.error_message is None

    def test_error_result(self):
        er = EvaluationResult(
            triggered=False,
            reason="Evaluation failed",
            error=True,
            error_message="Data not available",
        )
        assert er.error is True
        assert er.current_value is None

    def test_defaults(self):
        er = EvaluationResult(triggered=False, reason="No trigger")
        assert er.evidence == {}
        assert er.error is False
