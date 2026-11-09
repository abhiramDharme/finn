from __future__ import annotations

import logging
from datetime import datetime, timedelta

from finn.http import session
from finn.textutil import IST

log = logging.getLogger("finn.prices")

BHAV = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{stamp}.csv"


def fetch_sessions(days: int = 46, need: int = 22) -> dict[str, list[dict]]:
    """Official NSE end-of-day prints. One file is the whole cash market."""
    client = session()
    today = datetime.now(IST).date()
    sessions: list[tuple[str, dict[str, dict]]] = []
    for offset in range(days):
        if len(sessions) >= need:
            break
        day = today - timedelta(days=offset)
        stamp = day.strftime("%d%m%Y")
        try:
            response = client.get(BHAV.format(stamp=stamp), timeout=25)
        except Exception as exc:  # noqa: BLE001 - a missing day should not kill the book
            log.info("bhav %s failed: %s", stamp, exc)
            continue
        if response.status_code != 200 or "SYMBOL" not in response.text[:200]:
            continue
        book = _parse(response.text)
        if book:
            sessions.append((day.isoformat(), book))
            log.info("bhav %s symbols %s", day.isoformat(), len(book))
    sessions.reverse()
    series: dict[str, list[dict]] = {}
    for iso, book in sessions:
        for symbol, row in book.items():
            series.setdefault(symbol, []).append(
                {
                    "date": iso,
                    "close": row["close"],
                    "prev": row["prev"],
                    "volume": row["volume"],
                }
            )
    return series


def _parse(text: str) -> dict[str, dict]:
    lines = text.splitlines()
    if not lines:
        return {}
    header = [part.strip() for part in lines[0].split(",")]
    index = {name: position for position, name in enumerate(header)}
    needed = ("SYMBOL", "SERIES", "CLOSE_PRICE", "PREV_CLOSE", "TTL_TRD_QNTY")
    if any(name not in index for name in needed):
        return {}
    book = {}
    for line in lines[1:]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) <= index["TTL_TRD_QNTY"]:
            continue
        if parts[index["SERIES"]] != "EQ":
            continue
        symbol = parts[index["SYMBOL"]]
        try:
            book[symbol] = {
                "close": float(parts[index["CLOSE_PRICE"]]),
                "prev": float(parts[index["PREV_CLOSE"]]),
                "volume": float(parts[index["TTL_TRD_QNTY"]]),
            }
        except ValueError:
            continue
    return book


def is_short_session(series: list[dict]) -> bool:
    """A muhurat or other thin print: volume under half the recent average."""
    if len(series) < 6 or not series[-1].get("volume"):
        return False
    prior = [point["volume"] for point in series[:-1][-10:] if point.get("volume")]
    if len(prior) < 5:
        return False
    return series[-1]["volume"] < 0.45 * (sum(prior) / len(prior))


def latest_move(series: list[dict]) -> dict | None:
    if not series:
        return None
    skipped = None
    if is_short_session(series):
        skipped = series[-1]["date"]
        series = series[:-1]
    if not series:
        return None
    last = series[-1]
    prev_close = last.get("prev")
    if prev_close in (None, 0):
        prev_close = series[-2]["close"] if len(series) > 1 else None
    pct = None
    if prev_close:
        pct = (last["close"] - prev_close) / prev_close * 100
    volumes = [point["volume"] for point in series[:-1] if point.get("volume")]
    base = volumes[-20:]
    average = sum(base) / len(base) if len(base) >= 8 else None
    multiple = (last["volume"] / average) if average else None
    return {
        "date": last["date"],
        "close": last["close"],
        "pct": pct,
        "volume": last["volume"],
        "vol_x": multiple,
        "skipped_short_session": skipped,
    }
