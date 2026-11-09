from __future__ import annotations

from datetime import datetime

from finn.guidance import guidance_sentences, verdict
from finn.network import rank_contacts
from finn.prices import latest_move
from finn.statements import balance_read, cash_read, last_quarters, quarter_snapshot, trajectory_read
from finn.textutil import IST, format_pct, indian

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def build_memo(
    symbol: str,
    profile: dict | None,
    statements: dict,
    docs: dict | None,
    series: list[dict] | None,
    network: dict,
    universe: dict,
    *,
    in_portfolio: bool,
) -> dict:
    docs = docs or {}
    snap = quarter_snapshot(statements)
    trajectory = trajectory_read(statements)
    balance = balance_read(statements)
    cash = cash_read(statements)
    quarters = last_quarters(statements, 4)
    move = latest_move(series or [])
    contacts = rank_contacts(network, universe, symbol, today=datetime.now(IST), limit=3)
    guides = _refresh_guidance(docs.get("guidance") or [])
    promised = _promised(quarters, guides, bool((statements.get("quarters") or {}).get("rows", {}).get("Financing Profit")))
    bull, bear = _cases(trajectory, balance, cash, snap, docs.get("auditor"))
    from finn.documents import business_blurb

    chunks = docs.get("chunks") or []
    calls = [chunk for chunk in chunks if "concall" in (chunk.get("source") or "").lower()]
    reports = [chunk for chunk in chunks if chunk not in calls]
    blurb_source = (docs.get("annual") or {}).get("label") or "Annual report"
    blurb = business_blurb(" ".join(chunk.get("text") or "" for chunk in reports[:16]))
    if not blurb:
        blurb = business_blurb(" ".join(chunk.get("text") or "" for chunk in calls[:12]))
        blurb_source = "Concall"
    if not blurb:
        blurb = business_blurb(docs.get("blurb") or "")
    docs = {**docs, "blurb": blurb, "blurb_source": blurb_source}
    name = (profile or {}).get("name") or statements.get("name") or symbol
    return {
        "symbol": symbol,
        "name": name,
        "sector": (profile or {}).get("sector"),
        "in_portfolio": in_portfolio,
        "price": move,
        "market": _market(statements.get("top") or {}),
        "business": {
            "text": docs.get("blurb"),
            "source": docs.get("blurb_source") or (docs.get("annual") or {}).get("label"),
            "url": (docs.get("annual") or {}).get("url"),
        },
        "segments": (statements.get("segments") or docs.get("segments") or [])[:5],
        "snapshot": _public_snapshot(snap),
        "trajectory": trajectory,
        "balance": balance,
        "cash": cash,
        "promised": promised,
        "guidance": _standing(guides),
        "bull": bull,
        "bear": bear,
        "contacts": contacts,
        "sources": _sources(statements, docs),
        "warnings": docs.get("warnings") or [],
        "ask_ready": bool(docs.get("chunks")),
    }


def _refresh_guidance(quotes: list[dict]) -> list[dict]:
    """Re-read cached sentences with the current forward-looking rules."""
    fresh = []
    seen = set()
    for quote in quotes:
        for item in guidance_sentences(quote.get("text") or "", quote.get("source") or "Concall", limit=2):
            key = item["text"][:80]
            if key in seen:
                continue
            seen.add(key)
            fresh.append(item)
    return fresh


def _market(top: dict) -> dict:
    wanted = {}
    for key, value in top.items():
        folded = key.lower()
        if folded in {"market cap", "stock p/e", "book value", "dividend yield", "roce", "roe"}:
            wanted[key] = value
    return wanted


