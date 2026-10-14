"""Spring internships for college credit.

What qualifies (the rules Jalen set):
- Field: data analytics, cybersecurity or networking. General IT roles are kept but filtered out with the reason,
  because the credit needs one of those three fields; he can count one anyway if his coordinator approves it.
- Paid: the posting has to show some sign of pay. No sign at all, or "unpaid", filters it out.
- Hours: 10 to 30 a week. Full time, or a required range above 30, filters it out. Hours not listed is a warning.
- Dates: has to overlap January to May 2027. Summer-only or fall-only filters it out. Not listed is a warning.
- Where: remote (open to someone in Arizona), or onsite or hybrid in the Phoenix area. Tucson and anywhere
  else are filtered out.
Everything in the first half of this file is a pure function over posting text, unit tested, no network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .classify import _dates_in, parse_comp, parse_location

# ----------------------------------------------------------------------------- preferences

DEFAULT_PREFS = {"hours_min": 10, "hours_max": 30, "term": "Spring 2027", "start": "2027-01-01", "end": "2027-05-31"}
TRACK_LABELS = {"cyber": "Cybersecurity", "data": "Data analytics", "network": "Networking", "it": "General IT",
                "other": "Other"}
STATUS_LABELS = {"qualifies": "Qualifies", "check": "Qualifies, one thing to confirm", "out": "Filtered out"}


def prefs(profile: dict | None) -> dict:
    out = dict(DEFAULT_PREFS)
    out.update({k: v for k, v in ((profile or {}).get("internship") or {}).items() if v is not None})
    return out


# ----------------------------------------------------------------------------- is it an internship?

INTERN_TITLE = re.compile(
    r"\bintern(?:s|ship|ships)?\b|\bco-?op\b|\bapprentice(?:ship)?\b|\bfellowship\b"
    r"|\bstudent\s+(?:worker|assistant|aide|employee|technician|analyst|intern|associate|programmer|developer|"
    r"engineer|specialist|consultant)\b", re.I)
GRAD_ONLY_TITLE = re.compile(r"\b(?:ph\.?\s?d|doctoral|mba|masters?|master's|grad(?:uate)?)\b(?!\s*(?:level|program(?:me)?s?)\b)"
                             r"(?=[^,]*\bintern)|\bintern\b[^,]*\b(?:ms/phd|ph\.?d|masters?|master's|mba)\b|\b(?:ms|phd)\s*/\s*(?:phd|ms)\b",
                             re.I)
HIGH_SCHOOL = re.compile(r"\bhigh school (?:intern|student)", re.I)


def is_intern_title(title: str | None) -> bool:
    return bool(INTERN_TITLE.search(title or ""))


GENERIC_INTERN = re.compile(r"\s*(?:(?:college|student|university|undergraduate|paid|spring|summer|fall|\d{4}|part[- ]time)"
                            r"\s+)*(?:intern|internship|co-?op)s?\s*(?:\(.*\))?\s*", re.I)


def is_generic_intern(title: str | None) -> bool:
    """'Intern', 'College Intern', 'Student Intern': titles that don't say what the work is."""
    t = re.split(r"\s+[-\u2013\u2014|:]\s+|,\s+", title or "", maxsplit=1)
    return bool(GENERIC_INTERN.fullmatch(t[0])) and (len(t) == 1 or not t[1].strip())


def level_check(title: str, text: str) -> tuple[str, str]:
    """('pass' | 'fail', detail): fails internships meant for graduate or high school students."""
    t = title or ""
    if re.search(r"\bundergrad", t, re.I):
        return "pass", "Open to undergraduates."
    if GRAD_ONLY_TITLE.search(t):
        return "fail", "For graduate students (master's or PhD)."
    if HIGH_SCHOOL.search(t):
        return "fail", "For high school students."
    body = (text or "")[:8000]
    if re.search(r"(?:currently )?(?:pursuing|enrolled in) (?:an? )?(?:master'?s|ph\.?\s?d|doctoral|graduate)"
                 r"(?: degree| program)?", body, re.I) and not re.search(r"bachelor|undergrad", body, re.I):
        return "fail", "Asks for students in a master's or PhD program."
    return "pass", "Open to undergraduates."


# ----------------------------------------------------------------------------- field (track)

_NOT_CYBER = re.compile(r"securities|social security|food security|security (?:officer|guard|patrol)s?|loss prevention|"
                        r"physical security|national security polic|security systems? (?:install|tech)", re.I)
_CYBER = re.compile(r"cyber|information security|info\s?sec|\bsecurity\b|\bsoc\b|incident response|threat|vulnerab|"
                    r"penetration|pen ?test|\bgrc\b|identity (?:and|&) access|\biam\b|forensic|red team|blue team|"
                    r"appsec|devsecops", re.I)
_NOT_NETWORK = re.compile(r"provider network|network (?:development|contract|relations|strategy|adequacy)|"
                          r"social network|network marketing|merchant (?:&|and) network|networking event", re.I)
