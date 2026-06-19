-- US Open 2026 Fantasy Golf — Supabase schema

create extension if not exists "pgcrypto";

create table if not exists tournaments (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    year int not null,
    num_rounds int not null default 4,
    counting_scores int not null default 5,
    dropped_scores int not null default 2,
    is_active boolean not null default true,
    created_at timestamptz not null default now()
);

create table if not exists teams (
    id uuid primary key default gen_random_uuid(),
    tournament_id uuid not null references tournaments(id) on delete cascade,
    name text not null,
    created_at timestamptz not null default now(),
    unique (tournament_id, name)
);

create table if not exists players (
    id uuid primary key default gen_random_uuid(),
    tournament_id uuid not null references tournaments(id) on delete cascade,
    name text not null,
    tier int not null check (tier >= 1),
    created_at timestamptz not null default now(),
    unique (tournament_id, name)
);

create table if not exists team_players (
    id uuid primary key default gen_random_uuid(),
    team_id uuid not null references teams(id) on delete cascade,
    player_id uuid not null references players(id) on delete cascade,
    created_at timestamptz not null default now(),
    unique (team_id, player_id)
);

create table if not exists scores (
    id uuid primary key default gen_random_uuid(),
    player_id uuid not null references players(id) on delete cascade,
    round int not null check (round between 1 and 4),
    strokes int not null check (strokes >= 0),
    updated_at timestamptz not null default now(),
    unique (player_id, round)
);

create index if not exists idx_teams_tournament on teams(tournament_id);
create index if not exists idx_players_tournament on players(tournament_id);
create index if not exists idx_team_players_team on team_players(team_id);
create index if not exists idx_team_players_player on team_players(player_id);
create index if not exists idx_scores_player on scores(player_id);
create index if not exists idx_scores_round on scores(round);

insert into tournaments (name, year, num_rounds, counting_scores, dropped_scores, is_active)
select 'US Open 2026', 2026, 4, 5, 2, true
where not exists (
    select 1 from tournaments where name = 'US Open 2026' and year = 2026
);
