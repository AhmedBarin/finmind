from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal
from uuid import UUID


_ARABIC_MARKS = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED]")
_ARABIC_LETTER_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
    }
)


@dataclass(frozen=True, slots=True)
class CompanyAlias:
    company_id: UUID
    ticker: str
    alias_text: str


@dataclass(frozen=True, slots=True)
class CompanyMatch:
    company_id: UUID
    ticker: str
    matched_alias: str
    status: Literal["confirmed", "ambiguous", "candidate"]


def normalize_company_text(value: str) -> str:
    """Normalize Arabic/English text for exact alias matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("ـ", "")
    normalized = _ARABIC_MARKS.sub("", normalized)
    normalized = normalized.translate(_ARABIC_LETTER_MAP)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _contains_whole_alias(text: str, alias: str) -> bool:
    """Return True only when the complete alias appears as a phrase/token."""
    pattern = re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)")
    return pattern.search(text) is not None


def match_companies(
    text: str,
    aliases: list[CompanyAlias],
    *,
    context_tickers: list[str] | None = None,
) -> list[CompanyMatch]:
    """Find companies from exact text aliases and optional source context."""
    normalized_text = normalize_company_text(text)

    aliases_by_phrase: dict[str, dict[UUID, CompanyAlias]] = {}

    for alias in aliases:
        normalized_alias = normalize_company_text(alias.alias_text)
        if not normalized_alias:
            continue

        company_aliases = aliases_by_phrase.setdefault(normalized_alias, {})
        current = company_aliases.get(alias.company_id)

        if current is None or alias.alias_text < current.alias_text:
            company_aliases[alias.company_id] = alias

    matches_by_company: dict[
        UUID, list[tuple[CompanyAlias, Literal["confirmed", "ambiguous"]]]
    ] = {}

    for normalized_alias, company_aliases in aliases_by_phrase.items():
        if not _contains_whole_alias(normalized_text, normalized_alias):
            continue

        status: Literal["confirmed", "ambiguous"] = (
            "confirmed" if len(company_aliases) == 1 else "ambiguous"
        )

        for company_id, alias in company_aliases.items():
            matches_by_company.setdefault(company_id, []).append((alias, status))

    results: list[CompanyMatch] = []

    for company_id, company_matches in matches_by_company.items():
        status: Literal["confirmed", "ambiguous"] = (
            "confirmed"
            if any(match_status == "confirmed" for _, match_status in company_matches)
            else "ambiguous"
        )

        selected_alias = max(
            (alias for alias, _ in company_matches),
            key=lambda item: (
                len(normalize_company_text(item.alias_text)),
                item.alias_text,
            ),
        )

        results.append(
            CompanyMatch(
                company_id=company_id,
                ticker=selected_alias.ticker,
                matched_alias=selected_alias.alias_text,
                status=status,
            )
        )

    # Build this after the loop so it also exists when there are no text matches.
    matches_by_id = {match.company_id: match for match in results}

    ticker_aliases = {
        normalize_company_text(alias.ticker): alias
        for alias in aliases
        if normalize_company_text(alias.alias_text)
        == normalize_company_text(alias.ticker)
    }

    for ticker in context_tickers or []:
        alias = ticker_aliases.get(normalize_company_text(ticker))
        if alias is None or alias.company_id in matches_by_id:
            continue

        matches_by_id[alias.company_id] = CompanyMatch(
            company_id=alias.company_id,
            ticker=alias.ticker,
            matched_alias=f"Mubasher listing ticker: {alias.ticker}",
            status="candidate",
        )

    return sorted(
        matches_by_id.values(),
        key=lambda item: (item.ticker, str(item.company_id)),
    )