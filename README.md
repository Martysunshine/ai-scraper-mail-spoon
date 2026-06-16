# Infinity Outreach Agent

An **autonomous outreach engine**. Point it at the world and it will, on its own:

1. **Discover** religious organizations (churches, synagogues, temples, mandirs, Buddhist
   & Taoist centres) city by city, region by region.
2. **Find** each organization's public contact email from its website.
3. **Build** a bilingual email — the recipient's native language **+** English — from
   **your own fixed template**, personalizing only the greeting (`Dear {{org name}},`).
4. **Send** it through your Gmail/Workspace mailbox, within a daily limit, one at a time.

It runs continuously for hours, days, or weeks, tracks everything in a local database so it
**never contacts anyone twice**, and stops/resumes cleanly. No AI writes the emails — you
supply them. One command runs the whole thing.


---

## How it works

```
   ┌──────────────── one command: `cli auto` ────────────────┐
   │                                                          │
   ▼                                                          │
 seed region → discover → enrich → draft → send ──────────────┘  (loops, region by region)
 (Europe →      (Google     (public  (your      (Gmail,
  N.America →    primary,    website  template,   within the
  Asia → …)      OSM free    email)   bilingual)  daily limit)
                 fallback)
```

- **Google Places is the primary source** (best coverage, websites, phone numbers). Once the
  daily Google budget (`PLACES_DAILY_LIMIT`) is reached, discovery continues for free on
  **OpenStreetMap** (no key) — so it never stops, and runs free after the cap. Leave the key
  blank to run 100% free on OSM only.
- **No double-contact.** Every city and organization is tracked in `data/outreach.sqlite`.
- **Dry-run first.** Ships in `EMAIL_MODE=draft`: it discovers and drafts but **sends nothing**
  until you decide to go live.
- **You own the email.** Your finished HTML lives in `email_templates/` — one file per language.

**Religions targeted:** Christianity · Judaism · Hinduism · Buddhism · Taoism
**Regions, worked in order:** Europe → North America → Asia → South America → Oceania → Africa

---

# Part A · Quick setup (a person, ~10 minutes)

### 1 · Get the code and install

