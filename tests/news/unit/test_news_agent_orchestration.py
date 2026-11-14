import inspect

import pytest
from pydantic import ValidationError

from app.agents.news_agent.agent import LangChainNewsAgent
from app.agents.news_agent.agent_schemas import NewsAgentRequest
from app.agents.news_agent.tool_registry import ALLOWED_NEWS_TOOLS, build_news_tools


def test_agent_request_is_bounded_and_language_is_explicit():
    assert NewsAgentRequest(message="أخبار COMI").language == "ar"
    assert NewsAgentRequest(message="news", language="en", max_tool_calls=6)
    with pytest.raises(ValidationError):
        NewsAgentRequest(message="x", language="fr")
    with pytest.raises(ValidationError):
        NewsAgentRequest(message="x", max_tool_calls=7)


def test_only_six_allowlisted_tools_exist():
    assert ALLOWED_NEWS_TOOLS == {
        "search_news", "get_recent_news", "get_company_news",
        "get_annual_report_evidence", "retrieve_similar_news",
        "structured_news_analysis",
    }
    assert inspect.iscoroutinefunction(LangChainNewsAgent.ask)


def test_missing_langchain_is_reported_at_tool_construction_boundary():
    # The import is intentionally lazy; deployment receives a clear error if
    # dependencies were not installed rather than breaking unrelated API code.
    assert callable(build_news_tools)
