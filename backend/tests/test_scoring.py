from datetime import date

from app.services.classify import parse_location
from app.services.scoring import CompanySignals, JobView, ProfileView, normalize_weights, path_class_for, score_job

PROF = ProfileView(tech_areas={"networking", "security", "programming"}, sales_areas={"prospecting", "crm", "discovery"})
CYBER = CompanySignals(category="cybersecurity", has_se_org=True, se_roles_seen=8)


def jv(**kw):
    base = dict(title="Associate Sales Engineer", family="direct_se", is_program=False, program_target=None,
                program_official=False, description="Work with account executives. Networking and security.",
                location=parse_location("Phoenix, AZ"), grad_status="eligible_closer", grad_reason="", yoe_min=None,
                comp_annual_mid=90000, comp_known=True, source_is_original=True, last_verified_at=None,
                company=CompanySignals(category="cybersecurity"))
    base.update(kw)
    return JobView(**base)


def test_weights_normalize_to_100():
    w = normalize_weights({"career_path": 50})
    assert abs(sum(w.values()) - 100) < 1e-6 and w["career_path"] > 25


def test_path_needs_evidence_for_sdr():
    sdr = jv(title="SDR", family="pipeline", company=CompanySignals(has_se_org=True))
    assert path_class_for(sdr)[0] == "POSSIBLE"
    assert path_class_for(jv(family="pipeline", company=CompanySignals(se_transitions=2)))[0] == "LIKELY"
    assert path_class_for(jv(family="pipeline"))[0] == "WEAK"
    assert path_class_for(jv())[0] == "DIRECT"


def test_breakdown_sums_and_explains():
    r = score_job(jv(), PROF, today=date(2026, 10, 1))
    assert abs(sum(c["score"] for c in r["breakdown"].values()) - r["total"]) < 0.5
    assert all(c["reasons"] for c in r["breakdown"].values())


def test_geography_categories():
    sdr = dict(title="Sales Development Representative", family="pipeline", company=CYBER)
    assert score_job(jv(**sdr), PROF)["category"] == "entry_sales"
    assert score_job(jv(**sdr, location=parse_location("San Diego, CA")), PROF)["category"] == "entry_sales"
    assert score_job(jv(**sdr, location=parse_location("Remote - US")), PROF)["category"] == "entry_sales"
    assert score_job(jv(**sdr, location=parse_location("San Francisco, CA")), PROF)["category"] == "long_shot"
    assert score_job(jv(**sdr, location=parse_location("Austin, TX")), PROF)["category"] == "long_shot"
    assert score_job(jv(title="SDR", family="pipeline", company=CompanySignals(category="software")), PROF)["category"] == "other_sales"
    prog = score_job(jv(title="Associate Solutions Engineer", is_program=True, program_target="se",
                        location=parse_location("San Mateo, CA")), PROF)
    assert prog["category"] == "program" and "outside_area" in prog["flags"]
    assert score_job(jv(title="Sales Engineer", yoe_min=2), PROF)["category"] == "goal_se"
    assert score_job(jv(**sdr, grad_status="too_early"), PROF)["category"] == "long_shot"


def test_se_team_raises_sdr_path():
    weak = score_job(jv(title="SDR", family="pipeline", company=CompanySignals(category="cybersecurity", has_se_org=True)), PROF)
    strong = score_job(jv(title="SDR", family="pipeline", company=CYBER), PROF)
    assert strong["breakdown"]["career_path"]["score"] > weak["breakdown"]["career_path"]["score"]
