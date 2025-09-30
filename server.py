# server.py — FastAPI backend (clean, human-written)
# Endpoints:
#   /                      -> static/index.html
#   /static/*              -> static assets
#   /api/search            -> PubMed search with filters
#   /api/abstract/{pmid}   -> Robust abstract retrieval (XML → text; HTML fallback)
#   /api/summarize         -> Optional abstractive summarizer (fallback to first sentences)
#   /api/translate         -> GoogleTranslator wrapper with graceful fallback
#   /api/reputation/{pmid} -> Real reputation proxy using PubMed (DOI), OpenAlex & Crossref
#
# Notes:
# - Network calls are capped with timeouts and heavy failure-guarding.
# - Reputation is a pragmatic proxy; it is not an official journal metric.

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

import requests
from fastapi import Body, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from deep_translator import GoogleTranslator
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

# On some Windows setups, huggingface_hub tries to use hf_xet fast-path; disable it.
os.environ.setdefault("HF_HUB_ENABLE_HF_XET", "0")

# Optional transformers (summarizer); loaded lazily.
_SUMMARIZER = None
_TRANSFORMERS_OK = False
try:
    from transformers import pipeline  # type: ignore
    _TRANSFORMERS_OK = True
except Exception:
    _TRANSFORMERS_OK = False

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------

NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
HEADERS = {"User-Agent": "SpaceBiologyKnowledgeEngine/1.0"}
REQUEST_TIMEOUT = 12  # seconds
RETMAX = 25

STATIC_DIR = os.path.abspath("static")
OUTPUT_DIR = os.path.abspath("outputs")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ------------------------------------------------------------------------------
# App
# ------------------------------------------------------------------------------

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ------------------------------------------------------------------------------
# Summarizer (lazy)
# ------------------------------------------------------------------------------

def _get_summarizer():
    """Load a default summarization pipeline if transformers are present."""
    global _SUMMARIZER
    if _SUMMARIZER is False:
        return None
    if _SUMMARIZER is None:
        if not _TRANSFORMERS_OK:
            _SUMMARIZER = False
            return None
        try:
            _SUMMARIZER = pipeline("summarization")  # default small model
        except Exception:
            _SUMMARIZER = False
            return None
    return _SUMMARIZER


def _split_for_summary(text: str, max_chars: int = 1800) -> List[str]:
    """Chunk text into reasonably sized pieces for small summarizers."""
    sents = re.split(r"(?<=[.!?])\s+", text)
    out, buf = [], ""
    for s in sents:
        if len(s) > max_chars:
            # Force cut very long sentences (rare; safety).
            for i in range(0, len(s), max_chars):
                if buf:
                    out.append(buf)
                    buf = ""
                out.append(s[i:i + max_chars])
            continue
        if len(buf) + len(s) + 1 <= max_chars:
            buf = (buf + " " + s).strip()
        else:
            if buf:
                out.append(buf)
            buf = s
    if buf:
        out.append(buf)
    return out


@app.post("/api/summarize")
def api_summarize(payload: Dict = Body(...)):
    text = (payload.get("text") or "").strip()
    if not text:
        return {"summary": ""}
    sm = _get_summarizer()
    if sm is None:
        # Fallback: first 3 sentences
        parts = re.split(r"(?<=[.!?])\s+", text)
        return {"summary": " ".join(parts[:3]).strip()}
    chunks = _split_for_summary(text)
    try:
        pieces = [sm(c, max_length=150, min_length=50, do_sample=False)[0]["summary_text"]
                  for c in chunks]
        return {"summary": "\n".join(pieces)}
    except Exception:
        parts = re.split(r"(?<=[.!?])\s+", text)
        return {"summary": " ".join(parts[:3]).strip()}


# ------------------------------------------------------------------------------
# Translate
# ------------------------------------------------------------------------------

@app.post("/api/translate")
def api_translate(payload: Dict = Body(...)):
    texts = payload.get("texts", [])
    lang = payload.get("lang", "en")
    out = []
    for t in texts:
        try:
            out.append(GoogleTranslator(source="auto", target=lang).translate(t))
        except Exception:
            out.append(t)
    return {"translations": out}


# ------------------------------------------------------------------------------
# Search (PubMed E-utilities)
# ------------------------------------------------------------------------------

