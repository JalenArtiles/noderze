"""Applicant-tracking-system connectors.

Original company postings are preferred over aggregators. Parsers are pure functions over API payloads
(unit tested with fixtures); fetchers go through PoliteFetcher.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote, urlparse

from .fetch import FetchBlocked, PoliteFetcher


@dataclass
class RawPosting:
    title: str
    url: str
    ats_job_id: str
    location_text: str = ""
    description: str = ""
    posted_at: datetime | None = None
    comp_min: float | None = None
    comp_max: float | None = None
    comp_period: str | None = None
    workplace: str | None = None  # remote | hybrid | onsite
    apply_url: str | None = None
    source: str = ""
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- html -> text

class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "tr", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.parts.append("\n- ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    if "&lt;" in raw and "<" not in raw[:200]:
        raw = html.unescape(raw)  # Greenhouse escapes its HTML
    p = _Text()
    p.feed(raw)
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _ts(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc).replace(tzinfo=None)
        v = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, OSError):
        for fmt in ("%B %d, %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value), fmt)
            except ValueError:
                continue
    return None


# ----------------------------------------------------------------------------- parsers

def parse_greenhouse(payload: dict) -> list[RawPosting]:
    out = []
    for j in payload.get("jobs", []):
        out.append(RawPosting(
            title=j.get("title", "").strip(), url=j.get("absolute_url", ""), ats_job_id=str(j.get("id")),
            location_text=(j.get("location") or {}).get("name", ""), description=html_to_text(j.get("content")),
            posted_at=_ts(j.get("first_published") or j.get("updated_at")), source="greenhouse",
            extra={"departments": [d.get("name") for d in j.get("departments", [])]}))
    return out


def parse_lever(payload: list) -> list[RawPosting]:
    out = []
    for j in payload if isinstance(payload, list) else []:
        cats = j.get("categories") or {}
        lists = "\n".join(f"{x.get('text', '')}\n{html_to_text(x.get('content'))}" for x in j.get("lists", []))
        desc = "\n".join(filter(None, [j.get("descriptionPlain"), lists, j.get("additionalPlain")]))
        sal = j.get("salaryRange") or {}
        interval = (sal.get("interval") or "").lower()
        out.append(RawPosting(
            title=j.get("text", "").strip(), url=j.get("hostedUrl", ""), ats_job_id=str(j.get("id")),
            location_text="; ".join(cats.get("allLocations") or [cats.get("location") or ""]),
            description=desc, posted_at=_ts(j.get("createdAt")),
            comp_min=sal.get("min"), comp_max=sal.get("max"),
            comp_period=("hour" if "hour" in interval else "year") if sal else None,
            workplace=(j.get("workplaceType") or "").lower() or None, apply_url=j.get("applyUrl"), source="lever",
            extra={"commitment": cats.get("commitment"), "team": cats.get("team")}))
    return out


def parse_ashby(payload: dict) -> list[RawPosting]:
    out = []
    for j in payload.get("jobs", []):
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        cmin = cmax = period = None
        for comp in (j.get("compensation") or {}).get("summaryComponents") or []:
            if (comp.get("compensationType") or "").lower() == "salary":
                cmin, cmax = comp.get("minValue"), comp.get("maxValue")
                period = "hour" if "hour" in (comp.get("interval") or "").lower() else "year"
                break
        wp = (j.get("workplaceType") or "").lower()
        out.append(RawPosting(
            title=j.get("title", "").strip(), url=j.get("jobUrl", ""), ats_job_id=str(j.get("id")),
            location_text="; ".join(x for x in locs if x) + ("; Remote" if j.get("isRemote") else ""),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            posted_at=_ts(j.get("publishedAt")), comp_min=cmin, comp_max=cmax, comp_period=period,
            workplace={"onsite": "onsite", "remote": "remote", "hybrid": "hybrid"}.get(wp), apply_url=j.get("applyUrl"),
            source="ashby", extra={"employment_type": j.get("employmentType")}))
    return out


def parse_smartrecruiters_list(payload: dict, company_id: str) -> list[RawPosting]:
    out = []
    for j in payload.get("content", []):
        loc = j.get("location") or {}
        loc_text = ", ".join(x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x)
        if loc.get("remote"):
            loc_text += "; Remote"
        out.append(RawPosting(
            title=j.get("name", "").strip(), url=f"https://jobs.smartrecruiters.com/{company_id}/{j.get('id')}",
            ats_job_id=str(j.get("id")), location_text=loc_text, posted_at=_ts(j.get("releasedDate")),
            source="smartrecruiters"))
    return out


def parse_smartrecruiters_detail(payload: dict) -> str:
    secs = ((payload.get("jobAd") or {}).get("sections")) or {}
    return "\n\n".join(html_to_text((secs.get(k) or {}).get("text")) for k in
                       ("jobDescription", "qualifications", "additionalInformation") if secs.get(k))


def workday_endpoints(host: str, site: str) -> tuple[str, str]:
    """(API base, public base) for a Workday board. Two host styles exist:
    tenant.wd5.myworkdayjobs.com/<site> and wd5.myworkdaysite.com/recruiting/<tenant>/<site> (stored as site
    "<tenant>/<site>")."""
    if host.endswith("myworkdaysite.com") and "/" in site:
        tenant, s = site.split("/", 1)
        return f"https://{host}/wday/cxs/{tenant}/{s}", f"https://{host}/recruiting/{tenant}/{s}"
    tenant = host.split(".")[0]
    return f"https://{host}/wday/cxs/{tenant}/{site}", f"https://{host}/{site}"


def parse_workday_list(payload: dict) -> list[dict]:
    return [{"title": p.get("title", ""), "path": p.get("externalPath", ""), "locations": p.get("locationsText", ""),
             "posted": p.get("postedOn", "")} for p in payload.get("jobPostings", [])]


def parse_workday_detail(payload: dict, host: str, site: str, path: str) -> RawPosting:
    info = payload.get("jobPostingInfo") or {}
    locs = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
    return RawPosting(
        title=info.get("title", "").strip(), url=info.get("externalUrl") or workday_endpoints(host, site)[1] + path,
        ats_job_id=str(info.get("jobReqId") or info.get("id") or path), location_text="; ".join(x for x in locs if x),
        description=html_to_text(info.get("jobDescription")), posted_at=_ts(info.get("startDate")),
        source="workday", extra={"posted_on": info.get("postedOn"), "time_type": info.get("timeType"),
                                 "remote_type": info.get("remoteType")})


def parse_amazon(payload: dict) -> list[RawPosting]:
    out = []
    for j in payload.get("jobs", []):
        desc = "\n\n".join(filter(None, [html_to_text(j.get("description")),
                                         "Basic qualifications:\n" + html_to_text(j.get("basic_qualifications")),
                                         "Preferred qualifications:\n" + html_to_text(j.get("preferred_qualifications"))]))
        out.append(RawPosting(
            title=j.get("title", "").strip(), url="https://www.amazon.jobs" + (j.get("job_path") or ""),
            ats_job_id=str(j.get("id_icims") or j.get("id")),
            location_text=j.get("normalized_location") or j.get("location") or "", description=desc,
            posted_at=_ts(j.get("posted_date")), source="amazon"))
    return out


def parse_jobvite_html(html_text: str, token: str) -> list[RawPosting]:
    """Jobvite career pages list jobs as links to /<token>/job/<id> with a location cell nearby."""
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="(/' + re.escape(token) + r'/job/([A-Za-z0-9]+))"[^>]*>(.*?)</a>(.{0,600})',
                         html_text, re.S | re.I):
        jid = m.group(2)
        if jid in seen:
            continue
        seen.add(jid)
        title = html_to_text(m.group(3)).strip()
        loc = re.search(r'jv-job-list-location[^>]*>(.*?)</', m.group(4), re.S)
        out.append(RawPosting(title=title, url=f"https://jobs.jobvite.com{m.group(1)}", ats_job_id=jid,
                              location_text=html_to_text(loc.group(1)).strip() if loc else "", source="jobvite"))
    return out


# ----------------------------------------------------------------------------- fetchers

WORKDAY_QUERIES = ["sales engineer", "solutions engineer", "solutions consultant", "presales", "solutions architect",
                   "systems engineer", "university", "early career", "new grad", "sales development", "associate"]
AMAZON_QUERIES = ["associate solutions architect", "solutions architect 2027", "early career solutions architect"]


def fetch_postings(f: PoliteFetcher, ats_type: str, token: str | None, host: str | None = None,
                   site: str | None = None, log=lambda m: None) -> list[RawPosting]:
    if ats_type == "greenhouse":
        return parse_greenhouse(f.get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"))
    if ats_type == "lever":
        return parse_lever(f.get_json(f"https://api.lever.co/v0/postings/{token}?mode=json"))
    if ats_type == "ashby":
        return parse_ashby(f.get_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"))
    if ats_type == "smartrecruiters":
        out, offset = [], 0
        while offset < 500:
            page = f.get_json(f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100&offset={offset}")
            batch = parse_smartrecruiters_list(page, token)
            out += batch
            offset += 100
            if offset >= page.get("totalFound", 0) or not batch:
                break
        return out
    if ats_type == "workday":
        api, public = workday_endpoints(host or "", site or "")
        seen: dict[str, dict] = {}
        for q in WORKDAY_QUERIES:
            try:
                data = f.post_json(f"{api}/jobs",
                                   {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": q})
            except FetchBlocked as e:
                log(f"Workday search blocked: {e}")
                break
            for item in parse_workday_list(data):
                seen.setdefault(item["path"], item)
        out = []
        for path, item in seen.items():
            out.append(RawPosting(title=item["title"], url=f"{public}{path}", ats_job_id=path,
                                  location_text=item["locations"], source="workday",
                                  extra={"workday_path": path, "posted_on": item["posted"]}))
        return out
    if ats_type == "amazon":
        out: dict[str, RawPosting] = {}
        for q in AMAZON_QUERIES:
            data = f.get_json(f"https://www.amazon.jobs/en/search.json?base_query={quote(q)}&result_limit=50&sort=recent"
                              f"&country=USA")
            for p in parse_amazon(data):
                out.setdefault(p.ats_job_id, p)
        return list(out.values())
    if ats_type == "jobvite":
        return parse_jobvite_html(f.get_text(f"https://jobs.jobvite.com/{token}/jobs"), token)
    raise ValueError(f"Unsupported ATS type {ats_type}")


def workday_detail(f: PoliteFetcher, host: str, site: str, path: str) -> RawPosting:
    api, _ = workday_endpoints(host, site)
    return parse_workday_detail(f.get_json(f"{api}{path}"), host, site, path)


def workday_search(f: PoliteFetcher, host: str, site: str, query: str, pages: int = 1) -> list[dict]:
    """One Workday board search, newest results first, `pages` pages of 20."""
    api, _ = workday_endpoints(host, site)
    out: list[dict] = []
    for page in range(pages):
        data = f.post_json(f"{api}/jobs", {"appliedFacets": {}, "limit": 20, "offset": 20 * page, "searchText": query})
        batch = parse_workday_list(data)
        out += batch
        if len(batch) < 20 or 20 * (page + 1) >= int(data.get("total") or 0):
            break
    return out


def parse_workday_url(url: str) -> tuple[str, str, str] | None:
    """(host, site, job path) from a Workday posting link, for either host style."""
    u = urlparse(url)
    parts = [p for p in u.path.split("/") if p]
    host = u.netloc.lower()
    if "myworkdaysite.com" in host and len(parts) >= 3 and parts[0] == "recruiting":
        site, rest = f"{parts[1]}/{parts[2]}", parts[3:]
    elif "myworkdayjobs.com" in host and parts:
        if re.fullmatch(r"[a-z]{2}-[a-zA-Z]{2}", parts[0]) and len(parts) > 1:
            parts = parts[1:]
        site, rest = parts[0], parts[1:]
    else:
        return None
    if not rest or rest[0] != "job":
        return None
    return host, site, "/" + "/".join(rest)


def smartrecruiters_detail(f: PoliteFetcher, company_id: str, posting_id: str) -> str:
    return parse_smartrecruiters_detail(
        f.get_json(f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings/{posting_id}"))


def detect_ats(f: PoliteFetcher, name: str, slug: str) -> tuple[str, str] | None:
    """Probe public job-board APIs for likely board tokens."""
    candidates = list(dict.fromkeys([slug.replace("-", ""), slug, slug.split("-")[0], re.sub(r"\W", "", name.lower())]))
    for token in candidates:
        for kind, url in (
                ("greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{token}"),
                ("lever", f"https://api.lever.co/v0/postings/{token}?mode=json&limit=1"),
                ("ashby", f"https://api.ashbyhq.com/posting-api/job-board/{token}")):
            try:
                r = f.request("GET", url)
            except FetchBlocked:
                continue
            if r.status_code == 200 and r.text.strip() not in ("", "[]") and "not found" not in r.text[:200].lower():
                return kind, token
    return None


def parse_ats_url(url: str) -> tuple[str, str, str | None] | None:
    """Identify (ats_type, token, job_id) from a posting URL so leads can be resolved to originals."""
    u = urlparse(url)
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    if "greenhouse.io" in host and parts and parts[0] == "embed":
        m = re.search(r"for=([\w-]+)", u.query)
        jid = re.search(r"token=(\d+)", u.query)
        return ("greenhouse", m.group(1), jid.group(1) if jid else None) if m else None
    if host == "jobs.jobvite.com" and parts:
        return "jobvite", parts[0], parts[2] if len(parts) > 2 and parts[1] == "job" else None
    if "greenhouse.io" in host and parts:
        token = parts[0]
        jid = parts[2] if len(parts) >= 3 and parts[1] == "jobs" else None
        if "gh_jid" in u.query:
            jid = re.search(r"gh_jid=(\d+)", u.query).group(1)
        return "greenhouse", token, jid
    if host == "jobs.lever.co" and parts:
        return "lever", parts[0], parts[1] if len(parts) > 1 else None
    if host == "jobs.ashbyhq.com" and parts:
        return "ashby", parts[0], parts[1] if len(parts) > 1 else None
    if "myworkdayjobs.com" in host and parts:
        site = parts[1] if re.fullmatch(r"[a-z]{2}-[a-zA-Z]{2}", parts[0]) and len(parts) > 1 else parts[0]
        return "workday", host, site
    if "myworkdaysite.com" in host and len(parts) >= 3 and parts[0] == "recruiting":
        return "workday", host, f"{parts[1]}/{parts[2]}"
    if host == "jobs.smartrecruiters.com" and parts:
        return "smartrecruiters", parts[0], parts[1] if len(parts) > 1 else None
    return None


def fetch_single(f: PoliteFetcher, ats_type: str, token: str, job_id: str) -> RawPosting | None:
    if ats_type == "greenhouse":
        j = f.get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}")
        return parse_greenhouse({"jobs": [j]})[0]
    if ats_type == "lever":
        return (parse_lever([f.get_json(f"https://api.lever.co/v0/postings/{token}/{job_id}?mode=json")]) or [None])[0]
    if ats_type == "ashby":
        for p in fetch_postings(f, "ashby", token):
            if p.ats_job_id == job_id or job_id in p.url:
                return p
    return None


# ----------------------------------------------------------------------------- any page with schema.org markup

def parse_jsonld_posting(page_html: str, url: str, source: str = "page") -> RawPosting | None:
    """Most career sites embed a schema.org JobPosting for search engines. Reading it works on sites with no API."""
    import json
    for m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', page_html or "", re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for j in items:
            if not isinstance(j, dict) or "JobPosting" not in str(j.get("@type")):
                continue
            locs = j.get("jobLocation") or []
            locs = locs if isinstance(locs, list) else [locs]
            parts = []
            for loc in locs:
                a = (loc or {}).get("address") or {}
                if isinstance(a, dict):
                    city = (a.get("addressLocality") or "").strip().title()
                    region = (a.get("addressRegion") or "").strip()
                    parts.append(", ".join(x for x in (city, region) if x))
            if str(j.get("jobLocationType") or "").upper() == "TELECOMMUTE":
                parts.append("Remote")
            sal = j.get("baseSalary") or {}
            val = sal.get("value") if isinstance(sal, dict) else None
            cmin = cmax = period = None
            if isinstance(val, dict):
                cmin, cmax = val.get("minValue") or val.get("value"), val.get("maxValue") or val.get("value")
                unit = str(val.get("unitText") or "").upper()
                period = "hour" if unit == "HOUR" else "year" if unit == "YEAR" else None
                try:
                    cmin, cmax = (float(cmin) if cmin else None), (float(cmax) if cmax else None)
                except (TypeError, ValueError):
                    cmin = cmax = None
                if period is None:
                    cmin = cmax = None
            ident = j.get("identifier")
            ident = ident.get("value") if isinstance(ident, dict) else ident
            et = j.get("employmentType")
            return RawPosting(
                title=html_to_text(str(j.get("title") or "")).strip(), url=url, ats_job_id=str(ident or ""),
                location_text="; ".join(p for p in parts if p), description=html_to_text(j.get("description")),
                posted_at=_ts(j.get("datePosted")), comp_min=cmin, comp_max=cmax, comp_period=period, source=source,
                extra={"deadline": str(j.get("validThrough") or "")[:10] or None,
                       "employment_type": ", ".join(et) if isinstance(et, list) else et,
                       "hiring_org": ((j.get("hiringOrganization") or {}).get("name")
                                      if isinstance(j.get("hiringOrganization"), dict) else None)})
    return None


def parse_successfactors_search(page_html: str, base: str) -> list[RawPosting]:
    """SAP SuccessFactors career sites (jobs2web): search results link each job as /job/<City-Title-ST-zip>/<id>/."""
    out, seen = [], set()
    for m in re.finditer(r'<a\b([^>]*\bclass="[^"]*jobTitle-link[^"]*"[^>]*)>(.*?)</a>', page_html or "", re.S | re.I):
        href = re.search(r'href="([^"]+)"', m.group(1))
        if not href:
            continue
        link = html.unescape(href.group(1))
        link = link if link.startswith("http") else base.rstrip("/") + link
        jid = re.search(r"/(\d{5,})/?$", link)
        if not jid or jid.group(1) in seen:
            continue
        seen.add(jid.group(1))
        slug = re.search(r"/job/([^/]+)/\d+", link)
        loc = ""
        if slug:
            s = slug.group(1)
            st = re.search(r"-([A-Z]{2})-\d{5}", s)
            loc = f"{s.split('-')[0].replace('%20', ' ').title()}, {st.group(1)}" if st else ""
        out.append(RawPosting(title=html_to_text(m.group(2)).strip(), url=link, ats_job_id=jid.group(1),
                              location_text=loc, source="successfactors"))
    return out


def parse_successfactors_job(page_html: str, posting: RawPosting) -> RawPosting:
    m = re.search(r'<span class="jobdescription">(.*?)</span>\s*</div>', page_html or "", re.S)
    if m:
        posting.description = html_to_text(m.group(1))
    city = re.search(r'itemprop="addressLocality"[^>]*content="([^"]+)"', page_html or "")
    region = re.search(r'itemprop="addressRegion"[^>]*content="([^"]+)"', page_html or "")
    if city:
        posting.location_text = ", ".join(x for x in (city.group(1), region.group(1) if region else "") if x)
    posted = re.search(r'itemprop="datePosted"[^>]*content="([^"]+)"', page_html or "")
    if posted:
        try:
            posting.posted_at = datetime.strptime(posted.group(1), "%a %b %d %H:%M:%S UTC %Y")
        except ValueError:
            pass
    return posting


def parse_azstatejobs_search(page_html: str) -> list[dict]:
    """State of Arizona job search results: one table row per job, with the department, type and location."""
    rows = []
    for m in re.finditer(r'<tr\b((?:[^>"]|"[^"]*")*)>(.*?)</tr>', page_html or "", re.S):
        link = re.search(r'data-job-url="([^"]+)"', m.group(1))
        if not link:
            continue
        url, row = html.unescape(link.group(1)), m.group(2)

        def cell(cls):
            c = re.search(r'<td[^>]*class="[^"]*' + cls + r'[^"]*"[^>]*>(.*?)</td>', row, re.S)
            return re.sub(r"\s+", " ", html_to_text(c.group(1))).replace("- ", "").strip() if c else ""
        def items(cls):
            c = re.search(r'<td[^>]*class="[^"]*' + cls + r'[^"]*"[^>]*>(.*?)</td>', row, re.S)
            vals = [re.sub(r"\s+", " ", x).strip(" -") for x in html_to_text(c.group(1)).split("\n")] if c else []
            return list(dict.fromkeys(v for v in vals if v))
        title = re.search(r"<a[^>]*>(.*?)</a>", row, re.S)
        places = items("location")
        loc = "; ".join("Remote, Arizona" if "REMOTE" in x.upper() else f"{x.title()}, AZ" for x in places)
        rows.append({"url": url, "title": html_to_text(title.group(1)).strip() if title else cell("title"),
                     "department": cell("department"), "type": cell("employment-type"), "location": loc,
                     "closing": cell("closing")})
    return rows
