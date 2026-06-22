"""Tournament configuration and scoped data operations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from supabase import Client

logger = logging.getLogger(__name__)

ACTIVE_TOURNAMENT_KEY = "active_tournament_id"

DEFAULT_TEMPLATES: dict[str, dict[str, Any]] = {
    "us-open-2026": {
        "slug": "us-open-2026",
        "tournament_name": "US Open",
        "display_title": "US Open 2026 Kupongen",
        "datagolf_event_name": "U.S. Open",
        "datagolf_tour": "pga",
        "course_name": None,
        "month_label": "June",
        "prize_text": "4.000 kr",
        "excel_default_path": "US Open 2026 - Resultater.xlsx",
    },
    "the-open-2026": {
        "slug": "the-open-2026",
        "tournament_name": "The Open",
        "display_title": "The Open 2026 Kupongen",
        "datagolf_event_name": "The Open Championship",
        "datagolf_tour": "pga",
        "course_name": "Royal Birkdale",
        "month_label": "July",
        "prize_text": "4.000 kr",
        "excel_default_path": "The Open 2026 - Resultater.xlsx",
    },
    "masters-2026": {
        "slug": "masters-2026",
        "tournament_name": "Masters",
        "display_title": "Masters 2026 Kupongen",
        "datagolf_event_name": "Masters Tournament",
        "datagolf_tour": "pga",
        "course_name": "Augusta National",
        "month_label": "April",
        "prize_text": "4.000 kr",
        "excel_default_path": "Masters 2026 - Resultater.xlsx",
    },
    "pga-championship-2026": {
        "slug": "pga-championship-2026",
        "tournament_name": "PGA Championship",
        "display_title": "PGA Championship 2026 Kupongen",
        "datagolf_event_name": "PGA Championship",
        "datagolf_tour": "pga",
        "course_name": None,
        "month_label": "May",
        "prize_text": "4.000 kr",
        "excel_default_path": "PGA Championship 2026 - Resultater.xlsx",
    },
}


@dataclass
class TournamentConfig:
    id: int | None = None
    slug: str = "legacy"
    tournament_name: str = "Fantasy Golf"
    display_title: str = "Fantasy Golf Kupongen"
    datagolf_event_name: str | None = None
    datagolf_tour: str = "pga"
    course_name: str | None = None
    month_label: str | None = None
    prize_text: str = "4.000 kr"
    number_of_players_per_team: int = 7
    counting_scores_per_day: int = 5
    dropped_scores_per_day: int = 2
    rounds: int = 4
    post_cut_swap_round: int = 3
    max_swaps: int = 3
    excel_default_path: str | None = None
    is_active: bool = True
    uses_tournament_scope: bool = False

    @property
    def rounds_list(self) -> list[int]:
        return list(range(1, self.rounds + 1))

    @property
    def days_list(self) -> list[str]:
        return [f"Dag {n}" for n in self.rounds_list]

    @property
    def pre_cut_from(self) -> int:
        return 1

    @property
    def pre_cut_to(self) -> int:
        return max(1, self.post_cut_swap_round - 1)

    @property
    def post_cut_from(self) -> int:
        return self.post_cut_swap_round

    @property
    def post_cut_to(self) -> int:
        return self.rounds

    @property
    def roster_labels(self) -> dict[int, str]:
        return {
            rnd: ("Originalt lag" if rnd < self.post_cut_swap_round else "Etter bytter")
            for rnd in self.rounds_list
        }

    def roster_period_for_round(self, round_no: int) -> tuple[int, int]:
        if round_no < self.post_cut_swap_round:
            return self.pre_cut_from, self.pre_cut_to
        return self.post_cut_from, self.post_cut_to

    def rule_pills(self) -> list[str]:
        return [
            f"🥇 1. plass: {self.prize_text}",
            f"{self.number_of_players_per_team} spillere per lag",
            f"{self.counting_scores_per_day} laveste scorer teller",
            f"{self.dropped_scores_per_day} dårligste droppes hver dag",
            "Lavest totalscore vinner",
        ]

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TournamentConfig:
        return cls(
            id=int(row["id"]),
            slug=str(row.get("slug") or "legacy"),
            tournament_name=str(row.get("tournament_name") or "Fantasy Golf"),
            display_title=str(row.get("display_title") or "Fantasy Golf Kupongen"),
            datagolf_event_name=row.get("datagolf_event_name"),
            datagolf_tour=str(row.get("datagolf_tour") or "pga"),
            course_name=row.get("course_name"),
            month_label=row.get("month_label"),
            prize_text=str(row.get("prize_text") or "4.000 kr"),
            number_of_players_per_team=int(row.get("number_of_players_per_team") or 7),
            counting_scores_per_day=int(row.get("counting_scores_per_day") or 5),
            dropped_scores_per_day=int(row.get("dropped_scores_per_day") or 2),
            rounds=int(row.get("rounds") or 4),
            post_cut_swap_round=int(row.get("post_cut_swap_round") or 3),
            max_swaps=int(row.get("max_swaps") or 3),
            excel_default_path=row.get("excel_default_path"),
            is_active=bool(row.get("is_active")),
            uses_tournament_scope=True,
        )

    @classmethod
    def legacy_defaults(cls) -> TournamentConfig:
        return cls(uses_tournament_scope=False)

    def to_payload(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "tournament_name": self.tournament_name,
            "display_title": self.display_title,
            "datagolf_event_name": self.datagolf_event_name,
            "datagolf_tour": self.datagolf_tour,
            "course_name": self.course_name,
            "month_label": self.month_label,
            "prize_text": self.prize_text,
            "number_of_players_per_team": self.number_of_players_per_team,
            "counting_scores_per_day": self.counting_scores_per_day,
            "dropped_scores_per_day": self.dropped_scores_per_day,
            "rounds": self.rounds,
            "post_cut_swap_round": self.post_cut_swap_round,
            "max_swaps": self.max_swaps,
            "excel_default_path": self.excel_default_path,
            "is_active": self.is_active,
        }


def _table_exists(client: Client | None, table: str) -> bool:
    if client is None:
        return False
    try:
        client.table(table).select("id").limit(1).execute()
        return True
    except Exception:
        return False


def list_tournaments(client: Client | None) -> list[dict[str, Any]]:
    if client is None or not _table_exists(client, "tournaments"):
        return []
    try:
        response = client.table("tournaments").select("*").order("created_at").execute()
        return response.data or []
    except Exception as exc:
        logger.warning("list_tournaments failed: %s", exc)
        return []


def get_active_tournament_id(client: Client | None) -> int | None:
    if client is None:
        return None
    try:
        from lib import app_settings

        value = app_settings.get_setting(client, ACTIVE_TOURNAMENT_KEY)
        if value:
            return int(value)
    except Exception:
        pass
    try:
        response = (
            client.table("tournaments")
            .select("id")
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if response.data:
            return int(response.data[0]["id"])
    except Exception:
        pass
    return None


def set_active_tournament_id(client: Client | None, tournament_id: int) -> bool:
    if client is None:
        return False
    try:
        client.table("tournaments").update({"is_active": False}).neq("id", 0).execute()
        client.table("tournaments").update({"is_active": True}).eq("id", int(tournament_id)).execute()
    except Exception as exc:
        logger.warning("Could not update is_active flags: %s", exc)
    from lib import app_settings

    return app_settings.set_setting(client, ACTIVE_TOURNAMENT_KEY, str(int(tournament_id)))


def load_active_tournament(client: Client | None) -> TournamentConfig:
    if client is None or not _table_exists(client, "tournaments"):
        return TournamentConfig.legacy_defaults()

    tournament_id = get_active_tournament_id(client)
    if tournament_id is None:
        rows = list_tournaments(client)
        if rows:
            return TournamentConfig.from_row(rows[0])
        return TournamentConfig.legacy_defaults()

    try:
        response = client.table("tournaments").select("*").eq("id", tournament_id).limit(1).execute()
        if response.data:
            return TournamentConfig.from_row(response.data[0])
    except Exception as exc:
        logger.warning("load_active_tournament failed: %s", exc)
    return TournamentConfig.legacy_defaults()


def save_tournament(client: Client | None, config: TournamentConfig) -> TournamentConfig | None:
    if client is None or not _table_exists(client, "tournaments"):
        return None
    payload = config.to_payload()
    try:
        if config.id is None:
            response = client.table("tournaments").insert(payload).execute()
        else:
            response = client.table("tournaments").update(payload).eq("id", int(config.id)).execute()
        if response.data:
            saved = TournamentConfig.from_row(response.data[0])
            if saved.is_active:
                set_active_tournament_id(client, int(saved.id))
            return saved
    except Exception as exc:
        logger.error("save_tournament failed: %s", exc)
    return None


def create_tournament_from_template(client: Client | None, template_slug: str) -> TournamentConfig | None:
    template = DEFAULT_TEMPLATES.get(template_slug)
    if template is None or client is None:
        return None
    config = TournamentConfig(
        slug=template["slug"],
        tournament_name=template["tournament_name"],
        display_title=template["display_title"],
        datagolf_event_name=template.get("datagolf_event_name"),
        datagolf_tour=template.get("datagolf_tour", "pga"),
        course_name=template.get("course_name"),
        month_label=template.get("month_label"),
        prize_text=template.get("prize_text", "4.000 kr"),
        excel_default_path=template.get("excel_default_path"),
        is_active=False,
    )
    return save_tournament(client, config)


def _player_ids_for_tournament(client: Client, tournament_id: int) -> list[int]:
    response = client.table("players").select("id").eq("tournament_id", tournament_id).execute()
    return [int(row["id"]) for row in response.data or []]


def _team_ids_for_tournament(client: Client, tournament_id: int) -> list[int]:
    response = client.table("teams").select("id").eq("tournament_id", tournament_id).execute()
    return [int(row["id"]) for row in response.data or []]


def reset_scores(client: Client | None, tournament_id: int) -> int:
    if client is None:
        return 0
    if _table_exists(client, "tournaments"):
        player_ids = _player_ids_for_tournament(client, tournament_id)
        if not player_ids:
            return 0
        client.table("scores").delete().in_("player_id", player_ids).execute()
        try:
            client.table("live_events").delete().eq("tournament_id", tournament_id).execute()
        except Exception:
            pass
        return len(player_ids)
    client.table("scores").delete().neq("id", 0).execute()
    return 1


def reset_rosters(client: Client | None, tournament_id: int) -> None:
    if client is None:
        return
    if _table_exists(client, "tournaments"):
        team_ids = _team_ids_for_tournament(client, tournament_id)
        if team_ids:
            client.table("team_players").delete().in_("team_id", team_ids).execute()
        return
    client.table("team_players").delete().neq("id", 0).execute()


def reset_whole_tournament(client: Client | None, tournament_id: int) -> None:
    if client is None:
        return
    if not _table_exists(client, "tournaments"):
        reset_scores(client, None)
        reset_rosters(client, None)
        client.table("players").delete().neq("id", 0).execute()
        client.table("teams").delete().neq("id", 0).execute()
        try:
            client.table("daily_comments").delete().neq("id", 0).execute()
        except Exception:
            pass
        return

    player_ids = _player_ids_for_tournament(client, tournament_id)
    team_ids = _team_ids_for_tournament(client, tournament_id)
    if player_ids:
        client.table("scores").delete().in_("player_id", player_ids).execute()
        try:
            client.table("live_events").delete().eq("tournament_id", tournament_id).execute()
        except Exception:
            pass
    if team_ids:
        client.table("team_players").delete().in_("team_id", team_ids).execute()
    client.table("players").delete().eq("tournament_id", tournament_id).execute()
    client.table("teams").delete().eq("tournament_id", tournament_id).execute()
    try:
        client.table("daily_comments").delete().eq("tournament_id", tournament_id).execute()
    except Exception:
        pass


def event_name_matches(config: TournamentConfig, api_event_name: str | None) -> bool:
    if not config.datagolf_event_name or not api_event_name:
        return True
    expected = config.datagolf_event_name.casefold()
    actual = api_event_name.casefold()
    return expected in actual or actual in expected
