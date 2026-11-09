from __future__ import annotations

import json
from datetime import datetime

from finn.ask import answer
from finn.brief import build_brief
from finn.network import expertise, person_detail, search_people
from finn.paths import CACHE, DATA
from finn.research import build_memo
from finn.textutil import IST


class Library:
    def __init__(self) -> None:
        self.universe = json.loads((DATA / "universe.json").read_text())
        self.network = json.loads((DATA / "network.json").read_text())
        self.prices: dict = {}
        self.filings: dict = {}
        self.statements: dict = {}
        self.docs: dict = {}
        self.profiles: dict = {}
        self.loaded_at: str | None = None
        self.reload()

    def reload(self) -> None:
        self.prices = _read("prices.json", {})
        self.filings = _read("filings.json", {})
        self.statements = _read("statements.json", {})
        self.docs = _read("docs.json", {})
        self.profiles = _read("profiles.json", {})
        meta = _read("meta.json", {})
        self.loaded_at = meta.get("built_at")

    def symbols(self) -> dict[str, dict]:
        book = {}
        for group in ("portfolio", "research"):
            for company in self.universe[group]:
                book[company["symbol"]] = {**company, "book": group}
        return book

    def brief(self, window: str, price_pct: float, volume_x: float, wake: list[str] | None) -> dict:
        payload = build_brief(
            universe=self.universe,
            network=self.network,
            filings=self.filings,
            statements=self.statements,
            prices=self.prices,
            profiles=self.profiles,
            window=window,
            price_pct=price_pct,
            volume_x=volume_x,
            wake=wake,
            now=datetime.now(IST),
        )
        payload["built_at"] = self.loaded_at
        payload["portfolio"] = [
            {"symbol": company["symbol"], "name": company["name"], "sector": company["sector"]}
            for company in self.universe["portfolio"]
        ]
        payload["research"] = [
            {"symbol": company["symbol"], "name": company["name"], "sector": company["sector"]}
            for company in self.universe["research"]
        ]
        return payload

    def memo(self, symbol: str) -> dict:
        symbol = symbol.upper().strip()
        known = self.symbols().get(symbol)
        statements = self.statements.get(symbol)
        if not statements:
            raise KeyError(symbol)
        docs = self.docs.get(symbol) or {}
        # Segments are stored on the statement record by the pipeline.
        return build_memo(
            symbol,
            known,
            statements,
            docs,
            self.prices.get(symbol),
            self.network,
            self.universe,
            in_portfolio=bool(known and known["book"] == "portfolio"),
        )

    def ask(self, symbol: str, question: str) -> dict:
        symbol = symbol.upper().strip()
        docs = self.docs.get(symbol) or {}
        known = self.symbols().get(symbol)
        name = (known or {}).get("name") or (self.statements.get(symbol) or {}).get("name") or symbol
        return answer(question, docs.get("chunks") or [], name)

    def people(self, query: str = "", symbol: str | None = None) -> dict:
        from finn.network import rank_contacts

        calls = []
        if symbol:
            calls = rank_contacts(self.network, self.universe, symbol.upper(), limit=4)
        return {
            "investor": self.network.get("investor"),
            "source": self.network.get("source"),
            "expertise": expertise(self.network),
            "calls": calls,
            "results": search_people(self.network, query) if query else [],
            "reconnect_hint": "A name goes quiet. A company they know does something. That is the reason to write.",
        }

    def person(self, person_id: str) -> dict | None:
        person = person_detail(self.network, person_id)
        if not person:
            return None
        symbols = []
        for role in person.get("roles") or []:
            if role.get("symbol"):
                symbols.append(role["symbol"])
        recent = []
        for symbol in symbols:
            for filing in (self.filings.get(symbol) or [])[-6:]:
                recent.append(
                    {
                        "symbol": symbol,
                        "when": filing.get("when"),
                        "desc": filing.get("desc"),
                        "text": (filing.get("text") or "")[:180],
                    }
                )
        return {"person": person, "recent": recent[-5:]}


def _read(name: str, default):
    path = CACHE / name
    if not path.exists():
        return default
    return json.loads(path.read_text())
