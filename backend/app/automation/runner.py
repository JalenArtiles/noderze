"""Browser automation for application forms (Playwright, visible browser, your own session).

    python -m app.automation.runner --application-id 12

What it does
1. Opens the posting's apply page in a visible Chromium window with a persistent local profile.
2. Fills fields it can map confidently (name, email, phone, LinkedIn, location) and uploads the rendered
   resume version tied to the application.
3. Stops before submitting, takes a screenshot, and creates an Approval request.
4. Waits. Only after you approve in the app does it click Submit, and only if the page still looks the same.

What it never does
- Solve or bypass CAPTCHAs, MFA, login prompts, bot checks or rate limits. It pauses and asks you to take over.
- Automate LinkedIn Easy Apply or any site whose terms forbid automation.
- Enter passwords, SSNs, bank details or government ID numbers. It leaves those fields for you.
- Submit anything with unverified claims, even if TRUSTED_AUTO_SUBMIT is on.
"""
from __future__ import annotations

import argparse
import re
import sys
import time

from ..config import settings
from ..db import SessionLocal
from ..models import Application, Approval, Job, ResumeVersion
from ..services import approvals as A
from ..services.profile import get_profile, master_resume

BLOCKED_HOSTS = ("linkedin.com", "indeed.com", "glassdoor.com")
HUMAN_CHECK = re.compile(r"captcha|recaptcha|hcaptcha|turnstile|verify you are human|are you a robot|"
                         r"one-time (?:pass)?code|verification code|two-factor|2fa|sign in to continue|log in to apply", re.I)
SENSITIVE = re.compile(r"password|social security|ssn|bank|routing|account number|passport|driver'?s license|"
                       r"date of birth|\bdob\b", re.I)
FIELD_MAP = [
    (re.compile(r"^first\s*name|given name", re.I), "first_name"),
    (re.compile(r"^last\s*name|family name|surname", re.I), "last_name"),
    (re.compile(r"^(full\s*)?name$", re.I), "full_name"),
    (re.compile(r"e-?mail", re.I), "email"),
    (re.compile(r"phone|mobile", re.I), "phone"),
    (re.compile(r"linkedin", re.I), "linkedin"),
    (re.compile(r"^(current\s*)?(location|city)", re.I), "location"),
]


def _values(db) -> dict:
    res = master_resume(db)
    c = (res.parsed or {}).get("contact", {}) if res else {}
    name = c.get("name") or (get_profile(db).data or {}).get("name", "")
    first, _, last = name.partition(" ")
    link = c.get("linkedin")
    return {"first_name": first, "last_name": last, "full_name": name, "email": c.get("email"),
            "phone": c.get("phone"), "linkedin": f"https://{link}" if link and not link.startswith("http") else link,
            "location": c.get("location")}


def human_check_present(page) -> bool:
    for sel in ("iframe[src*='recaptcha']", "iframe[src*='hcaptcha']", "iframe[src*='challenges.cloudflare']",
                "input[autocomplete='one-time-code']", "input[type='password']"):
        if page.query_selector(sel):
            return True
    return bool(HUMAN_CHECK.search(page.inner_text("body")[:20000]))


def wait_for_human(page, why: str) -> None:
    print(f"\n>>> Paused: {why}\n    Complete it yourself in the browser window. Waiting...")
    while human_check_present(page):
        time.sleep(3)
    print("    Continuing.")


def fill(page, values: dict, resume_path: str | None) -> list[str]:
    filled = []
    for el in page.query_selector_all("input, textarea"):
        try:
            if not el.is_visible() or el.get_attribute("type") in ("hidden", "submit", "button", "checkbox", "radio"):
                continue
            label = ""
            el_id = el.get_attribute("id")
            if el_id:
                lab = page.query_selector(f"label[for='{el_id}']")
                label = lab.inner_text() if lab else ""
            label = (label or el.get_attribute("aria-label") or el.get_attribute("placeholder")
                     or el.get_attribute("name") or "").strip()
            if SENSITIVE.search(label):
                continue  # never typed by automation
            if el.get_attribute("type") == "file":
                if resume_path and re.search(r"resume|cv", label + (el.get_attribute("name") or ""), re.I):
                    el.set_input_files(resume_path)
                    filled.append("resume upload")
                continue
            if el.input_value():
                continue
            for rx, key in FIELD_MAP:
                if rx.search(label) and values.get(key):
                    el.fill(values[key])
                    filled.append(label)
                    break
        except Exception:
            continue
    return filled


def run(application_id: int) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Install automation extras: pip install -r requirements-automation.txt && playwright install chromium")
    db = SessionLocal()
    app = db.get(Application, application_id) or sys.exit("No such application")
    job = db.get(Job, app.job_id)
    url = job.apply_url or job.url
    if not url or any(h in url for h in BLOCKED_HOSTS):
        sys.exit("This posting is on a site that is not automated. Apply manually from the company page.")
    v = db.get(ResumeVersion, app.resume_version_id) if app.resume_version_id else None
    if not v or not v.output_path:
        sys.exit("Render the tailored resume version first (Resume page).")
    flagged = [e for e in v.edits if e.get("status") == "approved" and e.get("flags")]
    values = _values(db)
    profile_dir = settings.data_dir / "browser-profile"
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(profile_dir), headless=False)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        if human_check_present(page):
            wait_for_human(page, "a CAPTCHA, login or verification step")
        apply_btn = page.query_selector("a:has-text('Apply'), button:has-text('Apply')")
        if apply_btn and "apply" not in page.url.lower():
            apply_btn.click()
            page.wait_for_load_state("domcontentloaded")
            if human_check_present(page):
                wait_for_human(page, "a CAPTCHA, login or verification step")
        filled = fill(page, values, v.output_path)
        print("Filled:", ", ".join(filled) or "nothing automatically")
        print("Review every field in the browser. Custom questions are left for you; drafts are in the app.")
        shot = settings.data_dir / "screenshots" / f"application-{app.id}.png"
        page.screenshot(path=str(shot), full_page=True)
        ap = A.request(db, "submit_application", f"Submit application to {job.company.name}: {job.title}",
                       {"application_id": app.id, "url": page.url, "screenshot": str(shot), "filled": filled,
                        "unverified_claims": len(flagged)})
        print(f"Approval #{ap.id} created. Approve or reject it on the Approvals page. Waiting...")
        auto = settings.trusted_auto_submit and not flagged
        while True:
            db.expire_all()
            ap = db.get(Approval, ap.id)
            if ap.status in ("approved", "executed") or auto:
                break
            if ap.status == "rejected":
                print("Rejected. The browser stays open so you can finish or close it yourself.")
                input("Press Enter to close.")
                return
            time.sleep(3)
        if human_check_present(page):
            wait_for_human(page, "a verification step appeared before submit")
        btn = page.query_selector("button[type='submit'], input[type='submit'], button:has-text('Submit')")
        if not btn:
            print("No submit button found. Submit manually in the browser.")
        else:
            btn.click()
            page.wait_for_load_state("networkidle")
            ap.status, ap.result = "executed", {"final_url": page.url}
            app.stage, app.date_applied = "applied", app.date_applied or __import__("datetime").date.today()
            db.commit()
            print("Submitted. Marked as Applied in the tracker.")
        input("Press Enter to close the browser.")
        ctx.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--application-id", type=int, required=True)
    run(ap.parse_args().application_id)