_NETWORK = re.compile(r"\b(?:network(?:s|ing)?|net)\s+(?:engineer\w*|admin\w*|technician|operations|analyst|support|"
                      r"infrastructure|security|intern(?:ship)?|architect\w*|specialist|automation|monitoring|design|"
                      r"services intern)\b|\bnetwork(?:ing)?\s*(?:&|and)\s*(?:systems|security|infrastructure)|"
                      r"(?:computer|it|enterprise|wireless|data)\s+network|\bnoc\b|telecom\w*|"
                      r"infrastructure\s+(?:engineer\w*|intern|analyst|operations|services)|"
                      r"data cent(?:er|re) (?:tech\w*|operations|intern)|\bnetworking\b", re.I)
_DATA_STRONG = re.compile(r"\bdata\s+(?:analyst|analytics|analysis|visuali[sz]ation|reporting)\b|\banalytics\b|"
                          r"business intelligence|\bbi\b(?:\s+(?:analyst|developer|intern|engineer))|reporting analyst|"
                          r"tableau|power ?bi|\bstatistic", re.I)
_DATA_ADJ = re.compile(r"\bdata\s+(?:science|scientist|engineer\w*|management|governance|quality|operations|intern|"
                       r"integrity|specialist|insights?|strategy)\b|\bdatabase|\bsql\b|"
                       r"\bdata\b(?=.*\bintern)", re.I)
_IT = re.compile(r"\bIT\b|\bI\.T\.|information technology|help ?desk|service desk|desktop support|technical support|"
                 r"tech(?:nical)? support|systems? administrat\w*|sysadmin|end[- ]user|workstation|"
                 r"\btechnology intern|\btech intern|digital (?:and|&) (?:it|technology)")
_IT_CI = re.compile(r"information technology|help ?desk|service desk|desktop support|technical support|"
                    r"systems? administrat\w*|sysadmin|end[- ]user|workstation|technology intern|tech intern", re.I)

DESC_TERMS = {
    "cyber": ["cybersecurity", "cyber security", "information security", "vulnerability", "siem", "splunk", "soc",
              "incident response", "threat", "phishing", "firewall", "nist", "risk assessment", "penetration",
              "access management", "security operations", "malware", "security awareness"],
    "network": ["network", "networking", "routing", "switching", "router", "switches", "vlan", "lan", "wan",
                "tcp/ip", "dns", "dhcp", "cisco", "wireless", "wi-fi", "subnet", "network infrastructure"],
    "data": ["sql", "excel", "tableau", "power bi", "dashboard", "dashboards", "data analysis", "analytics",
             "statistics", "data visualization", "reporting", "python", "data cleaning", "etl"],
}


def _desc_hits(text: str, track: str) -> list[str]:
    low = (text or "")[:10000].lower()
    return [t for t in DESC_TERMS[track] if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low)]


def _title_track(part: str) -> tuple[str | None, str]:
    if _CYBER.search(part) and not _NOT_CYBER.search(part):
        return "cyber", "strong"
    if _NETWORK.search(part) and not _NOT_NETWORK.search(part):
        return "network", "strong"
    if _DATA_STRONG.search(part):
        return "data", "strong"
    if _DATA_ADJ.search(part):
        return "data", "adjacent"
    if _IT.search(part) or _IT_CI.search(part):
        return "it", "strong"
    return None, ""


@dataclass
class Track:
    track: str  # cyber | data | network | it | other
    strength: str  # strong | adjacent | description
    reason: str

    @property
    def label(self) -> str:
        return TRACK_LABELS.get(self.track, self.track)


def track_of(title: str, description: str = "") -> Track:
    """Field of an internship. The role part of the title ("Data Engineer Intern" in "Data Engineer Intern -
    Enterprise Security") decides first; the team part and then the posting text fill in for vague titles."""
    t = title or ""
    parts = re.split(r"\s+[-–—|:]\s+|,\s+|\s*\(", t, maxsplit=1)
    role, rest = parts[0], (parts[1] if len(parts) > 1 else "")
    tr, strength = _title_track(role)
    if tr and tr != "it":
        return Track(tr, strength, f"The title names {TRACK_LABELS[tr].lower()} work.")
    tr2, strength2 = _title_track(rest)
    if tr2 and tr2 != "it":
        return Track(tr2, strength2 if strength2 == "adjacent" else "strong",
                     f"The title names {TRACK_LABELS[tr2].lower()} work ({rest.strip(' )')}).")
    generic = not tr and not tr2 and re.fullmatch(r"\s*(?:(?:college|student|university|undergraduate|paid|spring|"
                                                   r"\d{4}|part[- ]time)\s+)*(?:intern|internship|co-?op)s?\s*", role, re.I)
    if generic:  # "Intern", "College Intern": the posting text decides
        hits = {k: _desc_hits(description, k) for k in ("cyber", "network", "data")}
        best = max(hits, key=lambda k: len(hits[k]))
        if len(hits[best]) >= 4:
            return Track(best, "description", f"The posting describes {TRACK_LABELS[best].lower()} work "
                                              f"({', '.join(hits[best][:4])}).")
    if tr == "it" or tr2 == "it":
        hits = {k: _desc_hits(description, k) for k in ("cyber", "network", "data")}
        best = max(hits, key=lambda k: len(hits[k]))
        if len(hits[best]) >= 4:
            return Track(best, "description", f"An IT internship whose posting is mostly {TRACK_LABELS[best].lower()} "
                                              f"work ({', '.join(hits[best][:4])}).")
        return Track("it", "strong", "General IT (help desk, support or systems), not data, cybersecurity or networking.")
    return Track("other", "", "Not a data, cybersecurity or networking internship.")


