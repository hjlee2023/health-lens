"""
Live PubMed fallback via NCBI E-utilities. No key required; a key only raises the rate limit.
Results are classified by evidence level and journal tier, then returned as fixed-schema cards.
Sort order is deterministic so the same query always produces the same output.
"""
import time
import xml.etree.ElementTree as ET

import requests

from taxonomy import PUBTYPE_TO_LEVEL, classify_journal_tier

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _esearch(term: str, retmax: int = 8, api_key: str | None = None) -> list[str]:
    params = {
        "db": "pubmed", "term": term, "retmode": "json",
        "retmax": retmax, "sort": "relevance",
    }
    if api_key:
        params["api_key"] = api_key
    r = requests.get(f"{BASE}/esearch.fcgi", params=params, timeout=8)
    r.raise_for_status()
    return r.json().get("esearchresult", {}).get("idlist", [])


def _efetch(pmids: list[str], api_key: str | None = None) -> str:
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    if api_key:
        params["api_key"] = api_key
    r = requests.get(f"{BASE}/efetch.fcgi", params=params, timeout=10)
    r.raise_for_status()
    return r.text


def _level_from_pubtypes(pubtypes: list[str]) -> str | None:
    """Pick the strongest (lowest-rank) study design from PubMed's publication type tags.

    Returns None when nothing matches, rather than defaulting to EXPERT: plenty of papers
    carry only 'Journal Article' and would be misclassified. Those are left to the LLM
    classifier, which reads the abstract. Explicit tags like Meta-Analysis or RCT, on the
    other hand, are reliable."""
    from taxonomy import EVIDENCE_LEVELS
    best, best_rank = None, 99
    for pt in pubtypes:
        code = PUBTYPE_TO_LEVEL.get(pt)
        if code and EVIDENCE_LEVELS[code]["rank"] < best_rank:
            best, best_rank = code, EVIDENCE_LEVELS[code]["rank"]
    return best


def _parse(xml_text: str) -> list[dict]:
    out = []
    root = ET.fromstring(xml_text)
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        # itertext() also picks up text that follows inline markup like <sub>, <i>, <sup>
        title_el = art.find(".//ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        journal = art.findtext(".//Journal/Title") or ""
        year = art.findtext(".//JournalIssue/PubDate/Year") or ""
        abstract = " ".join(
            "".join(t.itertext()).strip() for t in art.findall(".//AbstractText")
        ).strip()
        pubtypes = [pt.text or "" for pt in art.findall(".//PublicationType")]

        level = _level_from_pubtypes(pubtypes)
        first_author = art.findtext(".//AuthorList/Author/LastName") or ""
        authors = f"{first_author} 외" if first_author else ""
        out.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract or title,
            "summary": (abstract[:280] + "…") if len(abstract) > 280 else (abstract or title),
            "evidenceLevel": level,
            "journal": journal,
            "journalTier": classify_journal_tier(journal),
            "year": int(year) if year.isdigit() else None,
            "authors": authors,
            "citation": f"{title} {journal}. {year}.".strip(),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    # Stable order: evidence level (strongest first) → newest → pmid. Unclassified (None) ranks as EXPERT.
    from taxonomy import EVIDENCE_LEVELS
    out.sort(key=lambda c: (EVIDENCE_LEVELS[c["evidenceLevel"] or "EXPERT"]["rank"],
                            -(c["year"] or 0), c["pmid"]))
    return out


def search(term: str, retmax: int = 8, api_key: str | None = None) -> list[dict]:
    """Return classified evidence cards for a single query. Empty list on failure."""
    try:
        ids = _esearch(term, retmax=retmax, api_key=api_key)
        if not ids:
            return []
        time.sleep(0.34)  # Stay under NCBI's keyless limit of 3 req/s
        return _parse(_efetch(ids, api_key=api_key))
    except Exception as e:  # noqa: BLE001 - a fallback should fail quietly
        print(f"[pubmed] search failed: {e}")
        return []
