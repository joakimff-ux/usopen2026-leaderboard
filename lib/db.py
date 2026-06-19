"""Supabase database helpers."""

from __future__ import annotations

from typing import Any

import streamlit as st
from supabase import Client, create_client

TOURNAMENT_NAME = "US Open 2026"
TOURNAMENT_YEAR = 2026


def get_supabase_client() -> Client | None:
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        return None
    return create_client(url, key)


def get_supabase_client_from_config(url: str, key: str) -> Client:
    return create_client(url, key)


def get_active_tournament(client: Client) -> dict[str, Any] | None:
    response = (
        client.table("tournaments")
        .select("*")
        .eq("name", TOURNAMENT_NAME)
        .eq("year", TOURNAMENT_YEAR)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def ensure_tournament(client: Client) -> dict[str, Any]:
    tournament = get_active_tournament(client)
    if tournament:
        return tournament

    response = (
        client.table("tournaments")
        .insert(
            {
                "name": TOURNAMENT_NAME,
                "year": TOURNAMENT_YEAR,
                "num_rounds": 4,
                "counting_scores": 5,
                "dropped_scores": 2,
                "is_active": True,
            }
        )
        .execute()
    )
    return response.data[0]


def fetch_teams(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    response = (
        client.table("teams")
        .select("*")
        .eq("tournament_id", tournament_id)
        .order("name")
        .execute()
    )
    return response.data or []


def fetch_players(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    response = (
        client.table("players")
        .select("*")
        .eq("tournament_id", tournament_id)
        .order("tier")
        .order("name")
        .execute()
    )
    return response.data or []


def fetch_team_players(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    teams = fetch_teams(client, tournament_id)
    if not teams:
        return []

    team_ids = [team["id"] for team in teams]
    response = (
        client.table("team_players")
        .select("id, team_id, player_id, teams(name), players(name, tier)")
        .in_("team_id", team_ids)
        .execute()
    )
    return response.data or []


def fetch_scores(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    players = fetch_players(client, tournament_id)
    if not players:
        return []

    player_ids = [player["id"] for player in players]
    response = (
        client.table("scores")
        .select("*")
        .in_("player_id", player_ids)
        .execute()
    )
    return response.data or []


def reset_tournament_data(client: Client, tournament_id: str) -> None:
    teams = fetch_teams(client, tournament_id)
    players = fetch_players(client, tournament_id)

    team_ids = [team["id"] for team in teams]
    player_ids = [player["id"] for player in players]

    if player_ids:
        client.table("scores").delete().in_("player_id", player_ids).execute()
    if team_ids:
        client.table("team_players").delete().in_("team_id", team_ids).execute()
    if player_ids:
        client.table("players").delete().in_("id", player_ids).execute()
    if team_ids:
        client.table("teams").delete().in_("id", team_ids).execute()


def add_team(client: Client, tournament_id: str, name: str) -> dict[str, Any]:
    response = client.table("teams").insert({"tournament_id": tournament_id, "name": name.strip()}).execute()
    return response.data[0]


def remove_team(client: Client, team_id: str) -> None:
    client.table("team_players").delete().eq("team_id", team_id).execute()
    client.table("teams").delete().eq("id", team_id).execute()


def add_player(client: Client, tournament_id: str, name: str, tier: int) -> dict[str, Any]:
    response = (
        client.table("players")
        .insert({"tournament_id": tournament_id, "name": name.strip(), "tier": tier})
        .execute()
    )
    return response.data[0]


def remove_player(client: Client, player_id: str) -> None:
    client.table("scores").delete().eq("player_id", player_id).execute()
    client.table("team_players").delete().eq("player_id", player_id).execute()
    client.table("players").delete().eq("id", player_id).execute()


def set_team_roster(client: Client, team_id: str, player_ids: list[str]) -> None:
    client.table("team_players").delete().eq("team_id", team_id).execute()
    if player_ids:
        rows = [{"team_id": team_id, "player_id": player_id} for player_id in player_ids]
        client.table("team_players").insert(rows).execute()


def upsert_score(client: Client, player_id: str, round_num: int, strokes: int) -> None:
    client.table("scores").upsert(
        {"player_id": player_id, "round": round_num, "strokes": strokes},
        on_conflict="player_id,round",
    ).execute()


def delete_score(client: Client, player_id: str, round_num: int) -> None:
    client.table("scores").delete().eq("player_id", player_id).eq("round", round_num).execute()