# ----------------------------------------------------------------------------- pay

_UNPAID = re.compile(r"\bunpaid\b|\bnon-?paid\b|\bvolunteer (?:position|internship|role|opportunity)\b|"
                     r"without (?:pay|compensation)|no (?:monetary )?(?:compensation|pay)\b|"
                     r"(?:for|receive) (?:academic |college )?credit only|is not (?:a )?paid|not compensated", re.I)
_PAID = re.compile(r"\bpaid (?:intern(?:ship)?s?|position|role|opportunity|program|experience|student)\b|"
                   r"\b(?:this|the) (?:internship|position|role|opportunity) is paid\b|\bis a paid\b|"
                   r"\bhourly (?:rate|wage|pay|range|compensation)\b|\bper hour\b|\bpay (?:rate|range|scale)\b|"
                   r"\bstipend\b|\bwages?\b|\bsalary range\b|\bcompensation (?:range|for this|is|will be)\b|"
                   r"\bcompetitive (?:hourly )?(?:pay|wages?|compensation)\b|\bcompensated\b|\bbase pay\b", re.I)
_STIPEND = re.compile(r"(?:stipend of|stipend:?)\s*\$\s?([\d,]+(?:\.\d+)?)|\$\s?([\d,]+(?:\.\d+)?)\s*(?:\w+\s){0,2}stipend",
                      re.I)


def _sentence_around(text: str, start: int, end: int, width: int = 140) -> str:
    """The sentence holding text[start:end]. Periods inside numbers ($16.50) don't end a sentence."""
    before = [m.end() for m in re.finditer(r"[.!?](?=\s)|\n", text[:start])]
    a = before[-1] if before else 0
    after = re.search(r"[.!?](?=\s|$)|\n", text[end:])
    b = end + after.start() if after else len(text)
    s = re.sub(r"\s+", " ", text[a:b + 1]).strip()
    return s if len(s) <= width else s[:width - 1].rstrip() + "..."


@dataclass
class Pay:
    status: str  # amount | stated | none | unpaid
    label: str
    hourly: float | None = None
    evidence: str | None = None

    def as_dict(self) -> dict:
        return {"status": self.status, "label": self.label, "hourly": self.hourly, "evidence": self.evidence}


def pay_of(text: str, comp_min: float | None = None, comp_max: float | None = None,
           comp_period: str | None = None) -> Pay:
    body = text or ""
    m = _UNPAID.search(body)
    if m:
        return Pay("unpaid", "Unpaid", evidence=_sentence_around(body, m.start(), m.end()))
    lo, hi, period = comp_min, comp_max, comp_period
    if lo is None:
        c = parse_comp(body)
        lo, hi, period = c.min, c.max, c.period
    if lo is not None:
        hi = hi or lo
        if period == "hour":
            hourly = (lo + hi) / 2
            label = f"${lo:,.2f}".replace(".00", "") + (f" to ${hi:,.2f}".replace(".00", "") if hi != lo else "") + " an hour"
        else:
            hourly = (lo + hi) / 2 / 2080
            label = f"${lo:,.0f}" + (f" to ${hi:,.0f}" if hi != lo else "") + " a year (annualized)"
        ev = re.search(r"\$\s?" + re.escape(f"{lo:,.2f}".rstrip("0").rstrip(".").split(".")[0]), body)
        return Pay("amount", label, round(hourly, 2), _sentence_around(body, ev.start(), ev.end()) if ev else None)
    m = _STIPEND.search(body)
    if m:
        amount = (m.group(1) or m.group(2) or "").replace(",", "")
        return Pay("amount", f"${float(amount):,.0f} stipend", None, _sentence_around(body, m.start(), m.end()))
    m = _PAID.search(body)
    if m:
        return Pay("stated", "Paid, amount not listed", evidence=_sentence_around(body, m.start(), m.end()))
    return Pay("none", "No sign of pay in the posting")


# ----------------------------------------------------------------------------- hours

_WEEK = re.compile(r"week|\bwk\b|/wk|weekly", re.I)
_NOT_WEEK = re.compile(r"per day|a day|daily|per shift|shifts?\b|per month|a month|credit hours?|semester hours?|"
                       r"credits?\b|hours? of (?:training|service|coursework)|within \d+ hours", re.I)
