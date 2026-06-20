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
    active_from_round integer not null default 1 check (active_from_round between 1 and 4),
    active_to_round integer not null default 4 check (active_to_round between 1 and 4),
    unique(team_id, player_id, active_from_round)
);

create table if not exists scores (
    id bigint generated always as identity primary key,
    player_id bigint references players(id) on delete cascade,
    round_no integer not null check (round_no between 1 and 4),
    score integer not null,
    updated_at timestamptz default now(),
    unique(player_id, round_no)
);

create table if not exists daily_comments (
    id bigint generated always as identity primary key,
    round_no integer not null check (round_no between 1 and 4),
    title text not null,
    body text not null,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique (round_no)
);

create table if not exists sync_log (
    id bigint generated always as identity primary key,
    status text not null check (status in ('success', 'error', 'rate_limited')),
    http_status integer,
    message text not null,
    scores_written integer default 0,
    retry_count integer default 0,
    created_at timestamptz default now()
);

create table if not exists score_events (
    id bigint generated always as identity primary key,
    player_id bigint references players(id) on delete cascade,
    round_no integer not null check (round_no between 1 and 4),
    old_score integer not null,
    new_score integer not null,
    delta integer not null,
    created_at timestamptz default now()
);

create index if not exists score_events_created_at_idx on score_events (created_at desc);

create table if not exists app_settings (
    key text primary key,
    value text not null,
    updated_at timestamptz not null default now()
);
