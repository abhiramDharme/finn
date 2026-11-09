from __future__ import annotations

import re
from dataclasses import dataclass

NOISE_DESC = {
    "Copy of Newspaper Publication",
    "ESOP/ESOS/ESPS",
    "Trading Window",
    "Closure of Trading Window",
    "Statement of deviation(s) or variation(s) under Reg. 32",
    "Monitoring Agency Report",
    "Certificate under SEBI (Depositories and Participants) Regulations, 2018",
    "Loss of Share Certificate and Issue of Duplicate Share Certificate",
    "Integrated Filing- Governance",
}

DESC_MAP = {
    "Acquisition": "m_and_a",
    "Amalgamation/Merger": "m_and_a",
    "Demerger": "m_and_a",
    "Scheme of Arrangement": "m_and_a",
    "Other Restructuring": "m_and_a",
    "Dividend": "dividend",
    "Credit Rating": "credit_rating",
    "Credit Rating- New": "credit_rating",
    "Credit Rating- Revision": "credit_rating",
    "Bagging/Receiving of orders/contracts": "press_release",
    "Press Release": "press_release",
    "News Verification": "press_release",
    "Rumour Verification - Regulation 30(11)": "press_release",
    "Investor Presentation": "press_release",
    "Shareholders meeting": "agm_egm",
    "AGM": "agm_egm",
    "Postal Ballot": "postal_ballot",
    "Integrated Filing- Financial": "results",
    "Action(s) initiated or orders passed": "litigation",
    "Strikes/Lockouts/Disturbances": "litigation",
    "Defaults on Payment of Interest/Principal Amount": "litigation",
    "Corporate Insolvency Resolution Process": "litigation",
    "Allotment of Securities": "fund_raise",
    "Preferential Issue": "fund_raise",
    "Qualified Institutional Placement": "fund_raise",
    "Buyback": "fund_raise",
    "Change in Management": "management_change",
    "Change in Director(s)": "management_change",
    "Resignation of Director/KMP/SMP": "management_change",
    "Cessation": "management_change",
}

TOP_ROLE = re.compile(
    r"\b(chief financial officer|chief executive officer|managing director|"
    r"whole[- ]time director|chairman|cfo|ceo|md & ceo|md and ceo)\b",
    re.I,
)
SMP = re.compile(
    r"senior management|chief people officer|chief compliance officer|\bchro\b|\bciso\b|\bcpo\b",
    re.I,
)


@dataclass(frozen=True)
class FilingClass:
    category: str
    tier: str = ""


def _management_tier(blob: str) -> str:
    if TOP_ROLE.search(blob):
        return "kmp"
    if SMP.search(blob):
        return "smp"
    if re.search(r"\bdirector", blob, re.I):
        return "director"
    return "vague"


