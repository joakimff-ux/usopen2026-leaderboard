"""Unit tests for round-based roster scoring logic."""

from __future__ import annotations

import pandas as pd


PRE_CUT_FROM, PRE_CUT_TO = 1, 2
POST_CUT_FROM, POST_CUT_TO = 3, 4
PLAYERS_PER_TEAM = 7
COUNTING_SCORES = 5
ROUNDS = [1, 2, 3, 4]
DAYS = ["Dag 1", "Dag 2", "Dag 3", "Dag 4"]
ROSTER_LABELS = {1: "Originalt lag", 2: "Originalt lag", 3: "Etter bytter", 4: "Etter bytter"}


def roster_period_for_round(round_no: int) -> tuple[int, int]:
    if round_no <= 2:
        return PRE_CUT_FROM, PRE_CUT_TO
    return POST_CUT_FROM, POST_CUT_TO


def links_have_round_ranges(links: pd.DataFrame) -> bool:
    return (
        not links.empty
        and "active_from_round" in links.columns
        and "active_to_round" in links.columns
    )


def get_team_player_ids(links: pd.DataFrame, team_id: int, round_no: int) -> set[int]:
    active_from, active_to = roster_period_for_round(round_no)
    team_links = links[
        (links.team_id.astype(int) == team_id)
        & (links.active_from_round.astype(int) == active_from)
        & (links.active_to_round.astype(int) == active_to)
    ]
    return set(team_links.player_id.astype(int).tolist())


def count_post_cut_swaps(original_ids: set[int], post_cut_ids: set[int]) -> int:
    return len(original_ids - post_cut_ids)


def build_model(teams, players, links, scores):
    score_map = {}
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
                round_rows.append({"Lag": t["name"], "Dag": day, "Spiller": p["name"], "Score": val})
            scored = pd.DataFrame(round_rows).dropna(subset=["Score"]).sort_values("Score", ascending=True)
            counting = scored.head(COUNTING_SCORES)
            day_sum = counting.Score.sum() if len(counting) else None
            row[day] = day_sum
            if day_sum is not None:
                total += int(day_sum)
        row["Totalt"] = total
        summary.append(row)
    return pd.DataFrame(summary), pd.DataFrame(detail)


def make_links(team_id: int, pre_ids: list[int], post_ids: list[int]) -> pd.DataFrame:
    rows = []
    for pid in pre_ids:
        rows.append(
            {
                "team_id": team_id,
                "player_id": pid,
                "active_from_round": PRE_CUT_FROM,
                "active_to_round": PRE_CUT_TO,
            }
        )
    for pid in post_ids:
        rows.append(
            {
                "team_id": team_id,
                "player_id": pid,
                "active_from_round": POST_CUT_FROM,
                "active_to_round": POST_CUT_TO,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    teams = pd.DataFrame([{"id": 1, "name": "Testlag"}])
    players = pd.DataFrame(
        [{"id": i, "name": f"Player {i}"} for i in range(1, 11)]
    )
    original = [1, 2, 3, 4, 5, 6, 7]
    swapped = [1, 2, 3, 8, 9, 10, 7]  # 3 swaps: 4->8, 5->9, 6->10
    links = make_links(1, original, swapped)

    assert count_post_cut_swaps(set(original), set(swapped)) == 3

    scores = []
    for pid in original:
        scores.append({"player_id": pid, "round_no": 1, "score": pid})
        scores.append({"player_id": pid, "round_no": 2, "score": pid + 10})
    for pid in swapped:
        scores.append({"player_id": pid, "round_no": 3, "score": 1})
        scores.append({"player_id": pid, "round_no": 4, "score": 2})
    scores_df = pd.DataFrame(scores)

    leaderboard, _ = build_model(teams, players, links, scores_df)
    row = leaderboard.iloc[0]

    pre_cut_day1 = sum(pid for pid in original[:5])
    pre_cut_day2 = sum(pid + 10 for pid in original[:5])
    post_cut_day3 = 5
    post_cut_day4 = 10

    assert row["Dag 1"] == pre_cut_day1, row["Dag 1"]
    assert row["Dag 2"] == pre_cut_day2, row["Dag 2"]
    assert row["Dag 3"] == post_cut_day3, row["Dag 3"]
    assert row["Dag 4"] == post_cut_day4, row["Dag 4"]
    assert row["Totalt"] == pre_cut_day1 + pre_cut_day2 + post_cut_day3 + post_cut_day4

    print("PASS: Dag 1-2 use original roster")
    print("PASS: Dag 3-4 use post-cut roster")
    print("PASS: 3 swaps counted correctly")
    print(f"Sample totals: Dag1={row['Dag 1']}, Dag2={row['Dag 2']}, Dag3={row['Dag 3']}, Dag4={row['Dag 4']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
