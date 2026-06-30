"""Tickets Outside SLA — team leaderboard, styled for a wide, short office TV.

Ranks the processing team most-breaches-on-top in the exact Optimize Advisor
Portal look. People with zero open breaches are dropped from the table (just
summarised in the footer). Auto-refreshes so the TV stays current untouched.

Data source, in priority order:
  1. Live HubSpot query (cached 15 min) — when HUBSPOT_TOKEN is set. Simplest deploy.
  2. The database snapshot written by jobs/sync.py — if you run the cron instead.
  3. A demo seed of the real scraped numbers — so it always renders.

If a real logo file exists at assets/logo.(svg|png) it's used; else a built-in
compass mark + wordmark is drawn.
"""
import base64
import datetime as dt
import os
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import db

TZ = ZoneInfo("America/Toronto")
HERE = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="Tickets Outside SLA — Leaderboard",
                   page_icon="◆", layout="wide",
                   initial_sidebar_state="collapsed")

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60_000, key="tick")
except Exception:
    pass

# --- Optimize Advisor Portal palette (sampled from the portal) -------------
NAVY = "#2B3A4E"
NAVY_LINE = "rgba(255,255,255,.07)"
ORANGE = "#C97B30"
TEAL = "#5E8A7E"
INK = "#FFFFFF"
MUTED = "#9CB0C2"


def _token():
    tok = os.environ.get("HUBSPOT_TOKEN")
    if not tok:
        try:
            tok = st.secrets.get("HUBSPOT_TOKEN")
        except Exception:
            tok = None
    return tok


@st.cache_data(ttl=900, show_spinner=False)
def _live_counts(_cache_key: str):
    """Query HubSpot at most once every 15 min. Returns (counts, fetched_at)."""
    from hubspot_client import HubSpot
    return HubSpot(token=_token()).fetch_breached(), dt.datetime.now(dt.timezone.utc)


def load_standings():
    """Return (df[person,tickets] desc, clean_count, captured_at, source)."""
    token = _token()
    if token:
        try:
            counts, fetched = _live_counts(token[-8:])
            df = pd.DataFrame(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])),
                              columns=["person", "tickets"])
            clean = sum(1 for p in db.ROSTER if counts.get(p, 0) == 0)
            return df, clean, fetched, "hubspot"
        except Exception as e:  # fall through to DB/demo if the API hiccups
            st.toast(f"HubSpot fetch failed, showing last snapshot: {e}", icon="⚠️")
    db.seed_demo_if_empty()
    df = db.latest_standings()
    clean = int((df["tickets"] == 0).sum())
    run = db.latest_run()
    captured, source = (run[0], run[2]) if run else (None, "demo")
    return df, clean, captured, source


def logo_markup() -> str:
    for ext, mime in (("svg", "image/svg+xml"), ("png", "image/png")):
        path = os.path.join(HERE, "assets", f"logo.{ext}")
        if os.path.exists(path):
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return f'<img class="logo-img" src="data:{mime};base64,{b64}" alt="Optimize Advisor Portal"/>'
    return f"""
    <div class="brand">
      <svg class="mark" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
        <rect x="5" y="5" width="110" height="110" rx="24" fill="none" stroke="{INK}" stroke-width="3"/>
        <circle cx="60" cy="60" r="40" fill="none" stroke="{INK}" stroke-width="2.5"/>
        <polygon points="60,18 67,60 60,102 53,60" fill="{INK}"/>
        <polygon points="18,60 60,53 102,60 60,67" fill="{INK}" opacity=".88"/>
        <polygon points="60,60 84,36 70,60 60,72" fill="{INK}" opacity=".55"/>
        <polygon points="60,60 36,36 60,50 72,60" fill="{INK}" opacity=".55"/>
        <polygon points="60,60 84,84 60,70 50,60" fill="{INK}" opacity=".55"/>
        <polygon points="60,60 36,84 50,60 60,50" fill="{INK}" opacity=".55"/>
        <circle cx="60" cy="60" r="5.5" fill="{NAVY}" stroke="{INK}" stroke-width="2.5"/>
      </svg>
      <div class="wm"><b>OPTIMIZE</b><span>Advisor Portal</span></div>
    </div>"""


