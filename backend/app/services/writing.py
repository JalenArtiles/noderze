"""Writing engine for cover letters, application answers, outreach and interview prep.

Voice: a real college senior. Plain, specific, short. No em dashes, no stock phrases.
Grounding: every claim about the candidate must come from the fact ledger or profile. Where a personal
reason is needed and none is on file, the draft contains a [bracketed prompt] instead of invented text.
"""
from __future__ import annotations

import re
from datetime import date

from ..util import clean_dashes
from .llm import llm
from .taxonomy import AREA_LABELS, _area_regex, areas_in, certs_in

BANNED = ["i am thrilled", "i'm thrilled", "passionate about", "my passion", "excited to apply", "i am excited to",
          "dynamic", "fast-paced", "synergy", "leverage", "utilize", "delve", "testament", "unique blend",
          "perfect fit", "ideal candidate", "go-getter", "hit the ground running", "results-driven", "detail-oriented",
          "team player", "in today's", "ever-evolving", "cutting-edge", "world-class", "game-changer", "spearhead",
          "seamless", "robust", "i believe i would be", "esteemed", "thrive in", "wealth of"]
LIMITS = {"recruiter_connect": 200, "alumni": 200, "sdr_manager": 200, "recruiter_followup": 900, "employee_info": 900,
          "hiring_manager": 700, "answer": 1500}
VOICE = ("Write like a capable college senior, not a marketer. Short sentences, concrete details, first person. "
         "Never use em dashes. Avoid: " + ", ".join(BANNED[:20]) + ". Do not invent experience, numbers, tools, "
         "titles or motivations. Only use the facts provided. If a personal reason is needed and not provided, "
         "write a short [bracketed prompt] for the candidate to fill in.")


def style_check(text: str, kind: str = "answer") -> tuple[str, list[str]]:
    cleaned = clean_dashes(text).strip()
    flags = []
    low = cleaned.lower()
    for b in BANNED:
        if b in low:
            flags.append(f"Generic phrase: '{b}'.")
    if cleaned.count("!") > 1:
        flags.append("More than one exclamation mark.")
    limit = LIMITS.get(kind)
    if limit and len(cleaned) > limit:
        flags.append(f"{len(cleaned)} characters; the limit for this kind is {limit}.")
    if "[" in cleaned:
        flags.append("Contains a [bracketed prompt] you need to fill in before using.")
    return cleaned, flags


def prose_claim_check(text: str, corpus: str, held_certs: set[str]) -> list[str]:
    """Check sentences that talk about the candidate ('I', 'my') for unsupported tools, numbers or certs."""
    flags = []
    low_corpus = corpus.lower()
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if not re.search(r"\b(i|i've|i'm|my|me)\b", sent, re.I):
            continue
        for kind in ("tech",):
            for _, terms in areas_in(sent, kind).items():
                for t in terms:
                    if t not in low_corpus:
                        flags.append(f"Check: '{t}' in a sentence about you, but it is not in your resume or profile.")
        for num in re.findall(r"\$?\b\d[\d,.]*(?:[kKmMbB]\b|%|\+)?", sent):
            num = num.rstrip(".,")
            if num not in corpus and not re.fullmatch(r"20\d\d", num):
                flags.append(f"Check: the number '{num}' is not in your source material.")
        for cert in certs_in(sent):
            if cert.lower() not in held_certs:
                flags.append(f"Check: mentions {cert}, which you don't hold.")
    return sorted(set(flags))


# ----------------------------------------------------------------------------- fact helpers

def _org(role_text: str | None, section: str = "experience") -> str:
    """Experience lines read 'Title - Org'; project lines read 'Org | Detail - Project'."""
    if not role_text:
        return ""
    head = role_text.split("\t")[0]
    parts = re.split(r"\s+[\u2014\u2013-]\s+", head)
    if section == "projects":
        return parts[0].split(" | ")[0].strip()
    return parts[1].strip() if len(parts) > 1 else parts[0].strip()


