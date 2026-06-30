# ◆ Open Tickets Outside SLA — Team Leaderboard

A wall-mountable leaderboard for the office TV. It mirrors the HubSpot report
**1 (a) Open Tickets (Outside SLA)** and ranks the processing team **most open
breaches on top**, so the biggest backlogs are front and centre. People sitting at
zero are listed as "All clear" at the foot of the board.

Built to match the **mpmg-tracker** stack: a Streamlit app + Postgres + a GitHub
Action that syncs every 15 minutes during office hours, deployed on Streamlit
Community Cloud behind Google sign-on (the same "one login, open the URL" model).

```
streamlit_app.py    # the TV board (Optimize Advisor Portal styling)
db.py               # SQLite locally / Postgres in prod; roster + snapshot schema
hubspot_client.py   # reproduces the report's 9 filters against the CRM API
jobs/sync.py        # writes a snapshot; run by the Action and by hand
.github/workflows/sync.yml   # the every-15-min cron, gated to ET office hours
```

---

## Run it locally (1 minute, no token needed)

```bash
cd sla-leaderboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Opens at `http://localhost:8501`. With no database configured it uses a local
SQLite file and **auto-seeds the real numbers scraped from the report on
2026-06-30**, so the board renders immediately. For full-screen TV mode press
`F11` (and Chrome's "fullscreen" / kiosk).

---

## Wire up the live HubSpot sync

The board shows demo numbers until the sync runs against HubSpot. You need a
**Private App token** (you create it — I don't handle credentials):

1. HubSpot → **Settings → Integrations → Private Apps → Create a private app**.
2. Name it e.g. *SLA Leaderboard (read-only)*. Under **Scopes** add:
   `crm.objects.tickets.read`, `crm.schemas.tickets.read`, `crm.objects.owners.read`.
3. Create it and copy the token (`pat-na1-…`).

Test it locally, comparing against the report's current total:

```bash
export HUBSPOT_TOKEN="pat-na1-…"
export EXPECTED_TOTAL=460          # the report's current "Number of tickets"
python jobs/sync.py --dry-run      # prints counts + a calibration check, writes nothing
```

If the total is off, the residual filters in `hubspot_client.py` (the formula
field "Ticket Owner Check", the "test"/"custodian" text excludes) need a small
tweak — that's the one calibration pass. Once it matches, drop `--dry-run` to
write a snapshot.

---

## Deploy so the TV can open it (same as mpmg-tracker)

**1. Postgres** — create a free database at [neon.tech](https://neon.tech); copy the
connection string.

**2. Push to GitHub**
```bash
git add . && git commit -m "SLA leaderboard"
gh repo create sla-leaderboard --private --source=. --push
```

**3. Streamlit Cloud** — at [share.streamlit.io](https://share.streamlit.io): New app →
this repo → `streamlit_app.py`. In **Settings → Secrets** add `HUBSPOT_TOKEN`
(and `DATABASE_URL` only if you use the DB/cron path instead of live queries). In
**Settings → Sharing**, restrict viewers to the Optimize Google Workspace so it's
one-click SSO. Open that URL on the TV and leave it; it refreshes itself.

**4. Turn on the sync** — in the GitHub repo, **Settings → Secrets and variables →
Actions** add `DATABASE_URL` (same string) and `HUBSPOT_TOKEN`. The workflow runs
every 15 min, 08:30–17:30 ET, Mon–Fri. Trigger it once from the **Actions** tab to
confirm.

---

## Notes

- **Most on top.** Highest breach count leads; the top 3 are accented. Ties share a
  rank; zero-breach people sit at the bottom and are also summarised in the "All
  clear" footer. The roster is the report's 26-person "Assigned to" list, so people
  at zero still show (the raw report omits them).
- **Logo.** Drop the official asset at `assets/logo.svg` (or `.png`) and the board
  uses it automatically; otherwise it renders a built-in compass mark + wordmark.
- **Fonts.** The app loads Lora (serif) + Montserrat (sans) to match the portal.
- **Schedule drift.** GitHub's scheduled runs can be delayed a few minutes under
  load and occasionally skipped — fine for a 15-minute board, but it's not a
  hard guarantee. The board shows its last sync time so staleness is visible.
- **Office-hours gate** lives in `jobs/sync.py` (`America/Toronto`, 08:30–17:30,
  weekdays); the broad UTC cron just makes sure a fire is available across DST.
