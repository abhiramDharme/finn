from __future__ import annotations

import re

from finn.textutil import sentences

FORWARD = re.compile(
    r"\b(guidance|outlook|we expect|expect(?:s|ed)? to|we anticipate|aim to|we target|"
    r"on track to|going forward|next (?:quarter|year)|maintain our|likely to)\b",
    re.I,
)
PAST = re.compile(r"\b(grew|reported|stood at|came in|delivered|was up|were up)\b", re.I)
NUMBER = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)", re.I)
RANGE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:-|to)\s*(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)", re.I)


def guidance_sentences(text: str, source: str, limit: int = 8) -> list[dict]:
    found = []
    for sentence in sentences(text or ""):
        if len(sentence) < 50 or len(sentence) > 420:
            continue
        if sentence.endswith("?") or re.match(
            r"(i had a question|you want|you have|can you|could you|do we|do you|would you)\b",
            sentence,
            re.I,
        ):
            continue
        if re.search(r"\b(emotional moment|leaving this organization|i'm leaving|i am leaving)\b", sentence, re.I):
            continue
        if not NUMBER.search(sentence) and not re.search(r"\b(guidance|outlook|expect|margin|capex)\b", sentence, re.I):
            continue
        if not FORWARD.search(sentence):
            continue
        if PAST.search(sentence) and not re.search(r"\b(expect|guidance|outlook|aim|target)\b", sentence, re.I):
            continue
        metric = _metric(sentence)
        low, high = _band(sentence, metric)
        found.append(
            {
                "text": sentence,
                "source": source,
                "metric": metric,
                "low": low,
                "high": high,
            }
        )
        if len(found) >= limit:
            break
    return found


def _metric(sentence: str) -> str | None:
    low = sentence.lower()
    if "capex" in low or "capital expenditure" in low:
        return "capex"
    if "margin" in low:
        return "margin"
    if any(word in low for word in ("revenue", "sales", "top line", "topline")):
        return "revenue"
    if any(word in low for word in ("pat", "profit after", "net profit", "bottom line")):
        return "profit"
    return None


def _band(sentence: str, metric: str | None) -> tuple[float | None, float | None]:
    """Only a percent sitting next to the metric, and only in a range that metric can take."""
    window_word = {"margin": r"margin", "revenue": r"revenue|sales|top ?line|growth", "profit": r"profit|pat\b", "capex": r"capex|capital expenditure"}.get(metric or "", r"$^")
    spans = list(RANGE.finditer(sentence)) or list(NUMBER.finditer(sentence))
    for match in spans:
        nearby = sentence[max(0, match.start() - 45) : match.end() + 24]
        if not re.search(window_word, nearby, re.I):
            continue
        if match.re is RANGE:
            low, high = float(match.group(1)), float(match.group(2))
        else:
            low = high = float(match.group(1))
        if metric == "margin" and not 5 <= low <= 45:
            continue
        if metric in {"revenue", "profit"} and not -5 <= low <= 40:
            continue
        return low, high
    return None, None


def verdict(quote: dict, actual: float | None) -> str | None:
    """Compare a numeric guide with what the quarter printed. No number, no verdict."""
    if actual is None or quote.get("low") is None:
        return None
    low, high = quote["low"], quote["high"]
    if low is None or high is None:
        return None
    pad = 0.4
    if low - pad <= actual <= high + pad:
        return "held"
    if actual < low - pad:
        return "short"
    return "ahead"
