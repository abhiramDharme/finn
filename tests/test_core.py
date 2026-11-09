from datetime import datetime

from finn.brief import build_brief
from finn.classify import bucket, classify, score_filing
from finn.guidance import guidance_sentences, verdict
from finn.network import rank_contacts
from finn.people_extract import extract_people
from finn.statements import quarter_snapshot
from finn.textutil import format_pct, indian, one_line, org_match, pct_change

SRIVATSAN = """
Appointment of Mr. V.N. Srivatsan as the Chief Compliance Officer of the Bank.
Mr. V. N. Srivatsan has approximately 34 years of overall professional experience.
Prior to joining the Bank, he served as Head – Compliance: Overseas Banking and Subsidiaries & Data Privacy Officer at ICICI Bank Limited.
He holds a Post Graduate degree in Business Administration from PSG College of Technology.
"""

JYOTHSANA = """
Appointment of Mrs. Jyothsana Vasudevan as the President & CHRO, Senior Management Personnel of the Company.
Brief profile (in case of appointment) Mrs. Jyothsana Vasudevan (47 years) has experience spanning over 24 years.
In her last assignment she was working as a Sr. Vice President & Head HR at Avaada Manufacturing which is in the renewable energy business.
"""

JAGDISHAN = """
Mr. Sashidhar Jagdishan has vacated the office as the MD & CEO of the Bank.
Mr. Anup Bagchi has assumed charge as MD & CEO of the Bank effective today.
"""


def test_noise_stays_filed_away():
    kind = classify("Copy of Newspaper Publication", "Financial results for the quarter")
    assert kind.category == "unclassified"
    assert bucket(score_filing(kind, {"results"})) == "away"


def test_results_wake_you():
    kind = classify("Outcome of Board Meeting", "submitted the financial results for the period ended September 30, 2026")
    assert kind.category == "results"
    assert bucket(score_filing(kind, {"results"})) == "now"


def test_reaffirmed_rating_does_not_wake_you():
    kind = classify("Credit Rating", "S&P reaffirmed the rating with a stable outlook")
    assert kind.category == "credit_rating"
    assert kind.tier == "reaffirm"
    assert bucket(score_filing(kind, {"credit_rating"})) == "glance"


def test_downgrade_does():
    kind = classify("Credit Rating", "CRISIL downgraded the long-term rating")
    assert kind.tier == "downgrade"
    assert bucket(score_filing(kind, {"credit_rating"})) == "now"


def test_md_change_is_material_and_a_vague_one_is_not():
    sharp = classify("General Updates", "Change in Managing Director and Chief Executive Officer of the Bank")
    assert sharp.category == "management_change"
    assert sharp.tier == "kmp"
    vague = classify("Change in Management", "has informed the Exchange about change in Management")
    assert vague.tier == "vague"
    assert bucket(score_filing(vague, {"management_change"})) == "glance"


def test_srivatsan_comes_from_the_filing_not_from_memory():
    people = extract_people(SRIVATSAN)
    assert people
    person = people[0]
    assert "Srivatsan" in person["name"]
    assert person["previous_org"]
    assert org_match(person["previous_org"], "ICICI Bank Limited")


def test_previous_employer_survives_an_abbreviation_inside_the_sentence():
    people = extract_people(JYOTHSANA)
    person = next(item for item in people if "Jyothsana" in item["name"])
    assert org_match(person["previous_org"], "Avaada Manufacturing")


def test_the_person_who_left_does_not_inherit_the_new_hire_employer():
    people = extract_people(JAGDISHAN)
    left = next(item for item in people if "Jagdishan" in item["name"])
    joined = next(item for item in people if "Bagchi" in item["name"])
    assert left["action"] == "left"
    assert joined["action"] == "joined"
    assert not left["previous_org"]


def test_one_line_strips_exchange_boilerplate():
    raw = "Pidilite Industries Limited has submitted to the Exchange, the financial results for the period ended September 30, 2026."
    assert one_line(raw).startswith("The financial results")


def test_indian_grouping_and_percent():
    assert indian(231886) == "2,31,886"
    assert indian(1234) == "1,234"
    assert format_pct(-3.141) == "−3.1%"
    assert format_pct(pct_change(110, 100)) == "+10.0%"


def test_quarter_math_uses_the_same_quarter_last_year():
    statements = {
        "quarters": {
            "columns": [
                {"label": "Sep 2025", "date": "2025-09-30"},
                {"label": "Dec 2025", "date": "2025-12-31"},
                {"label": "Mar 2026", "date": "2026-03-31"},
                {"label": "Jun 2026", "date": "2026-06-30"},
                {"label": "Sep 2026", "date": "2026-09-30"},
            ],
            "rows": {
                "Sales": [100, 110, 120, 130, 121],
                "Operating Profit": [20, 22, 24, 26, 22],
                "Profit before tax": [15, 16, 17, 18, 16],
                "Net Profit": [10, 11, 12, 13, 11],
                "OPM %": [20, 20, 20, 20, 18.2],
            },
        }
    }
    snap = quarter_snapshot(statements)
    assert snap["period"] == "Sep 2026"
    assert round(snap["revenue"]["yoy"], 1) == 21.0
    assert round(snap["revenue"]["qoq"], 1) == -6.9
    assert snap["operating_label"] == "EBITDA"


