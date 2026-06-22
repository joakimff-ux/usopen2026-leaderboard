"""Admin UI for tournament setup and safe resets."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from lib.tournament import (
    DEFAULT_TEMPLATES,
    TournamentConfig,
    create_tournament_from_template,
    list_tournaments,
    load_active_tournament,
    reset_rosters,
    reset_scores,
    reset_whole_tournament,
    save_tournament,
    set_active_tournament_id,
)


def render_tournament_setup(
    sb,
    data_dir: Path,
    *,
    import_excel_callback,
    import_field_callback,
    clear_cache_callback,
) -> None:
    st.subheader("Turnering setup")
    cfg = st.session_state.get("tournament_config", TournamentConfig.legacy_defaults())
    tournaments = list_tournaments(sb)

    if not tournaments:
        st.warning(
            "Turneringstabellen finnes ikke ennå. Kjør `migrations/008_tournaments.sql` i Supabase. "
            "Appen bruker legacy-innstillinger til migrering er kjørt."
        )
        return

    options = {f"{row['display_title']} ({row['slug']})": int(row["id"]) for row in tournaments}
    labels = list(options.keys())
    active_id = cfg.id if cfg.id is not None else list(options.values())[0]
    default_label = next((label for label, tid in options.items() if tid == active_id), labels[0])
    selected_label = st.selectbox("Aktiv turnering", labels, index=labels.index(default_label))
    selected_id = options[selected_label]

    if selected_id != active_id:
        if st.button("Bytt aktiv turnering", type="primary"):
            set_active_tournament_id(sb, selected_id)
            st.session_state.tournament_config = load_active_tournament(sb)
            clear_cache_callback()
            st.success("Aktiv turnering oppdatert.")
            st.rerun()

    st.divider()
    st.markdown("**Rediger turneringsinnstillinger**")
    c1, c2 = st.columns(2)
    tournament_name = c1.text_input("Turneringsnavn", value=cfg.tournament_name)
    display_title = c2.text_input("Visningstittel", value=cfg.display_title)
    datagolf_event = c1.text_input("DataGolf event name", value=cfg.datagolf_event_name or "")
    datagolf_tour = c2.text_input("DataGolf tour", value=cfg.datagolf_tour)
    course_name = c1.text_input("Bane", value=cfg.course_name or "")
    month_label = c2.text_input("Måned", value=cfg.month_label or "")
    prize_text = st.text_input("Premietekst", value=cfg.prize_text)

    c3, c4, c5 = st.columns(3)
    players_per_team = c3.number_input("Spillere per lag", min_value=1, max_value=12, value=cfg.number_of_players_per_team)
    counting_scores = c4.number_input("Teller per dag", min_value=1, max_value=10, value=cfg.counting_scores_per_day)
    dropped_scores = c5.number_input("Droppes per dag", min_value=0, max_value=10, value=cfg.dropped_scores_per_day)
    c6, c7, c8 = st.columns(3)
    rounds = c6.number_input("Antall runder", min_value=1, max_value=4, value=cfg.rounds)
    post_cut_round = c7.number_input("Post-cut fra runde", min_value=2, max_value=4, value=cfg.post_cut_swap_round)
    max_swaps = c8.number_input("Maks bytter", min_value=0, max_value=7, value=cfg.max_swaps)
    excel_path = st.text_input("Standard Excel-fil (i data/)", value=cfg.excel_default_path or "")

    if st.button("Lagre turneringsinnstillinger"):
        updated = TournamentConfig(
            id=cfg.id,
            slug=cfg.slug,
            tournament_name=tournament_name.strip(),
            display_title=display_title.strip(),
            datagolf_event_name=datagolf_event.strip() or None,
            datagolf_tour=datagolf_tour.strip() or "pga",
            course_name=course_name.strip() or None,
            month_label=month_label.strip() or None,
            prize_text=prize_text.strip() or "4.000 kr",
            number_of_players_per_team=int(players_per_team),
            counting_scores_per_day=int(counting_scores),
            dropped_scores_per_day=int(dropped_scores),
            rounds=int(rounds),
            post_cut_swap_round=int(post_cut_round),
            max_swaps=int(max_swaps),
            excel_default_path=excel_path.strip() or None,
            is_active=True,
            uses_tournament_scope=True,
        )
        saved = save_tournament(sb, updated)
        if saved:
            st.session_state.tournament_config = saved
            clear_cache_callback()
            st.success("Turneringsinnstillinger lagret.")
            st.rerun()
        else:
            st.error("Kunne ikke lagre turnering.")

    st.divider()
    st.markdown("**Opprett ny turnering fra mal**")
    template_slug = st.selectbox(
        "Mal",
        list(DEFAULT_TEMPLATES.keys()),
        format_func=lambda slug: DEFAULT_TEMPLATES[slug]["display_title"],
    )
    if st.button("Opprett turnering fra mal"):
        created = create_tournament_from_template(sb, template_slug)
        if created:
            st.success(f"Opprettet {created.display_title}. Bytt aktiv turnering for å bruke den.")
            st.rerun()
        else:
            st.error("Kunne ikke opprette turnering.")

    st.divider()
    st.markdown("**Import for aktiv turnering**")
    uploaded = st.file_uploader("Excel-oppsett for aktiv turnering", type=["xlsx"], key="tournament_excel_upload")
    if st.button("Importer Excel-roster for aktiv turnering"):
        import_excel_callback(uploaded.getvalue() if uploaded else None)
        st.success("Excel-import fullført.")
        st.rerun()
    if st.button("Importer fullt DataGolf-felt for aktiv turnering"):
        import_field_callback()
        st.rerun()

    st.divider()
    st.markdown("**Sikker tilbakestilling (aktiv turnering)**")
    st.caption("Eksisterende turneringer i databasen slettes ikke. Kun data for aktiv turnering påvirkes.")

    confirm_phrase = st.text_input(
        "Skriv BEKREFT for destruktive handlinger",
        key="tournament_reset_confirm",
    )
    confirmed = confirm_phrase.strip().upper() == "BEKREFT"
    tid = cfg.id
    if tid is None:
        st.info("Ingen aktiv turnering valgt.")
        return

    r1, r2, r3 = st.columns(3)
    if r1.button("Reset scores only", disabled=not confirmed):
        reset_scores(sb, tid)
        clear_cache_callback()
        st.success("Scorer og live_events for aktiv turnering er slettet.")
        st.rerun()
    if r2.button("Reset rosters only", disabled=not confirmed):
        reset_rosters(sb, tid)
        clear_cache_callback()
        st.success("Laguttak (team_players) for aktiv turnering er slettet.")
        st.rerun()
    if r3.button("Reset whole tournament", disabled=not confirmed):
        reset_whole_tournament(sb, tid)
        clear_cache_callback()
        st.success("All data for aktiv turnering er slettet (lag, spillere, scorer, kommentarer).")
        st.rerun()
