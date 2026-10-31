import hashlib
import re


class NewsProcessor:
    """Cleans article text and prepares searchable fields."""

    @staticmethod
    def clean_body(body: str | None) -> str | None:
        if not body:
            return None

        body = body.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")

        paragraphs = []
        for paragraph in body.split("\n"):
            cleaned = re.sub(r"[ \t]+", " ", paragraph).strip()
            if cleaned:
                paragraphs.append(cleaned)

        return "\n\n".join(paragraphs) or None

    @staticmethod
    def normalize_title(title: str) -> str:
        cleaned = re.sub(r"\s+", " ", title).strip()
        return cleaned.casefold()

    @staticmethod
    def make_excerpt(body_cleaned: str | None, max_length: int = 500) -> str | None:
        if not body_cleaned:
            return None

        if len(body_cleaned) <= max_length:
            return body_cleaned

        excerpt = body_cleaned[: max_length - 1].rsplit(" ", maxsplit=1)[0]
        return f"{excerpt}…" if excerpt else f"{body_cleaned[: max_length - 1]}…"

    @staticmethod
    def content_hash(body_cleaned: str | None) -> str | None:
        if not body_cleaned:
            return None

        return hashlib.sha256(body_cleaned.encode("utf-8")).hexdigest()