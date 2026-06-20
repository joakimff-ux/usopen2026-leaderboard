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
            player_scores = [
                {"Spiller": p["name"], "Score": score_map.get((int(p.id), rnd))}
                for _, p in picked.iterrows()
            ]
            day_sum, _ = score_round_for_team(
                t["name"], rnd, day, player_scores, ROSTER_LABELS[rnd]
            )
            row[day] = day_sum
            if day_sum is not None:
                total += int(day_sum)
        row["Totalt"] = total
        summary.append(row)
    return pd.DataFrame(summary), pd.DataFrame(detail)


def count_post_cut_swaps(original_ids: set[int], post_cut_ids: set[int]) -> int:
    return len(original_ids - post_cut_ids)


def describe_post_cut_swaps(original_ids: set[int], post_cut_ids: set[int], players: pd.DataFrame):
    out_ids = original_ids - post_cut_ids
    in_ids = post_cut_ids - original_ids
    out_names = players[players.id.astype(int).isin(out_ids)].sort_values("name")["name"].tolist()
    in_names = players[players.id.astype(int).isin(in_ids)].sort_values("name")["name"].tolist()
    return len(out_ids), out_names, in_names


def rounds_with_scores(scores: pd.DataFrame) -> set[int]:
    if scores.empty or "round_no" not in scores.columns:
        return set()
    return {int(value) for value in scores["round_no"].dropna().unique()}