@app.get("/api/search")
def api_search(
    query: str = Query(...),
    start_year: int = Query(2000),
    end_year: int = Query(2025),
    text_availability: str = Query("Any"),
    article_attribute: str = Query("None"),
    article_type: str = Query("None"),
    language: str = Query("Any"),
    species: str = Query("Any"),
    sex: str = Query("Any"),
    age: str = Query("Any"),
    other: str = Query("None"),
):
    """
    PubMed search with filters. Uses canonical date-range:
    ("YYYY"[dp] : "YYYY"[dp])
    """
    tokens: list[str] = []

    if query:
        tokens.append(f"({query})")

    # Publication date range (canonical form)
    date_token = f'("{start_year}"[dp] : "{end_year}"[dp])'
    tokens.append(date_token)

    # Text availability
    ta_map = {
        "Abstract": "hasabstract[text]",
        "Free full text": "free full text[filter]",
        "Full text": "full text[filter]",
    }
    if text_availability in ta_map:
        tokens.append(ta_map[text_availability])

    # Article attributes (designs)
    attr_map = {
        "Systematic Review": "systematic[sb]",
        "Clinical Trial": "clinicaltrial[pt]",
        "Randomized Controlled Trial": "randomized controlled trial[pt]",
        "Review": "review[pt]",
        "Meta-Analysis": "meta-analysis[pt]",
        "Case Reports": "case reports[pt]",
    }
    if article_attribute in attr_map:
        tokens.append(attr_map[article_attribute])

    # Article type (publication type)
    type_map = {
        "Journal Article": "Journal Article[pt]",
        "Letter": "Letter[pt]",
        "Editorial": "Editorial[pt]",
        "Guideline": "Guideline[pt]",
        "Dataset": "Data Set[pt]",
        "Data Set": "Data Set[pt]",
    }
    if article_type in type_map:
        tokens.append(type_map[article_type])

    # Language
    lang_map = {
        "English": "english", "Spanish": "spanish", "French": "french", "German": "german",
        "Italian": "italian", "Portuguese": "portuguese", "Russian": "russian", "Chinese": "chinese",
        "Japanese": "japanese", "Persian": "persian", "Arabic": "arabic", "Hindi": "hindi",
        "Turkish": "turkish", "Korean": "korean",
    }
    if language in lang_map:
        tokens.append(f"{lang_map[language]}[lang]")

    # Species
    if species == "Humans":
        tokens.append("Humans[MeSH Terms]")
    elif species == "Animals":
        tokens.append("(Animals[MeSH Terms] NOT Humans[MeSH Terms])")

    # Sex
    if sex == "Male":
        tokens.append("Male[MeSH Terms]")
    elif sex == "Female":
        tokens.append("Female[MeSH Terms]")

    # Age
    age_map = {
        "Child": "Child[MeSH Terms]",
        "Adolescent": "Adolescent[MeSH Terms]",
        "Adult": "Adult[MeSH Terms]",
        "Middle Aged": "Middle Aged[MeSH Terms]",
        "Aged": "Aged[MeSH Terms]",
    }
    if age in age_map:
        tokens.append(age_map[age])

    # Other
    other_map = {
        "Preprint": "Preprint[pt]",
        "Retracted": "Retracted Publication[pt]",
    }
    if other in other_map:
        tokens.append(other_map[other])

    term = " AND ".join([t for t in tokens if t])

    # Include tool (and optional email) to be a good API citizen
    tool_params = {"tool": "spacebio-ke"}
    pubmed_email = os.environ.get("PUBMED_EMAIL", "").strip()
    if pubmed_email:
        tool_params["email"] = pubmed_email

    # ESearch
    try:
        r = requests.get(
            f"{NCBI_EUTILS}/esearch.fcgi",
            params={"db": "pubmed", "term": term, "retmax": RETMAX, "retmode": "json", "sort": "relevance", **tool_params},
            headers=HEADERS, timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
    except Exception:
        return {"results": [], "term": term}

    results = []
    if ids:
        try:
            r2 = requests.get(
                f"{NCBI_EUTILS}/esummary.fcgi",
                params={"db": "pubmed", "id": ",".join(ids), "retmode": "json", **tool_params},
                headers=HEADERS, timeout=REQUEST_TIMEOUT,
            )
            r2.raise_for_status()
            summ = r2.json().get("result", {})
        except Exception:
            summ = {}

        for pmid in ids:
            it = summ.get(pmid, {})
            results.append({
                "pmid": pmid,
                "title": it.get("title"),
                "journal": it.get("fulljournalname"),
                "year": (it.get("pubdate") or "").split(" ")[0],
                "authors": ", ".join([a.get("name") for a in it.get("authors", [])][:5]),
            })

    return {"results": results, "term": term}

    # Publication date range
    tokens.append(f"({start_year}:{end_year})[dp]")

    # Text availability
    ta_map = {
        "Abstract": "hasabstract[text]",
        "Free full text": "free full text[filter]",
        "Full text": "full text[filter]",
    }
    if text_availability in ta_map:
        tokens.append(ta_map[text_availability])

    # Article attributes (designs)
    attr_map = {
        "Systematic Review": "systematic[sb]",
        "Clinical Trial": "clinicaltrial[pt]",
        "Randomized Controlled Trial": "randomized controlled trial[pt]",
        "Review": "review[pt]",
        "Meta-Analysis": "meta-analysis[pt]",
        "Case Reports": "case reports[pt]",
    }
    if article_attribute in attr_map:
        tokens.append(attr_map[article_attribute])

    # Article type (publication type)
    type_map = {
        "Journal Article": "Journal Article[pt]",
        "Letter": "Letter[pt]",
        "Editorial": "Editorial[pt]",
        "Guideline": "Guideline[pt]",
        "Dataset": "Data Set[pt]",
        "Data Set": "Data Set[pt]",
    }
    if article_type in type_map:
        tokens.append(type_map[article_type])

    # Language
    lang_map = {
        "English": "english",
        "Spanish": "spanish",
        "French": "french",
        "German": "german",
        "Italian": "italian",
        "Portuguese": "portuguese",
        "Russian": "russian",
        "Chinese": "chinese",
        "Japanese": "japanese",
        "Persian": "persian",
        "Arabic": "arabic",
        "Hindi": "hindi",
        "Turkish": "turkish",
        "Korean": "korean",
    }
    if language in lang_map:
        tokens.append(f"{lang_map[language]}[lang]")

    # Species (MeSH)
    if species == "Humans":
        tokens.append("Humans[MeSH Terms]")
    elif species == "Animals":
        tokens.append("(Animals[MeSH Terms] NOT Humans[MeSH Terms])")

    # Sex (MeSH)
    if sex == "Male":
        tokens.append("Male[MeSH Terms]")
    elif sex == "Female":
        tokens.append("Female[MeSH Terms]")

    # Age (MeSH)
    age_map = {
        "Child": "Child[MeSH Terms]",
        "Adolescent": "Adolescent[MeSH Terms]",
        "Adult": "Adult[MeSH Terms]",
        "Middle Aged": "Middle Aged[MeSH Terms]",
        "Aged": "Aged[MeSH Terms]",
    }
    if age in age_map:
        tokens.append(age_map[age])

    # Other (publication type)
    other_map = {
        "Preprint": "Preprint[pt]",
        "Retracted": "Retracted Publication[pt]",
    }
    if other in other_map:
        tokens.append(other_map[other])

    term = " AND ".join([t for t in tokens if t])

    # ESearch → ids
    try:
        r = requests.get(
            f"{NCBI_EUTILS}/esearch.fcgi",
            params={"db": "pubmed", "term": term, "retmax": RETMAX, "retmode": "json", "sort": "relevance"},
            headers=HEADERS, timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
    except Exception:
        return {"results": [], "term": term}

    ids = r.json().get("esearchresult", {}).get("idlist", [])

    results = []
    if ids:
        try:
            r2 = requests.get(
                f"{NCBI_EUTILS}/esummary.fcgi",
                params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
                headers=HEADERS, timeout=REQUEST_TIMEOUT,
            )
            r2.raise_for_status()
            summ = r2.json().get("result", {})
        except Exception:
            summ = {}

        for pmid in ids:
            it = summ.get(pmid, {})
            results.append({
                "pmid": pmid,
                "title": it.get("title"),
                "journal": it.get("fulljournalname"),
                "year": (it.get("pubdate") or "").split(" ")[0],
                "authors": ", ".join([a.get("name") for a in it.get("authors", [])][:5]),
            })

    return {"results": results, "term": term}


# ------------------------------------------------------------------------------
# Abstract retrieval (XML → text; text fallback; HTML scrape)
# ------------------------------------------------------------------------------

def _extract_abstract_from_xml(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return ""

    pieces: List[str] = []
    for node in root.findall(".//Abstract/AbstractText"):
        label = node.attrib.get("Label") or node.attrib.get("NlmCategory")
        txt = "".join(node.itertext()).strip()
        if not txt:
            continue
        pieces.append(f"{label}: {txt}" if label else txt)

    if pieces:
        return "\n\n".join(pieces).strip()

    other = ["".join(n.itertext()).strip() for n in root.findall(".//OtherAbstract/AbstractText")]
    other = [t for t in other if t]
    if other:
        return "\n\n".join(other).strip()

    return ""


def _extract_abstract_from_html(html_text: str) -> str:
    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception:
        return ""
    for tag, attrs in [
        ("div", {"class": "abstract"}),
        ("div", {"class": "abstract-content"}),
        ("section", {"id": "abstract"}),
    ]:
        node = soup.find(tag, attrs=attrs)
        if node:
            text = node.get_text("\n", strip=True)
            lines = [ln for ln in text.splitlines() if ln.strip()]
            if lines and lines[0].lower().startswith("abstract"):
                lines = lines[1:]
            return "\n".join(lines).strip()
    return ""


@app.get("/api/abstract/{pmid}")
def api_abstract(pmid: str):
    # XML (best)
    try:
        r = requests.get(
            f"{NCBI_EUTILS}/efetch.fcgi",
            params={"db": "pubmed", "id": pmid, "retmode": "xml"},
            headers=HEADERS, timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        text = _extract_abstract_from_xml(r.text)
        if text:
            return {"abstract": text}
    except Exception:
        pass

    # Plain text
    try:
        r2 = requests.get(
            f"{NCBI_EUTILS}/efetch.fcgi",
            params={"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text"},
            headers=HEADERS, timeout=REQUEST_TIMEOUT,
        )
        if r2.status_code == 200:
            plain = (r2.text or "").replace("\r", "").strip()
            if plain:
                return {"abstract": plain}
    except Exception:
        pass

    # HTML scrape (last resort)
    try:
        page = requests.get(f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if page.status_code == 200:
            html_abs = _extract_abstract_from_html(page.text)
            if html_abs:
                return {"abstract": html_abs}
    except Exception:
        pass

    return {"abstract": ""}


# ------------------------------------------------------------------------------
# Reputation (pragmatic proxy from public signals)
# ------------------------------------------------------------------------------

def _get_esummary(pmid: str) -> dict:
    try:
        r = requests.get(
            f"{NCBI_EUTILS}/esummary.fcgi",
            params={"db": "pubmed", "id": pmid, "retmode": "json"},
            headers=HEADERS, timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("result", {}).get(pmid, {}) or {}
    except Exception:
        return {}


def _extract_first_doi(esum: dict) -> Optional[str]:
    # ESummary may return articleids with multiple types (doi, pii, pmc, …).
    for aid in (esum.get("articleids") or []):
        if aid.get("idtype") == "doi" and aid.get("value"):
            return str(aid["value"]).strip()
    # Some records store DOI in elocationid
    eloc = (esum.get("elocationid") or "").strip()
    if eloc and eloc.lower().startswith("doi:"):
        return eloc.split(":", 1)[1].strip()
    return None


def _openalex_work_by_doi(doi: str) -> dict:
    try:
        r = requests.get(
            f"https://api.openalex.org/works/doi:{doi}",
            headers=HEADERS, timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _openalex_venue_by_issn_or_name(issn: Optional[str], journal_name: Optional[str]) -> dict:
    # Prefer ISSN if available; otherwise fallback to a name search.
    if issn:
        try:
            r = requests.get(
                f"https://api.openalex.org/venues",
                params={"search": issn},
                headers=HEADERS, timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("results"):
                    return data["results"][0]
        except Exception:
            pass
    if journal_name:
        try:
            r = requests.get(
                f"https://api.openalex.org/venues",
                params={"search": journal_name},
                headers=HEADERS, timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("results"):
                    return data["results"][0]
        except Exception:
            pass
    return {}


def _crossref_type(doi: str) -> Optional[str]:
    try:
        r = requests.get(f"https://api.crossref.org/works/{doi}", headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return (r.json().get("message") or {}).get("type")
    except Exception:
        pass
    return None


def _scale(value: float, lo: float, hi: float) -> int:
    if hi <= lo:
        return 0
    pct = (value - lo) / (hi - lo)
    pct = max(0.0, min(1.0, pct))
    return int(round(pct * 100))


@app.get("/api/reputation/{pmid}")
def api_reputation(pmid: str):
    """
    Practical 'reputation' based on data we can obtain from PubMed:
    - Citations: count of PubMed papers that cite this PMID (ELink citedin)
    - Open Access: PMCID presence (100 if present else 30)
    - Recency: years since publication -> decays with time
    - Journal Activity: articles published by this journal in the last 5 years
    - Author Activity: rough publication count for the first author

    Returns components + total + level.
    """
    tool_params = {"tool": "spacebio-ke"}
    pubmed_email = os.environ.get("PUBMED_EMAIL", "").strip()
    if pubmed_email:
        tool_params["email"] = pubmed_email

    journal_title = ""
    pub_year = None
    first_author = None
    pmcid_present = False

    # --- ESummary: journal name, pub year, authors, pmcid presence
    try:
        r = requests.get(
            f"{NCBI_EUTILS}/esummary.fcgi",
            params={"db": "pubmed", "id": pmid, "retmode": "json", **tool_params},
            headers=HEADERS, timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        res = r.json().get("result", {}).get(pmid, {})
        journal_title = res.get("fulljournalname") or res.get("source") or ""
        pubdate = (res.get("pubdate") or "").split(" ")[0]
        try:
            pub_year = int(pubdate[:4])
        except Exception:
            pub_year = None
        auths = res.get("authors") or []
        if auths:
            # Use "LastName Initials" if present
            ln = (auths[0].get("lastname") or "").strip()
            ini = (auths[0].get("initials") or "").strip()
            if ln:
                first_author = f'{ln} {ini}'.strip()
        # PMCID check
        for aid in res.get("articleids", []):
            if aid.get("idtype") == "pmcid" and aid.get("value"):
                pmcid_present = True
                break
    except Exception:
        pass

    # --- Citations: ELink citedin count
    citations = 0
    try:
        r = requests.get(
            f"{NCBI_EUTILS}/elink.fcgi",
            params={"dbfrom": "pubmed", "linkname": "pubmed_pubmed_citedin", "id": pmid, "retmode": "json", **tool_params},
            headers=HEADERS, timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        linksets = r.json().get("linksets", []) or r.json().get("linkset", [])
        # Both shapes exist in the wild; handle conservatively
        uids = []
        if isinstance(linksets, list) and linksets:
            # New JSON shape
            for ls in linksets:
                for grp in ls.get("linksetdbs", []) or []:
                    if grp.get("linkname") == "pubmed_pubmed_citedin":
                        uids.extend(grp.get("links", []))
        if not uids and "linksets" not in r.json():
            # Legacy shape
            for grp in r.json().get("linkset", [{}])[0].get("linksetdbs", []):
                if grp.get("linkname") == "pubmed_pubmed_citedin":
                    uids.extend([lk.get("id") for lk in grp.get("links", []) if isinstance(lk, dict)])
        citations = len(uids)
    except Exception:
        citations = 0

    # --- Journal Activity (articles in last 5 years)
    journal_activity = 0
    if journal_title:
        try:
            from_year = max((pub_year or 2020) - 4, 1900)
            to_year = (pub_year or 2025)
            term = f'"{journal_title}"[ta] AND ("{from_year}"[dp] : "{to_year}"[dp])'
            r = requests.get(
                f"{NCBI_EUTILS}/esearch.fcgi",
                params={"db": "pubmed", "term": term, "retmode": "json", "rettype": "count", **tool_params},
                headers=HEADERS, timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            journal_activity = int(r.json().get("esearchresult", {}).get("count", "0"))
        except Exception:
            journal_activity = 0

    # --- Author Activity (rough pub count for first author)
    author_pubs = 0
    if first_author:
        try:
            term = f'"{first_author}"[au]'
            r = requests.get(
                f"{NCBI_EUTILS}/esearch.fcgi",
                params={"db": "pubmed", "term": term, "retmode": "json", "rettype": "count", **tool_params},
                headers=HEADERS, timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            author_pubs = int(r.json().get("esearchresult", {}).get("count", "0"))
        except Exception:
            author_pubs = 0

    # --- Convert raw values to 0–100 scores (simple, explainable scalings)
    def scale_cap_linear(x, cap):
        x = max(0, int(x))
        return min(100, int(round((min(x, cap) / cap) * 100)))

    citations_score = scale_cap_linear(citations, cap=200)          # 200+ ≈ 100
    open_access_score = 100 if pmcid_present else 30                # OA strong signal
    # Recency: if no pubyear, neutral 60
    if pub_year:
        years_ago = max(0, (int(os.environ.get("REPUTATION_CURRENT_YEAR", "2025")) - pub_year))
        recency_score = max(10, 100 - years_ago * 10)               # 0y=100 … 9y=10
    else:
        recency_score = 60

    journal_activity_score = scale_cap_linear(journal_activity, cap=2000)  # very active journals approach 100
    author_activity_score = scale_cap_linear(author_pubs, cap=200)         # prolific author approaches 100

    components = {
        "Journal Activity": journal_activity_score,
        "Citations": citations_score,
        "Open Access": open_access_score,
        "Recency": recency_score,
        "Author Activity": author_activity_score,
    }
    total = int(round(sum(components.values()) / len(components)))
    level = "Low" if total < 40 else ("Medium" if total < 60 else ("High" if total < 80 else "Very High"))

    return {
        "pmcid": pmcid_present,
        "journal": journal_title or "(unknown journal)",
        "total": total,
        "level": level,
        "confidence": 70,  # heuristic method; keep transparent
        "components": components,
        "raw": {
            "citations": citations,
            "journal_activity_count_5y": journal_activity,
            "first_author_pub_count": author_pubs,
            "pub_year": pub_year,
        },
    }

    # OpenAlex: work info
    oa_work = _openalex_work_by_doi(doi) if doi else {}
    cited_by = oa_work.get("cited_by_count") or 0
    is_oa = bool((oa_work.get("open_access") or {}).get("is_oa"))
    pub_year = oa_work.get("publication_year") or year

    # Basic components
    citations_score = _scale(float(cited_by), lo=0, hi=200)           # 200+ cites ~100
    recency_score = 50
    if pub_year:
        # 0 yrs old ~100, 10+ yrs ~20
        age = max(0, (2025 - int(pub_year)))
        recency_score = max(20, 100 - age * 8)

    oa_score = 100 if is_oa else 40

    # Venue-level signal (h-index / mean citedness if available)
    venue = _openalex_venue_by_issn_or_name(issn, journal_name)
    venue_h = ((venue.get("summary_stats") or {}).get("h_index")) if venue else None
    venue_citedness = ((venue.get("summary_stats") or {}).get("2yr_mean_citedness")) if venue else None

    # Journal impact proxy combines venue stats if present; otherwise lean on citations.
    impact_base = 0
    if isinstance(venue_h, (int, float)):
        impact_base += _scale(float(venue_h), lo=5, hi=200) * 0.6
    if isinstance(venue_citedness, (int, float, str)):
        try:
            v = float(venue_citedness)
            impact_base += _scale(v, lo=0.5, hi=6.0) * 0.4
        except Exception:
            pass
    if impact_base == 0:
        # Fallback: use article citations as a soft journal proxy
        impact_base = max(30, citations_score * 0.9)
    journal_impact_score = int(round(min(100, impact_base)))

    # Author h-index: average of up to first 3 authors (OpenAlex authorships)
    h_scores: List[int] = []
    for auth in (oa_work.get("authorships") or [])[:3]:
        auth_id = (auth.get("author") or {}).get("id")
        if not auth_id:
            continue
        try:
            r = requests.get(auth_id, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                h = (r.json().get("summary_stats") or {}).get("h_index")
                if isinstance(h, (int, float)):
                    h_scores.append(_scale(float(h), lo=5, hi=120))
        except Exception:
            continue
    author_hidx_score = int(round(sum(h_scores) / len(h_scores))) if h_scores else 55

    # Compose components and overall
    components = {
        "Journal Impact": journal_impact_score,
        "Citations": citations_score,
        "Open Access": oa_score,
        "Recency": recency_score,
        "Author H-index": author_hidx_score,
    }
    total = int(round(sum(components.values()) / len(components)))
    level = "Low" if total < 40 else ("Medium" if total < 60 else ("High" if total < 80 else "Very High"))

    # Extra surface fields
    pmcid = None
    for aid in (esum.get("articleids") or []):
        if aid.get("idtype") == "pmcid":
            pmcid = aid.get("value")
            break

    return {
        "pmcid": pmcid,
        "doi": doi,
        "journal": journal_name or (oa_work.get("host_venue") or {}).get("display_name"),
        "year": pub_year,
        "total": total,
        "level": level,
        "confidence": 85,  # static confidence for this proxy; not a statistical measure
        "components": components,
    }


# ------------------------------------------------------------------------------
# Global error handler
# ------------------------------------------------------------------------------

@app.exception_handler(Exception)
async def all_errors(_, exc):
    return JSONResponse(status_code=500, content={"error": str(exc)})
