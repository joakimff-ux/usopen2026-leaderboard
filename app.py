from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from supabase import create_client

from lib import datagolf_sync
from lib.daily_report import TONES, generate_daily_report

DEFAULT_FILE = Path(__file__).parent / "data" / "US Open 2026 - Resultater.xlsx"
DAYS = ["Dag 1", "Dag 2", "Dag 3", "Dag 4"]
ROUNDS = [1, 2, 3, 4]
PLAYERS_PER_TEAM = 7
COUNTING_SCORES = 5
DROPPED_SCORES = PLAYERS_PER_TEAM - COUNTING_SCORES
MAX_POST_CUT_SWAPS = 3
PRE_CUT_FROM, PRE_CUT_TO = 1, 2
POST_CUT_FROM, POST_CUT_TO = 3, 4
ROSTER_LABELS = {
    1: "Originalt lag",
    2: "Originalt lag",
    3: "Etter bytter",
    4: "Etter bytter",
}

st.set_page_config(page_title="US Open 2026 - kuppongen", page_icon="⛳", layout="wide")

st.markdown('''
<style>
.stApp {background: radial-gradient(circle at top left, rgba(183,242,100,.22), transparent 25rem), linear-gradient(135deg,#f8f6e8,#e9f4df 50%,#d5ead3);}
.hero {padding:2rem 2.2rem;border-radius:28px;background:linear-gradient(120deg,#0b3d2e,#0f6b3d);color:white;box-shadow:0 18px 45px rgba(11,61,46,.22);margin-bottom:1.3rem;}
.hero h1 {font-size:clamp(2.2rem,5vw,4.2rem);margin:0;letter-spacing:-.05em;}
.hero p {font-size:1.05rem;color:#eafbd4;margin:.5rem 0 0 0;}
.pill {display:inline-block;margin:.9rem .5rem 0 0;padding:.45rem .75rem;border-radius:999px;background:rgba(183,242,100,.16);border:1px solid rgba(183,242,100,.38);font-weight:800;}
.card {padding:1rem 1.2rem;border-radius:22px;background:rgba(255,255,255,.74);border:1px solid rgba(11,61,46,.11);box-shadow:0 14px 35px rgba(20,70,40,.08);margin-bottom:1rem;}
[data-testid="stMetric"] {background:rgba(255,255,255,.78);border:1px solid rgba(11,61,46,.11);padding:1rem;border-radius:18px;}
.stButton button {border-radius:999px;background:linear-gradient(90deg,#0b3d2e,#0f6b3d)!important;color:white!important;font-weight:800;border:0;}
</style>
''', unsafe_allow_html=True)


def get_secret(name: str, default: str = "") -> str:
    """Read Streamlit secrets robustly. Accepts exact key names only."""
    try:
        value = st.secrets.get(name, default)
        return str(value).strip() if value is not None else default
    except Exception:
        return default

def get_any_secret(names: list[str], default: str = "") -> str:
    for name in names:
        value = get_secret(name, "")
        if value:
            return value
    return default


@st.cache_resource(show_spinner=False)
def supabase_client():
    url = get_secret("SUPABASE_URL")
    key = get_any_secret(["SUPABASE_ANON_KEY", "SUPABASE_KEY", "sb_publishable_key"])
    if not url or not key:
        return None
    return create_client(url, key)


sb = supabase_client()


def require_db():
    if sb is None:
        st.error("Supabase er ikke konfigurert. Legg SUPABASE_URL og SUPABASE_ANON_KEY i .streamlit/secrets.toml.")
        st.stop()


def fetch_table(name: str) -> pd.DataFrame:
    require_db()
    res = sb.table(name).select("*").execute()
    return pd.DataFrame(res.data or [])


def fetch_all() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    teams = fetch_table("teams")
    players = fetch_table("players")
    links = ensure_post_cut_rosters(fetch_table("team_players"))
    scores = fetch_table("scores")
    return teams, players, links, scores


def links_have_round_ranges(links: pd.DataFrame) -> bool:
    return (
        not links.empty
        and "active_from_round" in links.columns
        and "active_to_round" in links.columns
    )


def roster_period_for_round(round_no: int) -> tuple[int, int]:
    if round_no <= 2:
        return PRE_CUT_FROM, PRE_CUT_TO
    return POST_CUT_FROM, POST_CUT_TO


def filter_team_roster(
    links: pd.DataFrame,
    team_id: int,
    active_from_round: int,
    active_to_round: int,
) -> pd.DataFrame:
    if links.empty:
        return links
    if links_have_round_ranges(links):
        return links[
            (links.team_id.astype(int) == team_id)
            & (links.active_from_round.astype(int) == active_from_round)
            & (links.active_to_round.astype(int) == active_to_round)
        ]
    return links[links.team_id.astype(int) == team_id]


def get_team_player_ids(
    links: pd.DataFrame,
    team_id: int,
    round_no: int,
) -> set[int]:
    active_from, active_to = roster_period_for_round(round_no)
    team_links = filter_team_roster(links, team_id, active_from, active_to)
    if team_links.empty:
        return set()
    return set(team_links.player_id.astype(int).tolist())


def count_post_cut_swaps(original_ids: set[int], post_cut_ids: set[int]) -> int:
    return len(original_ids - post_cut_ids)


def describe_post_cut_swaps(
    original_ids: set[int],
    post_cut_ids: set[int],
    players: pd.DataFrame,
) -> tuple[int, list[str], list[str]]:
    out_ids = original_ids - post_cut_ids
    in_ids = post_cut_ids - original_ids
    out_names = players[players.id.astype(int).isin(out_ids)].sort_values("name")["name"].tolist()
    in_names = players[players.id.astype(int).isin(in_ids)].sort_values("name")["name"].tolist()
    return len(out_ids), out_names, in_names


