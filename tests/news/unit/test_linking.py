from uuid import UUID

from app.news.linking import CompanyAlias, match_companies


COMPANY_COMI = UUID("00000000-0000-0000-0000-000000000001")
COMPANY_SWDY = UUID("00000000-0000-0000-0000-000000000002")
COMPANY_ABUK = UUID("00000000-0000-0000-0000-000000000003")


def test_matches_exact_ticker_case_insensitively():
    aliases = [
        CompanyAlias(
            company_id=COMPANY_COMI,
            ticker="COMI",
            alias_text="COMI",
        )
    ]

    matches = match_companies("COMI shares rose today.", aliases)

    assert len(matches) == 1
    assert matches[0].company_id == COMPANY_COMI
    assert matches[0].ticker == "COMI"
    assert matches[0].status == "confirmed"


def test_matches_arabic_alias_after_normalization():
    aliases = [
        CompanyAlias(
            company_id=COMPANY_ABUK,
            ticker="ABUK",
            alias_text="ابو قير للاسمدة",
        )
    ]

    matches = match_companies("أَبُو قير للأسمدة تعلن نتائجها.", aliases)

    assert len(matches) == 1
    assert matches[0].company_id == COMPANY_ABUK
    assert matches[0].status == "confirmed"


def test_does_not_match_ticker_inside_another_word():
    aliases = [
        CompanyAlias(
            company_id=COMPANY_COMI,
            ticker="COMI",
            alias_text="COMI",
        )
    ]

    matches = match_companies("XCOMIY reported new results.", aliases)

    assert matches == []


def test_marks_shared_alias_as_ambiguous():
    aliases = [
        CompanyAlias(
            company_id=COMPANY_COMI,
            ticker="COMI",
            alias_text="Nile",
        ),
        CompanyAlias(
            company_id=COMPANY_SWDY,
            ticker="SWDY",
            alias_text="Nile",
        ),
    ]

    matches = match_companies("Nile announced a new project.", aliases)

    assert {match.ticker for match in matches} == {"COMI", "SWDY"}
    assert all(match.status == "ambiguous" for match in matches)


def test_returns_multiple_distinct_companies_mentioned_in_one_article():
    aliases = [
        CompanyAlias(
            company_id=COMPANY_COMI,
            ticker="COMI",
            alias_text="COMI",
        ),
        CompanyAlias(
            company_id=COMPANY_SWDY,
            ticker="SWDY",
            alias_text="SWDY",
        ),
    ]

    matches = match_companies(
        "COMI and SWDY announced separate updates.",
        aliases,
    )

    assert {match.ticker for match in matches} == {"COMI", "SWDY"}
    assert all(match.status == "confirmed" for match in matches)


def test_does_not_return_duplicate_match_for_duplicate_alias_rows():
    aliases = [
        CompanyAlias(
            company_id=COMPANY_COMI,
            ticker="COMI",
            alias_text="CIB",
        ),
        CompanyAlias(
            company_id=COMPANY_COMI,
            ticker="COMI",
            alias_text="CIB",
        ),
    ]

    matches = match_companies("CIB announced its results.", aliases)

    assert len(matches) == 1
    assert matches[0].ticker == "COMI"

def test_mubasher_listing_ticker_creates_candidate_link():
    aliases = [
        CompanyAlias(
            company_id=COMPANY_COMI,
            ticker="COMI",
            alias_text="COMI",
        )
    ]

    matches = match_companies(
        "عنوان خبر عربي",
        aliases,
        context_tickers=["COMI"],
    )

    assert len(matches) == 1
    assert matches[0].ticker == "COMI"
    assert matches[0].status == "candidate"