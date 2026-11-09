from __future__ import annotations

import re

STOP = {
    "the", "and", "for", "with", "what", "when", "where", "which", "that", "this",
    "from", "have", "they", "their", "about", "does", "did", "how", "why", "was",
    "were", "are", "you", "your", "into", "over", "than", "management", "company",
}


def answer(question: str, chunks: list[dict], company: str) -> dict:
    raw_terms = [term for term in re.findall(r"[a-z0-9%]+", (question or "").lower()) if len(term) > 2 and term not in STOP]
    terms = []
    for term in raw_terms:
        terms.append(term)
        if term.endswith("s") and len(term) > 4:
            terms.append(term[:-1])
    if not chunks:
        return {
            "refused": True,
            "answer": f"I don't have the annual report or a transcript loaded for {company}, so I won't answer.",
            "quotes": [],
        }
    if not terms:
        return {
            "refused": True,
            "answer": "Ask about something specific in the filings — capex, margins, a segment, guidance.",
            "quotes": [],
        }
    scored = []
    for chunk in chunks:
        text = chunk.get("text") or ""
        folded = text.lower()
        score = 0.0
        for term in terms:
            count = folded.count(term)
            if count:
                score += 1 + min(count, 4) * 0.25
        if score:
            scored.append((score, chunk))
    scored.sort(key=lambda item: -item[0])
    if not scored or scored[0][0] < 1.4:
        return {
            "refused": True,
            "answer": f"I can't find that in the annual-report pages or the concall transcripts I have for {company}. I won't answer it from anywhere else.",
            "quotes": [],
        }
    top = []
    seen = set()
    for score, chunk in scored:
        key = chunk["text"][:80]
        if key in seen:
            continue
        seen.add(key)
        top.append(chunk)
        if len(top) == 3:
            break
    lead = _best_sentence(top[0]["text"], terms) or top[0]["text"][:280]
    return {
        "refused": False,
        "answer": lead,
        "quotes": [{"text": _trim(chunk["text"]), "source": chunk.get("source"), "url": chunk.get("url")} for chunk in top],
    }


def _best_sentence(text: str, terms: list[str]) -> str | None:
    parts = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))
    best = None
    best_score = 0
    for part in parts:
        if len(part) < 40:
            continue
        score = sum(1 for term in terms if term in part.lower())
        if score > best_score:
            best = part.strip()
            best_score = score
    return best


def _trim(text: str, limit: int = 420) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
