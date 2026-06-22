"""Unit tests for tournament configuration."""

from __future__ import annotations

from lib.tournament import (
    DEFAULT_TEMPLATES,
    TournamentConfig,
    event_name_matches,
)


def main() -> int:
    cfg = TournamentConfig.from_row(
        {
            "id": 2,
            "slug": "the-open-2026",
            "tournament_name": "The Open",
            "display_title": "The Open 2026 Kupongen",
            "datagolf_event_name": "The Open Championship",
            "datagolf_tour": "pga",
            "course_name": "Royal Birkdale",
            "month_label": "July",
            "prize_text": "4.000 kr",
            "number_of_players_per_team": 7,
            "counting_scores_per_day": 5,
            "dropped_scores_per_day": 2,
            "rounds": 4,
            "post_cut_swap_round": 3,
            "max_swaps": 3,
            "excel_default_path": "The Open 2026 - Resultater.xlsx",
            "is_active": True,
        }
    )
    assert cfg.display_title == "The Open 2026 Kupongen"
    assert cfg.roster_labels[1] == "Originalt lag"
    assert cfg.roster_labels[3] == "Etter bytter"
    assert cfg.roster_period_for_round(2) == (1, 2)
    assert cfg.roster_period_for_round(4) == (3, 4)
    assert len(cfg.rule_pills()) == 5

    open_template = DEFAULT_TEMPLATES["the-open-2026"]
    assert open_template["course_name"] == "Royal Birkdale"
    assert open_template["month_label"] == "July"

    assert event_name_matches(cfg, "The Open Championship")
    assert event_name_matches(cfg, "2026 The Open Championship")
    assert not event_name_matches(cfg, "U.S. Open")

    legacy = TournamentConfig.legacy_defaults()
    assert legacy.uses_tournament_scope is False
    assert legacy.rounds_list == [1, 2, 3, 4]

    print("All tournament tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
