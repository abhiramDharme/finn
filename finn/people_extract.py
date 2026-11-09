"""Pull the person, the role, and the prior employer out of a filing.

The only biography FINN will show is a sentence that appears in the document.
"""

from __future__ import annotations

import re

from finn.textutil import sentences

HONORIFIC = r"(?:Mr|Mrs|Ms|Shri|Smt)\.?"
NAME = (
    r"("
    r"(?:[A-Z]\.\s*){1,3}[A-Z][A-Za-z]+"
    r"|[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+){1,3}"
    r"|[A-Z][a-z]+\s+[A-Z]['’][A-Za-z]+"
    r")"
)
ROLE = (
    r"(Chief Compliance Officer|Chief Financial Officer|Chief Executive Officer|"
    r"Managing Director(?:\s*(?:&|and)\s*Chief Executive Officer)?|"
    r"President\s*(?:&|and)\s*CHRO|Independent Director|Non-Executive Director|"
    r"Whole[- ]time Director|Chairman|Group Head[^,.]{0,80}|MD\s*(?:&|and)\s*CEO|"
    r"CFO|CEO|CHRO)"
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _previous_org(text: str) -> tuple[str | None, str | None]:
    patterns = [
        r"Prior to joining.{0,260}?\bat\s+([A-Z][A-Za-z0-9&.,'’ \-]{2,80}?)(?:\s+which|\.\s|, He|, She)",
        r"[Ll]ast assignment.{0,220}?\bat\s+([A-Z][A-Za-z0-9&.,'’ \-]{2,70}?)(?:\s+which|\.\s|,)",
        r"previously (?:served|worked|was).{0,120}?\bat\s+([A-Z][A-Za-z0-9&.,'’ \-]{2,70})",
        r"former\s+(?:[A-Za-z]+\s+){0,6}of\s+([A-Z][A-Za-z0-9&.,'’ \-]{2,70})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        org = _clean(match.group(1))
        org = re.split(r"\b(He |She |His |Her |The )", org)[0].strip(" .,-")
        if 3 < len(org) < 90:
            title_match = re.search(r"(Head[^.]{0,60}|Sr\. Vice President[^.]{0,40}|Chief [^.]{0,40})", text)
            return org, _clean(title_match.group(0)) if title_match else None
    return None, None


def _good_bio(text: str) -> bool:
    if not text or len(text) < 90:
        return False
    return not re.search(
        r"letter no|not related|not debarred|listing regulations|vide its|was disclosed|exchange about|you are requested",
        text,
        re.I,
    )


def _profile_paragraph(text: str, name: str = "") -> str | None:
    cleaned = _clean(text)
    surname = name.split()[-1] if name else ""
    match = re.search(r"Brief profile", cleaned, re.I)
    if match:
        window = cleaned[match.start() : match.start() + 1100]
        window = re.split(r"Disclosure of relationships|Not applicable|You are requested|Sincerely|Yours faithfully", window, maxsplit=1)[0]
        window = re.sub(r"^Brief profile[^A-Z]*", "", window, flags=re.I).strip()
        if _good_bio(window):
            window = re.sub(r"^[^A-Z]*", "", window)
            cut = window.find("Mr ")
            if 0 < cut < 60:
                window = window[cut:]
            return window[:680]
    for sentence in sentences(cleaned):
        if surname and surname not in sentence:
            continue
        if re.search(r"prior to joining|last assignment|years of .{0,40}experience|served as", sentence, re.I) and _good_bio(sentence):
            return sentence
    return None


def _action(window: str, name_at: int = 0) -> str:
    """The verb after the name wins. 'Appointment of X' keeps the verb in front."""
    after = window[max(name_at, 0) :]
    before = window[: max(name_at, 0)]
    if re.search(r"appoint|assumed|joining|approved the appointment", after, re.I):
        return "joined"
    if re.search(r"resign|cessation|ceased|superannuat|vacated", after, re.I):
        return "left"
    if re.search(r"appoint|assumed charge|approved the appointment", before, re.I):
        return "joined"
    if re.search(r"resign|cessation|superannuat|vacated", before, re.I):
        return "left"
    return "changed"


def extract_people(text: str) -> list[dict]:
    cleaned = _clean(text)
    if not cleaned:
        return []
    found: list[dict] = []
    seen: set[str] = set()
    for match in re.finditer(HONORIFIC + r"\s+" + NAME, cleaned):
        name = _clean(match.group(1)).rstrip(".")
        key = name.lower()
        if key in seen or len(name) < 4:
            continue
        if name.lower() in {"limited", "exchange"}:
            continue
        start = max(0, match.start() - 40)
        window = cleaned[start : match.end() + 220]
        name_at = match.start() - start
        following = window[name_at + len(name) :]
        nxt = re.search(r"\b(?:Mr|Mrs|Ms|Shri|Smt)\b", following)
        if nxt:
            window = window[: name_at + len(name) + nxt.start()]
        role_match = re.search(ROLE, window, re.I)
        if not role_match and not re.search(r"appoint|resign|cessation|superannuat|assumed|vacated|director", window, re.I):
            continue
        seen.add(key)
        org, prior_title = _previous_org(cleaned)
        bio = _profile_paragraph(cleaned, name)
        if bio and not _good_bio(bio):
            bio = None
        found.append(
            {
                "name": name,
                "action": _action(window, name_at),
                "role": _clean(role_match.group(1)) if role_match else None,
                "bio": bio,
                "previous_org": org,
                "previous_title": prior_title,
            }
        )
    # A profile paragraph can name the previous employer once for the appointee.
    # Don't attach that employer to the person who left.
    if found:
        for person in found:
            if person["action"] != "joined":
                person["previous_org"] = None
                person["previous_title"] = None
        found = _dedupe_people(found)
        joined = [p for p in found if p["action"] == "joined" and p.get("previous_org")]
        if len(joined) > 1:
            for person in joined[1:]:
                person["previous_org"] = None
    return found


def _dedupe_people(people: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    order: list[str] = []
    for person in people:
        key = re.sub(r"[^a-z]", "", person["name"].lower())
        if key not in best:
            best[key] = person
            order.append(key)
            continue
        current = best[key]
        if (person.get("previous_org") and not current.get("previous_org")) or (
            (person.get("bio") or "") and len(person.get("bio") or "") > len(current.get("bio") or "")
        ):
            best[key] = person
    return [best[key] for key in order]
