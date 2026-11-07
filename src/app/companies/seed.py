import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.companies.catalog import EGX_COMPANIES
from app.companies.models import Company, CompanyAlias
from app.db.session import SessionLocal, engine
from app.news.linking import normalize_company_text


async def seed_companies() -> tuple[int, int]:
    companies_added = 0
    aliases_added = 0

    async with SessionLocal() as session:
        async with session.begin():
            for ticker, name_en in EGX_COMPANIES.items():
                company = await session.scalar(
                    select(Company).where(
                        Company.exchange == "EGX",
                        Company.ticker == ticker,
                    )
                )

                if company is None:
                    company = Company(
                        exchange="EGX",
                        ticker=ticker,
                        name_en=name_en,
                        is_active=True,
                    )
                    session.add(company)
                    await session.flush()
                    companies_added += 1
                elif company.name_en != name_en:
                    company.name_en = name_en

                aliases = (
                    (ticker, "und", "ticker"),
                    (name_en, "en", "short_name"),
                )

                for alias_text, language, alias_type in aliases:
                    alias_normalized = normalize_company_text(alias_text)

                    existing_alias = await session.scalar(
                        select(CompanyAlias).where(
                            CompanyAlias.company_id == company.id,
                            CompanyAlias.alias_normalized == alias_normalized,
                        )
                    )

                    if existing_alias is not None:
                        continue

                    session.add(
                        CompanyAlias(
                            company_id=company.id,
                            alias_text=alias_text,
                            alias_normalized=alias_normalized,
                            language=language,
                            alias_type=alias_type,
                            verification_status="verified",
                            verified_at=datetime.now(timezone.utc),
                        )
                    )
                    aliases_added += 1

    return companies_added, aliases_added


async def main() -> None:
    try:
        companies_added, aliases_added = await seed_companies()
        print(f"New companies added: {companies_added}")
        print(f"New aliases added: {aliases_added}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())