_SUMMER_NEAR = re.compile(r"summer|winter break|school breaks?|holiday", re.I)
_RANGE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*[- ]?(?:hours?|hrs?)\b", re.I)
_MIN = re.compile(r"(?:at least|a minimum of|minimum of|minimum requirement of|minimum|min\.?|no less than)\s*"
                  r"(\d{1,2})\s*[- ]?(?:hours?|hrs?)\b", re.I)
_MAX = re.compile(r"(?:up to|no more than|maximum of|max(?:imum)?(?: of)?|not to exceed|not exceed(?:ing)?|"
                  r"less than|under|fewer than|cap(?:ped)? at)\s*(\d{1,2})\s*[- ]?(?:hours?|hrs?)\b", re.I)
_ONE = re.compile(r"(?<![\d.-])(\d{1,2})\s*\+?\s*[- ]?(?:hours?|hrs?)\b", re.I)
_FULL = re.compile(r"\bfull[- ]?time\b", re.I)
_FULL_NOT = re.compile(r"student|enrol|undergrad|college|universit|degree|status|upon|offer|conver|after graduation|"
                       r"graduat|hire|hiring|opportunit|employment|role after|position after|career|return", re.I)
_PART = re.compile(r"\bpart[- ]?time\b", re.I)


def _week_context(text: str, m: re.Match) -> bool:
    after = text[m.end(): m.end() + 40]
    before = text[max(0, m.start() - 40): m.start()]
    window = text[max(0, m.start() - 15): m.end() + 25]
    if _NOT_WEEK.search(window):
        return False
    if _SUMMER_NEAR.search(text[max(0, m.start() - 25): m.end() + 25]):
        return False
    return bool(_WEEK.search(m.group(0)) or _WEEK.search(after) or re.search(r"week|part[- ]time", before, re.I))


@dataclass
class Hours:
    status: str  # ok | part_time | crosses | too_many | too_few | full_time | unknown
    label: str
    low: float | None = None
    high: float | None = None
    evidence: str | None = None

    def as_dict(self) -> dict:
        return {"status": self.status, "label": self.label, "low": self.low, "high": self.high,
                "evidence": self.evidence}


def hours_of(text: str, hints: dict | None = None, title: str = "", lo_pref: float = 10, hi_pref: float = 30) -> Hours:
    body = text or ""
    h = hints or {}
    lows: list[float] = []
    highs: list[float] = []
    ev = None
    used: list[tuple[int, int]] = []

    def take(m):
        nonlocal ev
        used.append((m.start(), m.end()))
        ev = ev or _sentence_around(body, m.start(), m.end())

    for m in _RANGE.finditer(body):
        if _week_context(body, m):
            a, b = float(m.group(1)), float(m.group(2))
            if a < b <= 60:
                lows.append(a)
                highs.append(b)
                take(m)
    for m in _MIN.finditer(body):
        if _week_context(body, m) and not any(s <= m.start() < e for s, e in used):
            lows.append(float(m.group(1)))
            take(m)
    for m in _MAX.finditer(body):
        if _week_context(body, m) and not any(s <= m.start() < e for s, e in used):
            highs.append(float(m.group(1)))
            take(m)
    for m in _ONE.finditer(body):
        if any(s <= m.start() < e for s, e in used) or not _week_context(body, m):
            continue
        v = float(m.group(1))
        if 1 <= v <= 60:
            lows.append(v)
            highs.append(v)
            take(m)

    time_type = " ".join(str(h.get(k) or "") for k in ("time_type", "commitment", "employment_type")).lower()
    full = bool(re.search(r"full[ _-]?time", time_type)) or bool(re.search(r"\bfull[- ]?time\b", title, re.I))
    part = bool(re.search(r"part[ _-]?time", time_type)) or bool(re.search(r"\bpart[- ]?time\b|\bPT\b", title))
    for m in _FULL.finditer(body):
        ctx = body[max(0, m.start() - 45): m.end() + 45]
        if not _FULL_NOT.search(ctx) and not _SUMMER_NEAR.search(ctx):
            full = True
            ev = ev or _sentence_around(body, m.start(), m.end())
            break
    pm = _PART.search(body)
    if pm:
        part = True
        ev = ev or _sentence_around(body, pm.start(), pm.end())

    if lows or highs:
        lo = min(lows) if lows else None
        hi = max(highs) if highs else None
        span = (f"{lo:g} to {hi:g}" if lo is not None and hi is not None and lo != hi else
                f"{(hi if hi is not None else lo):g}" if lo == hi or lo is None or hi is None else "")
        if lo is None:
            span = f"up to {hi:g}"
        elif hi is None:
            span = f"at least {lo:g}"
        label = f"{span} hours a week"
        if lo is not None and lo > hi_pref:
            return Hours("too_many", f"{label}, more than your {hi_pref:g}-hour limit", lo, hi, ev)
        if hi is not None and hi < lo_pref:
            return Hours("too_few", f"{label}, under your {lo_pref:g}-hour minimum", lo, hi, ev)
        if hi is not None and hi > hi_pref and hi >= 35 and lo is None:
            return Hours("too_many", f"{label}, full time", lo, hi, ev)
        if (hi is not None and hi > hi_pref) or (lo is not None and hi is None and lo >= hi_pref):
            return Hours("crosses", f"{label}; ask to stay at {hi_pref:g} or less", lo, hi, ev)
        return Hours("ok", label, lo, hi, ev)
    if part and not full:
        return Hours("part_time", "Part-time, exact hours not listed", evidence=ev)
    if full and not part:
        return Hours("full_time", "Full time (about 40 hours a week)", evidence=ev)
    if full and part:
        return Hours("part_time", "Part-time during the school year", evidence=ev)
    return Hours("unknown", "Hours not listed")