def _public_snapshot(snap: dict | None) -> dict | None:
    if not snap:
        return None
    def line(pack, kind):
        if not pack or pack.get("value") is None:
            return None
        value = pack["value"]
        shown = f"{value:.1f}%" if kind == "percent" else indian(value)
        return {"value": value, "shown": shown, "qoq": format_pct(pack.get("qoq")), "yoy": format_pct(pack.get("yoy"))}

    lines = [
        {"key": "revenue", "label": "Revenue", **(line(snap["revenue"], "cr") or {})},
        {"key": "operating", "label": snap["operating_label"], "note": snap["operating_note"], **(line(snap["operating"], "cr") or {})},
        {"key": "pbt", "label": "PBT", **(line(snap["pbt"], "cr") or {})},
        {"key": "pat", "label": "PAT", **(line(snap["pat"], "cr") or {})},
    ]
    lines = [item for item in lines if item.get("shown")]
    extra = []
    if snap.get("margin") and snap["margin"].get("value") is not None:
        extra.append(f"Margin {snap['margin']['value']:.1f}%")
    if snap.get("gross_npa") and snap["gross_npa"].get("value") is not None:
        extra.append(f"Gross NPA {snap['gross_npa']['value']:.2f}%")
    return {"period": snap["period"], "lines": lines, "extra": extra, "note": snap["operating_note"]}


def _transcript_month(label: str) -> datetime | None:
    parts = (label or "").replace(",", " ").split()
    if len(parts) < 2:
        return None
    month = MONTHS.get(parts[0][:3].lower())
    year = next((int(part) for part in parts if part.isdigit() and len(part) == 4), None)
    if not month or not year:
        return None
    return datetime(year, month, 1)


def _promised(quarters: list[dict], quotes: list[dict], lender: bool) -> list[dict]:
    dated = []
    for quote in quotes:
        when = _transcript_month(quote.get("source") or "")
        if when:
            dated.append((when, quote))
    dated.sort(key=lambda item: item[0])
    blocks = []
    for quarter in quarters:
        raw_date = quarter.get("date")
        try:
            ended = datetime.strptime(raw_date, "%Y-%m-%d") if raw_date else None
        except ValueError:
            ended = None
        prior = []
        if ended and dated:
            discussion = next((when for when, _quote in dated if when >= ended), None)
            if discussion:
                earlier = [(when, quote) for when, quote in dated if when < discussion]
                if earlier:
                    prior_when = earlier[-1][0]
                    prior = [quote for when, quote in earlier if when == prior_when]
        read, used = _read_gap(quarter, prior, lender)
        blocks.append(
            {
                "label": quarter["label"],
                "revenue": indian(quarter["revenue"]) if quarter.get("revenue") is not None else None,
                "operating": indian(quarter["operating"]) if quarter.get("operating") is not None else None,
                "pbt": indian(quarter["pbt"]) if quarter.get("pbt") is not None else None,
                "pat": indian(quarter["pat"]) if quarter.get("pat") is not None else None,
                "revenue_yoy": format_pct(quarter.get("revenue_yoy")),
                "pat_yoy": format_pct(quarter.get("pat_yoy")),
                "margin": f"{quarter['margin']:.1f}%" if quarter.get("margin") is not None else None,
                "quotes": [{"text": quote["text"], "source": quote["source"]} for quote in used[:2]],
                "read": read,
            }
        )
    return blocks


def _read_gap(quarter: dict, quotes: list[dict], lender: bool) -> tuple[str, list[dict]]:
    if not quotes:
        return "No earlier transcript states a number this quarter can be held to.", []
    used = []
    notes = []
    for quote in quotes:
        if quote.get("metric") == "margin" and quarter.get("margin") is not None:
            call = verdict(quote, quarter["margin"])
            if call:
                used.append(quote)
                band = _band_text(quote)
                notes.append(f"Margin printed {quarter['margin']:.1f}% against {band} they had named. {_word(call)}.")
        elif quote.get("metric") == "revenue" and quarter.get("revenue_yoy") is not None and quote.get("low") is not None and quote["low"] <= 80:
            call = verdict(quote, quarter["revenue_yoy"])
            if call:
                used.append(quote)
                notes.append(
                    f"Revenue was {format_pct(quarter['revenue_yoy'])} year on year, against {_band_text(quote)} growth they had named. {_word(call)}."
                )
    if not notes:
        used = quotes[:1]
        return "They said something forward-looking. It wasn't a number I can score against this quarter.", used
    return " ".join(notes[:2]), used


def _band_text(quote: dict) -> str:
    low, high = quote.get("low"), quote.get("high")
    if low is None:
        return "a figure"
    if high is None or abs(high - low) < 0.05:
        return f"{low:.0f}%"
    return f"{low:.0f}–{high:.0f}%"


