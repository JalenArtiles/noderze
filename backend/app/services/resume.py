"""Resume engine.

The master resume is parsed into a fact ledger. Every tailoring suggestion must trace back to a ledger
fact or a profile fact; anything else is flagged by the claim checker and cannot be approved without an
explicit acknowledgement. Rendering edits the original .docx in place so formatting survives.
"""
from __future__ import annotations

import copy
import difflib
import re
import shutil
from datetime import date
from pathlib import Path

import docx

from ..config import settings
from ..util import slugify
from .llm import llm
from .taxonomy import AREA_LABELS, _area_regex, areas_in, certs_in, certs_required

SECTION_ALIASES = {
    "summary": ["professional summary", "summary", "profile", "objective"],
    "coursework": ["relevant coursework", "coursework"],
    "skills": ["skills", "technical skills"],
    "experience": ["experience", "work experience", "professional experience"],
    "projects": ["projects", "project experience"],
    "education": ["education"],
    "certifications": ["certifications", "certificates", "licenses & certifications"],
    "activities": ["club involvement", "activities", "leadership", "involvement", "extracurricular"],
}
DATE_RANGE = re.compile(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}|\b\d{4}\s*[\u2013\u2014-]\s*"
                        r"(?:\d{4}|present|current)", re.I)
SE_TERMS = re.compile(r"sales engineer(?:ing)?|solutions? engineer(?:ing)?|pre-?sales engineer(?:ing)?", re.I)


def _section_key(text: str) -> str | None:
    t = text.strip().lower()
    for key, names in SECTION_ALIASES.items():
        if t in names:
            return key
    return None


def _is_list(p) -> bool:
    return p._p.pPr is not None and p._p.pPr.numPr is not None or "list" in (p.style.name or "").lower()


def parse_docx(path: str | Path) -> dict:
    d = docx.Document(str(path))
    contact: dict = {}
    sections: list[dict] = []
    current = {"key": "header", "title": "Header", "items": []}
    last_role = None
    for i, p in enumerate(d.paragraphs):
        text = p.text.strip()
        if not text:
            continue
        bold_first = bool(p.runs and p.runs[0].bold)
        key = _section_key(text)
        if key or (text.isupper() and len(text) < 40 and bold_first and i > 1):
            sections.append(current)
            current = {"key": key or slugify(text), "title": text.title(), "items": []}
            last_role = None
            continue
        if current["key"] == "header":
            if i == 0:
                contact["name"] = text.title() if text.isupper() else text
            else:
                email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
                phone = re.search(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text)
                link = re.search(r"linkedin\.com/in/[\w-]+", text, re.I)
                loc = re.match(r"([A-Za-z .]+,\s*[A-Z]{2})", text)
                contact.update({k: v.group(0) for k, v in
                                {"email": email, "phone": phone, "linkedin": link, "location": loc}.items() if v})
            continue
        if "\t" in p.text and bold_first and DATE_RANGE.search(p.text):
            head, _, dates = p.text.partition("\t")
            parts = re.split(r"\s+[\u2014\u2013|-]\s+|\s+\|\s+", head.strip(), maxsplit=1)
            last_role = {"kind": "role", "index": i, "text": text, "title": parts[0].strip(),
                         "org": parts[1].strip() if len(parts) > 1 else "", "dates": dates.strip()}
            current["items"].append(last_role)
            continue
        if last_role and re.fullmatch(r"[A-Za-z .&]+,\s*[A-Z]{2}(?:\s*(?:&|and)\s*[A-Za-z .]+,\s*[A-Z]{2})?(?:\s*\|.*)?", text) \
                and current["items"] and current["items"][-1] is last_role:
            last_role["location"] = text
            continue
        current["items"].append({"kind": "bullet" if _is_list(p) else "text", "index": i, "text": text,
                                 "role": last_role["text"] if last_role else None})
    sections.append(current)
    return {"contact": contact, "sections": [s for s in sections if s["key"] != "header" or s["items"]]}


def build_ledger(parsed: dict) -> list[dict]:
    ledger = []
    for s in parsed["sections"]:
        n = 0
        for it in s["items"]:
            n += 1
            ledger.append({"id": f"{s['key']}-{n}", "section": s["key"], "kind": it["kind"], "text": it["text"],
                           "index": it["index"], "role": it.get("role") or (it["text"] if it["kind"] == "role" else None)})
    return ledger


