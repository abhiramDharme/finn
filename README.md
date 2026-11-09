# FINN

A morning desk for one public-markets investor. It reads exchange filings and the company's own reports, and it says who in her notebook can help her understand them.

The desk has three places:

- **Brief** — what changed, with the routine filings put away. Last close is watched against a line she sets.
- **Company** — a memo from the primary documents: the statements, the annual report, the concalls. Promised versus printed, only when management actually named a number.
- **People** — not a contact list. Who can tell her something the filing can't, and how strong that link is.

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server.app:app --port 8000
```

The desk is live at https://finn-lilac-xi.vercel.app — open it on a phone.

Locally:

To read the book again from the exchanges:

```bash
python -m finn.pipeline
```

A symbol that isn't in the book can still be opened. The same engine fetches it. The first time takes about a minute.

## Tests

```bash
pytest
```

The tests cover classification, the person pulled out of a filing, quarter maths, guidance that is not a reported growth rate, and the network match on a prior employer named in the document.