# ----------------------------------------------------------------------------- dates

_SPRING = re.compile(r"spring\s*(?:semester\s*|term\s*|session\s*)?(?:of\s*)?(?:2027|'27)|spring 27\b|"
                     r"(?:jan(?:uary)?|feb(?:ruary)?)\.?\s*(?:-|\u2013|to|through|thru|until)\s*(?:apr(?:il)?|may|june?)\.?,?\s*2027|"
                     r"(?:january|jan\.?)\s*(?:\d{1,2}(?:st|nd|rd|th)?,?\s*)?2027|"
                     r"winter\s*/\s*spring|winter-spring|fall\s*(?:2026\s*)?(?:and|&|through|to|-)\s*spring", re.I)
_SCHOOL_YEAR = re.compile(r"academic year|school year|during the (?:semester|school year|academic year)|"
                          r"(?:fall|spring) (?:and|&|or) (?:spring|fall) semesters?|each semester|year[- ]round|"
                          r"\b(?:52|fifty[- ]two) weeks\b|12[- ]months?\b|ongoing (?:internship|position|basis)|"
                          r"2026\s*[-–/]\s*(?:20)?27|throughout the year|while (?:in|attending) school|"
                          r"around (?:your|their) class schedule|accommodate (?:your|a) class schedule", re.I)
_SPRING_ANY = re.compile(r"\bspring (?:semester|term|internship|intern|co-?op)\b|\bspring\b", re.I)
_SUMMER = re.compile(r"\bsummer\b", re.I)
_FALL_ONLY = re.compile(r"\bfall\s*(?:semester\s*)?(?:of\s*)?2026\b|(?:august|september)\s*(?:to|through|-|–)\s*"
                        r"december\s*(?:of\s*)?2026", re.I)


@dataclass
class Term:
    status: str  # spring | school_year | summer | fall | later | unknown
    label: str
    evidence: str | None = None

    def as_dict(self) -> dict:
        return {"status": self.status, "label": self.label, "evidence": self.evidence}


def term_of(title: str, text: str, feed_terms: list[str] | None = None, start: date = date(2027, 1, 1),
            end: date = date(2027, 5, 31)) -> Term:
    blob = f"{title}\n{(text or '')[:9000]}"
    terms = [t.lower() for t in feed_terms or []]
    m = _SPRING.search(blob)
    if m or any(t in ("spring 2027", "winter 2027") for t in terms):
        return Term("spring", "Spring 2027", _sentence_around(blob, m.start(), m.end()) if m else "Listed for spring 2027.")
    m = _SCHOOL_YEAR.search(blob)
    if m:
        return Term("school_year", "During the school year", _sentence_around(blob, m.start(), m.end()))
    # Explicit start dates
    for sent in re.split(r"(?<=[.!?\n])\s+", blob):
        if not re.search(r"\bstart|\bbegin|\bcommence", sent, re.I):
            continue
        ds = [d for d in _dates_in(sent) if d.year >= 2026]
        if not ds:
            continue
        first = min(ds)
        if date(2026, 11, 15) <= first <= date(2027, 3, 15):
            return Term("spring", f"Starts {first:%B %Y}", sent.strip()[:160])
        if first > end:
            return Term("later", f"Starts {first:%B %Y}, after spring", sent.strip()[:160])
        if first < date(2026, 11, 15) and re.search(r"\bend|through|until", sent, re.I) and max(ds) < start:
            return Term("fall", f"Ends {max(ds):%B %Y}, before spring", sent.strip()[:160])
    summer = _SUMMER.search(blob) or (terms and all(t.startswith("summer") for t in terms))
    spring_any = _SPRING_ANY.search(blob)
    if summer and not spring_any:
        sm = _SUMMER.search(blob)
        return Term("summer", "Summer internship", _sentence_around(blob, sm.start(), sm.end()) if sm else
                    "Listed for summer.")
    fm = _FALL_ONLY.search(blob)
    real_terms = [t for t in terms if t != "n/a"]
    if (fm or (real_terms and all(t.startswith("fall") for t in real_terms))) and not spring_any:
        return Term("fall", "Fall 2026 only", _sentence_around(blob, fm.start(), fm.end()) if fm else "Listed for fall.")
    if spring_any:
        return Term("spring", "Spring", _sentence_around(blob, spring_any.start(), spring_any.end()))
    return Term("unknown", "Dates not listed")