def prepare_leaderboard_display(leaderboard: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    if leaderboard.empty:
        return leaderboard

    started_rounds = rounds_with_scores(scores)
    visible_days = [
        day
        for rnd, day in zip(ROUNDS, DAYS)
        if day in leaderboard.columns
        and (rnd in started_rounds or leaderboard[day].notna().any())
    ]
    columns = ["Plass", "Lag", *visible_days, "Totalt"]
    return leaderboard[columns]


def get_highest_scored_round_from_details(details: pd.DataFrame) -> int:
    highest = 0
    if details.empty:
        return highest
    for rnd, day in zip(ROUNDS, DAYS):
        if not details[details["Dag"] == day].dropna(subset=["Score"]).empty:
            highest = rnd
    return highest


def get_next_active_round(scores: pd.DataFrame, details: pd.DataFrame) -> int:
    completed = get_highest_scored_round_from_details(details)
    started = rounds_with_scores(scores)
    if started and max(started) > completed:
        return max(started)
    return min(completed + 1, 4)


def get_global_highest_scored_round(details: pd.DataFrame) -> int:
    return get_highest_scored_round_from_details(details)


def team_scored_rounds(details: pd.DataFrame, team: str) -> set[int]:
    if details.empty or "Lag" not in details.columns:
        return set()
    team_details = details[details["Lag"] == team]
    scored_rounds: set[int] = set()
    for rnd, day in zip(ROUNDS, DAYS):
        if not team_details[team_details["Dag"] == day].dropna(subset=["Score"]).empty:
            scored_rounds.add(rnd)
    return scored_rounds


def ordered_round_days_with_scores(
    details: pd.DataFrame,
    team: str,
    scores: pd.DataFrame,
) -> list[tuple[int, str]]:
    next_active = get_next_active_round(scores, details)
    scored_rounds = team_scored_rounds(details, team)
    completed_global = get_highest_scored_round_from_details(details)

    ordered: list[tuple[int, str]] = [(next_active, DAYS[next_active - 1])]
    for rnd in range(completed_global, 0, -1):
        if rnd == next_active or rnd not in scored_rounds:
            continue
        ordered.append((rnd, DAYS[rnd - 1]))
    return ordered


def score_round_for_team(team_name, round_no, day, player_scores, roster_label):
    frame = pd.DataFrame(player_scores)
    scored = frame.dropna(subset=["Score"]).sort_values("Score", ascending=True)
    counting = scored.head(COUNTING_SCORES)
    dropped = scored.iloc[COUNTING_SCORES:]
    enough_scores = len(scored) >= COUNTING_SCORES
    team_score = int(counting["Score"].sum()) if enough_scores and not counting.empty else None
    detail_rows = []
    for rank, (_, row) in enumerate(counting.iterrows(), 1):
        detail_rows.append(
            {
                "Lag": team_name,
                "Dag": day,
                "Spiller": row["Spiller"],
                "Score": int(row["Score"]),
                "Status": "counted",
            }
        )
    for _, row in dropped.iterrows():
        detail_rows.append(
            {
                "Lag": team_name,
                "Dag": day,
                "Spiller": row["Spiller"],
                "Score": int(row["Score"]),
                "Status": "dropped",
            }
        )
    return team_score, detail_rows


def count_post_cut_swaps(original_ids: set[int], post_cut_ids: set[int]) -> int:
    return len(original_ids - post_cut_ids)


def teams_missing_post_cut_roster(links: pd.DataFrame) -> set[int]:
    if not links_have_round_ranges(links) or links.empty:
        return set()

    pre_cut_teams = set(
        links[
            (links.active_from_round.astype(int) == PRE_CUT_FROM)
            & (links.active_to_round.astype(int) == PRE_CUT_TO)
        ].team_id.astype(int).tolist()
    )
    post_cut_teams = set(
        links[
            (links.active_from_round.astype(int) == POST_CUT_FROM)
            & (links.active_to_round.astype(int) == POST_CUT_TO)
        ].team_id.astype(int).tolist()
    )
    return pre_cut_teams - post_cut_teams


def build_post_cut_seed_rows(links: pd.DataFrame) -> list[dict[str, int]]:
    if not links_have_round_ranges(links) or links.empty:
        return []

    missing_teams = teams_missing_post_cut_roster(links)
    if not missing_teams:
        return []

    pre_cut = links[
        (links.active_from_round.astype(int) == PRE_CUT_FROM)
        & (links.active_to_round.astype(int) == PRE_CUT_TO)
    ]
    return [
        {
            "team_id": int(row.team_id),
            "player_id": int(row.player_id),
            "active_from_round": POST_CUT_FROM,
            "active_to_round": POST_CUT_TO,
        }
        for _, row in pre_cut.iterrows()
        if int(row.team_id) in missing_teams
    ]


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

    detail_rows = pd.DataFrame(
        [
            {"Lag": "Testlag", "Dag": "Dag 1", "Score": 1},
            {"Lag": "Testlag", "Dag": "Dag 2", "Score": 2},
            {"Lag": "Annen", "Dag": "Dag 1", "Score": 0},
            {"Lag": "Annen", "Dag": "Dag 2", "Score": 1},
        ]
    )
    empty_scores = pd.DataFrame(columns=["player_id", "round_no", "score"])
    assert ordered_round_days_with_scores(detail_rows, "Testlag", empty_scores) == [
        (3, "Dag 3"),
        (2, "Dag 2"),
        (1, "Dag 1"),
    ]
    assert ordered_round_days_with_scores(detail_rows, "Annen", empty_scores) == [
        (3, "Dag 3"),
        (2, "Dag 2"),
        (1, "Dag 1"),
    ]

    only_day1 = pd.DataFrame(
        [
            {"Lag": "Testlag", "Dag": "Dag 1", "Score": 1},
            {"Lag": "Annen", "Dag": "Dag 1", "Score": 0},
        ]
    )
    assert ordered_round_days_with_scores(only_day1, "Testlag", empty_scores) == [(2, "Dag 2"), (1, "Dag 1")]

    day3_scored = pd.DataFrame(
        [
            {"Lag": "Testlag", "Dag": "Dag 1", "Score": 1},
            {"Lag": "Testlag", "Dag": "Dag 2", "Score": 2},
            {"Lag": "Testlag", "Dag": "Dag 3", "Score": 0},
            {"Lag": "Annen", "Dag": "Dag 1", "Score": 0},
        ]
    )
    scores_with_r3 = pd.DataFrame([{"player_id": 1, "round_no": 3, "score": 0}])
    assert ordered_round_days_with_scores(day3_scored, "Testlag", scores_with_r3) == [
        (4, "Dag 4"),
        (3, "Dag 3"),
        (2, "Dag 2"),
        (1, "Dag 1"),
    ]

    assert ordered_round_days_with_scores(pd.DataFrame(), "Testlag", empty_scores) == [(1, "Dag 1")]

    partial_day3_scores = pd.DataFrame([{"player_id": 1, "round_no": 3, "score": -1}])
    partial_lb = pd.DataFrame(
        [
            {
                "Plass": 1,
                "Lag": "Testlag",
                "Dag 1": 28,
                "Dag 2": 75,
                "Dag 3": None,
                "Totalt": 103,
            }
        ]
    )
    displayed = prepare_leaderboard_display(partial_lb, partial_day3_scores)
    assert "Dag 3" in displayed.columns, displayed.columns.tolist()
    assert pd.isna(displayed.iloc[0]["Dag 3"])

    partial_player_scores = [{"Spiller": f"Player {i}", "Score": None} for i in range(1, 8)]
    partial_player_scores[0]["Score"] = -1
    day_sum, _ = score_round_for_team("Testlag", 3, "Dag 3", partial_player_scores, "Etter bytter")
    assert day_sum is None, day_sum

    anders_dag_3 = [
        {"Spiller": "Mav McNealy", "Score": 0},
        {"Spiller": "Rai Rai", "Score": 0},
        {"Spiller": "Scottie Scheffler", "Score": 0},
        {"Spiller": "Tommy Fleetwood", "Score": 0},
        {"Spiller": "Russell Henley", "Score": 1},
        {"Spiller": "Tyrrell Hatton", "Score": 1},
        {"Spiller": "Viktor Hovland", "Score": None},
    ]
    day_sum, breakdown = score_round_for_team("Anders", 3, "Dag 3", anders_dag_3, "Etter bytter")
    assert day_sum == 1, day_sum
    assert [row["Spiller"] for row in breakdown if row["Status"] == "counted"] == [
        "Mav McNealy",
        "Rai Rai",
        "Scottie Scheffler",
        "Tommy Fleetwood",
        "Russell Henley",
    ]
    assert [row["Spiller"] for row in breakdown if row["Status"] == "dropped"] == ["Tyrrell Hatton"]

    philip_dag_3 = [
        {"Spiller": f"Player {i}", "Score": 0}
        for i in range(1, 6)
    ] + [{"Spiller": "Player 6", "Score": None}, {"Spiller": "Player 7", "Score": None}]
    day_sum, _ = score_round_for_team("Philip", 3, "Dag 3", philip_dag_3, "Etter bytter")
    assert day_sum == 0, day_sum

    joakim_round_2 = [
        {"Spiller": "Collin Morikawa", "Score": -5},
        {"Spiller": "Scottie Scheffler", "Score": -2},
        {"Spiller": "Kristoffer Reitan", "Score": 6},
        {"Spiller": "Brooks Koepka", "Score": 7},
        {"Spiller": "Viktor Hovland", "Score": -1},
        {"Spiller": "Patrick Reed", "Score": 3},
        {"Spiller": "Jackson Koivun", "Score": 1},
    ]
    day_sum, breakdown = score_round_for_team("Joakim", 2, "Dag 2", joakim_round_2, "Originalt lag")
    counted = [row["Spiller"] for row in breakdown if row["Status"] == "counted"]
    dropped = [row["Spiller"] for row in breakdown if row["Status"] == "dropped"]
    assert day_sum == -4, day_sum
    assert counted == [
        "Collin Morikawa",
        "Scottie Scheffler",
        "Viktor Hovland",
        "Jackson Koivun",
        "Patrick Reed",
    ], counted
    assert dropped == ["Kristoffer Reitan", "Brooks Koepka"], dropped

    original = [1, 2, 3, 4, 5, 6, 7]
    swapped = [1, 2, 3, 8, 9, 10, 7]
    links_with_post_cut = make_links(1, original, swapped)
    assert build_post_cut_seed_rows(links_with_post_cut) == []

    links_without_post_cut = make_links(1, original, [])
    seeded = build_post_cut_seed_rows(links_without_post_cut)
    assert len(seeded) == 7
    assert {row["player_id"] for row in seeded} == set(original)

    players = pd.DataFrame([{"id": i, "name": f"Player {i}"} for i in range(1, 11)])
    swap_count, out_names, in_names = describe_post_cut_swaps(set(original), set(swapped), players)
    assert swap_count == 3
    assert out_names == ["Player 4", "Player 5", "Player 6"]
    assert set(in_names) == {"Player 8", "Player 9", "Player 10"}

    print("PASS: Dag 1-2 use original roster")
    print("PASS: Dag 3-4 use post-cut roster")
    print("PASS: 3 swaps counted correctly")
    print("PASS: newest scored round shown first")
    print("PASS: next active round ordering in score details")
    print("PASS: Joakim Dag 2 team score uses 5 best rounds")
    print("PASS: Anders Dag 3 team score uses 5 best with one missing player")
    print("PASS: Philip Dag 3 team score is 0 with five even-par rounds")
    print("PASS: post-cut seeding only runs for teams without Dag 3-4 roster")
    print("PASS: post-cut swap out/in names derived correctly")
    print(f"Sample totals: Dag1={row['Dag 1']}, Dag2={row['Dag 2']}, Dag3={row['Dag 3']}, Dag4={row['Dag 4']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
