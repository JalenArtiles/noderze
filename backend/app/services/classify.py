"""Deterministic job classifiers. These run with no API key and are unit tested.

The LLM layer can enrich results, but these functions are the source of truth for scoring,
so scores stay explainable and reproducible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

# ----------------------------------------------------------------------------- role family

_SE_CLEAR = re.compile(
    r"\b(sales engineer(?:ing)?|solutions? engineer(?:ing)?|solutions? consultant|pre-?sales|presales|"
    r"technical sales|sales consultant|solution advisor|solutions? advisor|field applications? engineer)\b", re.I)
_SE_AMBIGUOUS = re.compile(
    r"\b(systems engineer|solutions? architect|customer engineer|technical specialist|solution specialist)\b", re.I)
_SALES_CONTEXT = re.compile(
    r"pre-?sales|presales|sales team|account executive|sales cycle|technical win|proof of concept|\bpoc\b|"
    r"customer-facing|demo|sales engineering|sales organization|go-to-market|customer engagements?|"
    r"strategic customers|trusted (?:customer )?advisor|help customers (?:craft|architect|design)", re.I)
_TECH_ENTRY = re.compile(
    r"\b(technical account manager|customer success engineer|customer success manager|implementation "
    r"(?:engineer|consultant|specialist)|onboarding (?:engineer|specialist)|support engineer|technical support|"
    r"product specialist|technical consultant|deployment engineer|professional services|customer support engineer)\b",
    re.I)
_PIPELINE = re.compile(
    r"\b(sales development|business development rep(?:resentative)?|\bbdr\b|\bsdr\b|account development|"
    r"\badr\b|market development rep(?:resentative)?|enterprise development representative|inside sales|account executive|"
    r"account representative|account manager|sales representative|sales associate|customer growth associate|"
    r"sales academy|leadership development program.*sales|sales development program|sales track)\b", re.I)
_PROGRAM = re.compile(
    r"\b(academy|rotational|rotation program|development program|graduate program|grad program|"
    r"early[- ]career|university grad(?:uate)?|new grad|class of 20\d\d|20\d\d start|cohort|apprentice|"
    r"emerging talent|tech u|csap|success graduate|leadership development)\b", re.I)
_SENIOR = re.compile(
    r"\b(?:senior|sr|staff|principal|lead|director|head of|vp|vice president|chief|distinguished|iii|iv)\b"
    r"|\b(?:engineering|sales|regional|area|district|channel|program|product|marketing|field) manager\b"
    r"|\bmanager(?:,| of\b)"
    r"|\b(?:sdr|bdr|adr|sales development|business development|inside sales) (?:team )?manager\b", re.I)
# Sales titles that signal an experienced seller even without "senior": enterprise, strategic, major, named,
# global, key or national accounts. Development reps on those teams (e.g. "Enterprise SDR") are still entry level.
_SENIOR_SALES = re.compile(
    r"\b(?:enterprise|strategic|major|named|global|key|large|corporate|national|federal)\s+(?:channel\s+|partner\s+)?"
    r"(?:account|sales)\s+"
    r"(?:executive|manager|director|lead)s?\b"
    r"|\b(?:account executive|account manager|account director|sales executive)\b[^|]{0,40}?"
    r"\b(?:enterprise|strategic|major accounts?|named accounts?|global accounts?|key accounts?|national accounts?|federal)\b",
    re.I)
_ENTRY_WORDS = re.compile(r"\b(?:associate|junior|jr\.?|new grad|early career|entry[- ]level|development rep(?:resentative)?|"
                          r"[sbaem]dr|intern)\b", re.I)


def is_senior_title(title: str) -> bool:
    """True for titles that ask for an experienced hire (senior, lead, manager, or enterprise/strategic sales)."""
    t = title or ""
    if _SENIOR.search(t) and not re.search(r"\b(associate|junior|new grad|early career)\b", t, re.I):
        return True
    return bool(_SENIOR_SALES.search(t)) and not _ENTRY_WORDS.search(t)


def sales_level(title: str) -> str | None:
    t = (title or "").lower()
    if re.search(r"development rep|development representative|\b[sbaemt]dr\b|lead development|pipeline development", t):
        return "Development rep (SDR / BDR / ADR)"
    if re.search(r"associate account executive|\baae\b|(?:junior|associate) account executive", t):
        return "Associate account executive"
    if "account executive" in t:
        return "Account executive"
    if "inside sales" in t:
        return "Inside sales"
    if re.search(r"renewal", t):
        return "Renewals"
    if re.search(r"account manager|account representative|sales representative|sales associate", t):
        return "Sales representative"
    return None


@dataclass
class RoleClass:
    family: str  # direct_se | technical_entry | pipeline | other
    is_program: bool
    is_senior: bool
    is_intern: bool
    reason: str


def classify_role(title: str, description: str | None = None) -> RoleClass:
    t = title or ""
    d = description or ""
    is_intern = bool(re.search(r"\bintern(ship)?\b|\bco-?op\b", t, re.I))
    is_program = bool(_PROGRAM.search(t)) or bool(re.search(
        r"\b(academy|cohort|rotational|development program|graduate program|training program|"
        r"(?:the|our) [A-Za-z]{2,12} program (?:was created|is designed|offers|will))\b", d[:4000], re.I))
    is_senior = is_senior_title(t)

    if _SE_CLEAR.search(t):
        return RoleClass("direct_se", is_program, is_senior, is_intern, "title names an SE / solutions role")
    if _SE_AMBIGUOUS.search(t):
        if _SALES_CONTEXT.search(d) or re.search(r"associate solutions architect|customer engineer", t, re.I):
            return RoleClass("direct_se", is_program, is_senior, is_intern,
                             "SE-adjacent title with pre-sales context in the posting")
        return RoleClass("other", is_program, is_senior, is_intern,
                         "ambiguous title with no pre-sales context found")
    if _TECH_ENTRY.search(t):
        return RoleClass("technical_entry", is_program, is_senior, is_intern, "technical customer-facing entry role")
    if _PIPELINE.search(t):
        return RoleClass("pipeline", is_program, is_senior, is_intern, "sales entry role")
    return RoleClass("other", is_program, is_senior, is_intern, "not a target family")


# ----------------------------------------------------------------------------- locations

STATES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california", "CO": "colorado",
    "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho",
    "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana",
    "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan", "MN": "minnesota",
    "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico", "NY": "new york", "NC": "north carolina",
    "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania",
    "RI": "rhode island", "SC": "south carolina", "SD": "south dakota", "TN": "tennessee", "TX": "texas",
    "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington", "WV": "west virginia",
    "WI": "wisconsin", "WY": "wyoming", "DC": "district of columbia",
}
NAME_TO_STATE = {v: k for k, v in STATES.items()}
CITY_TO_STATE = {
    # Arizona
    "phoenix": "AZ", "tempe": "AZ", "scottsdale": "AZ", "chandler": "AZ", "mesa": "AZ", "gilbert": "AZ",
    "glendale": "AZ", "tucson": "AZ", "peoria": "AZ", "goodyear": "AZ",
    # California
    "san francisco": "CA", "san jose": "CA", "san mateo": "CA", "palo alto": "CA", "mountain view": "CA",
    "sunnyvale": "CA", "santa clara": "CA", "cupertino": "CA", "menlo park": "CA", "redwood city": "CA",
    "redwood shores": "CA", "oakland": "CA", "los angeles": "CA", "irvine": "CA", "san diego": "CA",
    "sacramento": "CA", "pleasanton": "CA", "foster city": "CA", "fremont": "CA", "milpitas": "CA",
    "burlingame": "CA", "emeryville": "CA", "santa monica": "CA", "torrance": "CA", "costa mesa": "CA",
    "newport beach": "CA", "el segundo": "CA", "culver city": "CA", "san ramon": "CA", "anaheim": "CA",
    "roseville": "CA", "foothill ranch": "CA", "carlsbad": "CA", "pasadena": "CA", "long beach": "CA",
    "santa ana": "CA", "aliso viejo": "CA", "burbank": "CA", "riverside": "CA", "temecula": "CA", "oceanside": "CA",
    "escondido": "CA", "la jolla": "CA", "playa vista": "CA", "marina del rey": "CA", "lake forest": "CA",
    "rancho santa margarita": "CA", "thousand oaks": "CA", "westlake village": "CA", "calabasas": "CA",
    "huntington beach": "CA", "manhattan beach": "CA", "redondo beach": "CA", "mission viejo": "CA",
    "san clemente": "CA", "laguna hills": "CA", "sorrento valley": "CA",
    # Texas
    "austin": "TX", "dallas": "TX", "houston": "TX", "plano": "TX", "san antonio": "TX", "irving": "TX",
    "frisco": "TX", "fort worth": "TX", "addison": "TX", "round rock": "TX",
    # Florida
    "tampa": "FL", "miami": "FL", "orlando": "FL", "jacksonville": "FL", "fort lauderdale": "FL",
    "boca raton": "FL", "clearwater": "FL", "st. petersburg": "FL", "st petersburg": "FL",
    # Other common hubs
    "new york": "NY", "seattle": "WA", "boston": "MA", "chicago": "IL", "atlanta": "GA", "denver": "CO",
    "research triangle park": "NC", "rtp": "NC", "raleigh": "NC", "charlotte": "NC", "nashville": "TN",
    "arlington": "VA", "reston": "VA", "herndon": "VA", "mclean": "VA", "salt lake city": "UT",
    "indianapolis": "IN", "waltham": "MA", "washington": "DC",
}
REGIONS = {  # remote regions some companies encode in titles
    "west": {"AZ", "CA", "NV", "OR", "WA", "UT", "CO", "NM", "ID", "MT", "WY"},
    "west coast": {"CA", "OR", "WA"}, "pacific": {"CA", "OR", "WA"},
    "mountain": {"AZ", "CO", "UT", "NM", "NV", "ID", "MT", "WY"}, "southwest": {"AZ", "NM", "NV", "TX", "OK"},
    "southeast": {"FL", "GA", "SC", "NC", "AL", "MS", "TN"}, "northeast": {"NY", "NJ", "MA", "CT", "PA", "RI", "NH", "VT", "ME"},
    "midwest": {"IL", "IN", "OH", "MI", "WI", "MN", "IA", "MO", "KS", "NE", "ND", "SD"},
    "tola": {"TX", "OK", "LA", "AR"}, "central": {"TX", "OK", "KS", "NE", "MO", "IL", "MN", "IA"},
}
SOCAL_CITIES = {"san diego", "los angeles", "irvine", "costa mesa", "newport beach", "santa monica", "el segundo",
                "culver city", "torrance", "anaheim", "foothill ranch", "carlsbad", "pasadena", "long beach", "santa ana",
                "aliso viejo", "burbank", "riverside", "temecula", "oceanside", "escondido", "la jolla", "playa vista",
                "marina del rey", "lake forest", "rancho santa margarita", "thousand oaks", "westlake village",
                "calabasas", "huntington beach", "manhattan beach", "redondo beach", "mission viejo", "san clemente",
                "laguna hills", "sorrento valley", "orange"}
_DUBLIN_IE = re.compile(r"dublin,?\s*(ireland|ie\b)", re.I)


@dataclass
class LocationInfo:
    states: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    remote_type: str = "unknown"  # onsite | hybrid | remote | unknown
    remote_scope: str | None = None  # "US", "region:southeast", "restricted: ..."
    allowed_states: list[str] | None = None  # when remote is restricted to a set of states
    regions: list[str] = field(default_factory=list)  # socal | norcal | ca_unknown
    international_only: bool = False


# Countries, regions and major non-US cities. Only used when no US state was found in the location,
# so "Athens, GA" or "Paris, TX" are never treated as international.
_INTERNATIONAL = re.compile(
    r"\b(united kingdom|uk|great britain|britain|england|scotland|wales|london|manchester|edinburgh|ireland|germany|berlin|munich|frankfurt|"
    r"france|paris|spain|madrid|barcelona|italy|milan|rome|netherlands|amsterdam|belgium|brussels|switzerland|zurich|"
    r"geneva|austria|vienna|sweden|stockholm|norway|oslo|denmark|copenhagen|finland|helsinki|poland|warsaw|krakow|"
    r"portugal|lisbon|czech|prague|romania|bucharest|hungary|budapest|greece|turkey|istanbul|israel|tel aviv|"
    r"uae|dubai|abu dhabi|saudi|riyadh|qatar|doha|south africa|johannesburg|cape town|nigeria|lagos|kenya|nairobi|"
    r"egypt|cairo|india|bangalore|bengaluru|mumbai|delhi|hyderabad|pune|chennai|singapore|malaysia|kuala lumpur|"
    r"indonesia|jakarta|philippines|manila|vietnam|thailand|bangkok|japan|tokyo|osaka|korea|seoul|china|beijing|"
    r"shanghai|shenzhen|hong kong|taiwan|taipei|australia|sydney|melbourne|brisbane|perth|new zealand|auckland|"
    r"canada|toronto|vancouver|montreal|ottawa|calgary|mexico|mexico city|guadalajara|brazil|sao paulo|são paulo|"
    r"argentina|buenos aires|colombia|bogota|bogotá|chile|costa rica|emea|apac|apj|latam|anz|dach|nordics|benelux|"
    r"bavaria|westphalia|baden)\b"
    # Titles like "BDR - German Speaking": a non-English market, so not a US role.
    r"|\b(?:arabic|bahasa(?: indonesia)?|cantonese|mandarin|chinese|japanese|korean|german|dutch|turkish|hebrew|danish|"
    r"norwegian|swedish|finnish|polish|italian|french|czech|greek|russian|thai|vietnamese)(?:[- ]speaking|[- ]speaker| fluent)")


def _remote_states(loc: str) -> list[str] | None:
    """States a remote posting is limited to, from location entries like "Remote - Illinois, USA" or
    "Connecticut (Remote)". A plain "Remote" entry anywhere in the list means no state limit."""
    parts = [x for x in re.split(r"[;|]|\s+or\s+", loc or "") if re.search(r"\bremote\b", x, re.I)]
    if not parts:
        return None
    states: set[str] = set()
    for part in parts:
        found = parse_location(re.sub(r"\bremote\b", " ", part, flags=re.I)).states
        if not found:
            return None
        states |= set(found)
    return sorted(states)


def parse_location(location_text: str | None, description: str | None = None, title: str | None = None) -> LocationInfo:
    loc = location_text or ""
    desc = description or ""
    info = LocationInfo()
    blob = f"{loc} | {title or ''}"

    for m in re.finditer(r"([A-Z][A-Za-z .'-]{2,40}),\s*([A-Z]{2})\b", loc):
        city, st = m.group(1).strip(), m.group(2)
        if st in STATES:
            info.cities.append(city)
            info.states.append(st)
    low = loc.lower()
    for city, st in CITY_TO_STATE.items():
        if city in low and re.search(r"(?<![a-z])" + re.escape(city) + r"(?![a-z])", low):
            if city == "washington" and "washington, dc" not in low and "washington dc" not in low:
                continue
            info.cities.append(city.title())
            info.states.append(st)
    for name, st in NAME_TO_STATE.items():
        if name == "washington" and re.search(r"washington,?\s*d\.?c", low):
            continue
        if name == "virginia" and "west virginia" in low and low.count("virginia") == 1:
            continue
        if name in low and re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", low):
            info.states.append(st)
    if re.search(r"dublin,?\s*(ca|california)", low):
        info.states.append("CA")
    info.states = sorted(set(info.states))
    info.cities = sorted(set(info.cities))
    if "CA" in info.states:
        ca_cities = {c.lower() for c in info.cities if CITY_TO_STATE.get(c.lower()) == "CA" or c.lower() in SOCAL_CITIES}
        if ca_cities & SOCAL_CITIES or re.search(r"southern california|\bsocal\b|orange county|inland empire", low):
            info.regions.append("socal")
        if ca_cities - SOCAL_CITIES:
            info.regions.append("norcal")
        if not info.regions:
            info.regions.append("ca_unknown")
    if not info.states and not re.search(r"\b(us|usa|u\.s\.|united states)\b", low) and (
            (loc and _INTERNATIONAL.search(low)) or _INTERNATIONAL.search((title or "").lower())):
        info.international_only = True
    if _DUBLIN_IE.search(loc):
        info.international_only = not info.states

    # Work mode comes from the location field and explicit title tags like "(Remote)" or "- Hybrid",
    # never from phrases such as "Hybrid Infrastructure" or "hybrid cloud".
    title_mode = re.search(r"\((?:[^)]*\b)?(remote|hybrid)\b[^)]*\)|[-,|]\s*(remote|hybrid)\b(?!\s+(?:cloud|infra|it\b))",
                           title or "", re.I)
    blob_low = (loc + " " + (title_mode.group(0) if title_mode else "")).lower()
    desc_low = desc[:6000].lower()
    if re.search(r"\bhybrid\b", blob_low) or re.search(
            r"\bhybrid (?:work|schedule|role|position|model|opportunity|in)\b|days? (?:per|a) week in (?:the |our )?office"
            r"|\d days?/week in office|in-person collaboration", desc_low):
        info.remote_type = "hybrid"
    elif re.search(r"\bremote\b", blob_low):
        info.remote_type = "remote"
    elif re.search(r"\bon-?site\b|\bin-?office\b|five days per week|5 days a week|fully in office", desc_low):
        info.remote_type = "onsite"
    elif re.search(r"(?:fully |100% )remote|remote (?:role|position|opportunity)\b|work from anywhere in the u",
                   desc_low):
        info.remote_type = "remote"
    elif info.states:
        info.remote_type = "onsite"

    if info.remote_type == "remote":
        region = None
        for name in sorted(REGIONS, key=len, reverse=True):
            if re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", (title or "").lower()):
                region = name
                break
        restrict = re.search(r"must (?:reside|live|be located|be based) (?:in|within) ([^.;\n]{3,120})", desc, re.I)
        tz = re.search(r"\b(pacific|mountain|central|eastern)\s+time\s*zone", desc, re.I)
        remote_states = _remote_states(loc)
        if region:
            info.remote_scope = f"region:{region}"
            info.allowed_states = sorted(REGIONS[region])
        elif remote_states:
            info.remote_scope = "restricted: " + ", ".join(remote_states)
            info.allowed_states = remote_states
        elif restrict:
            phrase = restrict.group(1)
            info.remote_scope = f"restricted: {phrase.strip()}"
            st = parse_location(phrase).states
            if st:
                info.allowed_states = st
            elif re.search(r"united states|\bus\b|\busa\b", phrase, re.I):
                info.remote_scope = "US"
        elif tz:
            zone = tz.group(1).lower()
            info.remote_scope = f"timezone:{zone}"
            info.allowed_states = sorted(REGIONS["pacific"] | {"AZ", "NV"}) if zone == "pacific" else (
                sorted(REGIONS["mountain"]) if zone == "mountain" else None)
        else:
            info.remote_scope = "US" if re.search(r"\b(us|usa|united states|u\.s\.)\b", blob, re.I) else "unspecified"
    return info


# ----------------------------------------------------------------------------- compensation

_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"


def _to_float(num: str, k: str | None) -> float:
    v = float(num.replace(",", ""))
    return v * 1000 if k else v


@dataclass
class Comp:
    min: float | None = None
    max: float | None = None
    period: str | None = None  # year | hour
    note: str | None = None

    @property
    def annual_mid(self) -> float | None:
        if self.min is None:
            return None
        mid = (self.min + (self.max or self.min)) / 2
        return mid * 2080 if self.period == "hour" else mid


def parse_comp(text: str | None) -> Comp:
    if not text:
        return Comp()
    rng = re.compile(r"\$\s?" + _NUM + r"\s?([kK])?\s*(?:usd)?\s*(?:-|\u2013|\u2014|to)\s*\$?\s?" + _NUM + r"\s?([kK])?",
                     re.I)
    single = re.compile(r"\$\s?" + _NUM + r"\s?([kK])?(?:\s*(?:/|per)\s*(yr|year|hour|hr))?", re.I)
    best: Comp | None = None
    for m in rng.finditer(text):
        lo, hi = _to_float(m.group(1), m.group(2)), _to_float(m.group(3), m.group(4) or m.group(2))
        if hi < lo or lo <= 0:
            continue
        ctx = text[m.end(): m.end() + 40].lower()
        period = "hour" if re.search(r"hour|/hr|\bhr\b|hourly", ctx) or hi < 500 else "year"
        if period == "year" and hi < 20000:
            continue  # stipends, fees, not salaries
        c = Comp(lo, hi, period)
        if best is None or (c.annual_mid or 0) > (best.annual_mid or 0):
            best = c
    if best is None:
        for m in single.finditer(text):
            v = _to_float(m.group(1), m.group(2))
            per = (m.group(3) or "").lower()
            period = "hour" if per.startswith("h") or v < 500 else "year"
            if period == "year" and v < 20000:
                continue
            best = Comp(v, v, period)
            break
    if best is None:
        return Comp()
    if re.search(r"commission|ote|on-target|incentive|plus commission|\+ ?uncapped", text, re.I):
        best.note = "Range may include or exclude commission; check the posting wording."
    return best


# ----------------------------------------------------------------------------- experience

def parse_yoe(text: str | None) -> tuple[float | None, bool]:
    """Return (minimum years requested, is_preferred_only)."""
    if not text:
        return None, False
    best: tuple[float, bool] | None = None
    pat = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|\u2013|to)\s*(\d{1,2})\s*\+?\s*)?(?:years?|yrs?)(?:'s?)?(?:\s+of)?"
                     r"([^.\n]{0,80})", re.I)
    for m in pat.finditer(text):
        tail = m.group(3).lower()
        before = text[max(0, m.start() - 60): m.start()].lower()
        if "experience" not in tail and "experience" not in before:
            continue
        if re.search(r"\b(ago|old|age|warranty|program|months)\b", tail[:20]):
            continue
        years = float(m.group(1))
        if years > 15:
            continue
        window = (before + tail)
        preferred = bool(re.search(r"prefer|plus|nice to have|ideally|bonus", window))
        if best is None or years < best[0]:
            best = (years, preferred)
    return best if best else (None, False)


# ----------------------------------------------------------------------------- graduation compatibility

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
_MON = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
        r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_MD = re.compile(r"\b" + _MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(20\d\d))?", re.I)
_MY = re.compile(r"\b" + _MON + r"\.?,?\s+(20\d\d)\b", re.I)
_DM = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\s+" + _MON + r",?\s+(20\d\d)\b", re.I)


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _dates_in(sentence: str) -> list[date]:
    out: list[date] = []
    years = [(m.start(), int(m.group(0))) for m in re.finditer(r"\b20\d\d\b", sentence)]
    for m in _MD.finditer(sentence):
        mon = MONTHS[m.group(1).lower()[:3]]
        if m.group(3):
            yr = int(m.group(3))
        else:
            following = [y for pos, y in years if pos > m.end()]
            if not following:
                continue
            yr = following[0]
        d = _safe_date(yr, mon, int(m.group(2)))
        if d:
            out.append(d)
    for m in _MY.finditer(sentence):
        d = _safe_date(int(m.group(2)), MONTHS[m.group(1).lower()[:3]], 1)
        if d and not any(x.year == d.year and x.month == d.month for x in out):
            out.append(d)
    for m in _DM.finditer(sentence):
        d = _safe_date(int(m.group(3)), MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
        if d and d not in out:
            out.append(d)
    return out


GRAD_LABELS = {
    "eligible_now": "Eligible now",
    "eligible_closer": "Eligible closer to graduation",
    "likely_may_2027": "Likely intended for May 2027 graduates",
    "internship_convert": "Internship that could convert to full-time",
    "too_early": "Starts before you graduate",
    "too_late": "Intended for later graduates",
    "requires_experience": "Requires previous experience",
    "unclear": "Unclear",
}


def apply_window(start: date) -> tuple[date, date]:
    """Undated entry roles hire within weeks for a near-term start: apply 1 to 3 months before you can start."""
    m = start.month - 3
    open_ = date(start.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)
    m2 = start.month - 1
    close = date(start.year + (m2 - 1) // 12, (m2 - 1) % 12 + 1, 1)
    return open_, close


def _window_reason(start: date) -> str:
    o, c = apply_window(start)
    return (f"Roles like this usually hire within a few weeks for a near-term start. For your {start:%B %Y} start, "
            f"apply around {o:%B} to {c:%B %Y}. Until then, save the company and get to know its recruiter.")


def grad_compat(title: str, text: str | None, grad: date, today: date, start: date | None = None) -> tuple[str, str]:
    """Classify whether a posting fits a candidate graduating on `grad` who can start on `start`."""
    body = text or ""
    sentences = re.split(r"(?<=[.!?\n])\s+", body)
    is_intern = bool(re.search(r"\bintern(ship)?\b|\bco-?op\b", title, re.I))
    grad_year = grad.year

    # Explicit start dates
    start_dates: list[date] = []
    for s in sentences:
        if re.search(r"\bstart", s, re.I) and not re.search(r"start(?:ed|ing)? (?:your|a|the) career", s, re.I):
            start_dates += _dates_in(s)
    # Explicit graduation windows
    windows: list[tuple[date, date, str]] = []
    for s in sentences:
        if not re.search(r"graduat|degree by|completing (?:their|your) bachelor", s, re.I):
            continue
        ds = _dates_in(s)
        if len(ds) >= 2:
            windows.append((min(ds), max(ds), s.strip()))
        elif len(ds) == 1 and re.search(r"\bby\b|before|no later than", s, re.I):
            windows.append((date(1900, 1, 1), ds[0], s.strip()))
        elif len(ds) == 1:
            windows.append((ds[0], ds[0], s.strip()))
    class_of = re.search(r"class of (20\d\d)|(20\d\d) (?:start|graduates?|new grad|university grad)|"
                         r"new grad(?:uate)? (20\d\d)|(20\d\d) new grad", f"{title} {body}", re.I)
    if not class_of and _PROGRAM.search(title):
        class_of = re.search(r"\b(20\d\d)\b", title)

    if is_intern:
        if re.search(r"(fall|autumn) 20\d\d|spring 2027|winter 2026", f"{title} {body}", re.I) and not re.search(
                r"summer 2027", f"{title} {body}", re.I):
            return "internship_convert", "Term-time internship that runs before your May 2027 graduation."
        for lo, hi, _ in windows:
            if lo <= grad <= hi + _days(45):
                return "internship_convert", "Graduation window includes May 2027."
        return "too_late", ("Internships usually require returning to school afterward; "
                            "you graduate in May 2027, so look for the full-time version of this program.")

    for lo, hi, s in windows:
        if hi < grad - _days(20):
            return "too_early", f"Requires graduating by {hi:%B %Y}; you graduate {grad:%B %Y}."
        if lo > grad + _days(60):
            return "too_late", f"Intended for graduates from {lo:%B %Y}; you graduate {grad:%B %Y}."
    if start_dates:
        after = [d for d in start_dates if d >= grad - _days(14)]
        if not after:
            first = min(start_dates)
            return "too_early", f"Start date {first:%B %d, %Y} is before your graduation ({grad:%B %Y})."
        if any(lo <= grad <= hi + _days(45) for lo, hi, _ in windows) or class_of:
            return "likely_may_2027", f"Has a start date after graduation ({min(after):%B %Y}) and a matching class year."
        return "likely_may_2027", f"Has a start date after your graduation ({min(after):%B %d, %Y})."
    for lo, hi, _ in windows:
        if lo <= grad <= hi + _days(45):
            return "likely_may_2027", "Graduation window includes May 2027."
    if class_of:
        yr = int(next(g for g in class_of.groups() if g))
        if yr == grad_year:
            return "likely_may_2027", f"Posting targets the {yr} graduating class."
        if yr < grad_year:
            return "too_early", f"Posting targets the {yr} class."
        return "too_late", f"Posting targets the {yr} class."

    yoe, preferred = parse_yoe(body)
    if yoe is not None and yoe >= 2 and not preferred and not re.search(
            r"new grad|recent grad|university grad|or equivalent (?:military|academy)|graduate of", body, re.I):
        return "requires_experience", f"Asks for {yoe:g}+ years of experience."
    start = start or date(grad.year + (grad.month // 12), grad.month % 12 + 1, 1)
    window_open, _ = apply_window(start)
    entryish = bool(sales_level(title)) or bool(re.search(
        r"recent (?:college )?grad|new grad|university grad|early[- ]career|entry[- ]level|associate|junior|"
        r"within (?:less than )?(?:one|1|12 months)", f"{title} {body}", re.I))
    if entryish or (yoe is not None and yoe <= 1):
        if today < window_open:
            return "eligible_closer", _window_reason(start)
        if today <= start:
            return "eligible_now", f"You're in the apply window for your {start:%B %Y} start."
        return "eligible_now", "Entry-level role; you're available now."
    return "unclear", "No graduation window, start date or experience requirement found."


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)
