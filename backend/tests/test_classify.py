from datetime import date

from app.services.classify import classify_role, grad_compat, parse_comp, parse_location, parse_yoe

G, T = date(2027, 5, 15), date(2026, 10, 1)


def test_role_families():
    assert classify_role("Associate Solutions Engineer, San Mateo").family == "direct_se"
    assert classify_role("Sales Development Representative (AAE), Phoenix").family == "pipeline"
    assert classify_role("Technical Account Manager").family == "technical_entry"
    assert classify_role("Systems Engineer", "Maintain Linux servers").family == "other"
    assert classify_role("Associate Systems Engineer", "support customers in the pre-sales process").family == "direct_se"
    assert classify_role("Leadership Development Program 2027 (Sales)").is_program


def test_seniority():
    assert classify_role("Senior Sales Engineer").is_senior
    assert classify_role("Manager, Sales Engineering").is_senior
    assert classify_role("Sr. Solutions Engineer").is_senior
    assert not classify_role("Associate Sales Engineer").is_senior
    assert not classify_role("Account Manager Small Business").is_senior
    # Enterprise, strategic and named-account sellers are experienced hires; their SDRs are not.
    for t in ("Strategic Account Executive", "Account Executive - Enterprise", "Named Account Manager - SLED",
              "Major Account Manager - FSI", "Enterprise Account Executive - West", "Account Executive, Federal"):
        assert classify_role(t).is_senior, t
    assert classify_role("SDR Manager").is_senior
    assert classify_role("Strategic Channel Account Manager - Reseller").is_senior
    assert classify_role("Software Engineer II - EDR Workflows - Security").family != "pipeline"
    for t in ("Enterprise Business Development Representative", "Enterprise SDR", "Associate Account Executive",
              "Account Executive, Commercial - Kansas City", "Inside Sales Representative"):
        assert not classify_role(t).is_senior, t


def test_locations():
    li = parse_location("Remote - US", "", "Associate Sales Engineer, SE Desk - Southeast")
    assert li.remote_type == "remote" and "AZ" not in li.allowed_states
    assert parse_location("Chandler, AZ, US", "Hybrid in our Chandler office").remote_type == "hybrid"
    assert parse_location("Remote", "design hybrid cloud environments", "Solution Architect - Hybrid Infrastructure").remote_type == "remote"
    assert parse_location("Dublin, CA").states == ["CA"]
    assert parse_location("Dublin, Ireland").international_only
    for loc in ("Stockholm, Sweden", "Tokyo", "Remote - Taiwan", "Toronto, ON", "EMEA - Remote"):
        assert parse_location(loc).international_only, loc
    for loc in ("Athens, GA", "Paris, TX", "Remote, US", "Phoenix, AZ"):
        assert not parse_location(loc).international_only, loc
    assert parse_location("Washington, DC").states == ["DC"]
    # "Remote - <state>" limits where you can live; a plain "Remote" entry does not.
    assert parse_location("Remote (Tennessee, USA)").allowed_states == ["TN"]
    assert parse_location("Remote - Illinois, USA; Remote - Missouri, US").allowed_states == ["IL", "MO"]
    assert parse_location("Connecticut (Remote)").allowed_states == ["CT"]
    assert parse_location("San Francisco; Remote").allowed_states is None
    assert parse_location("Remote - US").allowed_states is None
    assert parse_location("Hybrid", "", "Business Development Representative, Beijing").international_only
    assert parse_location("Hybrid", "", "Business Development Representative - German Speaking").international_only
    assert not parse_location("Hybrid", "", "Business Development Representative (BDR)").international_only


def test_comp_and_yoe():
    c = parse_comp("$35 to $40 Hourly")
    assert c.period == "hour" and c.annual_mid == 78000
    assert parse_comp("$72,000.00 - $104,300.00").max == 104300
    assert parse_comp("raised $700M in funding").min is None
    assert parse_yoe("Preferred 1+ years experience with customers") == (1.0, True)
    assert parse_yoe("3+ years experience in pre-sales") == (3.0, False)


def test_graduation_compatibility():
    assert grad_compat("Solutions Architect, AWSI - 2027", "Start dates are tentatively set to occur January 4 and July 6 of 2027.", G, T)[0] == "likely_may_2027"
    assert grad_compat("ASA Early Career - 2027", "Start dates are tentatively set to occur January 25, 2027.", G, T)[0] == "too_early"
    assert grad_compat("SA Intern", "Expected Graduation: December 2027 - September 2028", G, T)[0] == "too_late"
    assert grad_compat("Undergrad SWE", "intended for students completing their Bachelor's degree by January 2027", G, T)[0] == "too_early"
    assert grad_compat("Sales Engineer", "5+ years of experience required", G, T)[0] == "requires_experience"
    assert grad_compat("Customer Growth Associate, University Graduate, 2027 Start", "", G, T)[0] == "likely_may_2027"
