from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

STOP = {
    "the", "and", "for", "with", "from", "that", "this", "have", "has", "was", "were",
    "are", "been", "will", "its", "their", "about", "into", "over", "under", "than",
    "ltd", "limited", "private", "company", "india", "indian",
}


def parse_nse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "-", "—", "NA", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def indian(value: float, decimals: int = 0) -> str:
    neg = value < 0
    number = abs(value)
    raw = f"{number:.{decimals}f}"
    whole, dot, frac = raw.partition(".")
    if len(whole) <= 3:
        body = whole
    else:
        head, tail = whole[:-3], whole[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.append(head[-2:])
            head = head[:-2]
        if head:
            parts.append(head)
        body = ",".join(reversed(parts)) + "," + tail
    if decimals:
        body = f"{body}.{frac}"
    return f"-{body}" if neg else body


def format_pct(value: float | None) -> str | None:
    if value is None:
        return None
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{abs(value):.1f}%"


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100


def unspace(text: str) -> str:
    """Some annual reports extract as 'T h e'. Join runs of single letters."""
    tokens = (text or "").split()
    if not tokens:
        return text or ""
    singles = sum(1 for token in tokens if len(token) == 1 and token.isalpha())
    if singles < 12 or singles / len(tokens) < 0.35:
        return re.sub(r"\s+", " ", text or "").strip()
    out: list[str] = []
    buf: list[str] = []
    for token in tokens:
        if len(token) == 1 and token.isalpha():
            buf.append(token)
        else:
            if buf:
                out.append("".join(buf))
                buf = []
            out.append(token)
    if buf:
        out.append("".join(buf))
    return " ".join(out)


def sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    cleaned = re.sub(r"(\d)\s+(st|nd|rd|th)\b", r"\1\2", cleaned, flags=re.I)
    cleaned = re.sub(r"\b([A-Z])\.(?=\s|[A-Z])", r"\1§", cleaned)
    cleaned = re.sub(r"\b(Mr|Mrs|Ms|Dr|Shri|Smt|Rs|No|Fig)\.", r"\1§", cleaned)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [part.replace("§", ".").strip() for part in parts if part.strip()]


def one_line(text: str | None, fallback: str = "") -> str:
    """First useful sentence of an exchange blurb, with the boilerplate cut."""
    raw = re.sub(r"\s+", " ", text or "").strip()
    if not raw:
        return fallback
    raw = re.sub(
        r"^.*?\bhas (?:informed the Exchange (?:about|regarding|that)|submitted to the Exchange,?)\s*",
        "",
        raw,
        count=1,
        flags=re.I,
    )
    raw = re.sub(r"^(please note that|this is to inform( you)? that)\s*", "", raw, flags=re.I)
    raw = raw.strip(" -–—")
    if not raw:
        return fallback
    line = sentences(raw)[0] if sentences(raw) else raw
    if line and line[0].islower():
        line = line[0].upper() + line[1:]
    if len(line) > 220:
        line = line[:217].rstrip() + "…"
    return line


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2 and t not in STOP}


def norm_org(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(
        r"\b(limited|ltd|private|pvt|plc|inc|corp|corporation|company|co|the|of|and)\b",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def org_match(a: str, b: str) -> bool:
    left, right = norm_org(a), norm_org(b)
    if len(left) < 4 or len(right) < 4:
        return False
    return left in right or right in left


def shared_phrase(title: str, text: str) -> str | None:
    words = re.findall(r"[A-Za-z][A-Za-z&'-]+", title or "")
    words = [w for w in words if w.lower() not in {"head", "senior", "manager", "the", "and", "of"}]
    hay = (text or "").lower()
    for size in (3, 2):
        if len(words) < size:
            continue
        for i in range(len(words) - size + 1):
            phrase = " ".join(words[i : i + size])
            if phrase.lower() in hay and len(phrase) > 8:
                return phrase
    return None


def friendly_when(moment: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now(IST)
    local = moment.astimezone(IST)
    clock = local.strftime("%-I:%M%p").lower()
    if local.date() == now.astimezone(IST).date():
        return f"Today, {clock}"
    return f"{local.strftime('%-d %b')}, {clock}"