def classify(desc: str | None, text: str | None) -> FilingClass:
    desc = (desc or "").strip()
    blob = f"{desc}. {text or ''}"

    if desc in NOISE_DESC or re.search(r"\b(esop|esos|esps|employee stock option)\b", blob, re.I):
        return FilingClass("unclassified", "routine")

    if re.search(r"\btranscript\b", blob, re.I):
        return FilingClass("earnings_call")
    if desc.startswith("Analysts/") or "institutional investor meet" in desc.lower():
        if re.search(r"\b(audio recording|recording of|earnings call)\b", blob, re.I):
            return FilingClass("earnings_call")
        return FilingClass("investor_meetings", "routine")

    if re.search(r"\b(auditor|secretarial auditor|cost auditor)\b", blob, re.I) and not TOP_ROLE.search(blob):
        return FilingClass("unclassified", "routine")

    if re.search(r"\b(pledge|pledged|encumbrance)\b", blob, re.I) and re.search(r"\bshare", blob, re.I):
        return FilingClass("pledging")

    if re.search(r"\b(sast|insider trading|promoter[s]? (has |have )?(bought|sold|acquired|purchased))\b", blob, re.I):
        return FilingClass("insider_trading")

    if re.search(r"\b(nclt|insolvency|sebi (has )?order|penalty|fine of|show[- ]cause|litigation|writ petition)\b", blob, re.I):
        return FilingClass("litigation")

    if re.search(r"\b(acquire[ds]?|acquisition of|amalgamation|merger|demerger|joint venture|scheme of arrangement)\b", blob, re.I):
        if not re.search(r"\b(financial results|unaudited|audited financial)\b", blob, re.I):
            return FilingClass("m_and_a")

    if re.search(r"\b(qualified institutional|preferential (issue|allotment)|rights issue|buyback|commercial paper|non-convertible debenture)\b", blob, re.I):
        if re.search(r"\bredemption\b", blob, re.I) and not re.search(r"\b(issue|issuance|raised|raising)\b", blob, re.I):
            return FilingClass("fund_raise", "routine")
        return FilingClass("fund_raise")

    if re.search(r"\b(financial results|unaudited financial|audited financial)\b", blob, re.I) or desc == "Integrated Filing- Financial":
        return FilingClass("results")

    if re.search(
        r"\b(resign|cessation|superannuat|appointed as|appointment of|change in management|"
        r"change in (?:the )?(?:managing )?director|assumed charge|vacated the office)\b",
        blob,
        re.I,
    ):
        if re.search(r"\b(director|kmp|key managerial|md|ceo|cfo|chairman|compliance officer|chief )\b", blob, re.I):
            return FilingClass("management_change", _management_tier(blob))

    if re.search(r"\b(greenfield|capacity expansion|new plant|capex of|capital expenditure)\b", blob, re.I):
        return FilingClass("capex")

    if re.search(r"\b(sub-division|stock split|bonus (issue|shares|equity))\b", blob, re.I):
        return FilingClass("bonus_split")

    if re.search(r"\bdividend\b", blob, re.I):
        return FilingClass("dividend")

    if re.search(r"\b(credit rating|rated by|crisil|icra|care ratings|s&p)\b", blob, re.I) or "credit rating" in desc.lower():
        tier = ""
        if re.search(r"\bdowngrad", blob, re.I):
            tier = "downgrade"
        elif re.search(r"\bupgrad", blob, re.I):
            tier = "upgrade"
        elif re.search(r"\bre-?affirm", blob, re.I):
            tier = "reaffirm"
        return FilingClass("credit_rating", tier)

    if re.search(r"\bpostal ballot\b", blob, re.I):
        return FilingClass("postal_ballot")
    if re.search(r"\b(annual general meeting|extraordinary general meeting|\bagm\b|\begm\b)\b", blob, re.I):
        return FilingClass("agm_egm")

    mapped = DESC_MAP.get(desc)
    if mapped:
        tier = _management_tier(blob) if mapped == "management_change" else ""
        return FilingClass(mapped, tier)

    if re.search(r"\b(order worth|received an order|bagged)\b", blob, re.I):
        return FilingClass("press_release")

    return FilingClass("unclassified")


CATEGORY_LABEL = {
    "results": "Results",
    "m_and_a": "M&A",
    "fund_raise": "Fund raise",
    "management_change": "Management",
    "litigation": "Litigation",
    "insider_trading": "Insider",
    "earnings_call": "Earnings call",
    "investor_meetings": "Investor meeting",
    "credit_rating": "Credit rating",
    "dividend": "Dividend",
    "bonus_split": "Bonus or split",
    "capex": "Capex",
    "press_release": "Update",
    "postal_ballot": "Postal ballot",
    "agm_egm": "Shareholder meeting",
    "pledging": "Pledging",
    "unclassified": "Routine",
}

DEFAULT_WAKE = [
    "results",
    "m_and_a",
    "fund_raise",
    "management_change",
    "litigation",
    "insider_trading",
    "credit_rating",
    "capex",
    "pledging",
]

WEIGHT = {
    "m_and_a": 92,
    "management_change": 86,
    "litigation": 84,
    "pledging": 80,
    "results": 78,
    "insider_trading": 74,
    "fund_raise": 72,
    "capex": 68,
    "credit_rating": 50,
    "bonus_split": 42,
    "dividend": 36,
    "earnings_call": 34,
    "press_release": 32,
    "postal_ballot": 24,
    "investor_meetings": 16,
    "agm_egm": 14,
    "unclassified": 6,
}


def score_filing(kind: FilingClass, wake: set[str], network_hit: bool = False) -> int:
    score = WEIGHT.get(kind.category, 10)
    if kind.tier == "kmp":
        score += 8
    elif kind.tier == "director":
        score -= 26
    elif kind.tier == "smp":
        score -= 24
    elif kind.tier == "vague":
        score -= 40
    elif kind.tier == "routine":
        score -= 36
    elif kind.tier == "downgrade":
        score += 16
    elif kind.tier == "reaffirm":
        score -= 16
    elif kind.tier == "upgrade":
        score += 4
    if network_hit and kind.category in {"m_and_a", "litigation", "capex", "management_change", "results"}:
        score += 4
    if kind.category not in wake:
        score = min(score, 48)
    return score


def bucket(score: int) -> str:
    if score >= 62:
        return "now"
    if score >= 30:
        return "glance"
    return "away"