def _first_person(fact: dict) -> str:
    sent = re.split(r"(?<=[.])\s+", fact["text"].strip())[0].rstrip(".")
    sent = sent[0].lower() + sent[1:] if sent and sent[:2] != "AI" else sent
    org = _org(fact.get("role"), fact.get("section", "experience"))
    if not org:
        return f"I {sent}."
    if fact.get("section") == "projects":
        the = "the " if re.search(r"fellowship|program|academy|club", org, re.I) else ""
        return f"Through {the}{org}, I {sent}."
    return f"At {org}, I {sent}."


SE_CORE = ("discovery", "value_selling", "customer_facing", "prospecting", "demo", "presentation")


def best_facts(ledger: list[dict], text: str, sections=("experience", "projects"), k: int = 2,
               kind: str | None = None) -> list[dict]:
    """Pick resume facts that match the posting (weight 2) and core SE skills (weight 1)."""
    kinds = [kind] if kind else ["tech", "sales"]
    jd = [_area_regex(kd, a) for kd in kinds for a in areas_in(text, kd)]
    core = [_area_regex("sales", a) for a in SE_CORE] if (kind in (None, "sales")) else []
    pool = [f for f in ledger if f["section"] in sections and f["kind"] in ("bullet", "text")]

    def score(f):
        return 2 * sum(bool(r.search(f["text"])) for r in jd) + sum(bool(r.search(f["text"])) for r in core)

    ranked = sorted(pool, key=lambda f: (-score(f), f["index"]))
    return [f for f in ranked if score(f) > 0][:k] or ranked[:1]


def _relevant_courses(profile: dict, ledger: list[dict], text: str, k: int = 3) -> list[str]:
    """Prefer the profile's course names (they are the corrected spellings), then the resume's."""
    courses = [c for c in profile.get("coursework", []) if isinstance(c, str)]
    if not courses:
        for f in ledger:
            if f["section"] == "coursework":
                courses += [c.strip() for c in f["text"].split(",")]
    rx = [_area_regex("tech", a) for a in areas_in(text, "tech")] + [_area_regex("tech", a) for a in ("networking", "security")]
    return sorted(courses, key=lambda c: -sum(bool(r.search(c)) for r in rx))[:k]


def _story_prompt(ledger: list[dict]) -> str:
    teach = next((f for f in ledger if f["kind"] in ("bullet", "text") and re.search(r"instruct|teach|coach|tutor", f["text"], re.I)), None)
    if teach:
        return ("[Open with a short personal story. One option from your resume: " + teach["text"].rstrip(".").lower()
                + ", where you had to explain the same thing several ways until it clicked.]")
    return "[Open with a short personal story the interviewer can relate to.]"


def _clean_title(title: str) -> str:
    return re.sub(r",\s*[A-Z][a-zA-Z .]+$", "", title).strip()


# ----------------------------------------------------------------------------- generators

def _grad_phrase(profile: dict) -> str:
    g = str(profile.get("expected_graduation", ""))
    try:
        return date(int(g[:4]), int(g[5:7]), 1).strftime("%B %Y")
    except (ValueError, IndexError):
        return "[graduation date]"


def cover_letter(ctx: dict) -> tuple[str, str]:
    """ctx: profile, ledger, company, company_facts, job_title, job_text, program, analysis. Returns (text, by)."""
    if ctx.get("mode") == "intern":
        return intern_cover_letter(ctx)
    p, led = ctx["profile"], ctx["ledger"]
    if llm.available:
        out = llm.text(VOICE + " Write a cover letter of 230 to 320 words.", _ctx_prompt(ctx, "cover letter"))
        if out:
            return out, "llm"
    name = p.get("name", "")
    jt = f"{ctx['job_title']}\n{ctx['job_text'] or ''}"
    sales = best_facts(led, jt, k=2)
    tech_proj = best_facts(led, jt, sections=("projects",), k=1, kind="tech")
    courses = _relevant_courses(p, led, jt)
    program = ctx.get("program")
    lines = [f"Dear {ctx['company']} recruiting team,", ""]
    target = f"{ctx['company']}'s {program}" if program else f"the {_clean_title(ctx['job_title'])} role"
    lines.append(f"I'm a senior at Arizona State University studying {p.get('degree_short', 'Applied Computing with a cybersecurity focus')}, "
                 f"graduating in {_grad_phrase(p)}. I'm applying to {target}.")
    lines.append("")
    para = [_first_person(f) for f in sales]
    if tech_proj and tech_proj[0] not in sales:
        para.append(_first_person(tech_proj[0]))
    lines.append(" ".join(para))
    lines.append("")
    if len(courses) > 1:
        lines.append(f"My coursework includes {', '.join(courses[:-1])} and {courses[-1]}.")
    lines.append("")
    why = ctx.get("why_company_fact")
    closing = (f"What draws me to {ctx['company']}: {why}" if why else
               f"[One specific reason you want to work at {ctx['company']}: a product you tried, a customer story, "
               f"or a conversation with someone there.]")
    if ctx.get("family") in ("direct_se",) or program:
        closing += (" I haven't held a sales engineering title yet. I'm looking for a team that trains people into the "
                    "role, and I'd bring sales reps and technical coursework to that training from day one.")
    lines += [closing, "", "Thank you for your time,", name]
    return "\n".join(l for l in lines if l is not None).replace("\n\n\n", "\n\n"), "template"