def build_post_cut_swaps_display(
    teams: pd.DataFrame,
    players: pd.DataFrame,
    links: pd.DataFrame,
    leaderboard: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Build swap summary rows sorted by leaderboard position."""
    if not links_have_round_ranges(links) or teams.empty or players.empty:
        return []

    ranking = {
        row["Lag"]: int(row["Plass"])
        for _, row in leaderboard.iterrows()
    } if not leaderboard.empty else {}

    rows: list[dict[str, Any]] = []
    for _, team in teams.iterrows():
        team_id = int(team.id)
        team_name = team["name"]
        original_ids = get_team_player_ids(links, team_id, 1)
        post_cut_ids = get_team_player_ids(links, team_id, 3)
        swap_count, out_names, in_names = describe_post_cut_swaps(
            original_ids,
            post_cut_ids,
            players,
        )
        if swap_count == 0:
            continue
        rows.append(
            {
                "Plass": ranking.get(team_name, 9999),
                "Lag": team_name,
                "out_names": out_names,
                "in_names": in_names,
                "swap_count": swap_count,
            }
        )

    return sorted(rows, key=lambda row: row["Plass"])


def swap_rows_to_dataframe(swap_rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Lag": row["Lag"],
                "Ut": ", ".join(row["out_names"]),
                "Inn": ", ".join(row["in_names"]),
                "Antall bytter": f"{row['swap_count']}/{MAX_POST_CUT_SWAPS}",
            }
            for row in swap_rows
        ]
    )


def render_post_cut_swaps_section(
    teams: pd.DataFrame,
    players: pd.DataFrame,
    links: pd.DataFrame,
    leaderboard: pd.DataFrame,
) -> None:
    st.subheader("Bytter etter dag 2")
    swap_rows = build_post_cut_swaps_display(teams, players, links, leaderboard)
    if not swap_rows:
        st.info("Ingen lag har gjort bytter ennå.")
        return

    st.dataframe(
        swap_rows_to_dataframe(swap_rows),
        width="stretch",
        hide_index=True,
    )


def prepare_laguttak_roster_state(
    team_id: int,
    original_names: list[str],
    post_cut_names: list[str],
    *,
    force_reload: bool = False,
) -> tuple[str, str]:
    """Initialize roster widget state before multiselect widgets are created."""
    prev_team_id = st.session_state.get("laguttak_team_id")
    pre_key = f"original_roster_{team_id}"
    post_key = f"post_cut_roster_{team_id}"
    team_changed = prev_team_id != team_id

    if team_changed:
        if prev_team_id is not None:
            for stale_key in (
                f"original_roster_{prev_team_id}",
                f"post_cut_roster_{prev_team_id}",
                f"legacy_roster_{prev_team_id}",
            ):
                st.session_state.pop(stale_key, None)
        st.session_state.laguttak_team_id = team_id

    if team_changed or force_reload or pre_key not in st.session_state:
        st.session_state[pre_key] = original_names
    if team_changed or force_reload or post_key not in st.session_state:
        st.session_state[post_key] = post_cut_names

    return pre_key, post_key


def teams_missing_post_cut_roster(links: pd.DataFrame) -> set[int]:
    """Teams that have a pre-cut roster but no Dag 3-4 roster yet."""
    if not links_have_round_ranges(links) or links.empty:
        return set()

    pre_cut_teams = set(
        links[
            (links.active_from_round.astype(int) == PRE_CUT_FROM)
            & (links.active_to_round.astype(int) == PRE_CUT_TO)
        ].team_id.astype(int).tolist()
    )
    post_cut_teams = set(
        links[
            (links.active_from_round.astype(int) == POST_CUT_FROM)
            & (links.active_to_round.astype(int) == POST_CUT_TO)
        ].team_id.astype(int).tolist()
    )
    return pre_cut_teams - post_cut_teams


def build_post_cut_seed_rows(links: pd.DataFrame) -> list[dict[str, int]]:
    """Copy pre-cut rosters only for teams without any saved post-cut roster."""
    if not links_have_round_ranges(links) or links.empty:
        return []

    missing_teams = teams_missing_post_cut_roster(links)
    if not missing_teams:
        return []

    pre_cut = links[
        (links.active_from_round.astype(int) == PRE_CUT_FROM)
        & (links.active_to_round.astype(int) == PRE_CUT_TO)
    ]
    return [
        {
            "team_id": int(row.team_id),
            "player_id": int(row.player_id),
            "active_from_round": POST_CUT_FROM,
            "active_to_round": POST_CUT_TO,
        }
        for _, row in pre_cut.iterrows()
        if int(row.team_id) in missing_teams
    ]


def ensure_post_cut_rosters(links: pd.DataFrame) -> pd.DataFrame:
    """Seed Dag 3-4 rosters only when a team has no post-cut roster saved yet."""
    inserts = build_post_cut_seed_rows(links)
    if not inserts:
        return links

    sb.table("team_players").upsert(
        inserts,
        on_conflict="team_id,player_id,active_from_round",
    ).execute()
    return fetch_table("team_players")


def save_team_roster(
    team_id: int,
    player_ids: list[int],
    active_from_round: int,
    active_to_round: int,
) -> None:
    sb.table("team_players").delete().eq("team_id", team_id).eq(
        "active_from_round", active_from_round
    ).eq("active_to_round", active_to_round).execute()
    if player_ids:
        sb.table("team_players").insert(
            [
                {
                    "team_id": team_id,
                    "player_id": pid,
                    "active_from_round": active_from_round,
                    "active_to_round": active_to_round,
                }
                for pid in player_ids
            ]
        ).execute()


def clear_cache():
    st.cache_data.clear()


AUTO_SYNC_INTERVAL_MS = 300_000


def init_sync_state() -> None:
    if "auto_sync_enabled" not in st.session_state:
        st.session_state.auto_sync_enabled = False
    if "last_datagolf_sync_attempt_at" not in st.session_state:
        st.session_state.last_datagolf_sync_attempt_at = None
    if "datagolf_sync_status" not in st.session_state:
        st.session_state.datagolf_sync_status = None
    if "daily_report_draft" not in st.session_state:
        st.session_state.daily_report_draft = ""
    if "daily_report_title" not in st.session_state:
        st.session_state.daily_report_title = ""


def get_sync_secrets() -> dict[str, str]:
    return {
        "SUPABASE_URL": get_secret("SUPABASE_URL"),
        "SUPABASE_ANON_KEY": get_any_secret(["SUPABASE_ANON_KEY", "SUPABASE_KEY", "sb_publishable_key"]),
        "DATA_GOLF_API_KEY": get_secret("DATA_GOLF_API_KEY"),
    }


def format_sync_timestamp(value: datetime | None) -> str:
    if value is None:
        return "Aldri"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def perform_live_sync(use_backoff: bool = True) -> datagolf_sync.SyncResult:
    result = datagolf_sync.execute_sync(sb, get_sync_secrets(), use_backoff=use_backoff)
    st.session_state.datagolf_sync_status = result
    st.session_state.last_datagolf_sync_attempt_at = result.synced_at
    if result.auto_sync_suspended:
        st.session_state.auto_sync_enabled = False
    return result


def get_last_sync_attempt_time() -> datetime | None:
    session_ts = st.session_state.get("last_datagolf_sync_attempt_at")
    if session_ts is not None:
        return session_ts
    return datagolf_sync.get_last_sync_attempt(sb)


def maybe_run_auto_sync() -> None:
    if sb is None or not st.session_state.get("auto_sync_enabled"):
        return
    if datagolf_sync.is_auto_sync_suspended(sb):
        st.session_state.auto_sync_enabled = False
        return
    last_attempt = get_last_sync_attempt_time()
    if not datagolf_sync.is_auto_sync_due(sb, last_attempt=last_attempt):
        return
    result = perform_live_sync(use_backoff=False)
    if result.success:
        clear_cache()


def setup_auto_refresh() -> None:
    if not st.session_state.get("auto_sync_enabled"):
        return
    from streamlit_autorefresh import st_autorefresh

    st_autorefresh(interval=AUTO_SYNC_INTERVAL_MS, key="datagolf_auto_refresh")
    maybe_run_auto_sync()


def render_datagolf_sync_status(result: datagolf_sync.SyncResult | None) -> None:
    last_success = datagolf_sync.get_last_successful_sync(sb)
    auto_sync_suspended = datagolf_sync.is_auto_sync_suspended(sb)

    if result is not None:
        last_success = result.last_successful_sync or last_success
        auto_sync_suspended = result.auto_sync_suspended or auto_sync_suspended

    st.metric("Sist vellykket synk", format_sync_timestamp(last_success))

    if result is None:
        st.info("Ingen synkronisering kjørt ennå. Klikk knappen over for å hente U.S. Open-scorer fra DataGolf.")
        if auto_sync_suspended:
            st.warning(
                "Auto-sync er midlertidig deaktivert etter 3 påfølgende HTTP 429-svar fra DataGolf."
            )
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Siste forsøk", format_sync_timestamp(result.synced_at))
    c2.metric("Scorer oppdatert", result.scores_written)
    c3.metric("Matchede spillere", len(result.matched_players))

    if result.event_name:
        st.caption(f"DataGolf-turnering: {result.event_name}")
    if result.retry_count:
        st.caption(f"DataGolf-forsøk i siste sync: {result.retry_count}")
    if auto_sync_suspended:
        st.warning(
            "Auto-sync er midlertidig deaktivert etter 3 påfølgende HTTP 429-svar fra DataGolf. "
            "Kjør manuell sync når API-et svarer igjen."
        )
    if result.warning:
        st.warning(result.warning)
    elif result.error:
        st.error(f"API-feil: {result.error}")
    if result.matched_players:
        with st.expander(f"Matchede spillere ({len(result.matched_players)})"):
            for name in result.matched_players:
                st.write(name)
    if result.unmatched_players:
        with st.expander(f"Umatchede spillere ({len(result.unmatched_players)})"):
            for name in result.unmatched_players:
                st.write(name)


def render_field_import_result(result: datagolf_sync.FieldImportResult) -> None:
    if result.event_name:
        st.caption(f"DataGolf-turnering: {result.event_name}")
    if result.error:
        st.error(result.error)
        return
    if not result.success:
        st.error("Import av startliste feilet.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Spillere i startliste", result.field_count)
    c2.metric("Fant fra før", result.existing_count)
    c3.metric("Nye spillere lagt til", result.added_count)

    if result.new_players:
        with st.expander(f"Nye spillere ({len(result.new_players)})"):
            for name in result.new_players:
                st.write(name)
    if result.ambiguous_names:
        with st.expander(f"Tvetydige / ikke importerte ({len(result.ambiguous_names)})"):
            for name in result.ambiguous_names:
                st.write(name)

def parse_excel(file_bytes: bytes | None = None) -> tuple[pd.DataFrame, list[str]]:
    source = io.BytesIO(file_bytes) if file_bytes else DEFAULT_FILE
    raw = pd.read_excel(source, sheet_name=0, header=None, engine="openpyxl")
    header_row = 2
    teams = [str(x).strip() for x in raw.iloc[header_row, 6:].tolist() if pd.notna(x) and str(x).strip()]
    rows = []
    tier = None
    for r in range(header_row + 1, len(raw)):
        player = raw.iat[r, 0] if 0 < raw.shape[1] else None
        if pd.isna(player) or not str(player).strip():
            continue
        txt = str(player).strip()
        if txt.lower().startswith("tier"):
            tier = txt
            continue
        row = {"name": txt, "tier": tier}
        for offset, team in enumerate(teams, start=6):
            marker = raw.iat[r, offset] if offset < raw.shape[1] else None
            row[team] = str(marker).strip().upper() == "X" if pd.notna(marker) else False
        rows.append(row)
    return pd.DataFrame(rows), teams


def import_excel_to_supabase(file_bytes: bytes | None = None):
    require_db()
    players_df, teams = parse_excel(file_bytes)
    for team in teams:
        sb.table("teams").upsert({"name": team}, on_conflict="name").execute()
    for _, row in players_df.iterrows():
        sb.table("players").upsert({"name": row["name"], "tier": row.get("tier")}, on_conflict="name").execute()
    teams_db = fetch_table("teams")
    players_db = fetch_table("players")
    team_id = dict(zip(teams_db["name"], teams_db["id"])) if not teams_db.empty else {}
    player_id = dict(zip(players_db["name"], players_db["id"])) if not players_db.empty else {}
    links = []
    for _, row in players_df.iterrows():
        for team in teams:
            if bool(row.get(team)) and team in team_id and row["name"] in player_id:
                pid = int(player_id[row["name"]])
                tid = int(team_id[team])
                links.append(
                    {
                        "team_id": tid,
                        "player_id": pid,
                        "active_from_round": PRE_CUT_FROM,
                        "active_to_round": PRE_CUT_TO,
                    }
                )
                links.append(
                    {
                        "team_id": tid,
                        "player_id": pid,
                        "active_from_round": POST_CUT_FROM,
                        "active_to_round": POST_CUT_TO,
                    }
                )
    if links:
        sb.table("team_players").upsert(links, on_conflict="team_id,player_id,active_from_round").execute()


def fmt_score(x):
    if pd.isna(x): return ""
    x = int(x)
    return "E" if x == 0 else (f"{x:+d}" if x > 0 else str(x))


def score_round_for_team(
    team_name: str,
    round_no: int,
    day: str,
    player_scores: list[dict[str, Any]],
    roster_label: str,
) -> tuple[int | None, list[dict[str, Any]]]:
    """Pick the 5 lowest round scores from up to 7 roster players."""
    frame = pd.DataFrame(player_scores)
    scored = frame.dropna(subset=["Score"]).sort_values("Score", ascending=True)
    counting = scored.head(COUNTING_SCORES)
    dropped = scored.iloc[COUNTING_SCORES:]
    team_score = int(counting["Score"].sum()) if not counting.empty else None

    detail_rows: list[dict[str, Any]] = []
    for rank, (_, row) in enumerate(counting.iterrows(), 1):
        detail_rows.append(
            {
                "Lag": team_name,
                "Dag": day,
                "Runde": round_no,
                "Spiller": row["Spiller"],
                "Score": int(row["Score"]),
                "Lagtype": roster_label,
                "Rang": rank,
                "Teller": "✅ Teller",
                "Status": "counted",
            }
        )
    for _, row in dropped.iterrows():
        detail_rows.append(
            {
                "Lag": team_name,
                "Dag": day,
                "Runde": round_no,
                "Spiller": row["Spiller"],
                "Score": int(row["Score"]),
                "Lagtype": roster_label,
                "Rang": None,
                "Teller": "❌ Droppes",
                "Status": "dropped",
            }
        )
    for _, row in frame[frame["Score"].isna()].iterrows():
        detail_rows.append(
            {
                "Lag": team_name,
                "Dag": day,
                "Runde": round_no,
                "Spiller": row["Spiller"],
                "Score": None,
                "Lagtype": roster_label,
                "Rang": None,
                "Teller": "Mangler score",
                "Status": "missing",
            }
        )
    return team_score, detail_rows


def collect_team_round_player_scores(
    team_id: int,
    round_no: int,
    players: pd.DataFrame,
    links: pd.DataFrame,
    score_map: dict[tuple[int, int], int],
) -> list[dict[str, Any]]:
    picked_ids = get_team_player_ids(links, team_id, round_no)
    picked = players[players.id.astype(int).isin(picked_ids)].sort_values("name")
    return [
        {
            "Spiller": p["name"],
            "Score": score_map.get((int(p.id), round_no)),
        }
        for _, p in picked.iterrows()
    ]


def prepare_leaderboard_display(leaderboard: pd.DataFrame) -> pd.DataFrame:
    """Show only ranking columns and hide day columns with no registered scores."""
    if leaderboard.empty:
        return leaderboard

    visible_days = [
        day for day in DAYS
        if day in leaderboard.columns and leaderboard[day].notna().any()
    ]
    columns = ["Plass", "Lag", *visible_days, "Totalt"]
    return leaderboard[columns]


def get_global_highest_scored_round(details: pd.DataFrame) -> int:
    highest = 0
    if details.empty:
        return 0
    for rnd, day in zip(ROUNDS, DAYS):
        if not details[details["Dag"] == day].dropna(subset=["Score"]).empty:
            highest = rnd
    return highest


def team_scored_rounds(details: pd.DataFrame, team: str) -> set[int]:
    team_details = details[details["Lag"] == team]
    scored_rounds: set[int] = set()
    for rnd, day in zip(ROUNDS, DAYS):
        if not team_details[team_details["Dag"] == day].dropna(subset=["Score"]).empty:
            scored_rounds.add(rnd)
    return scored_rounds


def ordered_round_days_with_scores(details: pd.DataFrame, team: str) -> list[tuple[int, str]]:
    """Show next active round first, then prior rounds with scores (newest first)."""
    global_highest = get_global_highest_scored_round(details)
    next_active = min(global_highest + 1, 4)
    scored_rounds = team_scored_rounds(details, team)

    ordered: list[tuple[int, str]] = [(next_active, DAYS[next_active - 1])]
    for rnd in range(global_highest, 0, -1):
        if rnd == next_active or rnd not in scored_rounds:
            continue
        ordered.append((rnd, DAYS[rnd - 1]))
    return ordered


def build_model(teams: pd.DataFrame, players: pd.DataFrame, links: pd.DataFrame, scores: pd.DataFrame):
    if teams.empty or players.empty:
        return pd.DataFrame(), pd.DataFrame()
    score_map = {}
    if not scores.empty:
        for _, s in scores.iterrows():
            score_map[(int(s.player_id), int(s.round_no))] = int(s.score)
    detail = []
    summary = []
    for _, t in teams.sort_values("name").iterrows():
        team_id = int(t.id)
        team_name = t["name"]
        total = 0
        row = {"Lag": team_name}
        for rnd, day in zip(ROUNDS, DAYS):
            player_scores = collect_team_round_player_scores(
                team_id, rnd, players, links, score_map
            )
            day_sum, round_detail = score_round_for_team(
                team_name,
                rnd,
                day,
                player_scores,
                ROSTER_LABELS[rnd],
            )
            row[day] = day_sum
            if day_sum is not None:
                total += int(day_sum)
            detail.extend(round_detail)
        row["Totalt"] = total
        summary.append(row)
    leaderboard = pd.DataFrame(summary)
    if not leaderboard.empty:
        leaderboard = leaderboard.sort_values("Totalt", ascending=True).reset_index(drop=True)
        leaderboard.insert(0, "Plass", range(1, len(leaderboard) + 1))
    details = pd.DataFrame(detail)
    return leaderboard, details


def fetch_latest_daily_comment() -> dict | None:
    try:
        response = (
            sb.table("daily_comments")
            .select("*")
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None
    except Exception:
        return None


def save_daily_comment(round_no: int, title: str, body: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "round_no": int(round_no),
        "title": title.strip(),
        "body": body.strip(),
        "updated_at": now,
    }
    sb.table("daily_comments").upsert(payload, on_conflict="round_no").execute()


def copy_text_to_clipboard(text: str) -> None:
    import json

    import streamlit.components.v1 as components

    components.html(
        f"""<script>
        navigator.clipboard.writeText({json.dumps(text)});
        </script>""",
        height=0,
    )


def admin_login():
    configured = get_any_secret(["ADMIN_PASSWORD", "admin_password"])
    if not configured:
        st.sidebar.warning("Admin-passord mangler i .streamlit/secrets.toml")
        return False
    pw = st.sidebar.text_input("Admin-passord", type="password")
    ok = pw == configured
    if pw and not ok:
        st.sidebar.error("Feil passord")
    return ok


st.markdown(f'''
<div class="hero">
  <h1>⛳ US Open 2026 Kupongen</h1>
  <p>Fantasy golf med live leaderboard.</p>
  <span class="pill">🥇 1. plass: 4.000 kr</span><span class="pill">7 spillere per lag</span><span class="pill">5 laveste scorer teller</span><span class="pill">2 dårligste droppes hver dag</span><span class="pill">Lavest totalscore vinner</span>
</div>
''', unsafe_allow_html=True)

init_sync_state()
setup_auto_refresh()

with st.sidebar:
    mode = st.radio("Modus", ["Deltakervisning", "Admin"])
    st.caption("Regel: 7 spillere totalt, 5 laveste scorer teller per dag.")
    if sb is None:
        st.error("Supabase mangler. Sjekk .streamlit/secrets.toml")
    else:
        st.success("Supabase tilkoblet")
    is_admin = admin_login() if mode == "Admin" else False

require_db()
teams, players, links, scores = fetch_all()
leaderboard, details = build_model(teams, players, links, scores)

if mode == "Admin" and is_admin:
    tabs = st.tabs(["Importer", "Scorer", "Lag", "Spillere", "Laguttak", "Dagsrapport"])
    with tabs[0]:
        st.subheader("Importer fra Excel")
        uploaded = st.file_uploader("Last opp Excel-oppsett", type=["xlsx"])
        if st.button("Importer lag, spillere og valg fra Excel"):
            import_excel_to_supabase(uploaded.getvalue() if uploaded else None)
            st.success("Import fullført. Last siden på nytt om dataene ikke vises med én gang.")
            st.rerun()
    with tabs[1]:
        st.subheader("Live scoring from DataGolf")

        if st.button(
            "Sync all scores from DataGolf now",
            type="primary",
            key="sync_all_scores_datagolf",
        ):
            with st.spinner("Henter U.S. Open-scorer fra DataGolf..."):
                result = perform_live_sync(use_backoff=True)
            if result.success:
                clear_cache()
                st.success(
                    f"Oppdaterte {result.scores_written} scorer for "
                    f"{len(result.matched_players)} spillere. Leaderboard er oppdatert."
                )
                st.rerun()
            elif result.rate_limited:
                st.warning(result.warning or "DataGolf rate limit (HTTP 429). Eksisterende scorer er beholdt.")
            else:
                st.error(result.error or "DataGolf-synkronisering feilet.")

        auto_sync_suspended = datagolf_sync.is_auto_sync_suspended(sb)
        auto_sync = st.checkbox(
            "Auto-sync every 5 minutes",
            value=st.session_state.auto_sync_enabled and not auto_sync_suspended,
            key="datagolf_auto_sync_checkbox",
            disabled=auto_sync_suspended,
        )
        st.session_state.auto_sync_enabled = auto_sync and not auto_sync_suspended
        if auto_sync_suspended:
            st.caption("Auto-sync er pauset til DataGolf slutter å returnere HTTP 429.")

        render_datagolf_sync_status(st.session_state.get("datagolf_sync_status"))

        st.divider()
        st.subheader("Manuell scoreoppdatering (reserve)")
        if players.empty:
            st.info("Importer eller legg til spillere først.")
        else:
            p_name = st.selectbox("Spiller", players.sort_values("name")["name"].tolist())
            p_id = int(players.loc[players.name == p_name, "id"].iloc[0])
            c1, c2 = st.columns(2)
            rnd = c1.selectbox("Runde", ROUNDS, format_func=lambda r: f"Dag {r}")
            score = c2.number_input("Score", min_value=-20, max_value=30, value=0, step=1)
            if st.button("Lagre score"):
                sb.table("scores").upsert({"player_id": p_id, "round_no": int(rnd), "score": int(score)}, on_conflict="player_id,round_no").execute()
                clear_cache()
                st.success("Score lagret.")
                st.rerun()
            st.dataframe(scores.merge(players[["id","name"]], left_on="player_id", right_on="id", how="left")[["name","round_no","score"]].sort_values(["round_no","name"]) if not scores.empty else pd.DataFrame(), width="stretch", hide_index=True)
    with tabs[2]:
        st.subheader("Legg til / fjern lag")
        new_team = st.text_input("Nytt lagnavn")
        if st.button("Legg til lag") and new_team.strip():
            sb.table("teams").upsert({"name": new_team.strip()}, on_conflict="name").execute()
            st.rerun()
        if not teams.empty:
            del_team = st.selectbox("Fjern lag", teams.sort_values("name")["name"].tolist())
            if st.button("Fjern valgt lag"):
                tid = int(teams.loc[teams.name == del_team, "id"].iloc[0])
                sb.table("teams").delete().eq("id", tid).execute()
                st.rerun()
    with tabs[3]:
        st.subheader("Legg til / fjern spiller")
        c1, c2 = st.columns(2)
        new_player = c1.text_input("Spillernavn")
        tier = c2.text_input("Tier", placeholder="f.eks. Tier 1")
        if st.button("Legg til spiller") and new_player.strip():
            sb.table("players").upsert({"name": new_player.strip(), "tier": tier.strip() or None}, on_conflict="name").execute()
            st.rerun()

        st.divider()
        st.subheader("DataGolf startliste")
        st.caption(
            "Henter hele U.S. Open-feltet fra DataGolf og legger kun til spillere som ikke finnes fra før. "
            "Eksisterende lag og rosters endres ikke."
        )
        if st.button("Hent hele startlisten fra DataGolf", key="import_datagolf_field"):
            with st.spinner("Henter startliste fra DataGolf..."):
                field_result = datagolf_sync.import_missing_field_players(
                    sb,
                    datagolf_sync.get_api_key_from_mapping(get_sync_secrets()),
                )
            render_field_import_result(field_result)
            if field_result.success and field_result.added_count:
                clear_cache()
                st.success("Startliste importert. Nye spillere er tilgjengelige for Dag 3–4-bytter.")
                st.rerun()
            elif field_result.success:
                st.info("Ingen nye spillere å legge til.")

        if not players.empty:
            del_player = st.selectbox("Fjern spiller", players.sort_values("name")["name"].tolist())
            if st.button("Fjern valgt spiller"):
                pid = int(players.loc[players.name == del_player, "id"].iloc[0])
                sb.table("players").delete().eq("id", pid).execute()
                st.rerun()
    with tabs[4]:
        st.subheader("Originalt lag (Dag 1–2)")
        if teams.empty or players.empty:
            st.info("Legg til lag og spillere først.")
        elif not links_have_round_ranges(links):
            st.warning(
                "Kjør migrations/001_round_based_rosters.sql i Supabase for å aktivere lagbytter etter dag 2."
            )
            t_name = st.selectbox("Lag", teams.sort_values("name")["name"].tolist(), key="assign_team")
            tid = int(teams.loc[teams.name == t_name, "id"].iloc[0])
            current_ids = links[links.team_id == tid].player_id.astype(int).tolist() if not links.empty else []
            player_options = players.sort_values("name")["name"].tolist()
            current_names = players[players.id.astype(int).isin(current_ids)].sort_values("name")["name"].tolist()
            legacy_key = f"legacy_roster_{tid}"
            if st.session_state.get("laguttak_team_id") != tid:
                if st.session_state.get("laguttak_team_id") is not None:
                    prev_tid = st.session_state.laguttak_team_id
                    st.session_state.pop(f"legacy_roster_{prev_tid}", None)
                st.session_state.laguttak_team_id = tid
                st.session_state[legacy_key] = current_names
            selected = st.multiselect("Velg 7 spillere", player_options, key=legacy_key)
            st.caption(
                f"Debug: team_id={tid}, team={t_name}, original roster={current_names}, post-cut roster={current_names}"
            )
            st.caption(f"Valgt: {len(selected)} av {PLAYERS_PER_TEAM}")
            if st.button("Lagre laguttak"):
                sb.table("team_players").delete().eq("team_id", tid).execute()
                new_ids = players[players.name.isin(selected)].id.astype(int).tolist()
                if new_ids:
                    sb.table("team_players").insert(
                        [{"team_id": tid, "player_id": pid} for pid in new_ids]
                    ).execute()
                clear_cache()
                st.rerun()
        else:
            t_name = st.selectbox("Lag", teams.sort_values("name")["name"].tolist(), key="assign_team")
            tid = int(teams.loc[teams.name == t_name, "id"].iloc[0])
            pre_cut_links = filter_team_roster(links, tid, PRE_CUT_FROM, PRE_CUT_TO)
            current_ids = pre_cut_links.player_id.astype(int).tolist() if not pre_cut_links.empty else []
            player_options = players.sort_values("name")["name"].tolist()
            current_names = players[players.id.astype(int).isin(current_ids)].sort_values("name")["name"].tolist()

            original_ids = get_team_player_ids(links, tid, 1)
            original_names = players[players.id.astype(int).isin(original_ids)].sort_values("name")["name"].tolist()

            post_cut_links = filter_team_roster(links, tid, POST_CUT_FROM, POST_CUT_TO)
            post_cut_ids = (
                set(post_cut_links.player_id.astype(int).tolist())
                if not post_cut_links.empty
                else set(current_ids)
            )
            post_cut_names = players[players.id.astype(int).isin(post_cut_ids)].sort_values("name")["name"].tolist()

            force_reload = st.session_state.pop("laguttak_force_reload_team_id", None) == tid
            pre_key, post_key = prepare_laguttak_roster_state(
                tid,
                current_names,
                post_cut_names,
                force_reload=force_reload,
            )
            st.caption(
                f"Debug: team_id={tid}, team={t_name}, "
                f"original roster count={len(original_names)}, "
                f"post-cut roster count={len(post_cut_names)}, "
                f"post-cut roster={post_cut_names}"
            )

            selected = st.multiselect(
                "Velg 7 spillere for Dag 1–2",
                player_options,
                key=pre_key,
            )
            st.caption(f"Valgt: {len(selected)} av {PLAYERS_PER_TEAM}")
            if st.button("Lagre originalt lag"):
                if len(selected) != PLAYERS_PER_TEAM:
                    st.error(f"Originalt lag må ha nøyaktig {PLAYERS_PER_TEAM} spillere.")
                else:
                    new_ids = players[players.name.isin(selected)].id.astype(int).tolist()
                    save_team_roster(tid, new_ids, PRE_CUT_FROM, PRE_CUT_TO)
                    clear_cache()
                    st.success("Originalt lag lagret for Dag 1–2.")
                    st.rerun()

            st.divider()
            st.subheader("Bytter etter dag 2")
            st.caption("Dag 3–4 bruker oppdatert lag. Maks 3 bytter per lag.")

            st.write("**Originalt lag (Dag 1–2):**", ", ".join(original_names) if original_names else "Ingen spillere")

            post_cut_selected = st.multiselect(
                "Velg 7 spillere for Dag 3–4",
                player_options,
                key=post_key,
            )
            post_cut_new_ids_list = players[players.name.isin(post_cut_selected)].id.astype(int).tolist()
            post_cut_new_ids = set(post_cut_new_ids_list)
            swaps_used = count_post_cut_swaps(original_ids, post_cut_new_ids)
            st.caption(f"Bytter brukt: {swaps_used}/{MAX_POST_CUT_SWAPS}")

            if st.button("Lagre lag etter bytter"):
                if len(post_cut_selected) != PLAYERS_PER_TEAM:
                    st.error(f"Lag etter bytter må ha nøyaktig {PLAYERS_PER_TEAM} spillere.")
                elif len(post_cut_new_ids) != PLAYERS_PER_TEAM:
                    st.error(
                        f"Post-cut roster må inneholde nøyaktig {PLAYERS_PER_TEAM} unike spillere. "
                        f"Fant {len(post_cut_new_ids)}."
                    )
                elif swaps_used > MAX_POST_CUT_SWAPS:
                    st.error(f"Maks {MAX_POST_CUT_SWAPS} bytter er tillatt etter dag 2.")
                else:
                    save_team_roster(
                        tid,
                        list(post_cut_new_ids),
                        POST_CUT_FROM,
                        POST_CUT_TO,
                    )
                    clear_cache()
                    st.session_state.laguttak_force_reload_team_id = tid
                    st.success("Lag for Dag 3–4 er lagret.")
                    st.rerun()
    with tabs[5]:
        st.subheader("Dagsrapport")
        st.caption("Generer en norsk oppsummering for deltakerne basert på leaderboard og tellende scorer.")

        c1, c2 = st.columns(2)
        report_round = c1.selectbox(
            "Runde / dag",
            ROUNDS,
            format_func=lambda r: DAYS[r - 1],
            key="daily_report_round",
        )
        report_tone = c2.selectbox("Tone", list(TONES), index=1, key="daily_report_tone")

        action1, action2, action3 = st.columns(3)
        if action1.button("Generer dagsrapport", type="primary", key="generate_daily_report"):
            title, body = generate_daily_report(
                leaderboard,
                details,
                int(report_round),
                tone=report_tone,
            )
            st.session_state.daily_report_title = title
            st.session_state.daily_report_draft = body
            st.rerun()

        report_title = st.text_input(
            "Tittel",
            value=st.session_state.get("daily_report_title", f"{DAYS[int(report_round) - 1]} – dagsrapport"),
        )
        report_body = st.text_area(
            "Dagsrapport (rediger før publisering)",
            value=st.session_state.get("daily_report_draft", ""),
            height=260,
        )

        if action2.button("Kopier tekst", key="copy_daily_report"):
            if report_body.strip():
                copy_text_to_clipboard(report_body)
                st.toast("Tekst kopiert til utklippstavlen.")
            else:
                st.warning("Ingen tekst å kopiere.")

        if action3.button("Lagre kommentar", key="save_daily_report"):
            if not report_body.strip():
                st.error("Skriv eller generer en dagsrapport først.")
            else:
                try:
                    save_daily_comment(
                        int(report_round),
                        report_title or f"{DAYS[int(report_round) - 1]} – dagsrapport",
                        report_body,
                    )
                    clear_cache()
                    st.success("Dagsrapport lagret.")
                    st.rerun()
                except Exception as exc:
                    st.error(
                        "Kunne ikke lagre. Kjør migrations/002_daily_comments.sql i Supabase først. "
                        f"({exc})"
                    )

        saved_for_round = pd.DataFrame()
        try:
            saved_for_round = fetch_table("daily_comments")
        except Exception:
            saved_for_round = pd.DataFrame()

        if not saved_for_round.empty:
            st.divider()
            st.caption("Lagrede dagsrapporter")
            st.dataframe(
                saved_for_round.sort_values("round_no")[["round_no", "title", "updated_at"]],
                width="stretch",
                hide_index=True,
            )

latest_comment = fetch_latest_daily_comment()
if latest_comment and latest_comment.get("body"):
    st.markdown("### 💬 Dagens kommentar")
    st.markdown(f"**{latest_comment.get('title', 'Dagsrapport')}**")
    st.write(latest_comment["body"])

st.subheader("🏆 Leaderboard")
if leaderboard.empty:
    st.info("Ingen data ennå. Gå til Admin og importer fra Excel.")
else:
    st.dataframe(prepare_leaderboard_display(leaderboard), width="stretch", hide_index=True)

st.subheader("🔎 Tellende og droppede scorer")
if details.empty:
    st.info("Ingen scorer registrert ennå.")
else:
    team = st.selectbox("Velg lag", sorted(details["Lag"].unique()))
    team_details = details[details["Lag"] == team]
    for idx, (rnd, day) in enumerate(ordered_round_days_with_scores(details, team)):
        day_df = team_details[team_details["Dag"] == day].copy()
        roster_label = ROSTER_LABELS[rnd]
        status_order = {"counted": 0, "dropped": 1, "missing": 2}
        day_df["status_order"] = day_df["Status"].map(status_order)
        day_df = day_df.sort_values(
            ["status_order", "Score"],
            ascending=[True, True],
            na_position="last",
        )
        counted_sum = int(day_df[day_df["Status"] == "counted"]["Score"].sum())
        display_df = day_df.copy()
        display_df["Score"] = display_df["Score"].map(fmt_score)
        with st.expander(f"{day} - {team} ({roster_label})", expanded=(idx == 0)):
            st.caption(f"Lagtype: {roster_label}")
            st.dataframe(
                display_df[["Teller", "Rang", "Spiller", "Score"]],
                width="stretch",
                hide_index=True,
            )
            team_row = leaderboard[leaderboard["Lag"] == team]
            if not team_row.empty and day in team_row.columns:
                leaderboard_value = team_row.iloc[0][day]
                st.caption(
                    f"**Lagscore {day}:** {fmt_score(counted_sum)} "
                    f"(sum av 5 beste) · Leaderboard viser: {fmt_score(leaderboard_value)}"
                )
                if pd.notna(leaderboard_value) and int(leaderboard_value) != counted_sum:
                    st.error("Avvik mellom beregnet lagscore og leaderboard.")

render_post_cut_swaps_section(teams, players, links, leaderboard)

st.subheader("📋 Spillerstall")
if not teams.empty and not players.empty:
    roster_rows = []
    for _, t in teams.sort_values("name").iterrows():
        tid = int(t.id)
        pre_ids = get_team_player_ids(links, tid, 1)
        post_ids = get_team_player_ids(links, tid, 3) if links_have_round_ranges(links) else pre_ids
        pre_names = players[players.id.astype(int).isin(pre_ids)].sort_values("name")["name"].tolist()
        post_names = players[players.id.astype(int).isin(post_ids)].sort_values("name")["name"].tolist()
        swaps = count_post_cut_swaps(pre_ids, post_ids) if links_have_round_ranges(links) else 0
        roster_rows.append(
            {
                "Lag": t["name"],
                "Dag 1–2": ", ".join(pre_names),
                "Dag 3–4": ", ".join(post_names),
                "Bytter": f"{swaps}/{MAX_POST_CUT_SWAPS}" if links_have_round_ranges(links) else "-",
            }
        )
    st.dataframe(pd.DataFrame(roster_rows), width="stretch", hide_index=True)