def test_a_reported_growth_rate_is_not_guidance():
    quotes = guidance_sentences("Standalone revenues grew by 22.2% with an underlying volume growth of 11.3%.", "Jul 2026")
    assert quotes == []


def test_esop_allotment_is_routine():
    kind = classify("General Updates", "Allotment of 37750 securities pursuant to ESOP at its meeting")
    assert kind.category == "unclassified"


def test_guidance_verdict_needs_a_number():
    quotes = guidance_sentences(
        "We expect margins to stay in the 18 to 20 percent range for the year. Demand is fine.",
        "Jul 2026",
    )
    assert quotes and quotes[0]["metric"] == "margin"
    assert verdict(quotes[0], 19) == "held"
    assert verdict(quotes[0], 14) == "short"
    assert verdict({"low": None, "high": None}, 19) is None


def test_network_matches_the_prior_employer_named_in_the_filing():
    network = {
        "people": [
            {
                "id": "ishita",
                "name": "Ishita Banerjee",
                "roles": [{"org": "ICICI Bank", "symbol": "ICICIBANK", "aliases": ["ICICI Bank Limited"], "title": "Corporate banking", "from": 2017, "to": None}],
                "themes": ["banks"],
                "last_touch": "2026-10-02",
            },
            {
                "id": "adil",
                "name": "Adil Merchant",
                "roles": [{"org": "HDFC Bank", "symbol": "HDFCBANK", "aliases": ["HDFC Bank Limited"], "title": "Business banking", "from": 2014, "to": 2023}],
                "themes": ["banks"],
                "last_touch": "2025-05-02",
            },
        ]
    }
    universe = {"portfolio": [{"symbol": "HDFCBANK", "name": "HDFC Bank", "themes": ["banks"], "related": {}}], "research": []}
    ranked = rank_contacts(
        network,
        universe,
        "HDFCBANK",
        category="management_change",
        filing_text="Prior to joining the Bank he served at ICICI Bank Limited.",
        previous_orgs=["ICICI Bank Limited"],
        filing_year=2026,
        today=datetime.fromisoformat("2026-11-09T12:00:00+05:30"),
    )
    assert ranked[0]["id"] == "ishita"
    assert ranked[0]["strength"] == "same institution"
    assert "not a confirmed introduction" in ranked[0]["reasons"][0]


def test_a_lender_is_not_labelled_ebitda():
    statements = {
        "quarters": {
            "columns": [{"label": "Sep 2026", "date": "2026-09-30"}],
            "rows": {"Revenue": [100], "Financing Profit": [40], "Profit before tax": [30], "Net Profit": [22], "Financing Margin %": [40]},
        }
    }
    snap = quarter_snapshot(statements)
    assert snap["lender"] is True
    assert snap["operating_label"] == "Financing profit"


def test_brief_window_hides_old_filings_and_keeps_fridays_move():
    universe = {"investor": "Meera Shah", "portfolio": [{"symbol": "PIDILITIND", "name": "Pidilite", "themes": [], "related": {}}], "research": []}
    filings = {
        "PIDILITIND": [
            {"seq": "1", "symbol": "PIDILITIND", "desc": "Outcome of Board Meeting", "text": "the financial results for the period ended September 30, 2026", "when": "05-Nov-2026 18:54:17", "url": "http://example"},
            {"seq": "2", "symbol": "PIDILITIND", "desc": "Copy of Newspaper Publication", "text": "Financial Results", "when": "09-Nov-2026 09:00:00", "url": "http://example"},
        ]
    }
    prices = {"PIDILITIND": [{"date": f"2026-10-{day:02d}", "close": 90, "prev": 90, "volume": 4} for day in range(1, 21)] + [{"date": "2026-11-06", "close": 100, "prev": 90, "volume": 10}]}
    # The fabricated October dates are only there so a volume average exists. The move uses prev close.
    payload = build_brief(
        universe=universe,
        network={"people": []},
        filings=filings,
        statements={},
        prices=prices,
        profiles={},
        window="24h",
        now=datetime.fromisoformat("2026-11-09T12:00:00+05:30"),
    )
    assert payload["now"] == []
    assert payload["away"]["count"] == 1
    assert payload["aside"]["name"] == "Pidilite"
    assert payload["alerts"] and payload["alerts"][0]["price_hit"]
