from abc import ABC, abstractmethod
from datetime import datetime

from app.news.schemas import FetchedArticle


class NewsSourceAdapter(ABC):
    """Common interface implemented by each news source adapter."""

    source_key: str
    name: str
    base_url: str
    source_type: str
    content_policy: str

    @abstractmethod
    async def fetch_articles(
        self,
        *,
        since: datetime | None = None,
    ) -> list[FetchedArticle]:
        """Fetch and normalize articles published after the given timestamp."""
        raise NotImplementedError