def _word(call: str) -> str:
    return {"held": "That held", "short": "That was short", "ahead": "That was ahead"}[call]


def _standing(quotes: list[dict]) -> list[dict]:
    if not quotes:
        return []
    # The latest transcript's own forward remarks, not a verdict.
    # The newest concall is what they are saying now. Later quarters have not printed.
    sources = {}
    for quote in quotes:
        sources.setdefault(quote["source"], []).append(quote)
    ordered = sorted(sources, key=lambda source: _transcript_month(source) or datetime.min)
    chosen = sources[ordered[-1]]
    return [{"text": quote["text"], "source": quote["source"], "metric": quote.get("metric")} for quote in chosen[:4]]


def _cases(trajectory, balance, cash, snap, auditor) -> tuple[list[dict], list[dict]]:
    bull = []
    bear = []
    sales = trajectory.get("sales") or []
    if len(sales) >= 2 and sales[0]["value"] and sales[-1]["value"] > sales[0]["value"] * 1.25:
        bull.append({"text": trajectory["read"].split(". ")[0] + ".", "source": "Annual statements"})
    margin = trajectory.get("margin") or []
    if len(margin) >= 2 and margin[-1]["value"] >= margin[0]["value"] + 0.8:
        bull.append(
            {
                "text": f"Margin expanded from {margin[0]['value']:.1f}% to {margin[-1]['value']:.1f}% between {margin[0]['label']} and {margin[-1]['label']}.",
                "source": "Annual statements",
            }
        )
    elif len(margin) >= 2 and margin[-1]["value"] <= margin[0]["value"] - 1.5:
        bear.append(
            {
                "text": f"Margin compressed from {margin[0]['value']:.1f}% to {margin[-1]['value']:.1f}% between {margin[0]['label']} and {margin[-1]['label']}.",
                "source": "Annual statements",
            }
        )
    if balance.get("de") is not None:
        if balance["de"] < 0.4:
            bull.append({"text": f"Borrowings are {balance['de']:.2f}× equity. The balance sheet is not the risk.", "source": "Balance sheet"})
        elif balance["de"] > 1:
            bear.append({"text": f"Borrowings are {balance['de']:.2f}× equity.", "source": "Balance sheet"})
    rows = cash.get("rows") or []
    if rows and rows[-1].get("fcf") is not None:
        if rows[-1]["fcf"] > 0 and (rows[-1].get("conversion") or 0) >= 0.7:
            bull.append({"text": cash["read"].split(".")[0] + ".", "source": "Cash-flow statement"})
        elif rows[-1]["fcf"] < 0:
            bear.append({"text": f"Free cash flow was negative in {rows[-1]['label']} ({indian(rows[-1]['fcf'])} cr).", "source": "Cash-flow statement"})
    wc = balance.get("wc") or []
    if len(wc) >= 2 and wc[-1]["value"] - wc[0]["value"] >= 15:
        bear.append(
            {
                "text": f"Working capital has stretched by {wc[-1]['value'] - wc[0]['value']:.0f} days since {wc[0]['label']}.",
                "source": "Ratios from the statements",
            }
        )
    if snap and snap.get("gross_npa") and snap["gross_npa"].get("value") is not None and (snap["gross_npa"].get("yoy") or 0) > 0.3:
        bear.append({"text": f"Gross NPA is {snap['gross_npa']['value']:.2f}% and higher than a year ago.", "source": "Quarterly results"})
    if auditor:
        bear.append({"text": auditor, "source": "Annual report"})
    return bull[:3], bear[:3]


def _sources(statements: dict, docs: dict) -> list[dict]:
    sources = []
    if statements.get("screener_url"):
        sources.append(
            {
                "label": "Consolidated statements, as filed",
                "url": statements["screener_url"],
                "note": "Numbers are the company's own results, read off the filed statements. Not a broker model.",
            }
        )
    annual = docs.get("annual") or {}
    if annual.get("url"):
        sources.append({"label": annual.get("label") or "Annual report", "url": annual["url"], "note": "Primary"})
    for item in docs.get("transcripts") or []:
        if item.get("url"):
            sources.append({"label": f"Concall {item.get('label') or ''}".strip(), "url": item["url"], "note": "Primary"})
    return sources
