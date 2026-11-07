from app.technical_analysis.models import TechnicalSnapshot


def test_snapshot_exposes_monitoring_signal_fields() -> None:
    columns = TechnicalSnapshot.__table__.columns

    assert {"ticker", "date", "calculated_at"} <= set(columns.keys())
    assert {"rsi", "sma_20", "sma_50", "atr"} <= set(columns.keys())
    assert "setup_score" in columns


def test_snapshot_is_versioned_per_ticker_date_config_and_input() -> None:
    constraints = [
        constraint
        for constraint in TechnicalSnapshot.__table__.constraints
        if constraint.name == "uq_technical_snapshots_ticker_date_config_input"
    ]

    assert len(constraints) == 1
    assert [column.name for column in constraints[0].columns] == [
        "ticker",
        "date",
        "config_version",
        "input_hash",
    ]
