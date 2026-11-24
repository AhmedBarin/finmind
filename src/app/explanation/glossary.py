"""Bilingual, descriptive definitions for technical indicators.

Definitions explain what a stored indicator represents. They do not interpret
current market conditions or provide an investment recommendation.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field


class IndicatorDefinition(BaseModel):
    """Arabic and English explanation for one glossary entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    aliases: tuple[str, ...] = ()
    explanation_ar: str = Field(min_length=1, max_length=1000)
    explanation_en: str = Field(min_length=1, max_length=1000)
    note_ar: str | None = Field(default=None, max_length=500)
    note_en: str | None = Field(default=None, max_length=500)


_DEFINITIONS = (
    IndicatorDefinition(
        name="RSI14",
        aliases=("RSI", "RSI 14", "RELATIVE STRENGTH INDEX"),
        explanation_ar=(
            "مؤشر الزخم النسبي لفترة 14 وحدة. يقارن متوسط المكاسب بمتوسط الخسائر "
            "ويعرض قراءة بين 0 و100؛ وهو وصف للزخم وليس دليلاً منفرداً على اتجاه السعر."
        ),
        explanation_en=(
            "The 14-period Relative Strength Index compares average gains with "
            "average losses and produces a reading from 0 to 100. It describes "
            "momentum and does not determine price direction on its own."
        ),
    ),
    IndicatorDefinition(
        name="SMA20",
        aliases=("SMA 20", "20-DAY SMA", "20 DAY MOVING AVERAGE"),
        explanation_ar="المتوسط الحسابي لأسعار الإغلاق خلال آخر 20 فترة.",
        explanation_en="The arithmetic average of closing prices over the latest 20 periods.",
    ),
    IndicatorDefinition(
        name="SMA50",
        aliases=("SMA 50", "50-DAY SMA", "50 DAY MOVING AVERAGE"),
        explanation_ar="المتوسط الحسابي لأسعار الإغلاق خلال آخر 50 فترة.",
        explanation_en="The arithmetic average of closing prices over the latest 50 periods.",
    ),
    IndicatorDefinition(
        name="SMA200",
        aliases=("SMA 200", "200-DAY SMA", "200 DAY MOVING AVERAGE"),
        explanation_ar="المتوسط الحسابي لأسعار الإغلاق خلال آخر 200 فترة.",
        explanation_en="The arithmetic average of closing prices over the latest 200 periods.",
    ),
    IndicatorDefinition(
        name="MACD",
        aliases=("MOVING AVERAGE CONVERGENCE DIVERGENCE",),
        explanation_ar=(
            "مؤشر يتكون عادةً من الفرق بين متوسطين أسيين للأسعار وخط إشارة، "
            "ويصف تغير الزخم والعلاقة بين المتوسطين."
        ),
        explanation_en=(
            "An indicator commonly formed from the difference between two "
            "exponential price averages and a signal line; it describes momentum "
            "and the relationship between those averages."
        ),
    ),
    IndicatorDefinition(
        name="ATR14",
        aliases=("ATR", "ATR 14", "AVERAGE TRUE RANGE"),
        explanation_ar=(
            "متوسط المدى الحقيقي لفترة 14 وحدة، ويصف مقدار حركة السعر المعتادة "
            "مع احتساب الفجوات السعرية. لا يحدد اتجاه الحركة."
        ),
        explanation_en=(
            "The 14-period Average True Range describes typical price movement "
            "while accounting for gaps. It does not indicate the direction of movement."
        ),
    ),
    IndicatorDefinition(
        name="ATR%",
        aliases=("ATR PERCENT", "ATR PCT", "ATR PERCENTAGE"),
        explanation_ar=(
            "قيمة ATR معبّراً عنها كنسبة مئوية من السعر وفق طريقة الحساب المعتمدة "
            "في النظام؛ وتُستخدم لوصف التقلب النسبي."
        ),
        explanation_en=(
            "ATR expressed as a percentage of price under the system's configured "
            "calculation; it describes relative volatility."
        ),
    ),
    IndicatorDefinition(
        name="ADX14",
        aliases=("ADX", "ADX 14", "AVERAGE DIRECTIONAL INDEX"),
        explanation_ar=(
            "مؤشر متوسط الاتجاه لفترة 14 وحدة، ويصف قوة الاتجاه دون تحديد ما إذا "
            "كان صاعداً أم هابطاً."
        ),
        explanation_en=(
            "The 14-period Average Directional Index describes trend strength "
            "without indicating whether the trend is upward or downward."
        ),
    ),
    IndicatorDefinition(
        name="Bollinger Bands",
        aliases=("BOLLINGER", "BOLLINGER BANDS", "BB"),
        explanation_ar=(
            "نطاقات حول متوسط متحرك، يتحدد عرضها عادةً بتقلب السعر. تصف النطاقات "
            "موقع السعر وتقلبه بالنسبة للفترة المستخدمة."
        ),
        explanation_en=(
            "Bands around a moving average whose width is commonly based on price "
            "volatility. They describe price position and volatility for the selected period."
        ),
    ),
    IndicatorDefinition(
        name="Support/Resistance",
        aliases=("SUPPORT", "RESISTANCE", "SUPPORT AND RESISTANCE", "S/R"),
        explanation_ar=(
            "مناطق سعرية تاريخية قد يظهر قربها اهتمام بالشراء أو البيع. هي تقديرات "
            "مبنية على البيانات السابقة وليست حدوداً مضمونة للسعر."
        ),
        explanation_en=(
            "Historical price areas where buying or selling interest may appear. "
            "They are estimates based on past data, not guaranteed price boundaries."
        ),
    ),
    IndicatorDefinition(
        name="Volume Ratio",
        aliases=("VOLUME RATIO", "VOLUME-RATIO", "VOL RATIO"),
        explanation_ar=(
            "نسبة حجم التداول إلى مرجع الحجم الذي يستخدمه النظام، مثل متوسط حجم "
            "فترة سابقة؛ وتوضح كيف يقارن الحجم الحالي بذلك المرجع."
        ),
        explanation_en=(
            "Trading volume divided by the reference volume used by the system, "
            "such as a prior-period average; it shows how current volume compares "
            "with that reference."
        ),
    ),
    IndicatorDefinition(
        name="Setup Score",
        aliases=("SETUP SCORE", "TECHNICAL SETUP SCORE"),
        explanation_ar=(
            "درجة مركبة تلخص نتائج عائلات المؤشرات الفنية وفق أوزان وقواعد النظام. "
            "تعكس توافق الإشارات المحسوبة ولا تمثل احتمال الربح."
        ),
        explanation_en=(
            "A composite score summarizing technical indicator families under the "
            "system's weights and rules. It reflects alignment of calculated signals "
            "and is not a probability of profit."
        ),
        note_ar="درجة الإعداد ليست احتمالاً للربح ولا توصية استثمارية.",
        note_en="Setup score is not a probability of profit or an investment recommendation.",
    ),
)


def _normalize_name(value: str) -> str:
    """Normalize case and separators while preserving Arabic letters."""
    return re.sub(r"[\s_\-]+", " ", value.strip()).casefold()


_LOOKUP = {
    _normalize_name(alias): definition
    for definition in _DEFINITIONS
    for alias in (definition.name, *definition.aliases)
}


def get_indicator_glossary(name: str) -> IndicatorDefinition | None:
    """Return a bilingual definition, or ``None`` when the name is unknown."""
    if not isinstance(name, str) or not name.strip():
        return None
    return _LOOKUP.get(_normalize_name(name))


def list_indicator_definitions() -> tuple[IndicatorDefinition, ...]:
    """Return all canonical glossary entries in their stable display order."""
    return _DEFINITIONS