CURVES = f"""
<svg class="curves" viewBox="0 0 1600 200" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M820 200 Q1060 40 1600 10" fill="none" stroke="{NAVY_LINE}" stroke-width="1.5"/>
  <path d="M1020 200 Q1220 60 1600 70" fill="none" stroke="{NAVY_LINE}" stroke-width="1.5"/>
  <path d="M1220 200 Q1360 90 1600 130" fill="none" stroke="{NAVY_LINE}" stroke-width="1.5"/>
</svg>"""

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Lora:wght@500;600;700&family=Montserrat:wght@500;600;700;800&display=swap');

#MainMenu, header, footer {{ visibility: hidden; }}
html, body, .stApp {{ background: {NAVY}; overflow: hidden; }}
.block-container {{ padding: 0; max-width: 100%; }}

.board {{ font-family:'Montserrat',sans-serif; color:{INK};
          height: 100vh; box-sizing: border-box;
          padding: 1.4rem 2.2rem 1.1rem; display:flex; flex-direction:column; }}

/* ---------- compact header (wide & short) ---------- */
.hero {{ position:relative; overflow:hidden; flex:0 0 auto;
         border-bottom:1px solid rgba(255,255,255,.12); padding-bottom:.9rem; }}
.curves {{ position:absolute; inset:0; width:100%; height:100%; z-index:0; pointer-events:none; }}
.hero-row {{ position:relative; z-index:1; display:flex; align-items:center; justify-content:space-between; gap:1.6rem; }}
.brand {{ display:flex; align-items:center; gap:.75rem; }}
.brand .mark {{ width:50px; height:50px; }} .logo-img {{ height:50px; width:auto; }}
.brand .wm b {{ font-family:'Lora',serif; font-size:1.4rem; letter-spacing:.04em; display:block; line-height:1; }}
.brand .wm span {{ font-size:.56rem; letter-spacing:.32em; text-transform:uppercase; color:{MUTED}; }}
.headline {{ text-align:center; }}
.headline .pip {{ width:34px; height:4px; background:{ORANGE}; border-radius:2px; margin:0 auto .4rem; }}
.headline h1 {{ font-family:'Lora',serif; font-weight:600; font-size:2.2rem; margin:0; line-height:1; }}
.headline .lbl {{ font-size:.62rem; letter-spacing:.3em; text-transform:uppercase; color:{MUTED}; margin-top:.35rem; font-weight:700; }}
.clock {{ text-align:right; min-width:180px; }}
.clock .t {{ font-family:'Lora',serif; font-size:1.6rem; line-height:1; }}
.clock .d {{ color:{MUTED}; font-size:.74rem; margin-top:.18rem; }}
.clock .upd {{ color:{ORANGE}; font-size:.68rem; margin-top:.35rem; }}

/* ---------- leaderboard: 3 short columns ---------- */
.rows {{ flex:1 1 auto; column-count:3; column-gap:1.5rem; margin-top:1.1rem; align-content:center; }}
.row {{ break-inside:avoid; display:flex; align-items:center; gap:.7rem;
        background:rgba(255,255,255,.05); border-radius:11px;
        padding:.6rem .95rem; margin-bottom:.6rem; border-left:3px solid transparent; }}
