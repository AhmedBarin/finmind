"""Stable values shared by Explanation Agent components."""

EXPLANATION_SCHEMA_VERSION = "explanation.v1"

ARABIC_RISK_DISCLAIMER = (
    "هذا الشرح لأغراض المعلومات ودعم القرار فقط، وليس نصيحة مالية أو ضماناً للأرباح."
)
ENGLISH_RISK_DISCLAIMER = (
    "This explanation is for information and decision support only; it is not financial advice or a guarantee of profit."
)

RECOMMENDATION_TERMS = frozenset(
    {
        "buy",
        "sell",
        "hold",
        "avoid",
        "purchase",
        "شراء",
        "اشترِ",
        "اشتر",
        "بيع",
        "بع",
        "احتفظ",
        "تجنب",
        "أنصح بـ",
        "توصية",
    }
)
