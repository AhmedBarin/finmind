"""Static Arabic glossary for the indicators stored on technical snapshots.

Definitions describe what a field means; they carry no thresholds or advice so
they cannot be mistaken for a recommendation.
"""

from __future__ import annotations

from typing import TypedDict


class GlossaryEntry(TypedDict):
    name: str
    name_ar: str
    definition_ar: str


INDICATOR_GLOSSARY: dict[str, GlossaryEntry] = {
    "rsi": {
        "name": "RSI (14)",
        "name_ar": "مؤشر القوة النسبية",
        "definition_ar": "مؤشر زخم يقيس سرعة وحجم تغيرات السعر الأخيرة على مقياس من صفر إلى مئة.",
    },
    "sma_20": {
        "name": "SMA (20)",
        "name_ar": "المتوسط المتحرك البسيط لعشرين جلسة",
        "definition_ar": "متوسط سعر الإغلاق لآخر عشرين جلسة تداول، ويعكس الاتجاه قصير المدى.",
    },
    "sma_50": {
        "name": "SMA (50)",
        "name_ar": "المتوسط المتحرك البسيط لخمسين جلسة",
        "definition_ar": "متوسط سعر الإغلاق لآخر خمسين جلسة تداول، ويعكس الاتجاه متوسط المدى.",
    },
    "atr": {
        "name": "ATR (14)",
        "name_ar": "متوسط المدى الحقيقي",
        "definition_ar": "مقياس للتقلب يعبّر عن متوسط مدى حركة السعر اليومية بوحدة السعر نفسها.",
    },
    "setup_score": {
        "name": "Setup score",
        "name_ar": "درجة الإعداد الفني",
        "definition_ar": "درجة مركّبة يحسبها المحرك الفني من عائلات المؤشرات، وهي وصف للحالة الفنية وليست توصية.",
    },
    "regime": {
        "name": "Market regime",
        "name_ar": "حالة السوق",
        "definition_ar": "تصنيف لحالة السعر بناءً على مؤشر ADX: اتجاه واضح (trending) أو انتقالية (transition) أو تذبذب عرضي (ranging).",
    },
    "risk_label": {
        "name": "Risk label",
        "name_ar": "تصنيف المخاطر",
        "definition_ar": "تصنيف لمستوى التقلب التاريخي للسهم: منخفض أو متوسط أو مرتفع أو مرتفع جدًا.",
    },
    "data_quality_status": {
        "name": "Data quality status",
        "name_ar": "حالة جودة البيانات",
        "definition_ar": "حالة بيانات الأسعار المستخدمة في الحساب: صالحة أو قديمة أو تاريخ غير كافٍ أو عليها ملاحظات.",
    },
    "volume": {
        "name": "Volume",
        "name_ar": "حجم التداول",
        "definition_ar": "عدد الأسهم المتداولة خلال جلسة التداول.",
    },
    "adj_close": {
        "name": "Adjusted close",
        "name_ar": "سعر الإغلاق المعدّل",
        "definition_ar": "سعر الإغلاق بعد تعديله لأثر التوزيعات وتجزئة الأسهم.",
    },
}

# Words in a question that point at a glossary entry.
GLOSSARY_ALIASES: dict[str, tuple[str, ...]] = {
    "rsi": ("rsi", "القوة النسبية"),
    "sma_20": ("sma20", "sma 20", "sma_20", "متوسط 20", "المتوسط المتحرك"),
    "sma_50": ("sma50", "sma 50", "sma_50", "متوسط 50", "المتوسط المتحرك"),
    "atr": ("atr", "المدى الحقيقي", "التقلب"),
    "setup_score": ("setup", "درجة الإعداد"),
    "regime": ("regime", "حالة السوق", "الاتجاه"),
    "risk_label": ("risk", "المخاطر", "المخاطرة"),
    "volume": ("volume", "حجم التداول", "السيولة"),
}


def lookup(name: str) -> GlossaryEntry | None:
    return INDICATOR_GLOSSARY.get(name.strip().lower())


def terms_in_question(question: str) -> list[str]:
    lowered = question.lower()
    return [
        name
        for name, aliases in GLOSSARY_ALIASES.items()
        if any(alias in lowered for alias in aliases)
    ]
