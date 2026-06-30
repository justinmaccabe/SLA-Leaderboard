"""Database layer for the SLA leaderboard.

Uses Postgres when DATABASE_URL is set (production / Streamlit Cloud), otherwise a
local SQLite file (`leaderboard.db`) so it runs with zero setup. Both the Streamlit
app and the GitHub Action sync job import from here, so this is the single source of
truth for the schema, the eligible roster, and read/write helpers.

Mirrors the structure of the mpmg-tracker `db.py`.
"""
from __future__ import annotations

import os
import time
import datetime as dt

import pandas as pd
from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, String, DateTime,
    Boolean, select, func,
)
from sqlalchemy.exc import OperationalError

# ---------------------------------------------------------------------------
# Eligible roster — the 26 people in the report's "Assigned to is any of" filter.
# A fewest-on-top leaderboard must show everyone who *could* have breached tickets,
# so people sitting at zero appear at the top as the "clean desk" leaders. The
# report itself only returns people with >=1 ticket, so we seed the full roster
# here and the sync left-joins counts onto it (missing = 0).
# ---------------------------------------------------------------------------
ROSTER = [
    "Aaron Kuruvilla", "Adam Goldband", "Ali Vahedi", "Andrew Kirkham",
    "Ardinela Hoxha", "Batuhan Karabay", "Christian Alvarez", "Ethan Golounov",
    "Gabriel Tan", "Hardeepika Ahluwalia", "Jay Suba", "Jeffrey Huang",
    "Jianna Mustafaj", "Marcus Jeong", "Mattias Farinaccia", "Michael Yang",
    "Milan Pandurevic", "Phil Kolanowski", "Rashi Tiwari", "Rohit Kapoor",
    "Ryan Connon", "Ryan Tam", "Sagar Parmar", "Shivani Shaurya",
    "Srijan Ahuja", "Stefan Tintor",
]

# Real standings scraped from the live report on 2026-06-30 (totals to 460).
# Used to seed a working demo before the live HubSpot token is wired up. Anyone
# in ROSTER not listed here is at 0.
DEMO_COUNTS = {
    "Milan Pandurevic": 166, "Ryan Tam": 165, "Stefan Tintor": 56,
    "Ardinela Hoxha": 22, "Rohit Kapoor": 10, "Hardeepika Ahluwalia": 8,
    "Ryan Connon": 6, "Gabriel Tan": 5, "Srijan Ahuja": 5,
    "Christian Alvarez": 4, "Rashi Tiwari": 3, "Aaron Kuruvilla": 3,
    "Shivani Shaurya": 3, "Marcus Jeong": 3, "Jay Suba": 1,
}

# Name of the HubSpot report this mirrors, shown on the board for provenance.
REPORT_NAME = "1 (a) Open Tickets (Outside SLA)"


def _database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:  # running inside Streamlit with a secret configured
            import streamlit as st
            url = st.secrets.get("DATABASE_URL")
        except Exception:
            url = None
    if not url:
        here = os.path.dirname(os.path.abspath(__file__))
        return f"sqlite:///{os.path.join(here, 'leaderboard.db')}"
    # SQLAlchemy wants postgresql+psycopg2:// ; accept the plain postgres:// form too
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


engine = create_engine(_database_url(), future=True)
metadata = MetaData()

# Every successful sync writes one run row + one snapshot row per roster member.
runs = Table(
    "runs", metadata,
    Column("captured_at", DateTime(timezone=True), primary_key=True),
    Column("total", Integer, nullable=False),     # total breached tickets (== report)
    Column("people", Integer, nullable=False),    # roster size at capture time
    Column("source", String, nullable=False),     # "hubspot" or "demo"
    Column("note", String),
)

snapshots = Table(
    "snapshots", metadata,
    Column("captured_at", DateTime(timezone=True), primary_key=True),
    Column("person", String, primary_key=True),
    Column("tickets", Integer, nullable=False, default=0),
)


def init_db():
    """Create tables, retrying so a cold (sleeping) Neon database wakes instead of
    crashing the first query."""
    for attempt in range(3):
        try:
            metadata.create_all(engine)
            return
        except OperationalError:
            if attempt == 2:
                raise
            time.sleep(2)


def write_snapshot(counts: dict, source: str, captured_at: dt.datetime | None = None,
                   note: str | None = None):
    """Record one capture: a `runs` row plus a `snapshots` row for every roster
    member (counts default to 0). `counts` maps person name -> ticket count."""
    captured_at = captured_at or dt.datetime.now(dt.timezone.utc)
    rows = [dict(captured_at=captured_at, person=p, tickets=int(counts.get(p, 0)))
            for p in ROSTER]
    # Include anyone returned by the source who isn't in the static roster, so a
    # newly-added processor still shows up rather than silently vanishing.
    for p, n in counts.items():
        if p not in ROSTER:
            rows.append(dict(captured_at=captured_at, person=p, tickets=int(n)))
    total = sum(int(n) for n in counts.values())
    with engine.begin() as conn:
        conn.execute(runs.insert().values(
            captured_at=captured_at, total=total, people=len(rows),
            source=source, note=note))
        conn.execute(snapshots.insert(), rows)
    return captured_at


def latest_run():
    """Return (captured_at, total, source) of the most recent run, or None."""
    with engine.begin() as conn:
        row = conn.execute(
            select(runs.c.captured_at, runs.c.total, runs.c.source)
            .order_by(runs.c.captured_at.desc()).limit(1)
        ).first()
    return tuple(row) if row else None


def latest_standings() -> pd.DataFrame:
    """The most recent snapshot as a DataFrame [person, tickets], sorted
    fewest-first (the leaderboard order). Empty frame if there is no data yet."""
    run = latest_run()
    if not run:
        return pd.DataFrame(columns=["person", "tickets"])
    captured_at = run[0]
    df = pd.read_sql(
        select(snapshots.c.person, snapshots.c.tickets)
        .where(snapshots.c.captured_at == captured_at),
        engine,
    )
    # fewest on top; ties broken alphabetically for a stable, fair order
    return df.sort_values(["tickets", "person"]).reset_index(drop=True)


def history(person: str | None = None) -> pd.DataFrame:
    """All snapshot rows over time (optionally for one person) for trend charts."""
    q = select(snapshots).order_by(snapshots.c.captured_at)
    if person:
        q = q.where(snapshots.c.person == person)
    return pd.read_sql(q, engine)


def seed_demo_if_empty():
    """If there is no data at all, write one snapshot from the scraped real numbers
    so the board renders immediately. No-op once any real sync has run."""
    init_db()
    if latest_run() is None:
        write_snapshot(DEMO_COUNTS, source="demo",
                       note="Seeded from live report scrape on 2026-06-30")
