from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from supabase import create_client

from lib import datagolf_sync

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


def ensure_post_cut_rosters(links: pd.DataFrame) -> pd.DataFrame:
    """Copy pre-cut rosters to post-cut when round columns exist but copies are missing."""
    if not links_have_round_ranges(links) or links.empty:
        return links

    pre_cut = links[
        (links.active_from_round.astype(int) == PRE_CUT_FROM)
        & (links.active_to_round.astype(int) == PRE_CUT_TO)
    ]
    post_cut = links[
        (links.active_from_round.astype(int) == POST_CUT_FROM)
        & (links.active_to_round.astype(int) == POST_CUT_TO)
    ]
    if pre_cut.empty:
        return links

    existing_post = {
        (int(row.team_id), int(row.player_id))
        for _, row in post_cut.iterrows()
    }
    inserts = []
    for _, row in pre_cut.iterrows():
        key = (int(row.team_id), int(row.player_id))
        if key not in existing_post:
            inserts.append(
                {
                    "team_id": key[0],
                    "player_id": key[1],
                    "active_from_round": POST_CUT_FROM,
                    "active_to_round": POST_CUT_TO,
                }
            )

    if inserts:
        sb.table("team_players").upsert(
            inserts,
            on_conflict="team_id,player_id,active_from_round",
        ).execute()
        return fetch_table("team_players")
    return links


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


def init_sync_state() -> None:
    if "auto_sync_enabled" not in st.session_state:
        st.session_state.auto_sync_enabled = False
    if "datagolf_sync_status" not in st.session_state:
        st.session_state.datagolf_sync_status = None


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


def perform_live_sync() -> datagolf_sync.SyncResult:
    result = datagolf_sync.execute_sync(sb, get_sync_secrets())
    st.session_state.datagolf_sync_status = result
    return result


def render_datagolf_sync_status(result: datagolf_sync.SyncResult | None) -> None:
    if result is None:
        st.info("Ingen synkronisering kjørt ennå. Klikk knappen over for å hente U.S. Open-scorer fra DataGolf.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sist synket", format_sync_timestamp(result.synced_at))
    c2.metric("Scorer oppdatert", result.scores_written)
    c3.metric("Matchede spillere", len(result.matched_players))
    c4.metric("Umatchede spillere", len(result.unmatched_players))

    if result.event_name:
        st.caption(f"DataGolf-turnering: {result.event_name}")
    if result.error:
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


@st.fragment(run_every=timedelta(minutes=5))
def datagolf_auto_sync_fragment() -> None:
    if sb is None:
        return
    if st.session_state.get("auto_sync_enabled"):
        result = perform_live_sync()
        if result.success:
            clear_cache()
            st.rerun()


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
        total = 0
        row = {"Lag": t["name"]}
        for rnd, day in zip(ROUNDS, DAYS):
            picked_ids = get_team_player_ids(links, team_id, rnd)
            picked = players[players.id.astype(int).isin(picked_ids)].sort_values("name")
            round_rows = []
            for _, p in picked.iterrows():
                val = score_map.get((int(p.id), rnd))
                round_rows.append(
                    {
                        "Lag": t["name"],
                        "Dag": day,
                        "Runde": rnd,
                        "Spiller": p["name"],
                        "Score": val,
                        "Lagtype": ROSTER_LABELS[rnd],
                    }
                )
            scored = pd.DataFrame(round_rows).dropna(subset=["Score"]).sort_values("Score", ascending=True)
            counting = scored.head(COUNTING_SCORES).copy()
            dropped = scored.iloc[COUNTING_SCORES:].copy()
            day_sum = counting.Score.sum() if len(counting) else None
            row[day] = day_sum
            if day_sum is not None:
                total += int(day_sum)
            for rank, (_, r) in enumerate(counting.iterrows(), 1):
                detail.append({**r.to_dict(), "Rang": rank, "Teller": "✅ Teller"})
            for _, r in dropped.iterrows():
                detail.append({**r.to_dict(), "Rang": None, "Teller": "❌ Droppes"})
        row["Totalt"] = total
        summary.append(row)
    leaderboard = pd.DataFrame(summary)
    if not leaderboard.empty:
        leaderboard = leaderboard.sort_values("Totalt", ascending=True).reset_index(drop=True)
        leaderboard.insert(0, "Plass", range(1, len(leaderboard) + 1))
    details = pd.DataFrame(detail)
    return leaderboard, details


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
  <h1>⛳ US Open 2026</h1>
  <p>Fantasy golf med live leaderboard og administrasjon rett i nettleseren.</p>
  <span class="pill">7 spillere per lag</span><span class="pill">5 laveste scorer teller</span><span class="pill">2 dårligste droppes hver dag</span><span class="pill">Lavest totalscore vinner</span>
