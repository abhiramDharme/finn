from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from finn.library import Library
from finn.paths import WEB

library = Library()
app = FastAPI(title="FINN")


class AskBody(BaseModel):
    symbol: str
    question: str = Field(min_length=2, max_length=400)


@app.post("/api/reload")
def reload_cache():
    library.reload()
    return {"ok": True, "companies": len(library.statements), "built_at": library.loaded_at}


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "built_at": library.loaded_at,
        "companies": len(library.statements),
        "filings": sum(len(items) for items in library.filings.values()),
    }


@app.get("/api/brief")
def brief(window: str = "24h", price: float = 3, volume: float = 2, wake: str | None = None):
    selected = [item for item in (wake or "").split(",") if item] or None
    return library.brief(window, price, volume, selected)


@app.get("/api/company/{symbol}")
def company(symbol: str):
    try:
        return library.memo(symbol)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No statements cached for {symbol}.") from None


@app.post("/api/ask")
def ask(body: AskBody):
    if body.symbol.upper() not in library.statements:
        raise HTTPException(status_code=404, detail="Load the company before asking its filings.")
    return library.ask(body.symbol, body.question)


@app.get("/api/network")
def network(q: str = "", symbol: str | None = None):
    return library.people(q, symbol)


@app.get("/api/person/{person_id}")
def person(person_id: str):
    found = library.person(person_id)
    if not found:
        raise HTTPException(status_code=404, detail="No one by that id in the notebook.")
    return found


@app.post("/api/live/{symbol}")
def live(symbol: str):
    """Pull one ticker that isn't in the cache. Same engine as the book."""
    from finn.announcements import fetch_symbol
    from finn.classify import classify
    from finn.documents import read_management_pdf, read_primary
    from finn.screener import fetch_company

    symbol = symbol.upper().strip()
    try:
        statements = fetch_company(symbol)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Couldn't read Screener: {exc}") from exc
    try:
        filings = fetch_symbol(symbol, days=150)
    except Exception:
        filings = []
    profiles = {}
    for filing in filings:
        kind = classify(filing.get("desc"), filing.get("text"))
        if kind.category == "management_change" and filing.get("url"):
            profiles[f"{symbol}-{filing.get('seq')}"] = read_management_pdf(filing["url"])
    docs = read_primary(
        statements.get("documents") or {},
        [{"url": filing["url"], "text": filing.get("text") or "", "label": (filing.get("when") or "")[:11]} for filing in filings if filing.get("url")],
    )
    library.statements[symbol] = statements
    library.filings[symbol] = filings
    library.docs[symbol] = docs
    library.profiles.update(profiles)
    if symbol not in library.prices:
        library.prices[symbol] = []
    return library.memo(symbol)


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