.row.top {{ border-left-color:{ORANGE}; background:rgba(201,123,48,.12); }}
.row .rank {{ flex:0 0 1.8rem; font-family:'Lora',serif; font-size:1.25rem; color:{MUTED}; text-align:right; }}
.row.top .rank {{ color:{ORANGE}; }}
.row .name {{ flex:1 1 auto; min-width:0; font-size:1.28rem; font-weight:600; letter-spacing:.01em;
              white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.row .bar {{ flex:0 0 30%; height:13px; border-radius:7px; background:rgba(255,255,255,.08); overflow:hidden; }}
.row .bar i {{ display:block; height:100%; border-radius:7px; }}
.row .n {{ flex:0 0 3.2rem; text-align:right; font-family:'Lora',serif; font-weight:700; font-size:1.6rem; }}

/* ---------- footer ---------- */
.foot {{ flex:0 0 auto; display:flex; justify-content:space-between; align-items:center;
         padding-top:.8rem; border-top:1px solid rgba(255,255,255,.12); color:{MUTED}; font-size:.84rem; }}
.foot b {{ color:{INK}; }}
.foot .big {{ font-family:'Lora',serif; color:{ORANGE}; font-size:1.5rem; vertical-align:-2px; }}
.foot .ok b {{ color:{TEAL}; }}
</style>
""", unsafe_allow_html=True)


def bar_color(n: int, mx: int) -> str:
    frac = (n / mx) if mx else 0
    if frac >= 0.45:
        return "#B85C2A"
    if frac >= 0.15:
        return ORANGE
    return "#D8A65E"


# --- data ------------------------------------------------------------------
df, clean, captured, source = load_standings()
df = df[df["tickets"] > 0].reset_index(drop=True)   # drop zeros from the table
now = dt.datetime.now(TZ)
total = int(df["tickets"].sum()) if not df.empty else 0
mx = int(df["tickets"].max()) if not df.empty else 0

updated_txt, source_txt = "—", ""
if captured is not None:
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=dt.timezone.utc)
    updated_txt = captured.astimezone(TZ).strftime("%-I:%M %p")
    source_txt = " · demo data" if source == "demo" else ""

# --- header ----------------------------------------------------------------
html = ['<div class="board">']
html.append(f"""
<div class="hero">
  {CURVES}
  <div class="hero-row">
    {logo_markup()}
    <div class="headline">
      <div class="pip"></div>
      <h1>Tickets Outside SLA</h1>
      <div class="lbl">Operations · Service Delivery</div>
    </div>
    <div class="clock">
      <div class="t">{now:%-I:%M %p}</div>
      <div class="d">{now:%A, %B %-d, %Y}</div>
      <div class="upd">Synced {updated_txt}{source_txt} · every 15 min</div>
    </div>
  </div>
</div>
""")

# --- ranked rows (most on top, zeros excluded) -----------------------------
html.append('<div class="rows">')
rank, last_n = 0, None
for i, r in df.iterrows():
    n = int(r["tickets"])
    if n != last_n:
        rank = i + 1
        last_n = n
    width = max((n / mx) * 100, 3) if mx else 0
    cls = "row top" if rank <= 3 else "row"
    html.append(f"""
    <div class="{cls}">
      <div class="rank">{rank}</div>
      <div class="name">{r['person']}</div>
      <div class="bar"><i style="width:{width:.0f}%;background:{bar_color(n, mx)}"></i></div>
      <div class="n">{n}</div>
    </div>""")
html.append('</div>')

# --- footer ----------------------------------------------------------------
html.append(f"""
<div class="foot">
  <div>Source: HubSpot · <b>{db.REPORT_NAME}</b></div>
  <div><span class="big">{total}</span> tickets outside SLA &nbsp;·&nbsp;
       <b>{len(df)}</b> with breaches &nbsp;·&nbsp;
       <span class="ok"><b>{clean}</b> all clear</span></div>
</div>""")
html.append('</div>')

# Strip leading whitespace from every line: Streamlit's markdown renderer treats
# any line indented 4+ spaces as a code block, which would print our HTML as text.
final_html = "\n".join(line.lstrip() for line in "\n".join(html).splitlines())
st.markdown(final_html, unsafe_allow_html=True)
