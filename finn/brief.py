from __future__ import annotations

from datetime import datetime, timedelta

from finn.classify import CATEGORY_LABEL, DEFAULT_WAKE, bucket, classify, score_filing
from finn.network import rank_contacts, reconnect
from finn.people_extract import extract_people
from finn.prices import latest_move
from finn.statements import quarter_snapshot
from finn.textutil import IST, format_pct, friendly_when, indian, one_line, parse_nse_dt, sentences

WINDOWS = {"24h": timedelta(hours=24), "3d": timedelta(days=3), "7d": timedelta(days=7), "30d": timedelta(days=30)}
WINDOW_LABEL = {"24h": "last 24 hours", "3d": "last 3 days", "7d": "last 7 days", "30d": "last 30 days"}


def build_brief(
    *,
    universe: dict,
    network: dict,
    filings: dict[str, list[dict]],
    statements: dict[str, dict],
    prices: dict[str, list[dict]],
    profiles: dict[str, dict],
    window: str = "24h",
    price_pct: float = 3,
    volume_x: float = 2,
    wake: list[str] | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(IST)
    window = window if window in WINDOWS else "24h"
    start = now - WINDOWS[window]
    wake_set = set(wake or DEFAULT_WAKE)
    names = {company["symbol"]: company for company in universe["portfolio"]}
    cards = []
    for symbol, company in names.items():
        for filing in filings.get(symbol) or []:
            moment = parse_nse_dt(filing.get("when"))
            if moment is None or moment < start or moment > now + timedelta(hours=6):
                continue
            cards.append(_card(filing, company, moment, now, statements.get(symbol), network, universe, wake_set, profiles.get(_key(filing))))
    cards = _dedupe(cards)
    now_items = [card for card in cards if card["bucket"] == "now"]
    glance = [card for card in cards if card["bucket"] == "glance"]
    away = [card for card in cards if card["bucket"] == "away"]
    now_items.sort(key=lambda card: (card["score"], card["iso"]))
    now_items.reverse()
    glance.sort(key=lambda card: card["iso"], reverse=True)
    away.sort(key=lambda card: card["iso"], reverse=True)

    alerts = _alerts(names, prices, price_pct, volume_x, filings, start)
    book = _book(names, prices)
    aside = _aside(names, filings, statements, network, universe, profiles, now, start, wake_set) if window != "30d" else None
    material_for_reconnect = [
        {"symbol": card["symbol"], "company": card["name"], "line": card["line"], "category_label": card["category_label"]}
        for card in now_items + glance
        if card["category"] in {"results", "m_and_a", "capex", "management_change", "litigation"}
    ]
    return {
        "as_of": now.isoformat(),
        "window": {"key": window, "label": WINDOW_LABEL[window], "start": start.isoformat()},
        "investor": universe.get("investor"),
        "lede": _lede(now_items, alerts, len(away), WINDOW_LABEL[window]),
        "book": book,
        "alerts": alerts,
        "thresholds": {"price_pct": price_pct, "volume_x": volume_x},
        "now": now_items,
        "glance": glance[:12],
        "away": {"count": len(away), "items": [_thin(card) for card in away[:40]]},
        "reconnect": reconnect(network, material_for_reconnect, now),
        "aside": aside,
        "wake": sorted(wake_set),
    }


def _key(filing: dict) -> str:
    return f"{filing.get('symbol')}-{filing.get('seq')}"


def _card(filing, company, moment, now, statements, network, universe, wake, profile) -> dict:
    text = filing.get("text") or ""
    if profile and profile.get("text"):
        text = text + "\n" + profile["text"]
    kind = classify(filing.get("desc"), text)
    people = extract_people(text) or ((profile or {}).get("people") or [])
    subject = next((person for person in people if person["action"] == "joined"), None) or (people[0] if people else None)
    previous = [subject["previous_org"]] if subject and subject.get("previous_org") else []
    contacts = rank_contacts(
        network,
        universe,
        company["symbol"],
        category=kind.category,
        filing_text=text,
        previous_orgs=previous,
        filing_year=moment.year,
        today=now,
        limit=1,
    )
    contact = contacts[0] if contacts and contacts[0]["score"] >= 48 else None
    score = score_filing(kind, wake, network_hit=bool(contact))
    line = _line(kind.category, {**filing, "text": text}, subject)
    numbers = quarter_snapshot(statements) if kind.category == "results" and statements else None
    profile_missing = bool(re_search_profile_missing(text, subject))
    return {
        "id": _key(filing),
        "symbol": company["symbol"],
        "name": company["name"],
        "category": kind.category,
        "category_label": CATEGORY_LABEL.get(kind.category, kind.category),
        "tier": kind.tier,
        "when": friendly_when(moment, now),
        "iso": moment.isoformat(),
        "line": line,
        "score": score,
        "bucket": bucket(score),
        "url": filing.get("url"),
        "numbers": _numbers(numbers),
        "person": _person(subject, profile_missing),
        "contact": contact,
    }


def re_search_profile_missing(text: str, subject: dict | None) -> bool:
    if subject and subject.get("bio") and len(subject["bio"]) > 80:
        return False
    lowered = (text or "").lower()
    return ("brief profile" in lowered and ("earlier" in lowered or "dated" in lowered)) or "was disclosed by" in lowered


def _line(category: str, filing: dict, subject: dict | None) -> str:
    text = filing.get("text") or ""
    if subject and subject.get("name") and category == "management_change":
        surname = subject["name"].split()[-1]
        for sentence in sentences(text):
            if surname in sentence and re_chairman(sentence) and 40 < len(sentence) < 240:
                return sentence
        verb = {"joined": "is in", "left": "has left", "changed": "is named in"}[subject["action"]]
        role = f" as {subject['role']}" if subject.get("role") else ""
        return f"{subject['name']} {verb}{role}."
    return one_line(text, filing.get("desc") or "Filing")


def re_chairman(sentence: str) -> bool:
    lowered = sentence.lower()
    return "chairman" in lowered or "assume office" in lowered or "assumed charge" in lowered


def _person(subject: dict | None, profile_missing: bool) -> dict | None:
    if not subject and not profile_missing:
        return None
    if not subject:
        return {"missing": True, "note": "This letter points at a profile in an earlier filing and doesn't repeat it."}
    note = None
    if profile_missing and not (subject.get("bio") and len(subject["bio"]) > 80):
        note = "This letter points at a profile in an earlier filing and doesn't repeat it."
    return {
        "name": subject.get("name"),
        "action": subject.get("action"),
        "role": subject.get("role"),
        "bio": subject.get("bio"),
        "previous_org": subject.get("previous_org"),
        "note": note,
    }


def _numbers(snap: dict | None) -> dict | None:
    if not snap:
        return None
    rows = []
    for key, label in (
        ("revenue", "Revenue"),
        ("operating", snap["operating_label"]),
        ("pbt", "PBT"),
        ("pat", "PAT"),
    ):
        pack = snap.get(key)
        if not pack or pack.get("value") is None:
            continue
        rows.append(
            {
                "label": label,
                "value": indian(pack["value"]),
                "qoq": format_pct(pack.get("qoq")),
                "yoy": format_pct(pack.get("yoy")),
            }
        )
    if not rows:
        return None
    note = "Operating profit, the EBITDA line in the filing." if snap["operating_label"] == "EBITDA" else snap["operating_note"]
    return {"period": snap["period"], "rows": rows, "note": note, "unit": "₹ cr"}


def _alerts(names, prices, price_pct, volume_x, filings, start) -> list[dict]:
    alerts = []
    for symbol, company in names.items():
        move = latest_move(prices.get(symbol) or [])
        if not move or move.get("pct") is None:
            continue
        price_hit = abs(move["pct"]) >= price_pct
        volume_hit = move.get("vol_x") is not None and move["vol_x"] >= volume_x
        if not price_hit and not volume_hit:
            continue
        same_day = False
        for filing in filings.get(symbol) or []:
            moment = parse_nse_dt(filing.get("when"))
            if moment and moment.date().isoformat() == move["date"]:
                same_day = True
                break
        alerts.append(
            {
                "symbol": symbol,
                "name": company["name"],
                "close": move["close"],
                "pct": round(move["pct"], 2),
                "pct_label": format_pct(move["pct"]),
                "vol_x": round(move["vol_x"], 2) if move.get("vol_x") else None,
                "date": move["date"],
                "price_hit": price_hit,
                "volume_hit": volume_hit,
                "has_filing": same_day,
            }
        )
    alerts.sort(key=lambda item: -abs(item["pct"]))
    return alerts


def _book(names, prices) -> dict | None:
    moves = []
    last_date = None
    for symbol in names:
        move = latest_move(prices.get(symbol) or [])
        if not move or move.get("pct") is None:
            continue
        moves.append(move["pct"])
        last_date = move["date"]
    if not moves:
        return None
    up = sum(1 for value in moves if value > 0)
    skipped = None
    for symbol in names:
        move = latest_move(prices.get(symbol) or [])
        if move and move.get("skipped_short_session"):
            skipped = move["skipped_short_session"]
            break
    return {
        "date": last_date,
        "up": up,
        "down": sum(1 for value in moves if value < 0),
        "names": len(moves),
        "skipped_short_session": skipped,
    }


def _aside(names, filings, statements, network, universe, profiles, now, start, wake) -> dict | None:
    wider = now - timedelta(days=7)
    if start <= wider:
        return None
    count = 0
    top = None
    for symbol, company in names.items():
        for filing in filings.get(symbol) or []:
            moment = parse_nse_dt(filing.get("when"))
            if moment is None or moment < wider or moment >= start:
                continue
            kind = classify(filing.get("desc"), filing.get("text"))
            score = score_filing(kind, wake)
            if bucket(score) != "now":
                continue
            count += 1
            if top is None or moment > top[0]:
                top = (moment, company["name"], one_line(filing.get("text"), filing.get("desc") or ""))
    if not count or not top:
        return None
    return {"count": count, "window": "7d", "name": top[1], "line": top[2]}


def _dedupe(cards: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    kept = []
    for card in cards:
        person = ((card.get("person") or {}).get("name") or "").lower()
        key = (card["symbol"], card["category"], person, card["iso"][:10], card["line"][:48])
        # Same person, same company, same day, same kind of news: one card.
        loose = (card["symbol"], card["category"], person, card["iso"][:10]) if person else key
        if loose in seen or key in seen:
            continue
        seen.add(loose)
        seen.add(key)
        kept.append(card)
    return kept


def _thin(card: dict) -> dict:
    return {"id": card["id"], "symbol": card["symbol"], "name": card["name"], "category_label": card["category_label"], "when": card["when"], "line": card["line"]}


def _lede(now_items: list[dict], alerts: list[dict], away_count: int, window_label: str) -> str:
    if not now_items and not alerts:
        filed = f" {away_count} routine {'filing was' if away_count == 1 else 'filings were'} put away." if away_count else ""
        return f"Nothing in the {window_label} needs you.{filed}"
    parts = []
    if now_items:
        first = now_items[0]
        contact = ""
        if first.get("contact"):
            contact = f" {first['contact']['name'].split()[0]} is the person in the notebook."
        line = first["line"].rstrip()
        if len(line) > 150:
            line = line[:147].rsplit(" ", 1)[0] + "…"
        if line and line[-1] not in ".!?…":
            line += "."
        parts.append(f"{first['name']}: {line}{contact}")
        extra = len(now_items) - 1
        if extra == 1:
            parts.append("One other item also needs you.")
        elif extra > 1:
            parts.append(f"{extra} other items also need you.")
    if alerts:
        alert = alerts[0]
        reason = []
        if alert["price_hit"]:
            reason.append(f"{alert['pct_label']}")
        if alert["volume_hit"] and alert.get("vol_x"):
            reason.append(f"volume {alert['vol_x']:.1f}×")
        attached = " A filing landed the same day." if alert["has_filing"] else " No filing that day."
        parts.append(f"{alert['name']} closed {' '.join(reason)}.{attached}")
    return " ".join(parts)