def titles_held(parsed: dict) -> list[str]:
    return [it["title"] for s in parsed["sections"] if s["key"] in ("experience", "projects")
            for it in s["items"] if it["kind"] == "role"]


# ----------------------------------------------------------------------------- consistency checks

def consistency_checks(parsed: dict, profile: dict) -> list[dict]:
    checks: list[dict] = []
    grad = str(profile.get("expected_graduation", ""))  # "2027-05"
    edu = next((s for s in parsed["sections"] if s["key"] == "education"), None)
    if grad and edu:
        g_year = int(grad[:4])
        month = date(g_year, int(grad[5:7] or 5), 1).strftime("%B") if len(grad) >= 7 else "May"
        for it in edu["items"]:
            if it["kind"] != "role":
                continue
            m = re.search(r"(\d{4})\s*[\u2013\u2014-]\s*(\d{4})(\s*\(in progress\))?", it.get("dates", ""))
            if m and "transfer" not in it.get("dates", "").lower() and int(m.group(2)) < g_year:
                checks.append({
                    "kind": "graduation_date", "severity": "high", "index": it["index"],
                    "find": m.group(0), "replace": f"Expected {month} {g_year}",
                    "message": (f"Education line shows '{m.group(0).strip()}' but your expected graduation is "
                                f"{month} {g_year}. New-grad programs screen on graduation date, so a 2026 end date can "
                                f"make you look ineligible for {g_year} cohorts.")})
    known_courses = [c for c in profile.get("coursework", []) if isinstance(c, str)]
    cw = next((s for s in parsed["sections"] if s["key"] == "coursework"), None)
    if cw and known_courses:
        for it in cw["items"]:
            for course in [c.strip() for c in it["text"].split(",")]:
                for k in known_courses:
                    r = difflib.SequenceMatcher(None, course.lower(), k.lower()).ratio()
                    if course.lower() != k.lower() and r > 0.88:
                        checks.append({"kind": "typo", "severity": "medium", "index": it["index"], "find": course,
                                       "replace": k, "message": f"'{course}' looks like a typo for '{k}'."})
    held = " ".join(titles_held(parsed)).lower()
    for s in parsed["sections"]:
        for it in s["items"]:
            for m in re.finditer(r"\b(?:experienced|expert|extensive experience|proven experience) in ([^.;]+)",
                                 it["text"], re.I):
                phrase = m.group(1)
                se = SE_TERMS.search(phrase)
                if se and not SE_TERMS.search(held):
                    checks.append({
                        "kind": "overclaim", "severity": "high", "index": it["index"], "find": se.group(0),
                        "replace": re.sub(r"\s*engineering$|\s*engineer$", "", se.group(0), flags=re.I),
                        "message": (f"'{m.group(0)[:80]}' claims SE experience, but no role on your resume has an SE "
                                    f"title. Recruiters check this. Describe the real work (technical client sales, "
                                    f"discovery, translating capabilities into business value) instead.")})
    profile_skills = ", ".join(str(v) for v in (profile.get("skills") or {}).values())
    resume_text = " ".join(it["text"] for s in parsed["sections"] for it in s["items"])
    for skill in re.split(r",\s*", profile_skills):
        sk = skill.strip()
        if 1 < len(sk) < 25 and not re.search(r"(?<![a-z])" + re.escape(sk.lower().split(" (")[0]) + r"(?![a-z])",
                                              resume_text.lower()):
            checks.append({"kind": "profile_only_skill", "severity": "low", "message":
                           f"'{sk}' is in your profile but not on your resume. Add it only if you can discuss it."})
    if "github.com" not in resume_text.lower():
        checks.append({"kind": "suggestion", "severity": "low",
                       "message": "No GitHub or portfolio link. One small demo project linked here helps for SE roles."})
    return checks


# ----------------------------------------------------------------------------- job analysis

