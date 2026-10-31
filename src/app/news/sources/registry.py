from app.news.sources.base import NewsSourceAdapter
from app.news.sources.mubasher import MubasherSource


class SourceRegistry:
    """Stores news source adapters by their unique source key."""

    def __init__(self) -> None:
        self._sources: dict[str, NewsSourceAdapter] = {}

    def register(self, source: NewsSourceAdapter) -> None:
        key = source.source_key.strip()

        if not key:
            raise ValueError("A news source must define a non-empty source_key.")

        if key in self._sources:
            raise ValueError(f"News source already registered: {key}")

        self._sources[key] = source

    def get(self, source_key: str) -> NewsSourceAdapter:
        try:
            return self._sources[source_key]
        except KeyError as exc:
            raise ValueError(f"Unknown news source: {source_key}") from exc

    def all(self) -> tuple[NewsSourceAdapter, ...]:
        return tuple(self._sources.values())


def create_default_registry() -> SourceRegistry:
    registry = SourceRegistry()
    registry.register(MubasherSource())
    return registry