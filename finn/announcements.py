from __future__ import annotations

import logging
from datetime import datetime, timedelta

from finn.http import session
from finn.textutil import IST

log = logging.getLogger("finn.announcements")
URL = "https://www.nseindia.com/api/corporate-announcements"


def fetch_symbol(symbol: str, days: int = 120) -> list[dict]:
    client = session()
    client.headers["Accept"] = "application/json"
    client.headers["Referer"] = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
    end = datetime.now(IST).date()
    start = end - timedelta(days=days)
    response = client.get(
        URL,
        params={
            "index": "equities",
            "symbol": symbol,
            "from_date": start.strftime("%d-%m-%Y"),
            "to_date": end.strftime("%d-%m-%Y"),
        },
        timeout=40,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        log.warning("unexpected announcements payload for %s", symbol)
        return []
    filings = []
    for item in payload:
        filings.append(
            {
                "seq": item.get("seq_id"),
                "symbol": item.get("symbol") or symbol,
                "company": item.get("sm_name"),
                "desc": item.get("desc") or "",
                "text": item.get("attchmntText") or "",
                "when": item.get("an_dt") or item.get("sort_date"),
                "url": item.get("attchmntFile"),
                "industry": item.get("smIndustry"),
            }
        )
    filings.sort(key=lambda filing: filing.get("when") or "")
    return filings
