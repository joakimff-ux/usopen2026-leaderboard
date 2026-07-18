"""Fantasy golf competition app."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from threading import Lock

import pandas as pd
import streamlit as st

from supabase import Client

from lib import (
    auth,
    datagolf_sync,
    db,
    excel_import,
    leaderboard_preview,
    live_feed,
    participant_admin,
    roster_changes,
    scoring,
    styles,
    time_display,
)

st.set_page_config(
    page_title="The Open 2026 Kupongen",
    page_icon="⛳",
    layout="wide",
    initial_sidebar_state="expanded",
)


def default_excel_path(tournament: dict) -> Path:
    return Path("data") / f"{tournament['name']} - Resultater.xlsx"


def render_active_tournament_info(tournament: dict) -> None:
    st.markdown("### Active tournament")
    st.write(f"**Name:** {tournament.get('name')}")
    st.write(f"**Display title:** {db.tournament_display_title(tournament)}")
    st.write(f"**DataGolf event:** {tournament.get('datagolf_event_name') or '—'}")
    st.write(f"**Course:** {tournament.get('course_name') or '—'}")
    if tournament.get("start_date") and tournament.get("end_date"):
        st.write(f"**Dates:** {tournament['start_date']} – {tournament['end_date']}")
    st.write(
        f"**Rules:** {tournament.get('num_rounds', 4)} rounds, "
        f"{tournament.get('counting_scores', 5)} counting, "
        f"{tournament.get('dropped_scores', 2)} dropped per round"
    )


def render_tournament_catalog(client: Client, active: dict | None) -> None:
    tournaments = db.list_tournaments(client)
    if not tournaments:
        st.info("No tournaments found in the database.")
        return
    rows = []
    for item in tournaments:
        is_active = active is not None and item["id"] == active["id"]
        rows.append(
            {
                "Active": "Yes" if is_active else "No",
                "Name": item.get("name"),
                "Year": item.get("year"),
                "DataGolf event": item.get("datagolf_event_name") or "—",
                "Course": item.get("course_name") or "—",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def format_score(value: int | None) -> str:
    return scoring.format_relative_score(value)


@st.cache_data(ttl=30, show_spinner=False)
def load_competition_data(tournament_id: str, tournament_rules: dict):
    client = db.get_supabase_client()
    if client is None:
        return None

    teams = db.fetch_teams(client, tournament_id)
    players = db.fetch_players(client, tournament_id)
    team_players = db.fetch_team_players(client, tournament_id)
    scores = db.fetch_scores(client, tournament_id)
    status_events = db.fetch_player_status_events(client, tournament_id)
    tournament_rounds = db.fetch_tournament_rounds(client, tournament_id)
    try:
        roster_change_rows = db.fetch_active_roster_changes(client, tournament_id)
    except Exception:
        roster_change_rows = []
    try:
        live_states = db.fetch_live_player_states(client, tournament_id)
    except Exception:
        live_states = []
    standings = scoring.build_team_standings(
        teams=teams,
        players=players,
        team_players=team_players,
        scores=scores,
        num_rounds=tournament_rules.get("num_rounds", 4),
        counting_scores=tournament_rules.get("counting_scores", 5),
        dropped_scores=tournament_rules.get("dropped_scores", 2),
        player_status_events=status_events,
        tournament_rounds=tournament_rounds,
        live_states=live_states,
        roster_change_rows=roster_change_rows,
        course_par=int(tournament_rules.get("course_par", 72)),
    )
    return {
        "teams": teams,
        "players": players,
        "team_players": team_players,
        "scores": scores,
        "status_events": status_events,
        "tournament_rounds": tournament_rounds,
        "live_states": live_states,
        "roster_changes": roster_change_rows,
        "standings": standings,
    }


def clear_data_cache() -> None:
    load_competition_data.clear()


def init_sync_state() -> None:
    if "auto_sync_enabled" not in st.session_state:
        st.session_state.auto_sync_enabled = True
    if "datagolf_sync_status" not in st.session_state:
        st.session_state.datagolf_sync_status = None
    if "datagolf_diagnostic_result" not in st.session_state:
        st.session_state.datagolf_diagnostic_result = None


def format_sync_timestamp(value: datetime | None) -> str:
    if value is None:
        return "Never"
    return time_display.format_oslo_time(value)


def get_app_secrets() -> dict[str, str]:
    return {
        "SUPABASE_URL": st.secrets.get("SUPABASE_URL", ""),
        "SUPABASE_ANON_KEY": st.secrets.get("SUPABASE_ANON_KEY", ""),
        "SUPABASE_SERVICE_ROLE_KEY": st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        "DATA_GOLF_API_KEY": st.secrets.get("DATA_GOLF_API_KEY", ""),
    }


def perform_datagolf_test() -> datagolf_sync.DataGolfDiagnosticResult:
    result = datagolf_sync.execute_datagolf_diagnostic(get_app_secrets())
    st.session_state.datagolf_diagnostic_result = result
    return result


def render_datagolf_diagnostics_panel(
    tournament: dict,
    diagnostic: datagolf_sync.DataGolfDiagnosticResult | None,
    last_sync: datagolf_sync.SyncResult | None,
) -> None:
    st.subheader("DataGolf diagnostics")
    st.caption("Read-only check against the live in-play feed. No scores are saved.")

    st.markdown("**Active tournament**")
    st.write(f"- Name: `{tournament.get('name')}`")
    st.write(f"- Display title: `{db.tournament_display_title(tournament)}`")
    st.write(f"- DataGolf event name: `{tournament.get('datagolf_event_name') or '—'}`")
    st.write(f"- Tournament ID: `{tournament['id']}`")

    st.divider()
    st.markdown("**Last score sync (writes to database)**")
    if last_sync is None:
        st.info("No score sync has been run in this session.")
    else:
        st.write(f"- Time: {format_sync_timestamp(last_sync.synced_at)}")
        st.write(f"- Status: {'Success' if last_sync.success else 'Failed'}")
        if last_sync.event_name:
            st.write(f"- DataGolf event: `{last_sync.event_name}`")
        if last_sync.error:
            st.error(last_sync.error)

    st.divider()
    if st.button("Test DataGolf", type="primary", key="test_datagolf_feed"):
        with st.spinner("Fetching live DataGolf feed (no database writes)..."):
            perform_datagolf_test()
        st.rerun()

    if diagnostic is None:
        st.caption("Click **Test DataGolf** to run a live feed check.")
        return

    st.markdown("**Latest diagnostic test**")
    st.write(f"- Checked at: {format_sync_timestamp(diagnostic.checked_at)}")
    st.write(f"- DataGolf event received: `{diagnostic.datagolf_event_name or '—'}`")
    st.write(f"- Event matches active tournament: **{'Yes' if diagnostic.event_found else 'No'}**")

    if diagnostic.error:
        st.error(diagnostic.error)
    elif diagnostic.event_found:
        st.success(
            f"DataGolf feed matches expected event "
            f"('{diagnostic.expected_event_name or diagnostic.datagolf_event_name}')."
        )

    if diagnostic.warning:
        st.warning(diagnostic.warning)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Players in feed", diagnostic.players_received)
    col2.metric("Players with scores", diagnostic.players_with_scores)
    col3.metric("Matched in DB", diagnostic.matched_count)
    col4.metric("Unmatched", diagnostic.unmatched_count)
    st.caption(f"Players in database for active tournament: {diagnostic.db_players_count}")

    if diagnostic.current_round is not None:
        st.caption(f"DataGolf current round: {diagnostic.current_round}")

    if diagnostic.matched_players:
        with st.expander(f"Matched players ({diagnostic.matched_count})", expanded=False):
            for name in diagnostic.matched_players:
                st.write(name)

    if diagnostic.unmatched_players:
        with st.expander(f"Unmatched players ({diagnostic.unmatched_count})", expanded=True):
            for name in diagnostic.unmatched_players:
                st.write(name)


def perform_live_sync() -> datagolf_sync.SyncResult:
    result = datagolf_sync.execute_sync(get_app_secrets())
    st.session_state.datagolf_sync_status = result
    if result.success:
        clear_data_cache()
    return result


@st.cache_resource
def sync_coordinator() -> dict:
    """Coordinate public sessions so one app process performs one due sync."""
    return {"lock": Lock(), "last_attempt": None}


def perform_live_sync_if_due() -> datagolf_sync.SyncResult | None:
    coordinator = sync_coordinator()
    now = datetime.now(timezone.utc)
    with coordinator["lock"]:
        last_attempt = coordinator["last_attempt"]
        if last_attempt is not None and now - last_attempt < timedelta(minutes=4, seconds=30):
            return None
        coordinator["last_attempt"] = now
    return perform_live_sync()


def render_datagolf_sync_status(result: datagolf_sync.SyncResult | None, tournament: dict | None) -> None:
    if tournament is not None:
        expected = tournament.get("datagolf_event_name") or "—"
        st.caption(f"Active tournament: {db.tournament_display_title(tournament)}")
        st.caption(f"Expected DataGolf event: {expected}")

    if result is None:
        label = tournament.get("datagolf_event_name") if tournament else "the active tournament"
        st.info(f"No sync has been run yet. Click the button above to fetch scores from DataGolf ({label}).")
        return

    status_label = "Success" if result.success else "Failed"
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Last sync", format_sync_timestamp(result.synced_at))
    col2.metric("Scores updated", result.scores_written)
    col3.metric("Matched players", len(result.matched_players))
    col4.metric("Unmatched players", len(result.unmatched_players))

    st.caption(f"Status: {status_label}")
    if result.event_name:
        st.caption(f"DataGolf event received: {result.event_name}")
    if result.expected_event_name:
        st.caption(f"DataGolf event expected: {result.expected_event_name}")
    if result.warning:
        st.warning(result.warning)

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


def render_sync_status(tournament: dict | None) -> None:
    render_datagolf_sync_status(st.session_state.get("datagolf_sync_status"), tournament)


@st.fragment(run_every=timedelta(seconds=30))
def live_feed_fragment(tournament_id: str) -> None:
    """Refresh the stored feed without requiring a full page reload."""
    client = db.get_supabase_client()
    if client is None:
        return
    try:
        events = db.fetch_live_feed_events(client, tournament_id, limit=15)
        roster_rows = db.fetch_team_players(client, tournament_id)
    except Exception:
        styles.render_live_feed([], {})
        st.caption("Livefeeden aktiveres når live-feed-skjemaet er installert i Supabase.")
        return

    affected_teams = live_feed.group_affected_teams(roster_rows)
    styles.render_live_feed(events, affected_teams)


@st.fragment(run_every=timedelta(minutes=5))
def datagolf_auto_sync_fragment(tournament: dict) -> None:
    if not tournament.get("is_active"):
        return
    if st.session_state.get("auto_sync_enabled"):
        result = perform_live_sync_if_due()
        if result is not None and result.success:
            st.rerun()


def get_client_or_warn() -> Client | None:
    client = db.get_supabase_client()
    if client is None:
        st.error(
            "Supabase is not configured. Add `SUPABASE_URL` and `SUPABASE_ANON_KEY` "
            "to `.streamlit/secrets.toml`, then restart the app."
        )
    return client


def get_write_client_or_warn() -> Client | None:
    client = db.get_supabase_write_client()
    if client is None:
        st.error(
            "Admin writes require `SUPABASE_URL` and the server-only "
            "`SUPABASE_SERVICE_ROLE_KEY` in Streamlit secrets."
        )
    return client


def render_tier_player_selectors(
    players: list[dict],
    key_prefix: str,
    defaults: set[str] | None = None,
) -> list[str]:
    defaults = defaults or set()
    selected: list[str] = []
    for tier in participant_admin.REQUIRED_TIERS:
        tier_players = [player for player in players if int(player["tier"]) == tier]
        name_by_id = {str(player["id"]): str(player["name"]) for player in tier_players}
        options: list[str | None] = [None, *name_by_id]
        default_id = next((player_id for player_id in name_by_id if player_id in defaults), None)
        choice = st.selectbox(
            f"Tier {tier}",
            options,
            index=options.index(default_id),
            format_func=lambda value, names=name_by_id: names.get(value, "Velg spiller"),
            key=f"{key_prefix}_tier_{tier}",
        )
        if choice is not None:
            selected.append(choice)
    return selected


def participant_preview(name: str, selected_ids: list[str], players: list[dict]) -> None:
    players_by_id = {str(player["id"]): player for player in players}
    st.markdown("**Forhåndsvisning**")
    st.write(f"Deltaker: **{name.strip() or '—'}**")
    rows = [
        {"Tier": players_by_id[player_id]["tier"], "Spiller": players_by_id[player_id]["name"]}
        for player_id in selected_ids
        if player_id in players_by_id
    ]
    if rows:
        st.dataframe(pd.DataFrame(rows).sort_values("Tier"), hide_index=True, use_container_width=True)
    else:
        st.caption("Ingen spillere valgt ennå.")


def render_roster_change_dashboard(
    total_teams: int,
    completed_teams: int,
    changes_used: int,
    window_is_open: bool,
) -> None:
    columns = st.columns(5)
    columns[0].metric("Lag", total_teams)
    columns[1].metric("Ferdige", completed_teams)
    columns[2].metric("Mangler", total_teams - completed_teams)
    columns[3].metric(
        "Bytter brukt",
        f"{changes_used} / {total_teams * roster_changes.MAX_CHANGES_PER_TEAM}",
    )
    columns[4].metric("Status", "🟢 Åpent" if window_is_open else "🔴 Stengt")


def reset_roster_team(
    editor_prefix: str,
    team_id: str,
    player_ids: list[str],
) -> None:
    for slot, player_id in enumerate(player_ids, start=1):
        st.session_state[f"{editor_prefix}_{team_id}_{slot}"] = player_id


def roster_change_export_csv(
    teams: list[dict],
    players: list[dict],
    change_rows: list[dict],
) -> bytes:
    players_by_id = {str(player["id"]): str(player["name"]) for player in players}
    teams_by_id = {str(team["id"]): str(team["name"]) for team in teams}
    rows = []
    for change in change_rows:
        team_label = teams_by_id.get(str(change["team_id"]), str(change["team_id"]))
        changed_at = change.get("changed_at")
        timestamp = ""
        if changed_at:
            try:
                timestamp = time_display.to_oslo_datetime(changed_at).strftime("%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                timestamp = str(changed_at)
        rows.append(
            {
                "Lag": team_label,
                "OUT spiller": players_by_id.get(
                    str(change["old_player_id"]), change["old_player_id"]
                ),
                "IN spiller": players_by_id.get(
                    str(change["new_player_id"]), change["new_player_id"]
                ),
                "Tidspunkt": timestamp,
                "Admin": str(change.get("changed_by") or ""),
            }
        )
    columns = ["Lag", "OUT spiller", "IN spiller", "Tidspunkt", "Admin"]
    return pd.DataFrame(rows, columns=columns).to_csv(index=False).encode("utf-8-sig")


def render_roster_change_summary(
    teams: list[dict],
    players: list[dict],
    change_rows: list[dict],
    *,
    heading: str,
) -> None:
    if not change_rows:
        return
    players_by_id = {str(player["id"]): str(player["name"]) for player in players}
    changes_by_team: dict[str, list[dict]] = {}
    for row in change_rows:
        changes_by_team.setdefault(str(row["team_id"]), []).append(row)

    st.markdown(f"#### {heading}")
    for team in teams:
        team_changes = changes_by_team.get(str(team["id"]), [])
        if not team_changes:
            continue
        with st.container(border=True):
            st.markdown(f"**{team['name']}**")
            out_col, in_col = st.columns(2)
            with out_col:
                st.markdown("**OUT**")
                for row in team_changes:
                    st.write(players_by_id.get(str(row["old_player_id"]), row["old_player_id"]))
            with in_col:
                st.markdown("**IN**")
                for row in team_changes:
                    st.write(players_by_id.get(str(row["new_player_id"]), row["new_player_id"]))


def render_roster_change_overview(
    teams: list[dict],
    players: list[dict],
    change_rows: list[dict],
) -> None:
    if not change_rows:
        return
    players_by_id = {str(player["id"]): str(player["name"]) for player in players}
    changes_by_team: dict[str, list[dict]] = {}
    for row in change_rows:
        changes_by_team.setdefault(str(row["team_id"]), []).append(row)

    st.markdown("### Bytteoversikt")
    st.caption("Alle lag og de sist lagrede spillerbyttene.")
    for team in teams:
        team_changes = changes_by_team.get(str(team["id"]), [])
        with st.container(border=True):
            st.markdown(f"**{team['name']}**")
            out_col, in_col = st.columns(2)
            with out_col:
                st.markdown("**OUT**")
                if not team_changes:
                    st.write("—")
                for row in team_changes:
                    st.write(players_by_id.get(str(row["old_player_id"]), row["old_player_id"]))
            with in_col:
                st.markdown("**IN**")
                if not team_changes:
                    st.write("—")
                for row in team_changes:
                    st.write(players_by_id.get(str(row["new_player_id"]), row["new_player_id"]))

    incoming = Counter(
        players_by_id.get(str(row["new_player_id"]), str(row["new_player_id"]))
        for row in change_rows
    )
    outgoing = Counter(
        players_by_id.get(str(row["old_player_id"]), str(row["old_player_id"]))
        for row in change_rows
    )
    st.markdown("#### Oppsummering")
    in_col, out_col = st.columns(2)
    with in_col:
        st.markdown("**Mest populære inn:**")
        for player_name, count in incoming.most_common(3):
            st.write(f"{player_name} ({count})")
    with out_col:
        st.markdown("**Mest populære ut:**")
        for player_name, count in outgoing.most_common(3):
            st.write(f"{player_name} ({count})")

    st.download_button(
        "📥 Last ned bytter (CSV)",
        data=roster_change_export_csv(teams, players, change_rows),
        file_name="bytter.csv",
        mime="text/csv",
        use_container_width=True,
    )


@st.dialog("Bekreft spillerbytter")
def confirm_roster_changes_dialog(
    client: Client,
    tournament_id: str,
    original_by_team: dict[str, list[str]],
    selected_by_team: dict[str, list[str]],
    valid_player_ids: set[str],
    teams: list[dict],
    players: list[dict],
) -> None:
    change_pairs = roster_changes.build_change_pairs(original_by_team, selected_by_team)
    render_roster_change_summary(
        teams,
        players,
        change_pairs,
        heading="Sammendrag før lagring",
    )
    st.write("Du er i ferd med å gjennomføre spillerbytter.")
    st.write("Disse vil gjelde fra og med runde 3.")
    st.write("Runde 1 og 2 endres ikke.")
    st.markdown("**Er du sikker?**")
    cancel_col, confirm_col = st.columns(2)
    if cancel_col.button("Kanseller", use_container_width=True):
        st.rerun()
    if confirm_col.button(
        "Ja, gjennomfør bytter",
        type="primary",
        use_container_width=True,
    ):
        try:
            current_tournament = db.get_active_tournament(client)
            window_is_open = bool(
                current_tournament
                and current_tournament.get("roster_change_window_open", False)
            )
            roster_changes.save_roster_changes(
                client,
                tournament_id,
                original_by_team,
                selected_by_team,
                valid_player_ids,
                window_is_open=window_is_open,
                changed_by="admin",
            )
            clear_data_cache()
            st.session_state.roster_changes_saved = True
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def page_leaderboard() -> None:
    client = get_client_or_warn()
    if client is None:
        return

    tournament = db.get_active_tournament(client)
    if not tournament:
        styles.render_hero("Leaderboard", "No active tournament configured")
        st.info("Set one tournament row to `is_active = true` in the tournaments table.")
        return

    styles.render_hero("Leaderboard", db.tournament_subtitle(tournament))

    data = load_competition_data(tournament["id"], tournament)
    standings = data["standings"]
    selected_team_id = st.query_params.get("team")
    if isinstance(selected_team_id, list):
        selected_team_id = selected_team_id[0] if selected_team_id else None
    valid_team_ids = {str(standing.team_id) for standing in standings}
    if selected_team_id not in valid_team_ids:
        selected_team_id = None

    if not standings:
        st.info("No teams found for the active tournament.")
        return

    styles.render_stat_cards(
        [
            ("Lag", str(len(standings))),
            ("Runder", "4"),
            ("1. plass", "4 500 kr"),
        ]
    )

    styles.render_rules_banner()

    with st.expander("Live scoring-status", expanded=False):
        render_sync_status(tournament)

    rows = []
    for index, standing in enumerate(standings, start=1):
        rows.append(
            {
                "Rank": index,
                "Team ID": str(standing.team_id),
                "Team": standing.team_name,
                "Selected": str(standing.team_id) == selected_team_id,
                "Preview href": leaderboard_preview.preview_href(
                    selected_team_id,
                    str(standing.team_id),
                ),
                "Round 1": format_score(standing.round_totals.get(1)),
                "Round 2": format_score(standing.round_totals.get(2)),
                "Round 3": format_score(standing.round_totals.get(3)),
                "Round 4": format_score(standing.round_totals.get(4)),
                "Total": format_score(standing.tournament_total),
            }
        )

    styles.render_leaderboard_table(rows)
    if selected_team_id:
        selected_standing = next(
            standing for standing in standings if str(standing.team_id) == selected_team_id
        )
        active_round = leaderboard_preview.active_round_number(
            data["scores"],
            data["live_states"],
            num_rounds=int(tournament.get("num_rounds", 4)),
        )
        preview_rows = leaderboard_preview.build_preview_rows(
            selected_standing,
            active_round,
            data["live_states"],
        )
        styles.render_team_preview(
            selected_standing.team_name,
            active_round,
            selected_standing.tournament_total,
            preview_rows,
        )
    live_feed_fragment(str(tournament["id"]))


def page_team_detail() -> None:
    client = get_client_or_warn()
    if client is None:
        return

    tournament = db.get_active_tournament(client)
    if not tournament:
        styles.render_hero("Team Detail", "No active tournament configured")
        st.info("Set one tournament row to `is_active = true` in the tournaments table.")
        return

    styles.render_hero("Team Detail", db.tournament_display_title(tournament))

    data = load_competition_data(tournament["id"], tournament)
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
                "Type": (
                    f"Straff ({player.status})"
                    if player.score_kind == "PENALTY"
                    else "Faktisk score"
                ),
            }
            for player in round_result.counting
        ]
        dropped_rows = [
            {
                "Player": player.player_name,
                "Tier": player.tier,
                "Strokes": format_score(player.strokes),
                "Type": (
                    f"Straff ({player.status})"
                    if player.score_kind == "PENALTY"
                    else (player.status or "Ikke tellende")
                ),
            }
            for player in round_result.dropped
        ]
        undecided_rows = [
            {
                "Player": player.player_name,
                "Tier": player.tier,
                "Strokes": format_score(player.strokes),
                "Type": "Ikke avgjort",
            }
            for player in round_result.undecided
        ]

        left, middle, right = st.columns(3)
        with left:
            st.markdown("**Counting (5)**")
            if counting_rows:
                st.dataframe(pd.DataFrame(counting_rows), use_container_width=True, hide_index=True)
            else:
                st.caption("Not enough scores entered yet.")
        with middle:
            st.markdown("**Dropped (2)**")
            if dropped_rows:
                st.dataframe(pd.DataFrame(dropped_rows), use_container_width=True, hide_index=True)
            else:
                st.caption("No dropped players yet.")
        with right:
            st.markdown("**Ikke avgjort**")
            if undecided_rows:
                st.dataframe(
                    pd.DataFrame(undecided_rows),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("Ingen uavklarte spillere.")


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

    client = get_write_client_or_warn()
    if client is None:
        return

    tournament = db.get_active_tournament(client)
    if not tournament:
        st.error("No active tournament found. Configure `is_active = true` on one row in tournaments.")
        return

    st.success("Admin session active.")
    if st.button("Log out"):
        auth.logout_admin()
        st.rerun()

    (
        tab_tournament,
        tab_datagolf,
        tab_import,
        tab_teams,
        tab_players,
        tab_rosters,
        tab_swaps,
        tab_scorer,
        tab_status,
        tab_reset,
    ) = st.tabs(
        [
            "Tournament",
            "DataGolf",
            "Import",
            "Teams",
            "Players",
            "Rosters",
            "Bytter",
            "Scorer",
            "Statuses & penalties",
            "Reset",
        ]
    )

    with tab_tournament:
        render_active_tournament_info(tournament)
        st.divider()
        st.markdown("### All tournaments")
        render_tournament_catalog(client, tournament)
        st.caption("The clean production schema seeds The Open 2026 as the active tournament.")

    with tab_datagolf:
        render_datagolf_diagnostics_panel(
            tournament,
            st.session_state.get("datagolf_diagnostic_result"),
            st.session_state.get("datagolf_sync_status"),
        )

    with tab_import:
        excel_default = default_excel_path(tournament)
        st.subheader("Import Excel roster")
        st.caption(f"Default file for active tournament: `{excel_default}`")

        uploaded = st.file_uploader("Upload new Excel roster file", type=["xlsx"])
        use_default = st.checkbox("Use default project Excel file", value=True)

        if st.button("Import roster", type="primary"):
            try:
                if uploaded is not None:
                    temp_path = Path("data/uploaded_roster.xlsx")
                    temp_path.parent.mkdir(parents=True, exist_ok=True)
                    temp_path.write_bytes(uploaded.getvalue())
                    result = excel_import.import_workbook(client, temp_path)
                elif use_default and excel_default.exists():
                    result = excel_import.import_workbook(client, excel_default)
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
        st.subheader("Legg til deltaker")
        teams = db.fetch_teams(client, tournament["id"])
        players = db.fetch_players(client, tournament["id"])
        team_players = db.fetch_team_players(client, tournament["id"])
        scores_registered = bool(db.fetch_scores(client, tournament["id"]))
        audit_rows = db.fetch_admin_audit(client, limit=1000)
        created_team_ids = participant_admin.created_participant_ids(audit_rows)

        st.caption("Velg nøyaktig én spiller fra hver av tier 1–7.")
        participant_name = st.text_input("Deltakernavn", key="new_participant_name")
        selected_player_ids = render_tier_player_selectors(players, "new_participant")
        validation = participant_admin.validate_participant(
            participant_name, selected_player_ids, players, teams
        )
        participant_preview(participant_name, selected_player_ids, players)
        for error in validation.errors:
            st.warning(error)
        confirmed = st.checkbox(
            "Jeg bekrefter at navn og alle sju spillervalg er korrekte.",
            key="confirm_new_participant",
        )
        if st.button(
            "Opprett deltaker",
            type="primary",
            disabled=not validation.is_valid or not confirmed,
        ):
            participant_admin.create_participant(
                client,
                tournament["id"],
                participant_name,
                selected_player_ids,
                players,
                teams,
            )
            clear_data_cache()
            st.success(f"Deltakeren {participant_name.strip()} er opprettet.")
            st.rerun()

        st.divider()
        st.subheader("Rediger ny deltaker")
        editable_teams = [team for team in teams if str(team["id"]) in created_team_ids]
        if not editable_teams:
            st.caption("Ingen deltakere er lagt til etter hovedimporten.")
        elif scores_registered:
            st.warning("Redigering er låst fordi første score er registrert.")
        else:
            edit_team = st.selectbox(
                "Deltaker",
                editable_teams,
                format_func=lambda team: team["name"],
                key="edit_new_participant_team",
            )
            current_ids = {
                str(link["player_id"])
                for link in team_players
                if str(link["team_id"]) == str(edit_team["id"])
            }
            edit_name = st.text_input(
                "Deltakernavn",
                value=edit_team["name"],
                key=f"edit_participant_name_{edit_team['id']}",
            )
            edited_player_ids = render_tier_player_selectors(
                players,
                f"edit_participant_{edit_team['id']}",
                defaults=current_ids,
            )
            edit_validation = participant_admin.validate_participant(
                edit_name,
                edited_player_ids,
                players,
                teams,
                exclude_team_id=str(edit_team["id"]),
            )
            participant_preview(edit_name, edited_player_ids, players)
            for error in edit_validation.errors:
                st.warning(error)
            edit_confirmed = st.checkbox(
                "Jeg bekrefter endringene.",
                key=f"confirm_edit_participant_{edit_team['id']}",
            )
            if st.button(
                "Lagre endringer",
                disabled=not edit_validation.is_valid or not edit_confirmed,
            ):
                participant_admin.update_participant(
                    client,
                    edit_team,
                    edit_name,
                    edited_player_ids,
                    players,
                    teams,
                    sorted(current_ids),
                    scores_registered=False,
                )
                clear_data_cache()
                st.success("Deltakeren er oppdatert.")
                st.rerun()

        st.divider()
        st.subheader("Alle deltakere")
        for team in teams:
            label = "Ny deltaker" if str(team["id"]) in created_team_ids else "Hovedimport"
            st.write(f"{team['name']} — {label}")

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
        st.subheader("Laguttak")
        st.info(
            "Nye deltakere opprettes og redigeres under Teams. "
            "De sju lagene fra hovedimporten er skrivebeskyttet her."
        )

    with tab_swaps:
        st.subheader("Bytter")
        st.caption(
            "Byttene gjelder fra og med runde 3. Opprinnelig laguttak og scorer "
            "fra runde 1 og 2 beholdes uendret."
        )
        tournament_id = str(tournament["id"])
        try:
            if "roster_change_window_open" not in tournament:
                raise RuntimeError("Manual roster-change window migration is missing.")
            active_change_set = db.fetch_active_roster_change_set(client, tournament_id)
            active_change_rows = db.fetch_active_roster_changes(
                client,
                tournament_id,
                active_change_set,
            )
        except Exception:
            st.error(
                "Byttefunksjonen krever databasemigrasjonene "
                "`005_roster_changes.sql`, `006_atomic_roster_change_window.sql` og "
                "`007_manual_roster_change_window.sql`."
            )
        else:
            teams = db.fetch_teams(client, tournament_id)
            players = db.fetch_players(client, tournament_id)
            team_players = db.fetch_team_players(client, tournament_id)
            players_by_id = {str(player["id"]): player for player in players}
            original_by_team = roster_changes.build_original_rosters(
                teams,
                players,
                team_players,
            )
            current_by_team = roster_changes.apply_roster_changes(
                original_by_team,
                active_change_rows,
            )

            window_is_open = bool(tournament.get("roster_change_window_open", False))
            control_col, status_col = st.columns([2, 1])
            status_col.metric(
                "🔓 Byttevindu",
                "ÅPENT" if window_is_open else "STENGT",
            )
            if control_col.button(
                "Steng byttevindu" if window_is_open else "Åpne byttevindu",
                type="primary" if not window_is_open else "secondary",
                use_container_width=True,
                key="toggle_roster_change_window",
            ):
                try:
                    db.set_roster_change_window(
                        client,
                        tournament_id,
                        not window_is_open,
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Kunne ikke endre byttevinduet: {exc}")

            change_set_key = str(active_change_set["id"]) if active_change_set else "original"
            editor_prefix = f"roster_editor_{tournament_id}_{change_set_key}"
            for team in teams:
                team_id = str(team["id"])
                for slot, player_id in enumerate(current_by_team.get(team_id, []), start=1):
                    state_key = f"{editor_prefix}_{team_id}_{slot}"
                    if state_key not in st.session_state:
                        st.session_state[state_key] = player_id

            selected_by_team = {
                str(team["id"]): [
                    str(st.session_state.get(
                        f"{editor_prefix}_{team['id']}_{slot}",
                        "",
                    ))
                    for slot in range(1, roster_changes.ROSTER_SIZE + 1)
                ]
                for team in teams
            }
            changes_by_team = roster_changes.change_count_by_team(
                original_by_team,
                selected_by_team,
            )
            valid_player_ids = set(players_by_id)
            valid_changed_teams = {
                team_id
                for team_id, count in changes_by_team.items()
                if count > 0
                and roster_changes.validate_rosters(
                    {team_id: selected_by_team[team_id]},
                    valid_player_ids,
                    {team_id: original_by_team[team_id]},
                ).is_valid
            }
            render_roster_change_dashboard(
                len(teams),
                len(valid_changed_teams),
                sum(changes_by_team.values()),
                window_is_open,
            )

            if st.session_state.pop("roster_changes_saved", False):
                st.success("Alle spillerbytter er lagret.")
            render_roster_change_overview(teams, players, active_change_rows)

            if not window_is_open:
                st.warning("Byttevinduet er stengt.")
            else:
                owner_by_team = {str(team["id"]): str(team["name"]) for team in teams}
                search_query = st.text_input(
                    "Søk i lag, eier eller spiller",
                    placeholder="For eksempel Scottie, Fleetwood eller Joakim",
                    key=f"{editor_prefix}_search",
                ).strip().casefold()
                visible_teams = []
                for team in teams:
                    team_id = str(team["id"])
                    searchable = [str(team["name"])]
                    searchable.extend(
                        str(players_by_id[player_id]["name"])
                        for player_id in {
                            *original_by_team.get(team_id, []),
                            *selected_by_team.get(team_id, []),
                        }
                        if player_id in players_by_id
                    )
                    if not search_query or any(
                        search_query in value.casefold() for value in searchable
                    ):
                        visible_teams.append(team)

                if visible_teams:
                    navigation = " · ".join(
                        f"[{escape(str(team['name']))}](#bytter-{team['id']})"
                        for team in visible_teams
                    )
                    st.markdown(f"**Hurtignavigasjon:** {navigation}")
                else:
                    st.info("Ingen lag eller spillere samsvarer med søket.")

                for team in visible_teams:
                    team_id = str(team["id"])
                    original_ids = original_by_team.get(team_id, [])
                    current_ids = current_by_team.get(team_id, [])
                    team_selected = selected_by_team.get(team_id, [])
                    changes_used = changes_by_team.get(team_id, 0)
                    team_validation = roster_changes.validate_rosters(
                        {team_id: team_selected},
                        valid_player_ids,
                        {team_id: original_ids},
                    )
                    is_complete = changes_used > 0 and team_validation.is_valid
                    st.markdown(
                        f'<div id="bytter-{escape(team_id)}"></div>',
                        unsafe_allow_html=True,
                    )
                    with st.container(border=True):
                        title_col, reset_col = st.columns([4, 1])
                        marker = "✅ " if is_complete else ""
                        title_col.markdown(
                            f"### {marker}{team['name']}  \n"
                            f"Bytter brukt: **{changes_used} / "
                            f"{roster_changes.MAX_CHANGES_PER_TEAM}**"
                        )
                        reset_col.button(
                            "↩ Tilbakestill lag",
                            key=f"{editor_prefix}_{team_id}_reset",
                            on_click=reset_roster_team,
                            args=(editor_prefix, team_id, current_ids),
                            use_container_width=True,
                        )

                        selector_columns = st.columns(roster_changes.ROSTER_SIZE)
                        for slot, column in enumerate(selector_columns, start=1):
                            state_key = f"{editor_prefix}_{team_id}_{slot}"
                            selected_id = str(st.session_state.get(state_key, ""))
                            original_id = (
                                original_ids[slot - 1]
                                if slot <= len(original_ids)
                                else None
                            )
                            lock_unchanged_slot = (
                                changes_used >= roster_changes.MAX_CHANGES_PER_TEAM
                                and selected_id == original_id
                            )
                            column.selectbox(
                                f"Spiller {slot}",
                                options=list(players_by_id),
                                format_func=lambda value, lookup=players_by_id: str(
                                    lookup[value]["name"]
                                ),
                                key=state_key,
                                disabled=lock_unchanged_slot,
                            )

                        if changes_used >= roster_changes.MAX_CHANGES_PER_TEAM:
                            st.caption("Maks tre bytter er brukt. Uendrede spillervalg er låst.")
                        for error in team_validation.errors:
                            _, _, message = error.partition(": ")
                            st.error(message)
                        try:
                            team_pairs = roster_changes.build_change_pairs(
                                {team_id: original_ids},
                                {team_id: team_selected},
                            )
                        except ValueError:
                            team_pairs = []
                        for pair in team_pairs:
                            old_name = escape(str(players_by_id[pair["old_player_id"]]["name"]))
                            new_name = escape(str(players_by_id[pair["new_player_id"]]["name"]))
                            st.markdown(
                                '<span style="color:#777;text-decoration:line-through">'
                                f"{old_name}</span> ➜ "
                                f'<span style="color:#18864b;font-weight:700">{new_name}</span>',
                                unsafe_allow_html=True,
                            )

                validation = roster_changes.validate_rosters(
                    selected_by_team,
                    valid_player_ids,
                    original_by_team,
                )
                for error in validation.errors:
                    team_id, _, message = error.partition(": ")
                    st.error(f"{owner_by_team.get(team_id, team_id)}: {message}")

                has_edits = roster_changes.rosters_differ(
                    current_by_team,
                    selected_by_team,
                )
                if not has_edits and validation.is_valid:
                    st.caption("Velg minst ett spillerbytte før lagring.")
                if st.button(
                    "💾 Lagre alle bytter",
                    type="primary",
                    disabled=not validation.is_valid or not has_edits,
                    key="save_all_roster_changes",
                    use_container_width=True,
                ):
                    confirm_roster_changes_dialog(
                        client,
                        tournament_id,
                        original_by_team,
                        selected_by_team,
                        valid_player_ids,
                        teams,
                        players,
                    )

    with tab_scorer:
        st.subheader("Live scoring from DataGolf")

        if st.button(
            "Sync all scores from DataGolf now",
            type="primary",
            key="sync_all_scores_datagolf",
        ):
            with st.spinner(
                f"Fetching scores from DataGolf for {db.tournament_display_title(tournament)}..."
            ):
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

        render_datagolf_sync_status(st.session_state.get("datagolf_sync_status"), tournament)

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

    with tab_status:
        st.subheader("Player status")
        st.caption(
            "Only explicit CUT, WD, or DQ statuses can activate a frozen penalty. "
            "Admin changes are appended to the audit history."
        )
        players = db.fetch_players(client, tournament["id"])
        player_options = {player["name"]: player["id"] for player in players}
        if players:
            with st.form("player_status_override"):
                selected_player_name = st.selectbox("Player", list(player_options))
                selected_status = st.selectbox("Status", ["CUT", "WD", "DQ", "ACTIVE"])
                effective_round = st.selectbox(
                    "Effective from round",
                    [3] if selected_status == "CUT" else [1, 2, 3, 4],
                )
                status_note = st.text_input("Reason / note")
                if st.form_submit_button("Save status override"):
                    db.add_player_status_event(
                        client,
                        player_options[selected_player_name],
                        int(effective_round),
                        selected_status,
                        source="ADMIN",
                        note=status_note,
                    )
                    clear_data_cache()
                    st.success("Status override saved and audited.")
                    st.rerun()
        else:
            st.info("Import players before adding statuses.")

        st.divider()
        st.subheader("Freeze round penalty")
        st.caption(
            "Do this only after the round is finished and all official completed scores are present. "
            "The normal penalty is the field's highest official score plus "
            f"{tournament.get('missing_score_penalty', 2)} strokes."
        )
        round_rows = db.fetch_tournament_rounds(client, tournament["id"])
        if round_rows:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Round": row["round"],
                            "State": row["state"],
                            "Worst official": row.get("official_worst_score"),
                            "Frozen penalty": row.get("penalty_score"),
                            "Override": row.get("is_override", False),
                            "Reason": row.get("override_reason"),
                            "Frozen at": row.get("frozen_at"),
                        }
                        for row in round_rows
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )

        freeze_round = st.selectbox("Round to freeze", [1, 2, 3, 4], key="freeze_round")
        freeze_confirm = st.checkbox(
            "I confirm the round is finished and official completed scores are final.",
            key="freeze_confirm",
        )
        if st.button("Freeze calculated penalty", disabled=not freeze_confirm):
            try:
                saved = db.freeze_round_penalty(client, tournament, int(freeze_round))
                clear_data_cache()
                st.success(f"Round {freeze_round} penalty frozen at {saved['penalty_score']}.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        with st.form("penalty_override"):
            override_round = st.selectbox("Round", [1, 2, 3, 4], key="override_round")
            override_score = st.number_input("Override penalty score", min_value=50, max_value=200)
            override_reason = st.text_input("Required override reason")
            if st.form_submit_button("Save penalty override"):
                try:
                    saved = db.freeze_round_penalty(
                        client,
                        tournament,
                        int(override_round),
                        override_score=int(override_score),
                        override_reason=override_reason,
                    )
                    clear_data_cache()
                    st.success(f"Round {override_round} override saved at {saved['penalty_score']}.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        st.divider()
        st.subheader("Audit history")
        audit_rows = db.fetch_admin_audit(client)
        if audit_rows:
            st.dataframe(pd.DataFrame(audit_rows), hide_index=True, use_container_width=True)
        else:
            st.caption("No admin overrides recorded yet.")

    with tab_reset:
        st.subheader("Reset tournament")
        st.warning(
            f"This deletes all teams, players, rosters, and scores for "
            f"{db.tournament_display_title(tournament)}."
        )
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

    styles.render_sidebar_brand()
    active_label = "No active tournament"
    if client is not None:
        active = db.get_active_tournament(client)
        if active is not None:
            active_label = db.tournament_display_title(active)
    st.sidebar.caption(f"Aktiv turnering: {active_label}")
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
