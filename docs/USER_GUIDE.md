# Noderze user guide

The practical guide: install, daily use, updates and troubleshooting. For the project overview see the [README](../README.md); for the design see [ARCHITECTURE.md](ARCHITECTURE.md).

Noderze is a personal career operating system for one goal: getting from ASU student to Sales Engineer or Solutions Engineer. It finds roles and development programs on companies' own job boards, researches them with sources, and scores fit against your profile with every point explained. It also tailors your resume without inventing anything, drafts outreach and answers, tracks applications, and waits for your approval before anything leaves your machine.

## How you use it (version 3)

- **Companies.** Cybersecurity companies ranked for you: entry sales roles (SDR, BDR, ADR, associate AE, inside sales) in Arizona, remote or Southern California, at companies with a real SE team. The SE team is counted live from each company's own job board.
- **Apply.** Click Apply on any role.
  - Noderze tailors your resume to the keywords that company screens for, using only things your experience supports.
  - It shows your keyword match before and after, and gives you the .docx.
  - It opens the company's application page.
  - Missing keywords stay missing until you click "I have this," which records it as your own claim.
- **Find recruiter.** One-click LinkedIn searches you open yourself: recruiters, SDR managers, sales engineers and ASU alumni. Ready-to-copy messages come with them, and LinkedIn connections you imported appear first.
- **Live updates.** Watched companies are rescanned every three hours (7 AM to 10 PM), and the feeds every six hours. Open pages refresh themselves when new roles arrive; the bar at the top shows the last scan and has a Refresh now button.
- **ASE roles and SE programs** (like Verkada's) have their own section and appear even outside your area, with a flag. SE roles you'd grow into are listed separately as goal roles.

**LinkedIn.** Noderze never logs into LinkedIn, follows, applies or sends messages for you. LinkedIn's terms ban automation and it restricts accounts that use it. Instead you get the exact searches to open, messages to paste, and an import of LinkedIn's own export of your connections (Contacts page).

## The Noderze app (no terminal windows)

After the first setup below, run this once in PowerShell:

```
powershell -ExecutionPolicy Bypass -File "$HOME\se-career-agent\noderze\setup-noderze.ps1"
```

It installs packages, loads new research (your own data is kept) and builds the fast production version. It also creates a **Noderze App** icon on your Desktop and in the Start menu. Click it to open Noderze in its own window; it starts the background servers itself, with no terminal windows.

The launcher is `noderze\noderze_launcher.py`, a small Python program run by the windowless `pythonw.exe`. It deliberately avoids hidden PowerShell and security-bypass flags, the pattern antivirus tools flag.

- **Stop Noderze:**
  ```
  & "$HOME\se-career-agent\backend\.venv\Scripts\python.exe" "$HOME\se-career-agent\noderze\noderze_launcher.py" --stop
  ```
- **Start quietly at sign-in** (so the 7 AM scans run): run the same line with `--autostart on`. Use `off` to undo it.
- **Logs:** they're in the `logs` folder.

## Updates (no zip files)

When this chat is linked to your computer, Claude can edit Noderze's files directly, and Noderze applies the changes itself:
- **Backend changes** reload within a few seconds, because the backend runs in auto-reload mode.
- **Interface changes** are rebuilt in the background (about 1 to 3 minutes) while the current version keeps working. Then they're swapped in, and the window reloads.
- **Failed updates:** if an update fails to build, Noderze keeps running the previous version and shows a notice at the top. Claude reads `logs\build.log` to fix it.

## Updating (manual, only if needed)

1. Extract the new zip over the old folder:
   ```
   Expand-Archive <zip> -DestinationPath ~ -Force
   ```
2. Run `setup-noderze.ps1` again. Your database, resume, `.env` files and installed packages are kept.

## Where jobs come from

| Source | What it covers | Key needed |
|---|---|---|
| Watched companies' own job boards | Every role posted by about 40 watched companies, checked daily | No |
| Board directory (`seed/board_directory.json`) | 2,647 company job boards found through real posting links, scanned weekly (Sunday 2 AM) for sales, SE and technical entry roles in your target locations | No |
| SimplifyJobs new-grad feed | Public GitHub feed of about 20,000 new-grad listings, checked daily | No |
| The Muse | Entry-level sales jobs in Phoenix, California and remote | No |
| Remotive | Remote sales roles open to US candidates | No |
| Adzuna | Aggregated listings from across US job boards (the widest coverage) | Free key from developer.adzuna.com: add `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` to `backend/.env` |
| Web search | Leads for deep research, recruiters and programs | Anthropic key (or Tavily, Brave, Serper) |

LinkedIn, Indeed, Glassdoor and Handshake are not scraped. Their terms forbid it, they block bots, and it can get your accounts flagged.

## What's in the box

```
backend/    FastAPI app, research and scoring engine, seed data, tests, browser runner
frontend/   Next.js UI
docs/       ARCHITECTURE.md (design), USER_GUIDE.md (this file), screenshots
noderze/    Windows app layer: setup, start, open, stop, icon
docker-compose.yml   optional Postgres
```

## Setup

You need Python 3.11 or newer and Node.js 20 or newer. Docker is optional (only for Postgres).

### 1. Backend

```bash
cd backend
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy `backend/.env.example` to `backend/.env`. Then open it:

- `AGENT_TOKEN`: set it to any long random string.
- `ANTHROPIC_API_KEY`: add your key (from console.anthropic.com). Optional, but it unlocks fact extraction, rewriting, better drafts, mock-interview feedback and, by default, web search. Web search must be enabled for your organization in the Claude Console.

Make the profile yours: copy `backend/seed/profile.example.json` to `backend/seed/profile.json` and edit it (school, graduation month, start month, skills, locations). Private notes about companies go in `backend/seed/personal.json` (see `personal.example.json`). Both files are gitignored, so they never reach GitHub.

Load the researched data and your resume, then start the API:

```bash
python scripts/seed_db.py --resume "/path/to/your_resume.docx"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 2. Frontend (in a second terminal)

Copy `frontend/.env.local.example` to `frontend/.env.local` and paste the same `AGENT_TOKEN`. Then:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

### 3. First run

1. **Today:** click **Find new jobs**. This reads the watched companies' job boards live and verifies the seeded postings.
2. **Resume:** review the three flagged issues (graduation date, the SE overclaim, a course-name typo).
3. **Opportunities:** open your top role and click **Prepare application**.
4. **Settings:** fill `work_authorization` and `story_hook` in your profile.

### Optional: Postgres

Run `docker compose up -d db`, then set this in `backend/.env`:

```
DATABASE_URL=postgresql+psycopg://agent:agent@localhost:5432/agent
```

Rerun the seed script afterwards.

### Optional: browser automation

```bash
pip install -r requirements-automation.txt
playwright install chromium
python -m app.automation.runner --application-id 1
```

It fills what it safely can and pauses for CAPTCHAs and logins. It waits for your approval in the app before clicking submit.

## Daily use

- **Each morning,** the scheduled scans run at 7:00 and 7:30 Phoenix time while the API is running. The Today page lists what to do, in order.
- **For a new company,** add it on Companies, set its watch status, and click **Full company analysis**.
- **For each application,** run Prepare application. Then:
  1. Approve or reject resume edits.
  2. Fill the [bracketed] prompts.
  3. Send outreach yourself once it's approved.
  4. Move the card on the Applications board.
- **When you find SE profiles at a company,** paste them under Career paths. Two observed moves from SDR or support into SE upgrade that company's sales roles from POSSIBLE to LIKELY.

## What was verified, and what wasn't

- **Verified:**
  - 41 backend tests pass. They cover classifiers, scoring, ATS parsers, dedup, the claim checker, the style guard, the seed-data privacy split, and the full resume-to-application flow on a generated sample resume (set `NODERZE_TEST_RESUME` to run it on your own).
  - The Next.js production build passes type checking.
  - A live server smoke test passed, including token auth and background workflows.
  - The tailored .docx was rendered and checked visually.
- **Not verified live:**
  - Calls to Greenhouse, Lever, Ashby, Workday and Amazon. The build environment's network allowlist blocked them. The parsers are tested against fixtures in each API's documented format, and the fetcher logs any failure and moves on.
  - Your first **Find new jobs** run is the real test. If a company's board isn't found, set its board on the company page under Job board.
  - **Claude-powered paths** need your key. Everything has a deterministic fallback, and those fallbacks are what the tests exercise.

## Troubleshooting

| Symptom | Fix |
|---|---|
| UI shows "Missing or wrong X-Agent-Token" | The token in `frontend/.env.local` must match `backend/.env`. Restart `npm run dev` after editing. |
| "No search results" in run logs | Add `ANTHROPIC_API_KEY` (with web search enabled in the Console) or a Tavily, Brave or Serper key. |
| A company shows 0 roles after a scan | Open the company, go to the Job board tab, and set the ATS type and token from its careers page URL. |
| Scores look wrong after editing your profile | Settings saves trigger a rescore. You can also call `POST /api/jobs/rescore`. |

## Tests

```bash
cd backend && pytest -q
```
