# Infinity Outreach Agent

Automated outreach engine for discovering religious organizations worldwide, enriching their public contact data, drafting bilingual emails (native language + English), and sending them through your own Gmail/Workspace mailbox.

Managed entirely from a **local web panel** at `http://127.0.0.1:8000`.

Built by **martin.matysek**

---

## What it does

1. Reads a list of countries → cities → religions
2. Searches Google (Places API) for religious venues in each city: churches, synagogues, temples, mandirs, Buddhist centres, Taoist temples
3. Visits each organization's official website and extracts their public contact email
4. Drafts a bilingual outreach email (native language + English) using a local AI model (Ollama/Hermes running on your machine)
5. Sends the emails one by one through your Gmail/Google Workspace account with a configurable daily limit

**Religions supported:** Christianity · Judaism · Hinduism · Buddhism · Taoism

**All configuration happens in the browser.** You pick which religions, which countries, what the email says, how many to send per day, and whether to auto-send or review first.

---

## Requirements

- Windows 10/11
- Python 3.11 or newer → https://python.org/downloads
- Git → https://git-scm.com
- Ollama (local AI for writing emails) → https://ollama.com
- A Google Cloud account for the Places API key (free tier works)
- A Gmail or Google Workspace account for sending

---

## Step 1 — Clone the repo

```powershell
git clone https://github.com/Martysunshine/ai-scraper-mail-spoon.git
cd ai-scraper-mail-spoon
```

---

## Step 2 — Install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

---

## Step 3 — Configure your environment

Copy the example config file:

```powershell
copy .env.example .env
```

Open `.env` in any text editor and fill in these values:

```env
# --- Google Places API (for discovering organizations) ---
# Go to https://console.cloud.google.com
# Create a project → Enable "Places API" → Create an API key → paste it here
GOOGLE_PLACES_API_KEY=your_key_here

# --- Your sending mailbox (Gmail or Google Workspace) ---
# IMPORTANT: use an App Password, NOT your normal password
# Gmail → Google Account → Security → 2-Step Verification → App passwords
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your_app_password_here
SENDER_EMAIL=you@gmail.com
SENDER_NAME=Your Name

# --- Daily send limit ---
# Gmail free: max ~500/day. Google Workspace: max ~2000/day.
# Start low (50-100) and increase gradually to avoid spam flags.
DAILY_SEND_LIMIT=100

# --- Email mode ---
# draft      = generate drafts only, never send automatically
# review     = only send drafts you manually approve in the panel
# auto_send  = send new drafts automatically (use after you trust the output)
EMAIL_MODE=review
```

Leave everything else at the default.

---

## Step 4 — Install and start Ollama (local AI model)

Ollama runs the AI that writes the emails on your machine. No cloud, no API cost.

```powershell
# 1. Download and install Ollama from https://ollama.com
# 2. Pull the model (do this once):
ollama pull hermes3
# 3. Ollama runs automatically in the background after install.
```

To verify it works after filling in `.env`:

```powershell
.\.venv\Scripts\python.exe -m infinity_outreach.cli test-llm
```

You should see: `Local Ollama connection works.`

If Ollama is offline, the engine still works — it uses a template fallback and flags those drafts for review.

---

## Step 5 — Start the system

Double-click **`start.bat`** — or run in PowerShell:

```powershell
.\start.bat
```

Your browser will open automatically at **http://127.0.0.1:8000**

The terminal window stays open while the server runs. Close it to stop.

---

## Step 6 — Configure your campaign in the browser

Go to **Campaign Setup** (`/settings`):

| Setting | What to do |
|---|---|
| **Religions** | Tick the ones you want to target |
| **Countries** | Type to filter, tick the markets you want (language travels with each country) |
| **App name / pitch** | Describe Infinity Faith — the AI uses this to write the emails |
| **Sender name / email** | Your identity shown in the email |
| **Email mode** | Start with `review`, switch to `auto_send` once you trust the output |
| **Daily send limit** | Keep under your Gmail cap. Ramp up slowly. |
| **Languages** | Native + English both ticked = bilingual email |

Click **Save campaign**. Done. The engine picks it up automatically on every run.

---

