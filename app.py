"""US Open 2026 Fantasy Golf Competition."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from supabase import Client

from lib import auth, datagolf_sync, db, excel_import, scoring, styles

DEFAULT_EXCEL = Path("data/US Open 2026 - Resultater.xlsx")

st.set_page_config(
    page_title="US Open 2026 Fantasy Golf",
    page_icon="⛳",
    layout="wide",
    initial_sidebar_state="expanded",
)


def format_score(value: int | None) -> str:
    return "—" if value is None else str(value)


@st.cache_data(ttl=30, show_spinner=False)
def load_competition_data(tournament_id: str):
    client = db.get_supabase_client()
    if client is None:
        return None

    teams = db.fetch_teams(client, tournament_id)
    players = db.fetch_players(client, tournament_id)
    team_players = db.fetch_team_players(client, tournament_id)
    scores = db.fetch_scores(client, tournament_id)
    tournament = db.get_active_tournament(client)
    standings = scoring.build_team_standings(
        teams=teams,
        players=players,
        team_players=team_players,
        scores=scores,
        num_rounds=tournament["num_rounds"] if tournament else 4,
        counting_scores=tournament["counting_scores"] if tournament else 5,
        dropped_scores=tournament["dropped_scores"] if tournament else 2,
    )
    return {
        "tournament": tournament,
        "teams": teams,
        "players": players,
        "team_players": team_players,
        "scores": scores,
        "standings": standings,
    }


def clear_data_cache() -> None:
    load_competition_data.clear()


def init_sync_state() -> None:
    if "auto_sync_enabled" not in st.session_state:
        st.session_state.auto_sync_enabled = False
    if "datagolf_sync_status" not in st.session_state:
        st.session_state.datagolf_sync_status = None


def format_sync_timestamp(value: datetime | None) -> str:
    if value is None:
        return "Never"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def get_app_secrets() -> dict[str, str]:
    return {
        "SUPABASE_URL": st.secrets.get("SUPABASE_URL", ""),
        "SUPABASE_ANON_KEY": st.secrets.get("SUPABASE_ANON_KEY", ""),
        "DATA_GOLF_API_KEY": st.secrets.get("DATA_GOLF_API_KEY", ""),
    }


def perform_live_sync() -> datagolf_sync.SyncResult:
    result = datagolf_sync.execute_sync(get_app_secrets())
    st.session_state.datagolf_sync_status = result
    if result.success:
        clear_data_cache()
    return result


def render_datagolf_sync_status(result: datagolf_sync.SyncResult | None) -> None:
    if result is None:
        st.info("No sync has been run yet. Click the button above to fetch U.S. Open scores from DataGolf.")
        return

    status_label = "Success" if result.success else "Failed"
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Last sync", format_sync_timestamp(result.synced_at))
    col2.metric("Scores updated", result.scores_written)
    col3.metric("Matched players", len(result.matched_players))
    col4.metric("Unmatched players", len(result.unmatched_players))

    st.caption(f"Status: {status_label}")
    if result.event_name:
        st.caption(f"DataGolf event: {result.event_name}")

    if result.error:
        st.error(f"API error: {result.error}")

    if result.matched_players:
        with st.expander(f"Matched players ({len(result.matched_players)})", expanded=False):
            for name in result.matched_players:
                st.write(name)

    if result.unmatched_players:
        with st.expander(f"Unmatched players ({len(result.unmatched_players)})", expanded=True):
            for name in result.unmatched_players:
                st.write(name)


def render_sync_status() -> None:
    render_datagolf_sync_status(st.session_state.get("datagolf_sync_status"))


@st.fragment(run_every=timedelta(minutes=5))
def datagolf_auto_sync_fragment(tournament: dict) -> None:
    if not tournament.get("is_active"):
        return
    if st.session_state.get("auto_sync_enabled"):
        result = perform_live_sync()
        if result.success:
            st.rerun()


def get_client_or_warn() -> Client | None:
    client = db.get_supabase_client()
    if client is None:
        st.error(
            "Supabase is not configured. Add `SUPABASE_URL` and `SUPABASE_ANON_KEY` "
            "to `.streamlit/secrets.toml`, then restart the app."
        )
    return client


def page_leaderboard() -> None:
    styles.render_hero("Leaderboard", "US Open 2026 — lowest total score wins")

    client = get_client_or_warn()
    if client is None:
        return

    tournament = db.get_active_tournament(client)
    if not tournament:
        st.info("No tournament data yet. Import the Excel roster from the Admin page.")
        return

    data = load_competition_data(tournament["id"])
    standings = data["standings"]

    if not standings:
        st.info("No teams found.")
        return

    leader_total = next(
        (standing.tournament_total for standing in standings if standing.tournament_total is not None),
        None,
    )
    styles.render_stat_cards(
        [
            ("Teams", str(len(standings))),
            ("Rounds", "4"),
            ("Counting scores", "5 per round"),
            ("Leader total", format_score(leader_total)),
        ]
    )

    render_sync_status()

    rows = []
    for index, standing in enumerate(standings, start=1):
        rows.append(
            {
                "Rank": index,
                "Team": standing.team_name,
                "Round 1": format_score(standing.round_totals.get(1)),
                "Round 2": format_score(standing.round_totals.get(2)),
                "Round 3": format_score(standing.round_totals.get(3)),
                "Round 4": format_score(standing.round_totals.get(4)),
                "Total": format_score(standing.tournament_total),
            }
        )

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown(
        '<p class="mobile-note">Best 5 scores count each round. Worst 2 are dropped.</p>',
        unsafe_allow_html=True,
    )


def page_team_detail() -> None:
    styles.render_hero("Team Detail", "Round totals with counting and dropped players")

    client = get_client_or_warn()
    if client is None:
        return

    tournament = db.get_active_tournament(client)
    if not tournament:
        st.info("No tournament data yet.")
        return

    data = load_competition_data(tournament["id"])
    standings = data["standings"]
    if not standings:
        st.info("No teams found.")
        return

    team_names = [standing.team_name for standing in standings]
    selected_team = st.selectbox("Select team", team_names)
    standing = next(item for item in standings if item.team_name == selected_team)

    styles.render_stat_cards(
        [
            ("Team", standing.team_name),
            ("Round 1", format_score(standing.round_totals.get(1))),
            ("Round 2", format_score(standing.round_totals.get(2))),
            ("Round 3", format_score(standing.round_totals.get(3))),
            ("Round 4", format_score(standing.round_totals.get(4))),
            ("Tournament total", format_score(standing.tournament_total)),
        ]
    )

    for round_num in range(1, 5):
        round_result = standing.rounds[round_num]
        st.markdown(f"### Round {round_num}")
        st.write(f"Round total: **{format_score(round_result.total)}**")

        counting_rows = [
            {
                "Player": player.player_name,
                "Tier": player.tier,
                "Strokes": format_score(player.strokes),
            }
            for player in round_result.counting
        ]
        dropped_rows = [
            {
                "Player": player.player_name,
                "Tier": player.tier,
                "Strokes": format_score(player.strokes),
            }
            for player in round_result.dropped
        ]

        left, right = st.columns(2)
        with left:
            st.markdown("**Counting (5)**")
            if counting_rows:
                st.dataframe(pd.DataFrame(counting_rows), use_container_width=True, hide_index=True)
            else:
                st.caption("Not enough scores entered yet.")
        with right:
            st.markdown("**Dropped (2)**")
            if dropped_rows:
                st.dataframe(pd.DataFrame(dropped_rows), use_container_width=True, hide_index=True)
            else:
                st.caption("No dropped players yet.")


def page_admin() -> None:
    styles.render_hero("Admin", "Manage rosters, scores, and tournament data")

    if not auth.is_admin():
        with st.form("admin_login"):
            password = st.text_input("Admin password", type="password")
            submitted = st.form_submit_button("Log in")
            if submitted:
                if auth.login_admin(password):
                    st.success("Logged in.")
                    st.rerun()
                else:
                    st.error("Invalid password.")
        return

    client = get_client_or_warn()
    if client is None:
        return

    tournament = db.ensure_tournament(client)

    st.success("Admin session active.")
    if st.button("Log out"):
        auth.logout_admin()
        st.rerun()

    tab_import, tab_teams, tab_players, tab_rosters, tab_scorer, tab_reset = st.tabs(
        ["Import", "Teams", "Players", "Rosters", "Scorer", "Reset"]
    )

    with tab_import:
        st.subheader("Import Excel roster")
        st.caption(f"Default file: `{DEFAULT_EXCEL}`")

        uploaded = st.file_uploader("Upload new Excel roster file", type=["xlsx"])
        use_default = st.checkbox("Use default project Excel file", value=True)

        if st.button("Import roster", type="primary"):
            try:
                if uploaded is not None:
                    temp_path = Path("data/uploaded_roster.xlsx")
                    temp_path.parent.mkdir(parents=True, exist_ok=True)
                    temp_path.write_bytes(uploaded.getvalue())
                    result = excel_import.import_workbook(client, temp_path)
                elif use_default and DEFAULT_EXCEL.exists():
                    result = excel_import.import_workbook(client, DEFAULT_EXCEL)
                else:
                    st.error("Provide an uploaded file or enable the default Excel file.")
                    result = None

                if result:
                    clear_data_cache()
                    st.success(
                        f"Imported {result['players_imported']} players and "
                        f"{result['teams_imported']} teams."
                    )
                    st.json(result)
            except Exception as exc:
                st.error(str(exc))

    with tab_teams:
        st.subheader("Teams")
        teams = db.fetch_teams(client, tournament["id"])

        with st.form("add_team"):
            team_name = st.text_input("New team name")
            if st.form_submit_button("Add team"):
                if team_name.strip():
                    db.add_team(client, tournament["id"], team_name.strip())
                    clear_data_cache()
                    st.success(f"Added team {team_name.strip()}.")
                    st.rerun()

        for team in teams:
            cols = st.columns([4, 1])
            cols[0].write(team["name"])
            if cols[1].button("Remove", key=f"remove_team_{team['id']}"):
                db.remove_team(client, team["id"])
                clear_data_cache()
                st.rerun()

    with tab_players:
        st.subheader("Players")
        players = db.fetch_players(client, tournament["id"])

        with st.form("add_player"):
            player_name = st.text_input("Player name")
            player_tier = st.number_input("Tier", min_value=1, max_value=20, value=1, step=1)
            if st.form_submit_button("Add player"):
                if player_name.strip():
                    db.add_player(client, tournament["id"], player_name.strip(), int(player_tier))
                    clear_data_cache()
                    st.success(f"Added player {player_name.strip()}.")
                    st.rerun()

        for player in players:
            cols = st.columns([4, 1, 1])
            cols[0].write(f"{player['name']} (Tier {player['tier']})")
            if cols[2].button("Remove", key=f"remove_player_{player['id']}"):
                db.remove_player(client, player["id"])
                clear_data_cache()
                st.rerun()

    with tab_rosters:
        st.subheader("Edit team rosters")
        teams = db.fetch_teams(client, tournament["id"])
        players = db.fetch_players(client, tournament["id"])
        team_players = db.fetch_team_players(client, tournament["id"])

        if not teams:
            st.info("No teams available.")
        else:
            team_names = [team["name"] for team in teams]
            selected_team_name = st.selectbox("Team", team_names, key="roster_team_select")
            selected_team = next(team for team in teams if team["name"] == selected_team_name)
            current_ids = {
                link["player_id"] for link in team_players if link["team_id"] == selected_team["id"]
            }

            player_options = {f"{player['name']} (Tier {player['tier']})": player["id"] for player in players}
            default_labels = [
                label for label, player_id in player_options.items() if player_id in current_ids
            ]

            selected_labels = st.multiselect(
                "Select exactly 7 golfers",
                options=list(player_options.keys()),
                default=default_labels,
            )

            if len(selected_labels) != 7:
                st.warning(f"Select exactly 7 golfers. Currently selected: {len(selected_labels)}.")

            if st.button("Save roster", disabled=len(selected_labels) != 7):
                selected_ids = [player_options[label] for label in selected_labels]
                db.set_team_roster(client, selected_team["id"], selected_ids)
                clear_data_cache()
                st.success(f"Saved roster for {selected_team_name}.")
                st.rerun()

    with tab_scorer:
        st.subheader("Live scoring from DataGolf")

        if st.button(
            "Sync all scores from DataGolf now",
            type="primary",
            key="sync_all_scores_datagolf",
        ):
            with st.spinner("Fetching U.S. Open scores from DataGolf..."):
                result = perform_live_sync()
            if result.success:
                st.success(
                    f"Updated {result.scores_written} scores for "
                    f"{len(result.matched_players)} matched players."
                )
                st.rerun()
            else:
                st.error(result.error or "DataGolf sync failed.")

        auto_sync = st.checkbox(
            "Auto-sync every 5 minutes",
            value=st.session_state.auto_sync_enabled,
            key="datagolf_auto_sync_checkbox",
        )
        st.session_state.auto_sync_enabled = auto_sync

        render_datagolf_sync_status(st.session_state.get("datagolf_sync_status"))

        st.divider()
        st.subheader("Manual score entry")
        st.caption("Fallback if DataGolf sync is unavailable or a score needs correction.")
        players = db.fetch_players(client, tournament["id"])
        scores = db.fetch_scores(client, tournament["id"])
        scores_lookup = {(score["player_id"], score["round"]): score["strokes"] for score in scores}

        round_num = st.selectbox("Round", [1, 2, 3, 4], key="score_round_select")
        score_rows = []
        for player in players:
            current_value = scores_lookup.get((player["id"], round_num))
            score_rows.append(
                {
                    "player_id": player["id"],
                    "Player": player["name"],
                    "Tier": player["tier"],
                    "Strokes": current_value,
                }
            )

        edited = st.data_editor(
            pd.DataFrame(score_rows),
            column_config={
                "player_id": None,
                "Player": st.column_config.TextColumn(disabled=True),
                "Tier": st.column_config.NumberColumn(disabled=True),
                "Strokes": st.column_config.NumberColumn(min_value=0, step=1),
            },
            hide_index=True,
            use_container_width=True,
            key=f"score_editor_round_{round_num}",
        )

        if st.button("Save round scores", type="primary"):
            for _, row in edited.iterrows():
                player_id = row["player_id"]
                strokes = row["Strokes"]
                if pd.isna(strokes):
                    db.delete_score(client, player_id, round_num)
                else:
                    db.upsert_score(client, player_id, round_num, int(strokes))
            clear_data_cache()
            st.success(f"Saved scores for round {round_num}.")
            st.rerun()

    with tab_reset:
        st.subheader("Reset tournament")
        st.warning("This deletes all teams, players, rosters, and scores for US Open 2026.")
        confirm = st.checkbox("I understand this cannot be undone.")
        if st.button("Reset tournament", type="primary", disabled=not confirm):
            db.reset_tournament_data(client, tournament["id"])
            clear_data_cache()
            st.success("Tournament data reset.")
            st.rerun()


def main() -> None:
    styles.inject_styles()
    init_sync_state()

    client = db.get_supabase_client()
    if client is not None:
        tournament = db.get_active_tournament(client)
        if tournament is not None:
            datagolf_auto_sync_fragment(tournament)

    st.sidebar.title("⛳ Fantasy Golf")
    st.sidebar.caption("US Open 2026")
    page = st.sidebar.radio(
        "Navigation",
        ["Leaderboard", "Team Detail", "Admin"],
        label_visibility="collapsed",
    )

    if page == "Leaderboard":
        page_leaderboard()
    elif page == "Team Detail":
        page_team_detail()
    else:
        page_admin()


if __name__ == "__main__":
    main()