</div>
''', unsafe_allow_html=True)

init_sync_state()
datagolf_auto_sync_fragment()

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
    tabs = st.tabs(["Importer", "Scorer", "Lag", "Spillere", "Laguttak"])
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
                result = perform_live_sync()
            if result.success:
                clear_cache()
                st.success(
                    f"Oppdaterte {result.scores_written} scorer for "
                    f"{len(result.matched_players)} spillere. Leaderboard er oppdatert."
                )
                st.rerun()
            else:
                st.error(result.error or "DataGolf-synkronisering feilet.")

        auto_sync = st.checkbox(
            "Auto-sync every 5 minutes",
            value=st.session_state.auto_sync_enabled,
            key="datagolf_auto_sync_checkbox",
        )
        st.session_state.auto_sync_enabled = auto_sync

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
            current_names = players[players.id.astype(int).isin(current_ids)]["name"].tolist()
            selected = st.multiselect("Velg 7 spillere", player_options, default=current_names)
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
            current_names = players[players.id.astype(int).isin(current_ids)]["name"].tolist()
            selected = st.multiselect(
                "Velg 7 spillere for Dag 1–2",
                player_options,
                default=current_names,
                key="pre_cut_roster",
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

            original_ids = get_team_player_ids(links, tid, 1)
            original_names = players[players.id.astype(int).isin(original_ids)].sort_values("name")["name"].tolist()
            st.write("**Originalt lag (Dag 1–2):**", ", ".join(original_names) if original_names else "Ingen spillere")

            post_cut_links = filter_team_roster(links, tid, POST_CUT_FROM, POST_CUT_TO)
            post_cut_ids = post_cut_links.player_id.astype(int).tolist() if not post_cut_links.empty else current_ids
            post_cut_names = players[players.id.astype(int).isin(post_cut_ids)]["name"].tolist()
            post_cut_selected = st.multiselect(
                "Velg 7 spillere for Dag 3–4",
                player_options,
                default=post_cut_names,
                key="post_cut_roster",
            )
            post_cut_new_ids = set(players[players.name.isin(post_cut_selected)].id.astype(int).tolist())
            swaps_used = count_post_cut_swaps(original_ids, post_cut_new_ids)
            st.caption(f"Bytter brukt: {swaps_used}/{MAX_POST_CUT_SWAPS}")

            if st.button("Lagre lag etter bytter"):
                if len(post_cut_selected) != PLAYERS_PER_TEAM:
                    st.error(f"Lag etter bytter må ha nøyaktig {PLAYERS_PER_TEAM} spillere.")
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
                    st.success("Lag for Dag 3–4 er lagret.")
                    st.rerun()

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
    for rnd, day in zip(ROUNDS, DAYS):
        day_df = details[(details["Lag"] == team) & (details["Dag"] == day)].copy()
        if day_df.empty:
            continue
        day_df["Score"] = day_df["Score"].map(fmt_score)
        roster_label = ROSTER_LABELS[rnd]
        with st.expander(f"{day} - {team} ({roster_label})", expanded=(day == DAYS[0])):
            st.caption(f"Lagtype: {roster_label}")
            st.dataframe(day_df[["Teller", "Rang", "Spiller", "Score"]], width="stretch", hide_index=True)

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