ADJACENT = {
    "presentation": (r"stakeholder|instructed|explain|translated|guiding|point of contact|communicat",
                     "You have stakeholder communication and teaching experience. Say you explained technical "
                     "capabilities to stakeholders; don't call it executive presentations unless it was."),
    "demo": (r"translated .{0,40}(?:capabilit|technical)|guiding feature decisions|walk",
             "You walked stakeholders through what a product could do. Describe it that way, not as running "
             "product demos."),
    "objection_handling": (r"cold call|prospecting", "Cold calling involves objections. Mention it only with a real example."),
    "linux": (r"operating systems|\bbash\b", "Operating Systems coursework and Bash are adjacent. Don't list Linux "
              "administration until you've done hands-on work."),
    "apis": (r"\bjson\b|integration|prompt", "You can say you've worked with JSON data, not that you've built API integrations."),
    "rfp": (r"scoping|proposal", "You scoped a client engagement; that is not the same as RFP responses."),
    "quota": (r"new business|cold call", "You generated new business. Use activity numbers only if you know them."),
    "iot_hardware": (r"matterport|scann|camera|capture", "Operating capture or camera hardware on-site for a client is a "
                     "fair example of hands-on hardware deployment."),
    "cloud": (r"\bcloud\b", "Cloud appears in your interests, not in hands-on work yet."),
}
HARD_REQS = {
    "Security clearance": r"security clearance|ts/sci|active (?:secret|top secret)",
    "US citizenship": r"u\.?s\.? citizenship (?:is )?required|must be a u\.?s\.? citizen",
    "Willing to relocate": r"willing(?:ness)? to relocate|must relocate|relocate to",
    "Travel": r"travel (?:up to )?\d{1,3}\s?%|\d{1,3}\s?% travel",
}


def analyze(ledger: list[dict], profile: dict, job_title: str, job_text: str, checks: list[dict]) -> dict:
    text = f"{job_title}\n{job_text or ''}"
    profile_skills = " ".join(str(v) for v in (profile.get("skills") or {}).values())
    held_certs = {(c.get("name") if isinstance(c, dict) else str(c)).lower() for c in profile.get("certifications", [])}
    out = {"demonstrated": [], "emphasize": [], "missing": [], "should_not_claim": [], "keywords_to_mirror": [],
           "deprioritize": []}
    resume_text = " ".join(f["text"] for f in ledger)
    evidence = [f for f in ledger if f["section"] not in ("summary", "header")]  # stated interests are not evidence
    for kind in ("tech", "sales"):
        for area, terms in areas_in(text, kind).items():
            rx = _area_regex(kind, area)
            facts = [f for f in evidence if rx.search(f["text"])]
            label = AREA_LABELS[area]
            if facts:
                out["demonstrated"].append({"area": label, "facts": [f["id"] for f in facts[:3]],
                                            "quote": facts[0]["text"][:180]})
                missing_terms = [t for t in terms if not re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])",
                                                                    resume_text.lower())]
                out["keywords_to_mirror"] += [{"term": t, "area": label} for t in missing_terms[:2]]
            elif area in ADJACENT and (adj := [f for f in ledger if re.search(ADJACENT[area][0], f["text"], re.I)]):
                out["emphasize"].append({"area": label, "facts": [f["id"] for f in adj[:2]], "guidance": ADJACENT[area][1]})
            elif rx.search(profile_skills):
                out["emphasize"].append({"area": label, "facts": [], "guidance": "In your profile but not on your "
                                         "resume. Add it if you can discuss it in an interview."})
            else:
                out["missing"].append({"area": label, "terms": terms[:4]})
    req = set(certs_required(text))
    for cert in certs_in(text):
        if cert.lower() not in held_certs:
            (out["should_not_claim"] if cert in req else out["missing"]).append(
                {"area": cert, "reason": "Required and not held" if cert in req else "Preferred and not held"})
    for name, pat in HARD_REQS.items():
        if re.search(pat, text, re.I):
            out["missing" if name != "Security clearance" else "should_not_claim"].append(
                {"area": name, "reason": "Stated in the posting; confirm it applies to you before applying."})
    for c in checks:
        if c["kind"] == "overclaim":
            out["should_not_claim"].append({"area": "SE experience", "reason": c["message"]})
    jd_areas = set(areas_in(text, "tech")) | set(areas_in(text, "sales"))
    for f in ledger:
        if f["kind"] == "bullet" and f["section"] == "experience":
            hits = set(areas_in(f["text"], "tech")) | set(areas_in(f["text"], "sales"))
            if not hits & jd_areas:
                out["deprioritize"].append({"fact": f["id"], "text": f["text"][:120],
                                            "reason": "Doesn't map to anything this posting asks for."})
    return out