## Step 7 — Run the pipeline

On the **Dashboard** (`/`), click the buttons in order:

| Button | What it does |
|---|---|
| **1 · Seed cities** | Loads all cities for your selected countries into the database |
| **2 · Discover** | Searches Google Places for religious venues in each city |
| **3 · Enrich emails** | Visits each org's website and finds their public contact email |
| **4 · Draft** | Writes bilingual outreach emails using your local AI |
| **5 · Send** | Sends approved drafts through your mailbox (asks for confirmation first) |
| **Run all** | Runs steps 1–4 in one click (no send) |

Each step runs in the background. Refresh the page to see updated counts and the task log at the bottom.

---

## Step 8 — Review and approve drafts

Go to **Drafts** (`/drafts`):

- Read the full email for each organization (bilingual body shown)
- Click **Approve** to queue it for sending
- Click **Reject** to skip it
- Click **Suppress** to permanently block that email address (opt-out list)

Once you have approved drafts, go back to Dashboard and click **5 · Send**.

---

## How the sending works

- Emails go out **one by one** with a delay between each (looks human, avoids spam flags)
- The daily limit is enforced — it stops automatically when reached
- Every send is logged under **Logs** (`/logs`)
- If someone replies "unsubscribe" / "stop" / "remove me", the system can auto-detect it and block their address (IMAP scanner, configure `IMAP_*` in `.env` to enable)

---

## Folder structure

```
start.bat                        ← double-click to run everything
.env                             ← your secrets (never committed to git)
.env.example                     ← template for .env
official_languages_by_country.csv ← country/language/city source data

src/infinity_outreach/           ← the engine
  cli.py                         ← all CLI commands
  campaign.py                    ← discover → enrich → draft → send pipeline
  discovery.py                   ← Google Places search
  website_enricher.py            ← public website email extraction
  email_writer.py                ← bilingual draft generation (Ollama)
  email_sender.py                ← Gmail/SMTP sending
  compliance.py                  ← suppression list + daily budget
  models.py                      ← database schema
  constants.py                   ← religion taxonomy + language map

web/                             ← local control panel (FastAPI)
  app.py
  templates/                     ← HTML pages
  static/                        ← CSS + JS

data/
  outreach.sqlite                ← the database (auto-created)
  sample_organizations.csv       ← example orgs for testing

prompts/
  write_outreach_email.md        ← the prompt the AI uses to write emails
  agent_rules.md                 ← operating rules for autonomous agents
```

---

## Running without a Places API key

If you don't have a Google Places API key yet, you can skip discovery and import organizations manually from a CSV:

```powershell
.\.venv\Scripts\python.exe -m infinity_outreach.cli import-orgs data\sample_organizations.csv
```

The CSV format: `name, city, country, category, religion_guess, address, website, phone, source, source_id, notes`

---

## Useful CLI commands (optional)

All pipeline steps can also be run from the terminal instead of the browser:

```powershell
.\.venv\Scripts\python.exe -m infinity_outreach.cli stats          # quick status overview
.\.venv\Scripts\python.exe -m infinity_outreach.cli list-drafts    # list all drafts
.\.venv\Scripts\python.exe -m infinity_outreach.cli approve-draft 5
.\.venv\Scripts\python.exe -m infinity_outreach.cli suppress bad@address.com
.\.venv\Scripts\python.exe -m infinity_outreach.cli export-drafts  # export to CSV
.\.venv\Scripts\python.exe -m infinity_outreach.cli run --send     # full pipeline + send
```

---

## For AI agents (Hermes / OpenClaw)

To drive this from an autonomous agent on a sandboxed machine:

1. Clone the repo, install deps, configure `.env`, pull the Ollama model
2. Run `start.bat` once to boot the panel and init the database
3. Have the agent call the pipeline command in a loop:
   ```powershell
   .\.venv\Scripts\python.exe -m infinity_outreach.cli run --send
   ```
4. The agent can read campaign state and send counts via the JSON API:
   ```
   GET http://127.0.0.1:8000/api/status
   ```
5. Campaign config can be changed any time through the panel at port 8000 — the engine picks it up on the next run

Agent operating rules: see `prompts/agent_rules.md`
