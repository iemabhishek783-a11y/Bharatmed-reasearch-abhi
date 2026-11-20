"""NCBI PubMed E-utilities client (esearch + efetch), polite rate limiting."""
import asyncio, os, time
import httpx
from parse import parse_articles

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_lock = asyncio.Lock()
_last = 0.0


class UpstreamError(Exception):
    pass


async def _get(client, path, params):
    global _last
    params = {**params, "tool": "bharatmed-research"}
    if os.getenv("NCBI_EMAIL"):
        params["email"] = os.getenv("NCBI_EMAIL")
    key = os.getenv("NCBI_API_KEY")
    if key:
        params["api_key"] = key
    gap = 0.12 if key else 0.35  # NCBI: 3 req/s without key, 10 with
    async with _lock:
        wait = gap - (time.monotonic() - _last)
        if wait > 0:
            await asyncio.sleep(wait)
        _last = time.monotonic()
    try:
        r = await client.get(f"{BASE}/{path}", params=params, timeout=20)
        r.raise_for_status()
        return r
    except httpx.HTTPError as e:
        raise UpstreamError(f"PubMed request failed ({type(e).__name__})")


async def search(query, page=1, page_size=10, year_from=None, year_to=None, india_only=False, sort="relevance"):
    term = f"({query}) AND India[Affiliation]" if india_only else query
    p = {"db": "pubmed", "term": term, "retmode": "json", "retmax": page_size,
         "retstart": (page - 1) * page_size, "sort": "pub_date" if sort == "date" else "relevance"}
    if year_from or year_to:
        p.update(datetype="pdat", mindate=str(year_from or 1900), maxdate=str(year_to or 3000))
    async with httpx.AsyncClient() as c:
        data = (await _get(c, "esearch.fcgi", p)).json().get("esearchresult", {})
        ids = data.get("idlist", [])
        total = int(data.get("count", 0))
        arts = await _fetch(c, ids) if ids else []
    return {"total": total, "items": arts, "query_translation": data.get("querytranslation")}


async def _fetch(c, ids):
    r = await _get(c, "efetch.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
    by_id = {a["pmid"]: a for a in parse_articles(r.text)}
    return [by_id[i] for i in ids if i in by_id]  # keep PubMed's ranking order


async def get_one(pmid):
    async with httpx.AsyncClient() as c:
        arts = await _fetch(c, [pmid])
    return arts[0] if arts else None
