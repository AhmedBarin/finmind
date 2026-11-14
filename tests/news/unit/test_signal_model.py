from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.news.models import NewsSignal


def test_news_signal_persists_direction_coverage_and_evidence_provenance():
    columns = set(NewsSignal.__table__.columns.keys())

    assert {
        "company_id",
        "window_start",
        "window_end",
        "signal_version",
        "aggregation_config_version",
        "input_hash",
        "direction",
        "article_count",
        "eligible_article_count",
        "coverage_status",
        "contributing_article_ids",
        "contributing_analysis_ids",
        "reason_codes",
        "limitations",
    } <= columns
    assert "news_score" not in columns
    assert "recommendation" not in columns
    assert "impact_score" not in columns


def test_news_signal_table_compiles_for_postgresql_with_idempotency_index():
    ddl = str(CreateTable(NewsSignal.__table__).compile(dialect=postgresql.dialect()))
    indexes = {
        index.name: str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for index in NewsSignal.__table__.indexes
    }

    assert "CREATE TABLE news_signals" in ddl
    assert "ck_news_signals_direction" in ddl
    assert "ck_news_signals_coverage_status" in ddl
    assert "uq_news_signals_company_config_input" in ddl
    assert "company_id, as_of" in indexes["ix_news_signals_company_as_of"]