def answer(question_key: str, ctx: dict) -> tuple[str, str]:
    if ctx.get("mode") == "intern" and question_key in INTERN_QUESTIONS:
        return intern_answer(question_key, ctx)
    p, led = ctx["profile"], ctx["ledger"]
    q = QUESTIONS[question_key]
    if llm.available:
        out = llm.text(VOICE + " Answer in 90 to 160 words.", _ctx_prompt(ctx, f"application answer to: {q}"))
        if out:
            return out, "llm"
    jt = f"{ctx['job_title']}\n{ctx['job_text'] or ''}"
    facts = best_facts(led, jt, k=2)
    fp = " ".join(_first_person(f) for f in facts)
    company = ctx["company"]
    if question_key == "tell_me_about_yourself":
        hook = ctx.get("story_hook") or _story_prompt(led)
        return (f"{hook} I'm a senior at ASU studying {p.get('degree_short', 'Applied Computing (cybersecurity)')}, "
                f"graduating {_grad_phrase(p)}. {fp} That mix is why I'm aiming for {_clean_title(ctx['job_title'])}: the job is "
                f"half understanding the technology and half helping a customer decide, and I've done some of both."), "template"
    if question_key == "why_company":
        why = ctx.get("why_company_fact")
        return ((f"{why} " if why else f"[A specific reason {company} stands out to you.] ") +
                f"The {ctx['job_title']} role fits where I'm headed, and {ctx.get('program_line') or 'the team structure'} "
                f"is the kind of start I'm looking for."), "template"
    if question_key == "why_role":
        fits = [f["requirement"] for f in (ctx.get("analysis") or {}).get("fits", [])][:3]
        return (f"The posting asks for {', '.join(fits) if fits else 'a mix of technical and customer skills'}, which "
                f"lines up with what I've done. {fp} I want the version of that work where I'm the technical voice in "
                f"the deal."), "template"
    if question_key in ("why_se", "why_solutions_engineering"):
        return ("[One sentence on what draws you to being the technical voice in a sale.] "
                f"{fp} My coursework covers the technical side, from networks to secure coding. Sales engineering is "
                "the role where both halves of that background get used."), "template"
    if question_key == "why_cybersecurity":
        certs = [c.get("name") if isinstance(c, dict) else str(c) for c in p.get("certifications", [])]
        return ("[Your personal reason for choosing cybersecurity.] I chose a cybersecurity focus at ASU"
                + (f" and completed {certs[0]}" if certs else "") +
                ". Security products are hard to buy because the risk is invisible until it isn't, which is exactly "
                "where a technical seller helps."), "template"
    return "[Write your answer.]", "template"


QUESTIONS = {
    "tell_me_about_yourself": "Tell us about yourself.",
    "why_company": "Why this company?",
    "why_role": "Why this role?",
    "why_se": "Why sales engineering?",
    "why_solutions_engineering": "Why solutions engineering?",
    "why_cybersecurity": "Why cybersecurity?",
}


