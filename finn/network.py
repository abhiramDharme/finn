from __future__ import annotations

from datetime import datetime

from finn.textutil import IST, org_match, shared_phrase


def _years(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def _touch_days(person: dict, today: datetime) -> int | None:
    raw = person.get("last_touch")
    if not raw:
        return None
    try:
        then = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=IST)
    except ValueError:
        return None
    return (today.astimezone(IST).date() - then.date()).days


def _company(universe: dict, symbol: str) -> dict | None:
    for group in ("portfolio", "research"):
        for company in universe.get(group, []):
            if company["symbol"] == symbol:
                return company
    return None


def _role_hits_org(role: dict, org: str) -> bool:
    if org_match(role.get("org") or "", org):
        return True
    return any(org_match(alias, org) for alias in role.get("aliases") or [])


def rank_contacts(
    network: dict,
    universe: dict,
    symbol: str,
    *,
    category: str | None = None,
    filing_text: str = "",
    previous_orgs: list[str] | None = None,
    filing_year: int | None = None,
    today: datetime | None = None,
    limit: int = 3,
) -> list[dict]:
    today = today or datetime.now(IST)
    company = _company(universe, symbol) or {"name": symbol, "themes": [], "related": {}}
    related = company.get("related") or {}
    themes = set(company.get("themes") or [])
    previous_orgs = [org for org in (previous_orgs or []) if org]
    ranked: list[dict] = []

    for person in network.get("people", []):
        reasons: list[str] = []
        score = 0
        strength = "theme"
        caveat = None
        best_role = None

        for role in person.get("roles") or []:
            role_symbol = role.get("symbol")
            ended = role.get("to")
            current = ended is None
            if role_symbol == symbol or _role_hits_org(role, company.get("name", "")):
                best_role = role
                if current:
                    score = max(score, 100)
                    strength = "works there"
                    reasons.append(f"Works at {role['org']} now, as {role['title']}.")
                else:
                    score = max(score, 72)
                    if strength != "works there":
                        strength = "was there"
                    reasons.append(f"Was at {role['org']} from {role['from']} to {role['to']}, as {role['title']}.")
                    if filing_year and ended and ended <= filing_year - 2:
                        caveat = (
                            f"Left in {ended}, so this is context on the company, not on the person named in the filing."
                        )
                phrase = shared_phrase(role.get("title") or "", filing_text)
                if phrase:
                    reasons.append(f"The filing and their own role both talk about {phrase.lower()}.")
                    score += 8

            for supplier in related.get("suppliers") or []:
                if role_symbol == supplier or _role_hits_org(role, supplier):
                    score = max(score, 58)
                    if strength == "theme":
                        strength = "adjacent"
                    reasons.append(f"At {role['org']}, which supplies {company.get('name', symbol)}.")
            for other in (related.get("competitors") or []) + (related.get("customers") or []):
                if role_symbol == other:
                    score = max(score, 54)
                    if strength == "theme":
                        strength = "adjacent"
                    reasons.append(f"At {role['org']}, next door to {company.get('name', symbol)}.")

            if previous_orgs and any(_role_hits_org(role, org) for org in previous_orgs):
                overlap = "the same years" if current or (ended and ended >= 2020) else "an earlier stint"
                score = max(score, 88 if category == "management_change" else 64)
                strength = "same institution"
                org_name = next(org for org in previous_orgs if _role_hits_org(role, org))
                reasons.insert(
                    0,
                    f"The filing places the new person at {org_name}. "
                    f"{person['name'].split()[0]} was there too ({role['from']}–{role['to'] or 'now'}), {overlap}. "
                    "Same institution — not a confirmed introduction.",
                )

        if symbol in (person.get("covers") or []):
            score = max(score, 48)
            reasons.append(f"Covers {company.get('name', symbol)} from where they sit now.")

        shared = [theme for theme in person.get("themes") or [] if theme in themes]
        if category == "litigation" and "litigation" in (person.get("themes") or []):
            score = max(score, 70)
            strength = "theme"
            reasons.append("Does securities disputes. The person to call before you read an order.")
            shared = shared or ["litigation"]
        elif shared and score < 40:
            score = 32
            reasons.append(f"Your notebook's person for {shared[0]}. Not a company insider.")

        if score <= 0:
            continue
        days = _touch_days(person, today)
        stale = days is not None and days > 150
        if caveat:
            reasons.append(caveat)
        ranked.append(
            {
                "id": person["id"],
                "name": person["name"],
                "strength": strength,
                "score": score,
                "reasons": _unique(reasons)[:3],
                "last_touch": person.get("last_touch"),
                "last_note": person.get("last_note"),
                "stale": stale,
                "days_since": days,
                "title": _current_title(person),
                "themes": person.get("themes") or [],
            }
        )

    ranked.sort(key=lambda item: (-item["score"], item["name"]))
    return ranked[:limit]


