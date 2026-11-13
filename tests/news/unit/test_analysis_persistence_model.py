from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.news.models import NewsAnalysis


def test_news_analysis_table_has_versioned_provenance_and_evidence_fields():
    columns = set(NewsAnalysis.__table__.columns.keys())

    assert {
        "article_id",
        "company_id",
        "analysis_version",
        "schema_version",
        "model_provider",
        "model_name",
        "prompt_version",
        "taxonomy_version",
        "pipeline_version",
        "event_type",
        "direction",
        "relevance_score",
        "novelty_score",
        "classification_confidence",
        "evidence_spans",
        "requires_human_review",
    } <= columns
    assert "impact_score" not in columns
    assert "recommendation" not in columns


def test_news_analysis_table_compiles_for_postgresql():
    ddl = str(
        CreateTable(NewsAnalysis.__table__).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "CREATE TABLE news_analyses" in ddl
    assert "REFERENCES news_articles (id) ON DELETE CASCADE" in ddl
    assert "REFERENCES companies (id) ON DELETE SET NULL" in ddl
    assert "ck_news_analyses_direction" in ddl
    assert "ck_news_analyses_event_type" in ddl


def test_partial_unique_indexes_separate_linked_and_unlinked_analyses():
    indexes = {
        index.name: str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for index in NewsAnalysis.__table__.indexes
    }

    company_index = indexes["uq_news_analyses_article_company_version"]
    article_index = indexes["uq_news_analyses_article_only_version"]

    assert "UNIQUE" in company_index
    assert "article_id, company_id, analysis_version" in company_index
    assert "WHERE company_id IS NOT NULL" in company_index
    assert "UNIQUE" in article_index
    assert "article_id, analysis_version" in article_index
    assert "WHERE company_id IS NULL" in article_index
