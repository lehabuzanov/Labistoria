from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from difflib import SequenceMatcher
from typing import Iterable


XML_DECL_RE = re.compile(r"<\?xml[^>]*encoding=[\"']([^\"']+)[\"']", re.IGNORECASE)
NS_XML = "http://www.w3.org/XML/1998/namespace"


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def xml_id(attrs: dict[str, str]) -> str | None:
    return attrs.get(f"{{{NS_XML}}}id") or attrs.get("xml:id")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def strip_combining(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_surface(text: str) -> str:
    value = strip_combining(text.lower())
    substitutions = {
        "ѡ": "о",
        "ѻ": "о",
        "ѿ": "от",
        "ꙋ": "у",
        "оу": "у",
        "ѵ": "и",
        "і": "и",
        "ї": "и",
        "ѣ": "е",
        "ѫ": "у",
        "ѭ": "ю",
        "ꙗ": "я",
        "ѥ": "е",
        "є": "е",
        "ѕ": "з",
        "҃": "",
        "҇": "",
        "꙯": "",
        "ⷭ": "",
        "ⷮ": "",
        "ⷬ": "",
        "ⷯ": "",
        "ⷪ": "",
        "ⷢ": "",
        "ⷠ": "",
    }
    for src, target in substitutions.items():
        value = value.replace(src, target)
    value = re.sub(r"[^0-9a-zа-я]+", "", value)
    return value


def phonetic_key(text: str) -> str:
    value = normalize_surface(text)
    value = (
        value.replace("о", "a")
        .replace("е", "i")
        .replace("ѣ", "i")
        .replace("я", "а")
        .replace("ю", "у")
        .replace("ь", "")
        .replace("ъ", "")
    )
    return value


def safe_int(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def similarity_ratio(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def declared_xml_encoding(text: str) -> str | None:
    match = XML_DECL_RE.search(text[:200])
    return match.group(1) if match else None


def collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def ordered_unique(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