# ----------------------------------------------------------------------------- where

PHX_CORE = {"phoenix", "tempe", "scottsdale", "mesa", "chandler", "gilbert", "ahwatukee", "guadalupe",
            "paradise valley", "fountain hills", "sky harbor"}
PHX_OUTER = {"glendale", "peoria", "surprise", "goodyear", "avondale", "buckeye", "queen creek", "tolleson",
             "litchfield park", "cave creek", "carefree", "el mirage", "sun city", "sun city west", "youngtown",
             "laveen", "anthem", "apache junction", "san tan valley", "maricopa", "luke air force base",
             "gold canyon", "waddell", "new river", "deer valley"}
PHX_ALL = PHX_CORE | PHX_OUTER
# Names that also exist outside Arizona (Glendale CA, Peoria IL, Costa Mesa CA...) need "AZ" or "Arizona" nearby.
AMBIGUOUS = {"glendale", "peoria", "mesa", "surprise", "maricopa", "anthem", "gilbert", "chandler", "avondale",
             "goodyear", "laveen", "carefree", "sun city", "deer valley", "new river", "guadalupe", "buckeye"}
OTHER_AZ = re.compile(r"\b(tucson|oro valley|marana|sahuarita|green valley|sierra vista|fort huachuca|ft huachuca|"
                      r"flagstaff|yuma|prescott|prescott valley|kingman|lake havasu|casa grande|show low|sedona|"
                      r"nogales|douglas|bullhead|cottonwood|payson|safford|florence|coolidge|eloy|winslow|"
                      r"holbrook|page|globe|camp verde|wickenburg|bisbee|benson|willcox)\b", re.I)
_AZ = re.compile(r"\bAZ\b|arizona", re.I)
_REMOTE = re.compile(r"\bremote\b|work from home|\bwfh\b|\bvirtual\b|telework|anywhere in the (?:us|u\.s\.|united states)",
                     re.I)
_OTHER_STATE_CODE = re.compile(r",\s*(?!AZ\b)([A-Z]{2})\b")


@dataclass
class Where:
    status: str  # remote | phoenix | hybrid_phoenix | az_unknown | tucson | outside | unknown
    label: str
    city: str | None = None
    tier: str | None = None  # core | outer

    def as_dict(self) -> dict:
        return {"status": self.status, "label": self.label, "city": self.city, "tier": self.tier}


def _phx_city(part: str) -> str | None:
    low = part.lower()
    az = bool(_AZ.search(part))
    for city in sorted(PHX_ALL, key=len, reverse=True):
        if re.search(r"(?<![a-z])" + re.escape(city) + r"(?![a-z])", low):
            if city == "mesa" and re.search(r"costa mesa|mesa,?\s*(?:ca|california|co|colorado)", low):
                continue
            if city in AMBIGUOUS and not az:
                continue
            if city == "phoenix" and not az and _OTHER_STATE_CODE.search(part):
                continue
            return city
    return None


def where_of(location_text: str | None, description: str = "", title: str = "", workplace: str | None = None) -> Where:
    loc = location_text or ""
    parts = [p.strip() for p in re.split(r"[;|\n]|\s+or\s+|\s{2,}", loc) if p.strip()] or [""]
    city = None
    remote = False
    az_any = False
    other_az = None
    for part in parts:
        c = _phx_city(part)
        if c and not city:
            city = c
        if _REMOTE.search(part):
            remote = True
        if _AZ.search(part):
            az_any = True
        m = OTHER_AZ.search(part)
        if m and _AZ.search(part) or (m and m.group(1).lower() == "tucson"):
            other_az = other_az or m.group(1).title()
    if not city and not loc:
        c = _phx_city(f"{title}")
        city = c
    li = parse_location(loc, description, title)
    mode = (workplace or "").lower()
    if li.remote_type == "hybrid" or mode == "hybrid":
        mode = "hybrid"
    elif remote or mode == "remote" or li.remote_type == "remote":
        mode = "remote"
    if mode == "remote":
        if li.international_only and not az_any:
            return Where("outside", "Remote, but outside the US")
        if li.allowed_states and "AZ" not in li.allowed_states:
            return Where("outside", f"Remote, but only for people in {', '.join(li.allowed_states[:4])}")
        az_only = li.allowed_states == ["AZ"]
        if city:
            return Where("remote", f"Remote{' (Arizona residents)' if az_only else ''}, office in {city.title()}, AZ",
                         city, "core" if city in PHX_CORE else "outer")
        return Where("remote", "Remote" + (" (Arizona residents)" if az_only else ""))
    if city:
        tier = "core" if city in PHX_CORE else "outer"
        if mode == "hybrid":
            return Where("hybrid_phoenix", f"Hybrid in {city.title()}, AZ", city, tier)
        return Where("phoenix", f"{city.title()}, AZ", city, tier)
    if other_az:
        return Where("tucson" if other_az.lower() in ("tucson", "oro valley", "marana", "sahuarita", "green valley")
                     else "outside", f"{other_az}, AZ is outside the Phoenix area")
    if az_any:
        return Where("az_unknown", "Arizona, city not listed")
    if re.fullmatch(r"\s*(?:united states(?: of america)?|usa?|u\.s\.|\d+ locations|multiple locations|various(?: locations)?|"
                    r"nationwide|n/?a)\s*", loc, re.I):
        return Where("unknown", "Location not specific")
    if li.states or li.international_only or loc:
        shown = re.sub(r"\s+", " ", loc).strip()
        shown = shown if len(shown) <= 60 else shown[:57].rstrip(" ,;") + "..."
        return Where("outside", f"{shown or 'Outside the US'}, not remote")
    return Where("unknown", "Location not listed")


