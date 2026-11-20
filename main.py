import logging, time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import pubmed

# Log method/path/status only. Never log search text (it may contain clinical details).
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bharatmed")
app = FastAPI(title="BharatMed Research API", version="0.1.0")
api = APIRouter(prefix="/api/v1")


def err(status, code, msg):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": msg}})


_hits = defaultdict(deque)
LIMIT, WINDOW = 30, 60  # requests per IP per minute (in-memory; fine for one server)


@app.middleware("http")
async def limiter(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
        q, now = _hits[ip], time.monotonic()
        while q and now - q[0] > WINDOW:
            q.popleft()
        if len(q) >= LIMIT:
            return err(429, "rate_limited", "Too many requests. Wait a minute and try again.")
        q.append(now)
    resp = await call_next(request)
    log.info("%s %s %s", request.method, request.url.path, resp.status_code)
    return resp


@app.exception_handler(RequestValidationError)
async def _val(request, exc):
    return err(422, "invalid_input", "Check your search: query must be 2-300 characters, page 1-100, years 1800-2100.")


@app.exception_handler(HTTPException)
async def _http(request, exc):
    return err(exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(pubmed.UpstreamError)
async def _up(request, exc):
    return err(502, "upstream_unavailable", "PubMed could not be reached right now. Try again shortly.")


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    page: int = Field(1, ge=1, le=100)
    page_size: int = Field(10, ge=1, le=25)
    year_from: Optional[int] = Field(None, ge=1800, le=2100)
    year_to: Optional[int] = Field(None, ge=1800, le=2100)
    india_only: bool = False
    sort: str = Field("relevance", pattern="^(relevance|date)$")


@api.post("/research/search")
async def research_search(body: SearchIn):
    res = await pubmed.search(body.query, body.page, body.page_size, body.year_from, body.year_to, body.india_only, body.sort)
    return {"page": body.page, "page_size": body.page_size, **res,
            "notice": "Metadata from PubMed. Fields shown as null were not provided by the source."}


@api.get("/research/{pmid}")
async def research_get(pmid: str):
    if not pmid.isdigit() or len(pmid) > 9:
        raise HTTPException(400, "PMID must be digits only.")
    art = await pubmed.get_one(pmid)
    if not art:
        raise HTTPException(404, "No PubMed record found for this PMID.")
    return art


@api.get("/health")
async def health():
    return {"status": "ok", "version": app.version}


app.include_router(api)
@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(Path(__file__).parent / "index.html")