def outreach(kind: str, person: dict, ctx: dict) -> tuple[str, str]:
    if ctx.get("mode") == "intern":
        return intern_outreach(kind, person, ctx)
    p = ctx["profile"]
    first = (person.get("name") or "there").split()[0]
    me = (p.get("name") or "").split()[0]
    company, target = ctx["company"], ctx.get("program") or ctx.get("job_title") or "early-career SE roles"
    if llm.available:
        out = llm.text(VOICE + f" Write a {kind.replace('_', ' ')} message. Hard limit {LIMITS.get(kind, 700)} characters.",
                       _ctx_prompt(ctx, f"{kind} message to {person.get('name')} ({person.get('title')})"))
        if out:
            return out, "llm"
    grad = _grad_phrase(p)
    if kind == "recruiter_connect":
        msg = (f"Hi {first}, I'm an ASU cybersecurity senior ({grad}) with B2B sales experience, interested in "
               f"{company}'s {target}. I'd like to connect. {me}")
        if len(msg) > 200:
            msg = f"Hi {first}, ASU cybersecurity senior ({grad}) with B2B sales experience, interested in {company}'s {target}. {me}"
        return msg[:200], "template"
    if kind == "sdr_manager":
        return (f"Hi {first}, I'm an ASU cybersecurity senior ({grad}) with cold calling and prospecting experience. I'm "
                f"applying for {target} at {company} and would value connecting. {me}")[:200], "template"
    if kind == "alumni":
        return (f"Hi {first}, fellow Sun Devil here. I'm a cybersecurity senior aiming for sales engineering and "
                f"would value 15 minutes on your path at {company}. {me}")[:200], "template"
    fact = best_facts(ctx["ledger"], f"{ctx.get('job_title', '')} {ctx.get('job_text') or ''}", k=1)
    fact_line = _first_person(fact[0]) if fact else ""
    if kind == "recruiter_followup":
        return (f"Hi {first}, thanks for connecting. I'm graduating from ASU in {grad} with a cybersecurity focus and "
                f"applied (or am about to apply) for {target}. {fact_line} If you're recruiting for this, I'd appreciate "
                f"knowing what the team looks for most, and whether a short call would make sense. Thanks, {me}"), "template"
    if kind == "employee_info":
        return (f"Hi {first}, I'm an ASU senior studying cybersecurity, and I'm trying to break into sales engineering. "
                f"Your path at {company} is close to the one I'm aiming for. Would you have 15 minutes in the next few "
                f"weeks to tell me how you got into the role and what you'd do differently starting out? Happy to work "
                f"around your schedule. Thanks, {me}"), "template"
    if kind == "hiring_manager":
        return (f"Hi {first}, I applied for {target} at {company}. Short version: ASU cybersecurity senior ({grad}), "
                f"B2B sales internship, and client work explaining technical products. {fact_line} If it's useful, I can "
                f"send a two-minute walkthrough of how I'd explain {company}'s product to a buyer. Thanks, {me}"), "template"
    return "[Write your message.]", "template"