# ----------------------------------------------------------------------------- evaluation

CONVERSION = re.compile(r"full[- ]time (?:offer|employment|role|position)s? (?:upon|after)|return offer|convert(?:ed|s)? "
                        r"(?:to|into) (?:a )?full[- ]time|intern[- ]to[- ](?:hire|full)|pipeline (?:to|for) full[- ]time",
                        re.I)
CUSTOMER = re.compile(r"customer[- ]facing|client[- ]facing|work(?:ing)? (?:directly )?with (?:customers|clients)|"
                      r"pre-?sales|solutions? engineer|stakeholders", re.I)


@dataclass
class InternInput:
    title: str
    description: str = ""
    location_text: str = ""
    workplace: str | None = None
    comp_min: float | None = None
    comp_max: float | None = None
    comp_period: str | None = None
    hints: dict = field(default_factory=dict)  # time_type, commitment, employment_type, feed_terms
    is_active: bool = True
    readable: bool = True
    company_category: str | None = None
    company_watch: str | None = None
    source_is_original: bool = False
    overrides: dict = field(default_factory=dict)


def _check(key, label, state, detail, evidence=None) -> dict:
    return {"key": key, "label": label, "state": state, "detail": detail, "evidence": evidence}


def evaluate(x: InternInput, pref: dict | None = None) -> dict:
    p = prefs({"internship": pref or {}})
    ov = x.overrides or {}
    text = x.description or ""
    tr = track_of(x.title, text)
    pay = pay_of(text, x.comp_min, x.comp_max, x.comp_period)
    hrs = hours_of(text, x.hints, x.title, float(p["hours_min"]), float(p["hours_max"]))
    term = term_of(x.title, text, x.hints.get("feed_terms"), date.fromisoformat(p["start"]), date.fromisoformat(p["end"]))
    where = where_of(x.location_text, text, x.title, x.workplace)
    level, level_detail = level_check(x.title, text)
    unread = not x.readable

    checks = []
    # Field
    if tr.track in ("cyber", "data", "network"):
        checks.append(_check("field", "Field", "pass", f"{tr.label}. {tr.reason}"))
    elif tr.track == "it":
        checks.append(_check("field", "Field", "fail", tr.reason + " Ask your internship coordinator if it counts."))
    else:
        checks.append(_check("field", "Field", "fail", tr.reason))
    # Pay
    if ov.get("paid"):
        checks.append(_check("pay", "Paid", "pass", "You confirmed it's paid.", pay.evidence))
    elif pay.status in ("amount", "stated"):
        checks.append(_check("pay", "Paid", "pass", pay.label, pay.evidence))
    elif pay.status == "unpaid":
        checks.append(_check("pay", "Paid", "fail", "The posting says it's unpaid.", pay.evidence))
    elif unread:
        checks.append(_check("pay", "Paid", "warn", "Noderze couldn't read the full posting. Open it and look for pay."))
    else:
        checks.append(_check("pay", "Paid", "fail", "No sign of pay in the posting. If the recruiter tells you it's paid, "
                                                   "mark it confirmed."))
    # Hours
    lo, hi = p["hours_min"], p["hours_max"]
    if ov.get("hours_ok"):
        checks.append(_check("hours", f"{lo} to {hi} hours a week", "pass", "You confirmed the hours work.", hrs.evidence))
    elif hrs.status in ("ok", "part_time"):
        checks.append(_check("hours", f"{lo} to {hi} hours a week", "pass", hrs.label, hrs.evidence))
    elif hrs.status == "crosses":
        checks.append(_check("hours", f"{lo} to {hi} hours a week", "warn", hrs.label, hrs.evidence))
    elif hrs.status in ("too_many", "too_few", "full_time"):
        checks.append(_check("hours", f"{lo} to {hi} hours a week", "fail", hrs.label, hrs.evidence))
    else:
        checks.append(_check("hours", f"{lo} to {hi} hours a week", "warn",
                             "Hours not listed. Ask the recruiter before you apply." if not unread else
                             "Couldn't read the posting; check the hours."))
    # Dates
    if term.status in ("spring", "school_year"):
        checks.append(_check("term", "January to May 2027", "pass", term.label, term.evidence))
    elif term.status in ("summer", "fall", "later"):
        checks.append(_check("term", "January to May 2027", "fail", term.label, term.evidence))
    else:
        checks.append(_check("term", "January to May 2027", "warn", "Dates not listed. Confirm it runs this spring."))
    # Where
    if where.status in ("remote", "phoenix", "hybrid_phoenix"):
        checks.append(_check("where", "Remote or Phoenix area", "pass", where.label))
    elif where.status in ("az_unknown", "unknown"):
        checks.append(_check("where", "Remote or Phoenix area", "warn", where.label + ". Confirm where you'd work."))
    else:
        checks.append(_check("where", "Remote or Phoenix area", "fail", where.label))
    # Level and status of the posting
    if level == "fail":
        checks.append(_check("level", "For undergraduates", "fail", level_detail))
    if not x.is_active:
        checks.append(_check("open", "Still open", "fail", "The posting is closed or was removed."))

    fails = [c for c in checks if c["state"] == "fail"]
    warns = [c for c in checks if c["state"] == "warn"]
    if ov.get("include") and x.is_active:
        status = "check" if warns else "qualifies"
        note = "You chose to count this one."
    else:
        status = "out" if fails else "check" if warns or unread else "qualifies"
        note = None

    breakdown = _score(x, tr, pay, hrs, term, where, ov, checks)
    total = round(sum(b["score"] for b in breakdown.values()), 1)
    if status == "out":
        total = min(total, 49.0)
    flags = [f"{c['key']}_{c['state']}" for c in checks if c["state"] != "pass"]
    return {"track": tr.track, "track_label": tr.label, "track_strength": tr.strength, "track_reason": tr.reason,
            "status": status, "status_label": STATUS_LABELS[status], "note": note, "checks": checks,
            "pay": pay.as_dict(), "hours": hrs.as_dict(), "term": term.as_dict(), "where": where.as_dict(),
            "score": total, "breakdown": breakdown, "flags": flags,
            "reasons_out": [c["detail"] for c in fails]}