# ----------------------------------------------------------------------------- edits

def claim_check(before: str, after: str, ledger: list[dict], profile: dict) -> list[str]:
    """Flag anything in `after` that the resume or profile does not already support."""
    corpus = " ".join(f["text"] for f in ledger) + " " + before + " " + " ".join(
        str(v) for v in (profile.get("skills") or {}).values()) + " " + " ".join(profile.get("verified_claims") or [])
    flags = []
    for kind in ("tech", "sales"):
        for area, terms in areas_in(after, kind).items():
            for t in terms:
                if not re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", corpus.lower()):
                    flags.append(f"Introduces '{t}', which is not in your resume or profile.")
    for num in re.findall(r"(?<![A-Za-z])\$?\d[\d,.]*(?:[kKmMbB]\b|%|\+)?", after):
        if num.strip("$,.") not in corpus:
            flags.append(f"New number '{num}' is not in your source material.")
    for word in re.findall(r"\b(expert|extensive|mastered|led a team|managed a team|senior|spearheaded)\b", after, re.I):
        if word.lower() not in corpus.lower():
            flags.append(f"'{word}' is a stronger claim than your source text supports.")
    held = {(c.get("name") if isinstance(c, dict) else str(c)).lower() for c in profile.get("certifications", [])}
    for cert in certs_in(after):
        if cert.lower() not in held and cert.lower() not in corpus.lower():
            flags.append(f"Mentions {cert}, which you don't hold.")
    return sorted(set(flags))


def _reorder_list_line(text: str, priority_rx: list[re.Pattern]) -> str | None:
    label, sep, rest = text.partition(":")
    items = [x.strip() for x in (rest if sep else text).split(",") if x.strip()]
    if len(items) < 3:
        return None
    scored = sorted(enumerate(items), key=lambda t: (-sum(bool(r.search(t[1])) for r in priority_rx), t[0]))
    new_items = [x for _, x in scored]
    if new_items == items:
        return None
    return f"{label}: {', '.join(new_items)}" if sep else ", ".join(new_items)


def propose_edits(parsed: dict, ledger: list[dict], profile: dict, checks: list[dict], job_title: str,
                  job_text: str, company: str) -> list[dict]:
    edits: list[dict] = []
    n = 0

    def add(**kw):
        nonlocal n
        n += 1
        kw.setdefault("status", "pending")
        kw.setdefault("flags", [])
        edits.append({"id": f"e{n}", **kw})

    for c in checks:
        if c["kind"] in ("graduation_date", "typo", "overclaim") and "index" in c:
            add(kind="replace_text", category="fix", index=c["index"], find=c["find"], replace=c["replace"],
                rationale=c["message"], requires_fact_confirmation=c["kind"] == "graduation_date")
    text = f"{job_title}\n{job_text or ''}"
    jd_areas = list(areas_in(text, "tech")) + list(areas_in(text, "sales"))
    rx = [_area_regex("tech", a) for a in areas_in(text, "tech")] + [_area_regex("sales", a) for a in areas_in(text, "sales")]
    for s in parsed["sections"]:
        if s["key"] in ("skills", "coursework"):
            for it in s["items"]:
                new = _reorder_list_line(it["text"], rx)
                if new:
                    add(kind="replace_paragraph", category="reorder", index=it["index"], before=it["text"], after=new,
                        rationale="Puts the items this posting asks for first.")
        if s["key"] == "experience":
            groups: dict[str, list[dict]] = {}
            for it in s["items"]:
                if it["kind"] == "bullet" and it.get("role"):
                    groups.setdefault(it["role"], []).append(it)
            for role, items in groups.items():
                order = sorted(items, key=lambda it: (-sum(bool(r.search(it["text"])) for r in rx), it["index"]))
                if [i["index"] for i in order] != [i["index"] for i in items]:
                    add(kind="reorder", category="reorder", indices=[i["index"] for i in items],
                        new_order=[i["index"] for i in order], role=role,
                        rationale="Leads with the bullet most relevant to this posting.",
                        preview=[i["text"][:90] for i in order])
    if llm.available and jd_areas:
        _llm_rewrites(add, ledger, profile, job_title, job_text, company)
    for e in edits:
        if e["kind"] == "replace_paragraph":
            e["flags"] = claim_check(e["before"], e["after"], ledger, profile)
    return edits


