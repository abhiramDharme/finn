from __future__ import annotations

import io
import logging
import re
import zipfile

from pypdf import PdfReader

from finn.guidance import guidance_sentences
from finn.http import session
from finn.people_extract import extract_people

log = logging.getLogger("finn.documents")


def pdf_text(url: str, max_pages: int = 30, timeout: int = 40) -> str:
    client = session()
    response = client.get(url, timeout=timeout)
    response.raise_for_status()
    content = response.content
    if content[:2] == b"PK":
        content = _first_pdf(content)
    if not content or not content.startswith(b"%PDF"):
        raise ValueError("not a pdf")
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for page in reader.pages[:max_pages]:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _first_pdf(blob: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for name in archive.namelist():
            if name.lower().endswith(".pdf"):
                return archive.read(name)
    return b""


def business_blurb(text: str) -> str | None:
    from finn.textutil import unspace

    cleaned = unspace(text or "")
    picked = []
    for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
        sentence = re.sub(r"^[\d\s.&]+", "", sentence.strip())
        if len(sentence) < 90 or len(sentence) > 420:
            continue
        if re.search(
            r"\b(registered office|CIN|pursuant|notice is hereby|BSE Limited|shareholder|tax residence|certificate|members may|listing regulations|resolved that|shareholding|related party|annual general meeting|as on march|forward-looking|no assurance)\b",
            sentence,
            re.I,
        ):
            continue
        if re.search(r"\b(is a |is an |engaged in|manufactur|operates|our business|we are (?:a|an|the|one)|leading )\b", sentence, re.I):
            picked.append(sentence)
        if len(picked) == 2:
            break
    return " ".join(picked) or None


def read_management_pdf(url: str) -> dict:
    try:
        text = pdf_text(url, max_pages=4, timeout=30)
    except Exception as exc:  # noqa: BLE001
        log.info("management pdf failed %s", exc)
        return {"text": "", "people": [], "error": str(exc)}
    return {"text": text[:8000], "people": extract_people(text)}


def read_primary(documents: dict, announcement_pdfs: list[dict] | None = None) -> dict:
    """Annual-report opening and the last few concalls. Primary documents only."""
    warnings = []
    annual_text = ""
    annual_meta = None
    reports = documents.get("annual_reports") or []
    if reports:
        report = reports[0]
        try:
            annual_text = pdf_text(report["url"], max_pages=18, timeout=50)
            annual_meta = {"label": report["label"], "url": report["url"], "pages": 18}
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Annual report: {exc.__class__.__name__}")
            log.info("annual report failed: %s", exc)
    transcripts = []
    concalls = [item for item in documents.get("concalls") or [] if item.get("kind") == "transcript"][:4]
    nse_fallback = [item for item in (announcement_pdfs or []) if "transcript" in (item.get("text") or "").lower()]
    sources = concalls or nse_fallback[:4]
    for item in sources:
        try:
            text = pdf_text(item["url"], max_pages=16, timeout=40)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Transcript {item.get('label') or ''}: {exc.__class__.__name__}")
            continue
        label = item.get("label") or "Concall"
        transcripts.append(
            {
                "label": label,
                "url": item["url"],
                "text": text[:50000],
                "guidance": guidance_sentences(text, label),
            }
        )
    blurb = business_blurb(annual_text) or business_blurb("\n".join(item["text"][:4000] for item in transcripts))
    chunks = []
    if annual_text:
        chunks.extend(_chunks(annual_text, annual_meta["label"] if annual_meta else "Annual report", annual_meta["url"] if annual_meta else None))
    for item in transcripts:
        chunks.extend(_chunks(item["text"], f"Concall {item['label']}", item["url"]))
    return {
        "blurb": blurb,
        "annual": annual_meta,
        "transcripts": [{k: v for k, v in item.items() if k != "text"} | {"chars": len(item["text"])} for item in transcripts],
        "guidance": [quote for item in transcripts for quote in item["guidance"]],
        "chunks": chunks[:80],
        "warnings": warnings,
        "auditor": _auditor_note(annual_text),
    }


def _chunks(text: str, source: str, url: str | None, size: int = 700) -> list[dict]:
    words = re.sub(r"\s+", " ", text).split()
    chunks = []
    bucket: list[str] = []
    length = 0
    for word in words:
        bucket.append(word)
        length += len(word) + 1
        if length >= size:
            chunks.append({"source": source, "url": url, "text": " ".join(bucket)})
            bucket = []
            length = 0
    if bucket:
        chunks.append({"source": source, "url": url, "text": " ".join(bucket)})
    return chunks


def _auditor_note(text: str) -> str | None:
    if not text:
        return None
    if re.search(r"basis for qualified opinion|qualified opinion", text, re.I):
        return "The pages read include an auditor's qualified opinion. That is a reason to open the report, not a footnote."
    return None
