create table if not exists teams (
    id bigint generated always as identity primary key,
    name text not null unique,
    created_at timestamptz default now()
);

create table if not exists players (
    id bigint generated always as identity primary key,
    name text not null unique,
    country text,
    tier text,
    created_at timestamptz default now()
);

create table if not exists team_players (
    id bigint generated always as identity primary key,
    team_id bigint references teams(id) on delete cascade,
    player_id bigint references players(id) on delete cascade,
    unique(team_id, player_id)
);

create table if not exists scores (
    id bigint generated always as identity primary key,
    player_id bigint references players(id) on delete cascade,
    round_no integer not null check (round_no between 1 and 4),
    score integer not null,
    updated_at timestamptz default now(),
    unique(player_id, round_no)
);