def _llm_rewrites(add, ledger, profile, job_title, job_text, company) -> None:
    facts = [f for f in ledger if f["kind"] in ("bullet", "text") and f["section"] in ("experience", "projects", "summary")]
    schema = {"type": "object", "properties": {"rewrites": {"type": "array", "items": {"type": "object", "properties": {
        "fact_id": {"type": "string"}, "after": {"type": "string"}, "rationale": {"type": "string"}},
        "required": ["fact_id", "after", "rationale"]}}}, "required": ["rewrites"]}
    system = ("You tailor resume lines for an early-career technical sales candidate. Hard rules: never add skills, "
              "tools, numbers, titles, outcomes or responsibilities that are not in the original line. You may reorder "
              "clauses, use the posting's vocabulary for things the line already says, and tighten wording. "
              "No em dashes. No buzzwords like passionate, dynamic, leverage, spearheaded. Keep each line under 230 "
              "characters. Rewrite at most 5 lines, only where it clearly helps.")
    prompt = (f"Target: {job_title} at {company}\nPosting:\n{(job_text or '')[:6000]}\n\nResume lines:\n" +
              "\n".join(f"[{f['id']}] {f['text']}" for f in facts))
    out = llm.structured(system, prompt, schema) or {}
    by_id = {f["id"]: f for f in facts}
    for r in out.get("rewrites", [])[:5]:
        f = by_id.get(r.get("fact_id"))
        if f and r.get("after") and r["after"].strip() != f["text"]:
            add(kind="replace_paragraph", category="rewrite", index=f["index"], before=f["text"],
                after=r["after"].replace("\u2014", ", ").strip(), rationale=r.get("rationale", ""))


# ----------------------------------------------------------------------------- render

def _replace_paragraph_text(p, new_text: str) -> None:
    runs = p.runs
    if not runs:
        p.add_run(new_text)
        return
    runs[0].text = new_text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def _replace_in_runs(p, find: str, replace: str) -> bool:
    for r in p.runs:
        if find in r.text:
            r.text = r.text.replace(find, replace, 1)
            return True
    if find in p.text:  # spans runs: fall back to a paragraph rewrite that keeps the first run's style
        _replace_paragraph_text(p, p.text.replace(find, replace, 1))
        return True
    return False


def render(master_path: str, edits: list[dict], out_name: str) -> Path:
    out_dir = settings.data_dir / "resumes" / "versions"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{slugify(out_name)}.docx"
    shutil.copy(master_path, out)
    d = docx.Document(str(out))
    paras = list(d.paragraphs)
    # Whole-paragraph rewrites first, then targeted fixes (so a reorder can't resurrect a typo), then moves.
    order = {"replace_paragraph": 0, "replace_text": 1, "reorder": 2, "insert_after": 3}
    for e in sorted(edits, key=lambda x: order.get(x["kind"], 9)):
        if e.get("status") != "approved":
            continue
        if e["kind"] == "replace_text":
            _replace_in_runs(paras[e["index"]], e["find"], e["replace"])
        elif e["kind"] == "replace_paragraph":
            _replace_paragraph_text(paras[e["index"]], e["after"])
        elif e["kind"] == "reorder":
            elems = [copy.deepcopy(paras[i]._p) for i in e["new_order"]]
            for slot, new_el in zip(e["indices"], elems):
                old = paras[slot]._p
                old.addprevious(new_el)
                old.getparent().remove(old)
            paras = list(d.paragraphs)
        elif e["kind"] == "insert_after":
            from docx.text.paragraph import Paragraph
            anchor = paras[e["index"]]
            new_el = copy.deepcopy(anchor._p)
            anchor._p.addnext(new_el)
            _replace_paragraph_text(Paragraph(new_el, anchor._parent), e["text"])
    d.save(str(out))
    return out