```powershell
git clone https://github.com/Martysunshine/ai-scraper-mail-spoon.git
cd ai-scraper-mail-spoon
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

> The install includes `truststore`, which makes Python trust your computer's certificate
> store. On Windows with antivirus/proxy HTTPS scanning this is required, or every web
> request would fail with a certificate error.

### 2 · Configure `.env`

```powershell
copy .env.example .env
```

Open `.env` in VS Code and fill in the top block — that's your whole configuration:

| Setting | What to put |
|---|---|
| `SMTP_USER` / `SMTP_PASSWORD` | Your Gmail address + a **Gmail App Password** (Google Account → Security → 2-Step Verification → App passwords). **Not** your normal password. |
| `SENDER_NAME` / `SENDER_EMAIL` | Your name and from-address |
| `EMAIL_SUBJECT` | The subject line (`{{org_name}}` allowed) |
| `EMAIL_MODE` | Leave as `draft` for now (dry run — sends nothing) |
| `DAILY_SEND_LIMIT` | Stay under your Gmail cap (free ≈ 500/day); ramp up slowly |
| `GOOGLE_PLACES_API_KEY` | **Primary** discovery source. Leave blank to run **free, OSM-only** |

### 3 · Drop in your email

The emails live in **`email_templates/`** and ship ready to use — 26 languages, all built
from one source file, **`outreach_languages.md`** (one section per language). To use your own
copy, edit that file and regenerate the HTML:

```powershell
.\.venv\Scripts\python.exe tools\build_email_templates.py
```

- `{{org_name}}` is the only per-org placeholder — it becomes the greeting, e.g. `Dear First Baptist Church,`.
- The **signature** (Kind Regards + banner + buttons) lives in `email_templates/signature.html`
  and is appended to every email automatically.
- The **opt-out / unsubscribe** line is added automatically at the bottom — you don't manage it.
- A recipient gets its **native language + English**; any language without a file falls back to English.

Details in `email_templates/README.md`.

### 4 · Run it

```powershell
.\.venv\Scripts\python.exe -m infinity_outreach.cli auto
```

It seeds Europe, discovers organizations, finds emails, and prepares drafts — and because
you're in `draft` mode, **sends nothing yet**. Watch the live status line, or open the
read-only monitor in a second terminal:

```powershell
.\.venv\Scripts\python.exe -m infinity_outreach.cli web --port 8080
```
→ <http://127.0.0.1:8080> (progress bars, funnel, send counts, API budget — no buttons).

### 5 · Go live

1. Open the **Drafts** tab and read a few — they render exactly as they'll send.
2. When happy, set `EMAIL_MODE=auto_send` in `.env`.
3. Re-run `cli auto`. It now sends within your daily limit and keeps going until every
   organization in your selected regions has been contacted.

### Stop / resume / report

```powershell
.\.venv\Scripts\python.exe -m infinity_outreach.cli stop   # graceful stop (or Ctrl-C)
.\.venv\Scripts\python.exe -m infinity_outreach.cli auto   # resume — never re-contacts anyone
```
The full table of who was found and contacted is always at **`data\exports\organizations.csv`**.

---

# Part B · Running it with a local AI agent (OpenClaw + Ollama)

This engine is designed to be driven by an autonomous agent so **you never touch it** after
setup. Here the AI agent is the **brain** (it decides, monitors, reports) and this engine is the
**hands** (it does the discovering and sending). The agent's reasoning runs **locally** on
Ollama — no cloud, no API bills.

```
   ┌─────────────────────────┐        runs commands          ┌──────────────────────────┐
   │  OpenClaw agent          │  ───────────────────────────▶ │  Infinity Outreach engine │
   │  (reasoning on Ollama,   │   cli auto / stop / export    │  discover→enrich→draft→send│
   │   a local model)         │  ◀─────────────────────────── │  data/outreach.sqlite      │
   └─────────────────────────┘    reads /api/status + CSV     └──────────────────────────┘
```

> **Note:** the emails themselves are **not** written by the model — they come from your
> template files. Ollama only powers the agent's *decisions* (when to start, monitor, flip to
> live, stop, and summarize). This keeps the outgoing emails exactly as you wrote them.

### 1 · Install Ollama and pull a model

```powershell
# Download & install from https://ollama.com, then pull a local model:
ollama pull hermes3        # or llama3.1, qwen2.5, etc.
# Ollama then runs in the background at http://127.0.0.1:11434
```

### 2 · Install OpenClaw and point it at Ollama

Install your local agent (OpenClaw) per its own instructions, and configure it to use the
local Ollama endpoint, e.g.:

```
Model provider : ollama (OpenAI-compatible)
Base URL       : http://127.0.0.1:11434/v1
Model          : hermes3
```

### 3 · Prepare the engine once

Do **Part A steps 1–3** above on the same machine (clone, install, `.env`, drop your email
into `email_templates/`). Leave `EMAIL_MODE=draft` for the first autonomous run.

### 4 · Give the agent its mission

Paste this as the agent's task / system brief:

```text
You operate the Infinity Outreach engine in this repository. Your goal: contact every
targeted religious organization exactly once, autonomously, until none remain.

Working directory: <path to ai-scraper-mail-spoon>
Python:            .\.venv\Scripts\python.exe

Do this:
1. Start the engine:   python -m infinity_outreach.cli auto
   (it runs continuously; it resumes itself if restarted — never re-contacts anyone.)
2. Every ~10 minutes, read GET http://127.0.0.1:8080/api/status and note:
   region_progress, sent_today, places_calls_remaining, auto_last_status.
   (Run the monitor once with: python -m infinity_outreach.cli web --port 8080)
