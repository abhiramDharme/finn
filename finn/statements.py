from __future__ import annotations

import re

from bs4 import BeautifulSoup

from finn.textutil import indian, parse_number, pct_change


def _section_table(soup: BeautifulSoup, section_id: str):
    section = soup.select_one(f"#{section_id}")
    if not section:
        return None
    return section.select_one("table.data-table")


def parse_table(table) -> dict:
    if table is None:
        return {"columns": [], "rows": {}}
    columns = []
    for th in table.select("thead th")[1:]:
        columns.append(
            {
                "label": re.sub(r"\s+", " ", th.get_text(" ", strip=True)),
                "date": th.get("data-date-key"),
            }
        )
    rows: dict[str, list] = {}
    for tr in table.select("tbody tr"):
        classes = " ".join(tr.get("class") or [])
        if "hidden" in classes:
            continue
        cells = tr.select("td")
        if len(cells) < 2:
            continue
        name = re.sub(r"\s+", " ", cells[0].get_text(" ", strip=True))
        name = name.replace("+", "").strip()
        if not name or name.lower() == "raw pdf":
            continue
        rows[name] = [parse_number(td.get_text(" ", strip=True)) for td in cells[1:]]
    return {"columns": columns, "rows": rows}


def parse_statements(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    name_node = soup.select_one("h1")
    name = re.sub(r"\s+", " ", name_node.get_text(" ", strip=True)) if name_node else ""
    company_id = None
    info = soup.select_one("#company-info")
    if info:
        company_id = info.get("data-company-id")
    about = {
        "quarters": parse_table(_section_table(soup, "quarters")),
        "annual": parse_table(_section_table(soup, "profit-loss")),
        "balance": parse_table(_section_table(soup, "balance-sheet")),
        "cash": parse_table(_section_table(soup, "cash-flow")),
        "ratios": parse_table(_section_table(soup, "ratios")),
    }
    top = {}
    for li in soup.select("#top li"):
        key = re.sub(r"\s+", " ", (li.select_one(".name") or li).get_text(" ", strip=True))
        value = re.sub(r"\s+", " ", (li.select_one(".value") or li).get_text(" ", strip=True))
        if key and value and key != value:
            top[key] = value
    return {"name": name, "company_id": company_id, "top": top, **about}


def parse_segments(html: str) -> list[dict]:
    """Segment names are public. The rupee split is often behind a paywall, so it is omitted rather than guessed."""
    soup = BeautifulSoup(html, "html.parser")
    block = soup.select_one('[data-segment-line="Sales"]')
    labels = []
    scope = block or soup
    for cell in scope.select("td.text"):
        label = re.sub(r"\s+", " ", cell.get_text(" ", strip=True))
        if not label or label.lower() in {"sales", "unallocated", "less: intersegment", "sales growth %"}:
            continue
        if label not in labels:
            labels.append(label)
    return [{"name": label} for label in labels[:6]]


def _row(table: dict, *names: str) -> list | None:
    rows = table.get("rows") or {}
    for name in names:
        if name in rows:
            return rows[name]
    folded = {key.lower(): value for key, value in rows.items()}
    for name in names:
        if name.lower() in folded:
            return folded[name.lower()]
    return None


def _latest_index(values: list) -> int | None:
    for index in range(len(values) - 1, -1, -1):
        if values[index] is not None:
            return index
    return None


def series_points(table: dict, row_name: str, limit: int = 6, skip_ttm: bool = True) -> list[dict]:
    row = _row(table, row_name)
    if not row:
        return []
    points = []
    for column, value in zip(table.get("columns") or [], row):
        label = column.get("label") or ""
        if skip_ttm and label.upper() == "TTM":
            continue
        if value is None:
            continue
        points.append({"label": label, "date": column.get("date"), "value": value})
    return points[-limit:]


def quarter_snapshot(statements: dict) -> dict | None:
    quarters = statements.get("quarters") or {}
    columns = quarters.get("columns") or []
    revenue = _row(quarters, "Sales", "Revenue")
    operating = _row(quarters, "Operating Profit", "Financing Profit")
    margin = _row(quarters, "OPM %", "Financing Margin %")
    pbt = _row(quarters, "Profit before tax")
    pat = _row(quarters, "Net Profit")
    npa = _row(quarters, "Gross NPA %")
    net_npa = _row(quarters, "Net NPA %")
    if not revenue or not pat:
        return None
    index = _latest_index(revenue)
    if index is None:
        return None
    lender = _row(quarters, "Financing Profit") is not None

    def pack(row):
        if not row or index >= len(row):
            return None
        current = row[index]
        previous = row[index - 1] if index - 1 >= 0 else None
        year_ago = _year_ago(columns, row, index)
        return {
            "value": current,
            "qoq": pct_change(current, previous),
            "yoy": pct_change(current, year_ago),
            "previous": previous,
            "year_ago": year_ago,
        }

    period = columns[index]["label"] if index < len(columns) else ""
    operating_pack = pack(operating)
    if lender and operating_pack and (operating_pack.get("value") or 0) < 0:
        operating_pack = None
    return {
        "period": period,
        "date": columns[index].get("date") if index < len(columns) else None,
        "lender": lender,
        "revenue": pack(revenue),
        "operating": operating_pack,
        "operating_label": "Financing profit" if lender else "EBITDA",
        "operating_note": (
            "Lenders don't report EBITDA. The financing-profit line isn't comparable here, so it isn't shown."
            if lender and operating_pack is None
            else "Lenders don't report EBITDA. This is financing profit from the results statement."
            if lender
            else "Operating profit from the results statement — the EBITDA line Indian filings are read by, before other income, interest, depreciation and tax."
        ),
        "margin": pack(margin),
        "pbt": pack(pbt),
        "pat": pack(pat),
        "gross_npa": pack(npa),
        "net_npa": pack(net_npa),
        "unit": "₹ cr",
    }


def _year_ago(columns: list, row: list, index: int):
    current = columns[index].get("date") if index < len(columns) else None
    if not current:
        # Fall back four columns, which is a year of quarters when none are missing.
        ago = index - 4
        return row[ago] if ago >= 0 and ago < len(row) else None
    year, month, day = current.split("-")
    target = f"{int(year) - 1}-{month}-{day}"
    for position, column in enumerate(columns):
        if column.get("date") == target and position < len(row):
            return row[position]
    ago = index - 4
    return row[ago] if ago >= 0 and ago < len(row) else None


def trajectory_read(statements: dict) -> dict:
    annual = statements.get("annual") or {}
    sales_name = "Sales" if _row(annual, "Sales") else "Revenue"
    sales = series_points(annual, sales_name, limit=6)
    margin_name = "OPM %" if _row(annual, "OPM %") else "Financing Margin %"
    margin = series_points(annual, margin_name, limit=6)
    if any((point.get("value") or 0) < 0 for point in margin):
        margin = []
    pat = series_points(annual, "Net Profit", limit=6)
    read = []
    if len(sales) >= 2 and sales[0]["value"] and sales[-1]["value"] and sales[0]["value"] > 0:
        years = max(len(sales) - 1, 1)
        cagr = (sales[-1]["value"] / sales[0]["value"]) ** (1 / years) - 1
        read.append(
            f"{sales_name} went from {indian(sales[0]['value'])} cr in {sales[0]['label']} to {indian(sales[-1]['value'])} cr in {sales[-1]['label']}, about {cagr * 100:.0f}% a year."
        )
    if len(margin) >= 2 and margin[0]["value"] is not None and margin[-1]["value"] is not None:
        delta = margin[-1]["value"] - margin[0]["value"]
        direction = "wider" if delta > 0.4 else "narrower" if delta < -0.4 else "about flat"
        read.append(
            f"Margin is {direction} than in {margin[0]['label']}: {margin[0]['value']:.1f}% then, {margin[-1]['value']:.1f}% in {margin[-1]['label']}."
        )
    return {
        "sales": sales,
        "margin": margin,
        "pat": pat,
        "sales_label": sales_name,
        "read": " ".join(read) or "Not enough annual years to read a direction.",
    }


def balance_read(statements: dict) -> dict:
    balance = statements.get("balance") or {}
    ratios = statements.get("ratios") or {}
    equity_capital = series_points(balance, "Equity Capital", limit=1)
    reserves = series_points(balance, "Reserves", limit=1)
    borrowings = series_points(balance, "Borrowings", limit=4)
    equity = None
    if equity_capital and reserves and equity_capital[-1]["value"] is not None and reserves[-1]["value"] is not None:
        equity = equity_capital[-1]["value"] + reserves[-1]["value"]
    debt = borrowings[-1]["value"] if borrowings else None
    ratio = (debt / equity) if debt is not None and equity else None
    wc = series_points(ratios, "Working Capital Days", limit=4)
    debtor = series_points(ratios, "Debtor Days", limit=1)
    inventory = series_points(ratios, "Inventory Days", limit=1)
    payable = series_points(ratios, "Days Payable", limit=1)
    roce = series_points(ratios, "ROCE %", limit=4)
    read = []
    if ratio is not None:
        read.append(f"Borrowings are {ratio:.2f}× equity ({indian(debt)} cr against {indian(equity)} cr).")
    if len(wc) >= 2:
        delta = wc[-1]["value"] - wc[0]["value"]
        if abs(delta) >= 8:
            way = "longer" if delta > 0 else "shorter"
            read.append(
                f"The cash cycle is {abs(delta):.0f} days {way} than in {wc[0]['label']} ({wc[-1]['value']:.0f} days now)."
            )
        else:
            read.append(f"Working capital is {wc[-1]['value']:.0f} days, close to where it was in {wc[0]['label']}.")
    return {
        "debt": debt,
        "equity": equity,
        "de": ratio,
        "debt_label": borrowings[-1]["label"] if borrowings else None,
        "wc": wc,
        "debtor_days": debtor[-1]["value"] if debtor else None,
        "inventory_days": inventory[-1]["value"] if inventory else None,
        "payable_days": payable[-1]["value"] if payable else None,
        "roce": roce,
        "read": " ".join(read) or "The balance-sheet lines I could read don't support a sharper statement.",
    }


def cash_read(statements: dict) -> dict:
    cash = statements.get("cash") or {}
    annual = statements.get("annual") or {}
    cfo = series_points(cash, "Cash from Operating Activity", limit=5)
    fcf = series_points(cash, "Free Cash Flow", limit=5)
    pat = series_points(annual, "Net Profit", limit=5)
    by_label = {point["label"]: point["value"] for point in pat}
    rows = []
    for point in cfo:
        profit = by_label.get(point["label"])
        conversion = (point["value"] / profit) if profit else None
        flow = next((item["value"] for item in fcf if item["label"] == point["label"]), None)
        rows.append(
            {
                "label": point["label"],
                "cfo": point["value"],
                "pat": profit,
                "fcf": flow,
                "conversion": conversion,
            }
        )
    read = "I don't have a cash-flow line to set against profit."
    if rows and rows[-1]["conversion"] is not None:
        latest = rows[-1]
        ratio = latest["conversion"]
        if ratio >= 0.8:
            judgement = "Profits are reaching cash."
        elif ratio >= 0.4:
            judgement = "A real share of the profit is not showing up as cash."
        elif ratio >= 0:
            judgement = "Accounting profit and cash have diverged."
        else:
            judgement = "The business absorbed cash in a year it reported a profit." if (latest["pat"] or 0) > 0 else "Cash from operations was negative."
        fcf_bit = ""
        if latest["fcf"] is not None:
            fcf_bit = f" Free cash flow was {indian(latest['fcf'])} cr."
        read = (
            f"In {latest['label']}, cash from operations was {indian(latest['cfo'])} cr against profit of {indian(latest['pat'])} cr — {ratio:.0%} converted.{fcf_bit} {judgement}"
        )
    return {"rows": rows, "read": read}


def last_quarters(statements: dict, count: int = 4) -> list[dict]:
    quarters = statements.get("quarters") or {}
    columns = quarters.get("columns") or []
    revenue = _row(quarters, "Sales", "Revenue") or []
    operating = _row(quarters, "Operating Profit", "Financing Profit") or []
    pbt = _row(quarters, "Profit before tax") or []
    pat = _row(quarters, "Net Profit") or []
    margin = _row(quarters, "OPM %", "Financing Margin %") or []
    indexes = [index for index, value in enumerate(revenue) if value is not None]
    chosen = indexes[-count:]
    items = []
    for index in chosen:
        def at(row):
            return row[index] if index < len(row) else None

        items.append(
            {
                "label": columns[index]["label"] if index < len(columns) else "",
                "date": columns[index].get("date") if index < len(columns) else None,
                "revenue": at(revenue),
                "operating": at(operating),
                "pbt": at(pbt),
                "pat": at(pat),
                "margin": at(margin),
                "revenue_yoy": pct_change(at(revenue), _year_ago(columns, revenue, index)),
                "pat_yoy": pct_change(at(pat), _year_ago(columns, pat, index)),
            }
        )
    return items
