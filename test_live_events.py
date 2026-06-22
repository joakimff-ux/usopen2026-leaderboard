"""Unit tests for live score event formatting."""

from __future__ import annotations

import pandas as pd

from lib.live_events import (
    DISPLAY_EVENT_LIMIT,
    LiveEventsWriteResult,
    build_live_events_display,
    build_score_change_text,
    classify_score_change,
    format_event_time,
    player_counting_status,
    record_live_events,
)


class FakeQuery:
    def __init__(self, table_name: str, store: dict[str, list]):
        self.table_name = table_name
        self.store = store
        self.filters: dict[str, object] = {}
        self.selected = "*"
        self.ordered = False
        self.limited: int | None = None
        self.count_mode = False

    def select(self, columns: str, count: str | None = None):
        self.selected = columns
        self.count_mode = count == "exact"
        return self

    def eq(self, column: str, value: object):
        self.filters.setdefault("eq", []).append((column, value))
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

    def _filtered_rows(self) -> list[dict]:
        rows = list(self.store.get(self.table_name, []))
        if "in" in self.filters:
            column, values = self.filters["in"]
            allowed = set(values)
            rows = [row for row in rows if row[column] in allowed]
        for column, value in self.filters.get("eq", []):
            rows = [row for row in rows if row.get(column) == value]
        if self.ordered:
            column, desc = self.ordered
            rows = sorted(rows, key=lambda row: row[column], reverse=desc)
        if self.limited is not None:
            rows = rows[: self.limited]
        return rows

    def execute(self):
        rows = self._filtered_rows()
        if self.count_mode:
            return type("Result", (), {"data": rows, "count": len(rows)})()
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
    assert classify_score_change(-1) == ("Birdie", "🟢")
    assert classify_score_change(-2) == ("Eagle", "🟢")
    assert classify_score_change(0) == ("Par", "⚪")
    assert classify_score_change(1) == ("Bogey", "🔴")
    assert classify_score_change(2) == ("Double bogey+", "🔴")
    assert build_score_change_text(0, -1, -1) == "🟢 Birdie – til -1"
    assert build_score_change_text(-3, -4, -1) == "🟢 Birdie – til -4"
    assert build_score_change_text(0, 1, 1) == "🔴 Bogey – faller til +1"
    assert format_event_time("2026-06-19T14:05:00+00:00")  # smoke: returns HH:MM
    assert DISPLAY_EVENT_LIMIT == 8

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
        "live_events": [],
        "team_players": [
            {"player_id": 10, "active_from_round": 1, "active_to_round": 2},
        ],
    }
    client = FakeClient(store)
    db_players = [{"id": 10, "name": "Viktor Hovland"}]
    result = record_live_events(
        client,
        [{"player_id": 10, "round_no": 2, "score": -1}],
        db_players,
        active_round=2,
    )
    assert isinstance(result, LiveEventsWriteResult)
    assert result.written == 1
    assert result.changes_detected == 1
    assert store["live_events"][0]["change"] == -1
    assert "Birdie" in store["live_events"][0]["event_text"]

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
                "change": -1,
                "event_text": build_score_change_text(0, -1, -1),
                "created_at": "2026-06-19T14:05:00+00:00",
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
    assert list(display.columns) == [
        "Tid",
        "Spiller",
        "Hendelse",
        "Scoreendring",
        "Påvirker lag",
        "Teller/Droppes",
    ]
    assert display.iloc[0]["Spiller"] == "Viktor Hovland"
    assert display.iloc[0]["Hendelse"] == "🟢 Birdie – til -1"
    assert "Joakim" in display.iloc[0]["Påvirker lag"]
    assert "Teller" in display.iloc[0]["Teller/Droppes"]

    print("PASS: live event classification")
    print("PASS: record live events on sync diff")
    print("PASS: live events display for rostered players")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