def interview_questions(ctx: dict) -> dict:
    if ctx.get("mode") == "intern":
        return intern_interview_questions(ctx)
    jt = f"{ctx['job_title']}\n{ctx['job_text'] or ''}"
    company, product = ctx["company"], ctx.get("product") or f"{ctx['company']}'s product"
    tech = list(areas_in(jt, "tech"))
    bank = {
        "networking": ["Walk me through what happens when you type a URL into a browser.",
                       "How would you troubleshoot a device that can't reach the cloud from a customer network?"],
        "network_security": ["What does a firewall do that a VPN doesn't?", "Explain zero trust to a CFO in two minutes."],
        "security": ["What's the difference between a vulnerability, a threat and a risk?",
                     "How would you explain why a customer needs this if they've never been breached?"],
        "cloud": ["What's the shared responsibility model?", "When would a customer pick SaaS over self-hosted?"],
        "apis": ["What is a REST API, in plain terms?", "How would you prove an integration works during a trial?"],
        "programming": ["Tell me about something you built and a bug you had to track down."],
        "databases": ["Explain a SQL join to someone non-technical."],
        "ai": ["How did you judge whether a model answer was good in your AI evaluation work?"],
        "linux": ["How would you check whether a service is running and listening on a Linux box?"],
        "iot_hardware": ["How would you plan a hardware rollout across 50 sites?"],
    }
    return {
        "behavioral": ["Tell me about yourself.", "Tell me about a time you had to learn something technical quickly.",
                       "Tell me about a deal or project that didn't go your way. What did you do?",
                       "Describe a time you disagreed with a teammate or client.",
                       "What's your biggest weakness for this role, and what are you doing about it?"],
        "sales": ["How did you prospect in your internship, and what worked?", "Sell me something you use every day.",
                  "How do you know a prospect is qualified?", "How do you work with an account executive on a deal?"],
        "technical": [q for a in tech for q in bank.get(a, [])][:8] or bank["networking"],
        "product": [f"What problem does {product} solve, and for whom?", f"Who are {company}'s main competitors, and "
                    f"how would you position against one of them?", f"What would you want to learn in your first 90 days at {company}?"],
        "customer_scenario": [f"A prospect says their current tool works fine. How do you run discovery for {company}?",
                              "A trial is failing because of the customer's network. What do you do?"],
        "discovery": ["Write five discovery questions for this buyer and practice them out loud."],
        "demo": [f"Give a 5-minute demo or walkthrough of {product} to a non-technical buyer."],
        "objection": ["'It's too expensive.'", "'We already have something that does this.'", "'Security won't approve a cloud tool.'"],
        "why": ["Why sales engineering?", f"Why {company}?", "Why cybersecurity / software / AI?"],
    }


def _ctx_prompt(ctx: dict, what: str) -> str:
    facts = "\n".join(f"- {f['text']}" + (f" (role: {_org(f.get('role'))})" if f.get('role') else "")
                      for f in ctx["ledger"] if f["kind"] in ("bullet", "text", "role"))[:6000]
    cf = "\n".join(f"- {x}" for x in ctx.get("company_facts", [])[:15])
    p = ctx["profile"]
    intern = ("\nThis is a part-time spring 2027 internship (January to May) that the candidate is taking for academic "
              "credit while still in classes.") if ctx.get("mode") == "intern" else ""
    return (f"Write a {what}.{intern}\nCandidate: {p.get('name')}, graduating {_grad_phrase(p)}. "
            f"Interview style: {p.get('interview_style', '')}. Self-reported strengths: {', '.join(p.get('strengths', []))}.\n"
            f"Resume facts (only source of claims about the candidate):\n{facts}\n\nCompany: {ctx['company']}\n"
            f"Company facts (sourced):\n{cf}\n\nRole: {ctx['job_title']}\nPosting:\n{(ctx.get('job_text') or '')[:5000]}")


# ----------------------------------------------------------------------------- spring internships

TRACK_WORDS = {"cyber": "cybersecurity", "data": "data analytics", "network": "networking", "it": "IT"}
INTERN_QUESTIONS = {
    "tell_me_about_yourself": "Tell us about yourself.",
    "why_company": "Why this company?",
    "why_role": "Why this internship?",
    "availability": "What is your availability this spring?",
    "why_field": "Why this field?",
}


def _hours_phrase(ctx: dict) -> str:
    pref = (ctx.get("profile") or {}).get("internship") or {}
    return f"{pref.get('hours_min', 10)} to {pref.get('hours_max', 30)} hours a week"


def intern_cover_letter(ctx: dict) -> tuple[str, str]:
    p, led = ctx["profile"], ctx["ledger"]
    word = TRACK_WORDS.get(ctx.get("track"), "technical")
    if llm.available:
        out = llm.text(VOICE + " Write a cover letter of 200 to 280 words for a part-time spring internship.",
                       _ctx_prompt(ctx, "cover letter for a part-time spring 2027 internship taken for academic credit"))
        if out:
            return out, "llm"
    jt = f"{ctx['job_title']}\n{ctx['job_text'] or ''}"
    tech = best_facts(led, jt, k=1, kind="tech")
    people = best_facts(led, jt, k=1, kind="sales")
    courses = _relevant_courses(p, led, jt)
    lines = [f"Dear {ctx['company']} recruiting team,", "",
             f"I'm a senior at Arizona State University studying {p.get('degree_short', 'Applied Computing with a cybersecurity focus')}, "
             f"graduating in {_grad_phrase(p)}. I'm applying for the {_clean_title(ctx['job_title'])} for spring 2027. "
             f"I can work {_hours_phrase(ctx)} from January through May around my classes, and the internship would "
             f"count toward my degree.", ""]
    para = [_first_person(f) for f in tech + [f for f in people if f not in tech]]
    if para:
        lines += [" ".join(para), ""]
    if len(courses) > 1:
        lines += [f"My coursework includes {', '.join(courses[:-1])} and {courses[-1]}, so I'd start with the "
                  f"fundamentals and want to learn how {word} work is done on a real team.", ""]
    why = ctx.get("why_company_fact")
    lines += [f"What draws me to {ctx['company']}: {why}" if why else
              f"[One specific reason you want this internship at {ctx['company']}: the team, what they work on, or "
              f"someone you talked to there.]", "", "Thank you for your time,", p.get("name", "")]
    return "\n".join(lines).replace("\n\n\n", "\n\n"), "template"


