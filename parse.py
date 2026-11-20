"""Parse PubMed efetch XML into plain dicts. Standard library only.
Anything missing in the source is returned as None (never invented)."""
import xml.etree.ElementTree as ET


def _text(el):
    if el is None:
        return None
    t = "".join(el.itertext()).strip()
    return t or None


def _date(art):
    pd = art.find("Journal/JournalIssue/PubDate")
    if pd is None:
        return None
    ml = _text(pd.find("MedlineDate"))
    if ml:
        return ml
    parts = [_text(pd.find(k)) for k in ("Year", "Month", "Day")]
    return " ".join(p for p in parts if p) or None


def parse_articles(xml_text):
    root = ET.fromstring(xml_text)
    out = []
    for pa in root.findall("PubmedArticle"):
        mc = pa.find("MedlineCitation")
        art = mc.find("Article") if mc is not None else None
        if art is None:
            continue
        pmid = _text(mc.find("PMID"))
        ids = {}
        for a in pa.findall("PubmedData/ArticleIdList/ArticleId"):
            ids[a.get("IdType")] = _text(a)
        if not ids.get("doi"):
            for e in art.findall("ELocationID"):
                if e.get("EIdType") == "doi":
                    ids["doi"] = _text(e)
        authors, affils = [], []
        for au in art.findall("AuthorList/Author"):
            name = _text(au.find("CollectiveName"))
            if not name:
                name = " ".join(x for x in (_text(au.find("ForeName")), _text(au.find("LastName"))) if x) or None
            if name:
                authors.append(name)
            for af in au.findall("AffiliationInfo/Affiliation"):
                t = _text(af)
                if t and t not in affils:
                    affils.append(t)
        abs_parts = []
        for at in art.findall("Abstract/AbstractText"):
            t = _text(at)
            if t:
                label = at.get("Label")
                abs_parts.append(f"{label}: {t}" if label else t)
        out.append({
            "pmid": pmid,
            "pmcid": ids.get("pmc"),
            "doi": ids.get("doi"),
            "title": _text(art.find("ArticleTitle")),
            "authors": authors,
            "affiliations": affils[:5],
            "journal": _text(art.find("Journal/Title")),
            "publication_date": _date(art),
            "abstract": "\n".join(abs_parts) or None,
            "publication_types": [t for t in (_text(x) for x in art.findall("PublicationTypeList/PublicationType")) if t],
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
            "doi_url": f"https://doi.org/{ids['doi']}" if ids.get("doi") else None,
            "pmc_url": f"https://pmc.ncbi.nlm.nih.gov/articles/{ids['pmc']}/" if ids.get("pmc") else None,
            "source": "PubMed",
        })
    return out