# ----------------------------------------------------------------------------- ATS tailoring for entry sales

def ats_tailor(parsed: dict, ledger: list[dict], profile: dict, checks: list[dict], job_title: str, job_text: str,
               company: str, company_texts: list[str], sales_level: str | None) -> dict:
    """Keyword analysis plus edits. Edits that pass the claim check are pre-approved; flagged ones never are."""
    from . import keywords as K

    claims = profile.get("verified_claims") or []
    evidence_text = " ".join(f["text"] for f in ledger if f["section"] not in ("summary", "header")) + " " + " ".join(
        str(v) for v in (profile.get("skills") or {}).values())
    resume_text = " ".join(f["text"] for f in ledger)
    terms = K.screened_terms(job_text, company_texts)
    for t in terms:
        t["on_resume"] = K.present(t["term"], resume_text)
        t["supported"] = t["on_resume"] or K.supported(t["term"], evidence_text, claims)
        t["status"] = "on_resume" if t["on_resume"] else "added" if t["supported"] else "missing"
    edits = propose_edits(parsed, ledger, profile, checks, job_title, job_text, company)
    n = len(edits)
    skills = next((s for s in parsed["sections"] if s["key"] == "skills"), None)
    add_terms = [t["term"] for t in terms if t["status"] == "added" and t["group"] in ("sales", "tools", "domain")]
    keep_terms = [t["term"] for t in terms if t["status"] == "on_resume" and t["group"] in ("sales", "tools")]
    core = [t for t in K.CORE_ENTRY_SALES if K.supported(t, evidence_text, claims)]
    line_terms = list(dict.fromkeys(add_terms + keep_terms + core))[:12]
    if skills and skills["items"] and line_terms:
        last = skills["items"][-1]
        text = "Sales & Tools: " + ", ".join(line_terms)
        n += 1
        edits.append({"id": f"e{n}", "kind": "insert_after", "category": "keywords", "index": last["index"], "text": text,
                      "rationale": "Adds the terms this company screens for that your experience already supports.",
                      "flags": claim_check("", text, ledger, profile), "status": "pending"})
    summary = next((s for s in parsed["sections"] if s["key"] == "summary"), None)
    if summary and summary["items"]:
        mentioned = {t["term"] for t in terms if t["mentions"]}
        ranked = sorted([t for t in core if t != "CRM"], key=lambda t: (t not in mentioned, K.CORE_ENTRY_SALES.index(t)))
        top = [t.lower() for t in ranked[:3]] or ["prospecting", "cold calling"]
        listed = top[0] if len(top) == 1 else f"{', '.join(top[:-1])} and {top[-1]}"
        grad = str(profile.get("expected_graduation", "2027-05"))
        month = {"05": "May", "12": "December", "08": "August"}.get(grad[5:7], grad[5:7])
        role = re.split(r"\s*[,(\u2013-]\s", job_title)[0].strip() or "entry sales"
        text = (f"Cybersecurity student at Arizona State University (B.S. Applied Computing, graduating {month} {grad[:4]}) "
                f"with B2B sales experience in {listed}, plus client work translating technical capabilities into "
                f"business value. Seeking a {role} role at {company}, with the long-term goal of growing into sales engineering.")
        before = summary["items"][0]["text"]
        n += 1
        edits.append({"id": f"e{n}", "kind": "replace_paragraph", "category": "summary", "index": summary["items"][0]["index"],
                      "before": before, "after": text, "rationale": "Points your summary at this role and company.",
                      "flags": claim_check(before, text, ledger, profile), "status": "pending"})
    for e in edits:  # pre-approve everything that passes the claim check
        if not e.get("flags") and e["category"] in ("fix", "reorder", "keywords", "summary", "rewrite"):
            e["status"] = "approved"
            e["auto"] = True
    after_text = resume_text + " " + " ".join(e.get("text") or e.get("after") or "" for e in edits if e["status"] == "approved")
    return {"terms": terms, "before": K.coverage(terms, resume_text), "after": K.coverage(terms, after_text), "edits": edits}
