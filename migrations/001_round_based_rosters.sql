-- Round-based team rosters for post-cut player swaps.
-- Run once in the Supabase SQL editor before using lagbytter in the app.

alter table team_players
    add column if not exists active_from_round integer not null default 1
        check (active_from_round between 1 and 4),
    add column if not exists active_to_round integer not null default 4
        check (active_to_round between 1 and 4);

-- Existing selections become the original roster for rounds 1 and 2.
update team_players
set active_from_round = 1,
    active_to_round = 2
where active_from_round = 1
  and active_to_round = 4;

alter table team_players
    drop constraint if exists team_players_team_id_player_id_key;

alter table team_players
    drop constraint if exists team_players_team_player_period_key;

alter table team_players
    add constraint team_players_team_player_period_key
        unique (team_id, player_id, active_from_round);

-- Seed post-cut rosters (rounds 3 and 4) as copies of the original roster.
insert into team_players (team_id, player_id, active_from_round, active_to_round)
select team_id, player_id, 3, 4
from team_players
where active_from_round = 1
  and active_to_round = 2
on conflict (team_id, player_id, active_from_round) do nothing;