3. While EMAIL_MODE=draft, inspect a few drafts (the /drafts page). If the emails look
   correct, tell the operator they can set EMAIL_MODE=auto_send to go live. Do NOT change
   EMAIL_MODE yourself unless the operator authorized it.
4. If the loop reports an error or a misconfiguration, STOP and report it. Never work around
   a safety check (suppression list, daily limit, draft mode).
5. On request, produce the standing report: python -m infinity_outreach.cli export-orgs
   then read data/exports/organizations.csv and summarize who was found and contacted.
6. To stop cleanly: python -m infinity_outreach.cli stop

Follow prompts/agent_rules.md at all times.
```

### 5 · What the agent relies on

| Need | How |
|---|---|
| Run everything | `python -m infinity_outreach.cli auto` (idempotent, resumable, self-paced) |
| Live status (JSON) | `GET http://127.0.0.1:8080/api/status` |
| The deliverable table | `data/exports/organizations.csv` (refreshed every cycle) |
| Graceful stop | `python -m infinity_outreach.cli stop` (or SIGINT/SIGTERM) |
| Operating rules | `prompts/agent_rules.md` — public data only, no Maps scraping/captcha bypass, always honour the suppression list, never send in draft mode or past the daily limit |

Because all state lives in `data/outreach.sqlite`, the agent can kill and restart the loop at
any time and it picks up exactly where it left off.

---

## Folder structure

```
.env                              ← your config + secrets (never committed)
email_templates/
  outreach_languages.md           ← SOURCE: every language's email text
  outreach_<code>.html            ← generated from the markdown (26 languages)
  signature.html                  ← the signature appended to every email
  README.md                       ← how the templates + signature work
tools/build_email_templates.py    ← regenerates the HTML from the markdown
official_languages_by_country.csv ← country / language / city source data

src/infinity_outreach/
  autorun.py        ← the autonomous loop (`cli auto`)
  campaign.py       ← discover → enrich → draft → send orchestration
  discovery.py      ← Google Places (primary) discovery
  osm_discovery.py  ← OpenStreetMap (free fallback) discovery
  website_enricher.py ← public website email extraction
  email_writer.py   ← assembles the email from your template files
  email_sender.py   ← Gmail/SMTP sending
  reporting.py      ← writes data/exports/organizations.csv
  compliance.py     ← suppression list + daily budget
  models.py         ← database schema
  constants.py      ← religions + region order + language map
  cli.py            ← all CLI commands

web/                ← read-only monitoring panel (FastAPI)
data/
  outreach.sqlite   ← the database (auto-created)
  exports/organizations.csv ← the deliverable table
prompts/agent_rules.md        ← rules an autonomous agent must follow
```

---

## CLI reference

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m infinity_outreach.cli auto          # run autonomously until done (the main command)
& $py -m infinity_outreach.cli stop          # ask a running auto loop to stop gracefully
& $py -m infinity_outreach.cli send-test you@example.com   # send ONE real test email (template + signature)
& $py -m infinity_outreach.cli export-orgs   # write the organizations.csv report now
& $py -m infinity_outreach.cli web --port 8080   # read-only monitoring panel
& $py -m infinity_outreach.cli stats         # quick status summary
& $py -m infinity_outreach.cli suppress bad@addr.com   # block an address
```

Individual stages (`discover`, `enrich`, `draft`, `send`) are still available for manual/debug
use, but `auto` runs them all for you.

---

## Safety & compliance

- **Draft-first by default** — nothing is sent until you set `EMAIL_MODE=auto_send`.
- **Suppression list is always honoured** — opt-out replies are auto-detected (IMAP) and that
  address is never contacted again.
- **Daily limit enforced** — the loop stops sending when the cap is hit and resumes the next day.
- **Public data only** — organizational contact emails from public pages; no Maps scraping, no
  captcha/login bypass. See `prompts/agent_rules.md`.

Created by martin.matysek
