from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from finn.http import session
from finn.statements import parse_segments, parse_statements

log = logging.getLogger("finn.screener")


def search(query: str) -> list[dict]:
    client = session()
    response = client.get(
        "https://www.screener.in/api/company/search/",
        params={"q": query},
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        timeout=20,
    )
    response.raise_for_status()
    hits = []
    for item in response.json():
        url = item.get("url") or ""
        symbol = url.strip("/").split("/")[1] if "/company/" in url else None
        hits.append({"id": item.get("id"), "name": item.get("name"), "url": url, "symbol": symbol})
    return hits


def resolve(symbol: str) -> dict | None:
    symbol = symbol.upper().strip()
    for hit in search(symbol):
        if (hit.get("symbol") or "").upper() == symbol:
            return hit
    return None


def fetch_company(symbol: str) -> dict:
    hit = resolve(symbol)
    if not hit:
        raise LookupError(f"No company on Screener for {symbol}")
    client = session()
    page_url = "https://www.screener.in" + hit["url"]
    response = client.get(page_url, timeout=30)
    response.raise_for_status()
    parsed = parse_statements(response.text)
    soup = BeautifulSoup(response.text, "html.parser")
    documents = _documents(soup)
    segments = []
    if parsed.get("company_id"):
        consolidated = "true" if "/consolidated/" in hit["url"] else "false"
        try:
            segment_response = client.get(
                f"https://www.screener.in/api/segments/{parsed['company_id']}/quarters/1/",
                params={"consolidated": consolidated} if consolidated == "true" else None,
                headers={"X-Requested-With": "XMLHttpRequest", "Referer": page_url},
                timeout=20,
            )
            if segment_response.ok:
                segments = parse_segments(segment_response.text)
        except Exception as exc:  # noqa: BLE001
            log.info("segments %s: %s", symbol, exc)
    return {
        "symbol": symbol.upper(),
        "screener_url": page_url,
        "screener_id": hit.get("id"),
        "documents": documents,
        "segments": segments,
        **parsed,
    }


def _documents(soup: BeautifulSoup) -> dict:
    annual = []
    for link in soup.select(".annual-reports a"):
        href = link.get("href") or ""
        label = link.get_text(" ", strip=True)
        if href.startswith("http") and "Annual Report" in label:
            annual.append({"label": label, "url": href})
    transcripts = []
    concalls = soup.select_one(".documents.concalls")
    if concalls:
        for item in concalls.select("li"):
            label = ""
            stamp = item.select_one(".ink-600")
            if stamp:
                label = stamp.get_text(" ", strip=True)
            for link in item.select("a"):
                title = (link.get("title") or link.get_text(" ", strip=True) or "").lower()
                href = link.get("href") or ""
                if not href.startswith("http"):
                    continue
                if "transcript" in title:
                    transcripts.append({"label": label, "url": href, "kind": "transcript"})
                elif title.strip() in {"ppt", "presentation"} or "presentation" in title:
                    transcripts.append({"label": label, "url": href, "kind": "presentation"})
    return {"annual_reports": annual[:2], "concalls": transcripts[:8]}
