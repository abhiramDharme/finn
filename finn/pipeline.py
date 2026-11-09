from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone

from finn.announcements import fetch_symbol
from finn.classify import classify
from finn.documents import read_management_pdf, read_primary
from finn.paths import CACHE, DATA
from finn.prices import fetch_sessions
from finn.screener import fetch_company

log = logging.getLogger("finn")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FINN's local cache from public filings.")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--skip-docs", action="store_true")
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--prices-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    CACHE.mkdir(parents=True, exist_ok=True)
    universe = json.loads((DATA / "universe.json").read_text())
    symbols = args.symbols or [company["symbol"] for company in universe["portfolio"] + universe["research"]]

    if not args.skip_prices:
        log.info("fetching NSE bhavcopies")
        prices = fetch_sessions()
        _write("prices.json", prices)
        log.info("prices %s symbols", len(prices))
        if args.prices_only:
            return

    filings = _read("filings.json", {})
    statements = _read("statements.json", {})
    docs = _read("docs.json", {})
    profiles = _read("profiles.json", {})

    for symbol in symbols:
        log.info("filings %s", symbol)
        try:
            filings[symbol] = fetch_symbol(symbol)
        except Exception as exc:  # noqa: BLE001
            log.warning("filings %s failed: %s", symbol, exc)
        time.sleep(0.25)
    _write("filings.json", filings)

    for symbol in symbols:
        if symbol in statements and not args.symbols:
            # Still refresh. The book is the product. A stale statement is a wrong number.
            pass
        log.info("statements %s", symbol)
        try:
            company = fetch_company(symbol)
            statements[symbol] = company
        except Exception as exc:  # noqa: BLE001
            log.warning("statements %s failed: %s", symbol, exc)
        time.sleep(0.4)
        _write("statements.json", statements)

    for symbol in symbols:
        for filing in filings.get(symbol) or []:
            kind = classify(filing.get("desc"), filing.get("text"))
            if kind.category != "management_change" or not filing.get("url"):
                continue
            key = f"{symbol}-{filing.get('seq')}"
            if key in profiles and profiles[key].get("text"):
                continue
            log.info("profile %s", key)
            profiles[key] = read_management_pdf(filing["url"])
            time.sleep(0.2)
    _write("profiles.json", profiles)

    if not args.skip_docs:
        for symbol in symbols:
            record = statements.get(symbol) or {}
            documents = record.get("documents") or {}
            announcement_pdfs = [
                {"url": filing["url"], "text": filing.get("text") or "", "label": (filing.get("when") or "")[:11]}
                for filing in filings.get(symbol) or []
                if filing.get("url")
            ]
            log.info("documents %s", symbol)
            try:
                docs[symbol] = read_primary(documents, announcement_pdfs)
                docs[symbol]["segments"] = record.get("segments") or []
            except Exception as exc:  # noqa: BLE001
                log.warning("documents %s failed: %s", symbol, exc)
            _write("docs.json", docs)

    _write("meta.json", {"built_at": datetime.now(timezone.utc).isoformat(), "symbols": symbols})
    log.info("cache ready")


def _write(name: str, payload) -> None:
    path = CACHE / name
    path.write_text(json.dumps(payload, ensure_ascii=False))


def _read(name: str, default):
    path = CACHE / name
    if not path.exists():
        return default
    return json.loads(path.read_text())


if __name__ == "__main__":
    main()
