from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timezone


def now() -> datetime:
    """Naive UTC timestamp (portable across SQLite and Postgres)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today() -> date:
    return now().date()


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def norm_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"[^a-z0-9+ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def fingerprint(company: str, title: str, posting_id: str | None, url: str | None) -> str:
    """Stable dedup key. Posting ID wins when present, then URL, then company+title."""
    if posting_id:
        basis = f"{slugify(company)}|id|{posting_id}"
    elif url:
        basis = f"{slugify(company)}|url|{re.sub(r'[?#].*$', '', url.strip().lower())}"
    else:
        basis = f"{slugify(company)}|title|{norm_title(title)}"
    return hashlib.sha256(basis.encode()).hexdigest()[:32]


def clean_dashes(text: str) -> str:
    """User preference: no em dashes. Em dashes become commas; en dashes become plain hyphens."""
    text = re.sub(r"\s*\u2014\s*", ", ", text)
    return text.replace("\u2013", "-")
