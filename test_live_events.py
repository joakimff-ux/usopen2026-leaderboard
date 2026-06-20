"""Unit tests for live score event formatting."""

from __future__ import annotations

import pandas as pd

from lib.live_events import (
    build_live_events_display,
    build_score_change_text,
    classify_score_change,
    player_counting_status,
    record_score_events,
)


class FakeQuery:
    def __init__(self, table_name: str, store: dict[str, list]):
        self.table_name = table_name
        self.store = store
        self.filters: dict[str, object] = {}
        self.selected = "*"
        self.ordered = False
        self.limited: int | None = None

    def select(self, columns: str):
        self.selected = columns
        return self

    def in_(self, column: str, values: list[int]):
        self.filters["in"] = (column, values)
        return self

    def order(self, column: str, desc: bool = False):
        self.ordered = (column, desc)
        return self

    def limit(self, count: int):
        self.limited = count
        return self

    def insert(self, rows: list[dict]):
        self.store.setdefault(self.table_name, []).extend(rows)
        return self

    def execute(self):
        rows = list(self.store.get(self.table_name, []))
        if self.table_name == "scores" and "in" in self.filters:
            _, values = self.filters["in"]
            allowed = set(values)
            rows = [row for row in rows if row["player_id"] in allowed]
        if self.ordered:
            column, desc = self.ordered
            rows = sorted(rows, key=lambda row: row[column], reverse=desc)
        if self.limited is not None:
            rows = rows[: self.limited]
        return type("Result", (), {"data": rows, "count": len(rows)})()


class FakeClient:
    def __init__(self, store: dict[str, list]):
        self.store = store

    def table(self, name: str):
        return FakeQuery(name, self.store)


def get_team_player_ids(links: pd.DataFrame, team_id: int, round_no: int) -> set[int]:
    if round_no <= 2:
        active_from, active_to = 1, 2
    else:
        active_from, active_to = 3, 4
    team_links = links[
        (links.team_id.astype(int) == team_id)
        & (links.active_from_round.astype(int) == active_from)
        & (links.active_to_round.astype(int) == active_to)
    ]
    return set(team_links.player_id.astype(int).tolist())


def main() -> int:
    assert classify_score_change(-1) == ("birdie", "🐦")
    assert classify_score_change(-2) == ("stor forbedring", "🔥")
    assert classify_score_change(1) == ("bogey", "😬")
    assert classify_score_change(2) == ("dårlig utvikling", "⚠️")
    assert "E til -1" in build_score_change_text(0, -1, -1)
    assert "faller til +1" in build_score_change_text(0, 1, 1)

    team_scores = [
        (1, "A", -2),
        (2, "B", -1),
        (3, "C", 0),
        (4, "D", 1),
        (5, "E", 2),
        (6, "F", 3),
        (7, "G", 4),
    ]
    assert player_counting_status(3, team_scores) == "Teller"
    assert player_counting_status(7, team_scores) == "Droppes"

    store = {
        "scores": [{"player_id": 10, "round_no": 2, "score": 0}],
        "score_events": [],
    }
    client = FakeClient(store)
    written = record_score_events(
        client,
        [{"player_id": 10, "round_no": 2, "score": -1}],
    )
    assert written == 1
    assert store["score_events"][0]["delta"] == -1

    teams = pd.DataFrame([{"id": 1, "name": "Joakim"}])
    players = pd.DataFrame(
        [
            {"id": 10, "name": "Viktor Hovland"},
            {"id": 11, "name": "Scottie Scheffler"},
        ]
    )
    links = pd.DataFrame(
        [
            {"team_id": 1, "player_id": 10, "active_from_round": 1, "active_to_round": 2},
            {"team_id": 1, "player_id": 11, "active_from_round": 1, "active_to_round": 2},
        ]
    )
    events = pd.DataFrame(
        [
            {
                "player_id": 10,
                "player_name": "Viktor Hovland",
                "round_no": 2,
                "old_score": 0,
                "new_score": -1,
                "delta": -1,
            }
        ]
    )
    score_map = {(10, 2): -1, (11, 2): 1}
    display = build_live_events_display(
        events,
        teams,
        players,
        links,
        score_map,
        get_team_player_ids=get_team_player_ids,
        rostered_player_ids={10, 11},
    )
    assert not display.empty
    assert display.iloc[0]["Spiller"] == "Viktor Hovland"
    assert "Joakim" in display.iloc[0]["Påvirker lag"]
    assert "Teller" in display.iloc[0]["Teller/Droppes"]

    print("PASS: live event classification")
    print("PASS: record score events on sync diff")
    print("PASS: live events display for rostered players")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