def _current_title(person: dict) -> str:
    roles = person.get("roles") or []
    current = next((role for role in roles if role.get("to") is None), None)
    role = current or (roles[-1] if roles else None)
    if not role:
        return ""
    suffix = "" if role.get("to") is None else f", until {role['to']}"
    return f"{role['title']}, {role['org']}{suffix}"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def reconnect(network: dict, events: list[dict], today: datetime, limit: int = 3) -> list[dict]:
    """Someone gone quiet, whose old or current shop just did something real."""
    by_symbol: dict[str, dict] = {}
    for event in events:
        symbol = event.get("symbol")
        if symbol and symbol not in by_symbol:
            by_symbol[symbol] = event
    found: list[dict] = []
    for person in network.get("people", []):
        days = _touch_days(person, today)
        if days is None or days < 150:
            continue
        for role in person.get("roles") or []:
            event = by_symbol.get(role.get("symbol"))
            if not event:
                continue
            found.append(
                {
                    "id": person["id"],
                    "name": person["name"],
                    "symbol": role.get("symbol"),
                    "company": event.get("company") or role.get("org"),
                    "days_since": days,
                    "last_touch": person.get("last_touch"),
                    "line": event.get("line") or event.get("category_label") or "A filing",
                    "opener": (
                        f"{event.get('company') or role.get('org')} just filed. "
                        f"You haven't spoken to {person['name'].split()[0]} since {_month(person.get('last_touch'))}."
                    ),
                    "why": _current_title(person),
                }
            )
            break
    found.sort(key=lambda item: -item["days_since"])
    return found[:limit]


def _month(iso: str | None) -> str:
    if not iso:
        return "a long while"
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%B %Y")
    except ValueError:
        return iso


def search_people(network: dict, query: str, universe: dict | None = None) -> list[dict]:
    needle = (query or "").strip().lower()
    if not needle:
        return []
    hits = []
    for person in network.get("people", []):
        hay = " ".join(
            [
                person["name"],
                " ".join(person.get("themes") or []),
                " ".join((role.get("org") or "") + " " + (role.get("title") or "") for role in person.get("roles") or []),
                person.get("met_note") or "",
                person.get("last_note") or "",
            ]
        ).lower()
        if needle in hay or any(part in hay for part in needle.split() if len(part) > 3):
            hits.append(
                {
                    "id": person["id"],
                    "name": person["name"],
                    "title": _current_title(person),
                    "themes": person.get("themes") or [],
                    "last_touch": person.get("last_touch"),
                    "last_note": person.get("last_note"),
                    "met_note": person.get("met_note"),
                    "roles": person.get("roles") or [],
                }
            )
    return hits


def expertise(network: dict) -> list[dict]:
    order = [
        "specialty chemicals",
        "rural lending",
        "semiconductors",
        "electronics",
        "autos",
        "pharma",
        "banks",
        "fmcg",
        "consumer",
        "infra",
        "litigation",
    ]
    groups = []
    for theme in order:
        people = []
        for person in network.get("people", []):
            if theme in (person.get("themes") or []):
                people.append({"id": person["id"], "name": person["name"], "title": _current_title(person)})
        if people:
            groups.append({"theme": theme, "people": people})
    return groups


def person_detail(network: dict, person_id: str) -> dict | None:
    for person in network.get("people", []):
        if person["id"] == person_id:
            return person
    return None