def _score(x: InternInput, tr: Track, pay: Pay, hrs: Hours, term: Term, where: Where, ov: dict, checks) -> dict:
    out = {}

    def put(key, label, score, mx, reasons):
        out[key] = {"label": label, "score": round(score, 1), "max": mx, "reasons": reasons}

    field_pts = {"strong": 30, "adjacent": 22, "description": 20}.get(tr.strength, 0) if tr.track in (
        "cyber", "data", "network") else (12 if ov.get("include") else 0)
    put("field", "Field fit", field_pts, 30, [tr.reason])

    if ov.get("paid"):
        pts, why = 13, "You confirmed it's paid."
    elif pay.status == "amount" and pay.hourly:
        h = pay.hourly
        pts = 20 if h >= 25 else 18 if h >= 20 else 15 if h >= 17 else 12 if h >= 15 else 9
        why = f"{pay.label}."
    elif pay.status == "amount":
        pts, why = 12, f"{pay.label}."
    elif pay.status == "stated":
        pts, why = 10, "The posting says it's paid but doesn't list the rate."
    else:
        pts, why = 0, pay.label + "."
    put("pay", "Pay", pts, 20, [why])

    hpts = {"ok": 15, "part_time": 12, "crosses": 8, "unknown": 6}.get(hrs.status, 0)
    if ov.get("hours_ok"):
        hpts = 14
    put("hours", "Hours", hpts, 15, [hrs.label + "."])

    tpts = {"spring": 15, "school_year": 13, "unknown": 7}.get(term.status, 0)
    put("timing", "Spring timing", tpts, 15, [term.label + "."])

    wpts = {"remote": 10, "phoenix": 10 if where.tier == "core" else 8, "hybrid_phoenix": 10 if where.tier == "core" else 8,
            "az_unknown": 6, "unknown": 5}.get(where.status, 0)
    put("where", "Location", wpts, 10, [where.label + (". Close to ASU." if where.tier == "core" and where.status != "remote"
                                                       else ".")])

    cpts, reasons = 3.0, []
    if x.company_category == "cybersecurity" or x.company_watch in ("priority", "strong"):
        cpts += 3
        reasons.append("A cybersecurity company or one of your target companies, so it doubles as networking toward a "
                       "sales or SE role later.")
    elif x.company_category in ("software", "cloud_networking", "ai", "it_solutions"):
        cpts += 2
        reasons.append("A tech company, which builds experience you can use in technical sales.")
    if CONVERSION.search(x.description or ""):
        cpts += 2
        reasons.append("Mentions converting interns to full-time roles.")
    if CUSTOMER.search(x.description or ""):
        cpts += 2
        reasons.append("Includes customer or stakeholder work, good practice for SE.")
    if x.source_is_original:
        cpts += 1
        reasons.append("Read from the company's own posting.")
    put("career", "Career value", min(cpts, 10), 10, reasons or ["Solid experience; no extra career signals in the posting."])
    return out