def intern_answer(key: str, ctx: dict) -> tuple[str, str]:
    p, led = ctx["profile"], ctx["ledger"]
    q = INTERN_QUESTIONS[key]
    word = TRACK_WORDS.get(ctx.get("track"), "technical")
    if llm.available:
        out = llm.text(VOICE + " Answer in 80 to 150 words.",
                       _ctx_prompt(ctx, f"application answer for a part-time spring internship to: {q}"))
        if out:
            return out, "llm"
    jt = f"{ctx['job_title']}\n{ctx['job_text'] or ''}"
    facts = best_facts(led, jt, k=2)
    fp = " ".join(_first_person(f) for f in facts)
    company = ctx["company"]
    courses = _relevant_courses(p, led, jt, k=2)
    if key == "tell_me_about_yourself":
        hook = ctx.get("story_hook") or _story_prompt(led)
        return (f"{hook} I'm a senior at ASU studying {p.get('degree_short', 'Applied Computing (cybersecurity)')}, "
                f"graduating {_grad_phrase(p)}. {fp} This spring I'm looking for a part-time {word} internship so I can "
                f"use what I've learned on real systems before I graduate."), "template"
    if key == "why_company":
        why = ctx.get("why_company_fact")
        return ((f"{why} " if why else f"[A specific reason {company} stands out to you.] ") +
                f"The {_clean_title(ctx['job_title'])} would give me hands-on {word} experience during my last spring "
                f"at ASU, on a team that does this work every day."), "template"
    if key == "why_role":
        fits = [f["requirement"] for f in (ctx.get("analysis") or {}).get("fits", [])][:3]
        course_line = f" My coursework in {' and '.join(courses)} covers the basics." if courses else ""
        return (f"The posting asks for {', '.join(fits) if fits else 'curiosity and the fundamentals'}.{course_line} {fp} "
                f"I want an internship where I do real {word} work and learn how a team runs it day to day."), "template"
    if key == "availability":
        return (f"I'm available January through May 2027 for {_hours_phrase(ctx)}, scheduled around my classes. "
                "[Add the days and times you're free this spring.] The internship would also count toward my "
                "degree, so I'm committed to the full term."), "template"
    if key == "why_field":
        reason = {"cyber": "[Your personal reason for choosing cybersecurity.] ",
                  "data": "[Your personal reason for wanting to work with data.] ",
                  "network": "[Your personal reason for wanting networking experience.] "}.get(ctx.get("track"), "[Your reason.] ")
        return (reason + (f"Courses like {' and '.join(courses)} got me interested, and an internship is where I can "
                          f"see how it works outside a classroom." if courses else
                          "An internship is where I can see how it works outside a classroom.")), "template"
    return "[Write your answer.]", "template"


