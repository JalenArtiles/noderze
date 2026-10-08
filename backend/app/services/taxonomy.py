"""Skill taxonomy used for job analysis, resume matching and skill-gap analysis.

Areas map to term lists. Matching is word-boundary based and case-insensitive.
Short ambiguous tokens (go, ai, ml) are handled conservatively to avoid false hits.
"""
from __future__ import annotations

import re
from functools import lru_cache

TECH_AREAS: dict[str, list[str]] = {
    "networking": ["computer networks", "networking", "network fundamentals", "tcp/ip", "tcp", "dns", "dhcp",
                   "routing", "switching", "vlan", "subnet", "subnetting", "osi model", "lan", "wan", "sd-wan",
                   "load balancer", "load balancing", "bgp", "wi-fi", "wireless"],
    "network_security": ["network security", "firewall", "firewalls", "ids", "ips", "vpn", "zero trust", "sase",
                         "sse", "ztna", "segmentation", "secure web gateway", "proxy"],
    "security": ["cybersecurity", "cyber security", "information security", "threat", "threats", "vulnerability",
                 "vulnerabilities", "endpoint", "edr", "xdr", "siem", "soc", "incident response", "iam", "identity",
                 "mfa", "sso", "encryption", "dlp", "casb", "threat assessment", "malware", "ransomware",
                 "physical security", "access control", "secure coding"],
    "cloud": ["cloud", "aws", "azure", "gcp", "google cloud", "saas", "iaas", "paas", "kubernetes", "containers",
              "docker", "virtualization", "virtual machines", "vmware", "serverless", "cloud computing"],
    "linux": ["linux", "unix"],
    "programming": ["python", "java", "javascript", "golang", "c++", "c#", "ruby", "node.js", "scripting",
                    "programming", "bash", "scheme", "object-oriented programming"],
    "apis": ["api", "apis", "rest api", "restful", "integration", "integrations", "webhook", "webhooks", "sdk"],
    "databases": ["sql", "database", "databases", "database systems", "nosql", "postgres", "mysql"],
    "ai": ["artificial intelligence", "machine learning", "llm", "llms", "large language models", "generative ai",
           "genai", "prompt engineering", "ai evaluation", "ai-powered", "ai agents"],
    "operating_systems": ["operating systems", "windows", "macos"],
    "iot_hardware": ["iot", "sensors", "hardware", "electronics", "electrical systems", "cameras", "telematics"],
    "packet_analysis": ["wireshark", "packet capture", "packet analysis"],
}

SALES_AREAS: dict[str, list[str]] = {
    "prospecting": ["prospecting", "prospect", "cold call", "cold calling", "cold calls", "outbound",
                    "lead generation", "pipeline generation", "new business"],
    "crm": ["crm", "salesforce", "hubspot", "outreach.io", "sales navigator"],
    "discovery": ["discovery", "qualify", "qualification", "needs analysis", "meddic", "meddpicc",
                  "business requirements", "requirements gathering"],
    "demo": ["demo", "demos", "demonstration", "demonstrations", "proof of concept", "poc", "proof of value",
             "technical validation", "workshop", "workshops"],
    "presentation": ["presentation", "presentations", "presenting", "public speaking", "whiteboard",
                     "whiteboarding"],
    "customer_facing": ["customer-facing", "customer facing", "client-facing", "client facing", "stakeholders",
                        "client relationship", "client relationships", "trusted advisor"],
    "objection_handling": ["objection", "objections", "objection handling"],
    "value_selling": ["value selling", "business value", "roi", "value proposition", "business outcomes"],
    "rfp": ["rfp", "rfps", "rfi", "request for proposal"],
    "quota": ["quota", "quotas"],
    "ae_partnership": ["account executive", "account executives", "sales team", "sales teams", "sales reps"],
}

AREA_LABELS = {
    "networking": "Networking fundamentals", "network_security": "Network security", "security": "Cybersecurity",
    "cloud": "Cloud", "linux": "Linux", "programming": "Programming", "apis": "APIs and integrations",
    "databases": "Databases and SQL", "ai": "AI fundamentals", "operating_systems": "Operating systems",
    "iot_hardware": "IoT and hardware", "packet_analysis": "Packet analysis", "prospecting": "Prospecting",
    "crm": "CRM", "discovery": "Discovery and qualification", "demo": "Product demos and POCs",
    "presentation": "Presentations", "customer_facing": "Customer-facing work",
    "objection_handling": "Objection handling", "value_selling": "Value selling", "rfp": "RFP responses",
    "quota": "Quota experience", "ae_partnership": "Working with account executives",
}

CERT_PATTERNS = {
    "CCNA": r"\bccna\b", "Network+": r"network\s*\+", "Security+": r"security\s*\+", "CISSP": r"\bcissp\b",
    "AWS certification": r"\baws certified\b|\baws certification\b|aws solutions architect",
    "Azure certification": r"\baz-\d{3}\b|azure (?:administrator|fundamentals|certification)",
    "Security clearance": r"security clearance|\bts/sci\b|secret clearance|active clearance",
    "ITIL": r"\bitil\b",
}


def _term_regex(term: str) -> str:
    return r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"


@lru_cache(maxsize=None)
def _area_regex(kind: str, area: str) -> re.Pattern:
    # Same matches as joining _term_regex(t) for each term, about 6x faster on long postings: the shared
    # boundary check and a first-character test run once per position instead of once per term.
    terms = [t.lower() for t in (TECH_AREAS if kind == "tech" else SALES_AREAS)[area]]
    firsts = "".join(sorted({re.escape(t[0]) for t in terms}))
    alts = "|".join(re.escape(t) for t in terms)
    return re.compile(r"(?<![a-z0-9])(?=[" + firsts + r"])(?:" + alts + r")(?![a-z0-9])", re.I)


@lru_cache(maxsize=64)
def _areas_cached(text: str, kind: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    table = TECH_AREAS if kind == "tech" else SALES_AREAS
    out = []
    for area in table:
        hits = {m.group(0).lower() for m in _area_regex(kind, area).finditer(text)}
        if hits:
            out.append((area, tuple(sorted(hits))))
    return tuple(out)


def areas_in(text: str | None, kind: str = "tech") -> dict[str, list[str]]:
    """Return {area: [matched terms]} for areas present in text."""
    if not text:
        return {}
    return {area: list(hits) for area, hits in _areas_cached(text, kind)}


def certs_in(text: str | None) -> list[str]:
    if not text:
        return []
    return [name for name, pat in CERT_PATTERNS.items() if re.search(pat, text, re.I)]


def certs_required(text: str | None) -> list[str]:
    """Certs that appear in a 'required/must' sentence, as opposed to 'preferred/plus'."""
    if not text:
        return []
    found: list[str] = []
    for sentence in re.split(r"(?<=[.!?\n])\s+", text):
        low = sentence.lower()
        if re.search(r"preferred|a plus|is a plus|nice to have|bonus|ideal", low):
            continue
        if re.search(r"required|must have|must hold|must possess|minimum qualification", low):
            found += [c for c in certs_in(sentence) if c not in found]
    return found