def intern_outreach(kind: str, person: dict, ctx: dict) -> tuple[str, str]:
    p = ctx["profile"]
    first = (person.get("name") or "there").split()[0]
    me = (p.get("name") or "").split()[0]
    company, title = ctx["company"], _clean_title(ctx.get("job_title") or "internship")
    word = TRACK_WORDS.get(ctx.get("track"), "tech")
    if llm.available:
        out = llm.text(VOICE + f" Write a {kind.replace('_', ' ')} message about a spring internship. "
                                f"Hard limit {LIMITS.get(kind, 700)} characters.",
                       _ctx_prompt(ctx, f"{kind} message to {person.get('name')} ({person.get('title')})"))
        if out:
            return out, "llm"
    grad = _grad_phrase(p)
    fact = best_facts(ctx["ledger"], f"{ctx.get('job_title', '')} {ctx.get('job_text') or ''}", k=1)
    fact_line = _first_person(fact[0]) if fact else ""
    if kind == "recruiter_connect":
        for msg in (f"Hi {first}, I'm an ASU cybersecurity senior looking for a part-time {word} internship this spring. "
                    f"I saw {company}'s {title} and would like to connect. {me}",
                    f"Hi {first}, ASU cybersecurity senior looking for a spring {word} internship. I'm interested in "
                    f"{company}'s {title}. {me}",
                    f"Hi {first}, ASU senior interested in {company}'s spring {word} internship. Would like to connect. {me}"):
            if len(msg) <= 200:
                return msg, "template"
        return msg[:200], "template"
    if kind == "alumni":
        return (f"Hi {first}, fellow Sun Devil here. I'm a cybersecurity senior looking for a spring internship and "
                f"would value 10 minutes on your experience at {company}. {me}")[:200], "template"
    if kind == "recruiter_followup":
        return (f"Hi {first}, thanks for connecting. I applied (or am about to apply) for the {title} at {company}. "
                f"I'm an ASU senior studying Applied Computing with a cybersecurity focus, graduating in {grad}, and I'm "
                f"looking for a spring internship that counts toward my degree. {fact_line} Could you tell me what the team "
                f"looks for, and whether {_hours_phrase(ctx)} works for this role? Thanks, {me}"), "template"
    if kind in ("hiring_manager", "sdr_manager"):
        return (f"Hi {first}, I'm an ASU cybersecurity senior and applied for the {title} on your team. {fact_line} "
                f"I'm available {_hours_phrase(ctx)} this spring and would be glad to talk about how I could help. "
                f"Thanks, {me}"), "template"
    if kind == "employee_info":
        return (f"Hi {first}, I'm an ASU senior applying for {company}'s {title}. Would you have 10 minutes to tell me "
                f"what the work is like and what helped you get in? Happy to work around your schedule. Thanks, {me}"), "template"
    return "[Write your message.]", "template"


def intern_interview_questions(ctx: dict) -> dict:
    company = ctx["company"]
    tech = {
        "cyber": ["What are confidentiality, integrity and availability? Give an example of each.",
                  "What's the difference between a vulnerability, a threat and a risk?",
                  "A user reports a suspicious email. What do you do, step by step?",
                  "What is least privilege, and why does it matter?",
                  "An alert fires for a login from another country. How do you decide if it's real?",
                  "What does a SIEM do?"],
        "data": ["Explain the difference between an inner join and a left join.",
                 "Write a query that finds the top five customers by total sales.",
                 "You get a messy spreadsheet. How do you clean it before analyzing it?",
                 "When would you use the median instead of the mean?",
                 "How do you pick the right chart for a finding?",
                 "Explain one insight from a project to someone non-technical."],
        "network": ["Walk me through what happens when you type a URL into a browser.",
                    "What's the difference between TCP and UDP?",
                    "How does DHCP give a device an IP address?",
                    "How many usable hosts are in a /24, and why?",
                    "What is a VLAN for?",
                    "A user can't reach the internet. How do you troubleshoot it?"],
    }
    track = ctx.get("track")
    return {
        "behavioral": ["Tell me about yourself.", "Tell me about a time you had to learn something technical quickly.",
                       "Tell me about a project that didn't go as planned. What did you do?",
                       "How will you balance this internship with your classes?",
                       "Describe a time you explained something technical to a non-technical person."],
        "technical": tech.get(track, tech["network"][:3] + tech["cyber"][:3]),
        "role": ["What do you hope to learn in this internship?", f"What do you know about what {company} does?",
                 "What tools have you used, and how comfortable are you with each?"],
        "why": ["Why this internship?", f"Why {company}?", f"Why {TRACK_WORDS.get(track, 'this field')}?"],
    }
