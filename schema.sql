create table if not exists tournaments (
    id bigint generated always as identity primary key,
    slug text not null unique,
    tournament_name text not null,
    display_title text not null,
    datagolf_event_name text,
    datagolf_tour text not null default 'pga',
    course_name text,
    month_label text,
    prize_text text not null default '4.000 kr',
    number_of_players_per_team integer not null default 7,
    counting_scores_per_day integer not null default 5,
    dropped_scores_per_day integer not null default 2,
    rounds integer not null default 4 check (rounds between 1 and 4),
    post_cut_swap_round integer not null default 3 check (post_cut_swap_round between 2 and 4),
    max_swaps integer not null default 3,
    excel_default_path text,
    is_active boolean not null default false,
    created_at timestamptz not null default now()
);

create table if not exists teams (
    id bigint generated always as identity primary key,
    tournament_id bigint references tournaments(id) on delete cascade,
    name text not null,
    created_at timestamptz default now()
);

create unique index if not exists teams_tournament_name_idx on teams (tournament_id, name);

create table if not exists players (
    id bigint generated always as identity primary key,
    tournament_id bigint references tournaments(id) on delete cascade,
    name text not null,
    country text,
    tier text,
    created_at timestamptz default now()
);

create unique index if not exists players_tournament_name_idx on players (tournament_id, name);

create table if not exists team_players (
    id bigint generated always as identity primary key,
    tournament_id bigint references tournaments(id) on delete cascade,
    team_id bigint references teams(id) on delete cascade,
    player_id bigint references players(id) on delete cascade,
    active_from_round integer not null default 1 check (active_from_round between 1 and 4),
    active_to_round integer not null default 4 check (active_to_round between 1 and 4),
    unique(team_id, player_id, active_from_round)
);

create table if not exists scores (
    id bigint generated always as identity primary key,
    tournament_id bigint references tournaments(id) on delete cascade,
    player_id bigint references players(id) on delete cascade,
    round_no integer not null check (round_no between 1 and 4),
    score integer not null,
    updated_at timestamptz default now()
);

create unique index if not exists scores_tournament_player_round_idx on scores (tournament_id, player_id, round_no);

create table if not exists daily_comments (
    id bigint generated always as identity primary key,
    tournament_id bigint references tournaments(id) on delete cascade,
    round_no integer not null check (round_no between 1 and 4),
    title text not null,
    body text not null,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create unique index if not exists daily_comments_tournament_round_idx on daily_comments (tournament_id, round_no);

create table if not exists sync_log (
    id bigint generated always as identity primary key,
    tournament_id bigint references tournaments(id) on delete set null,
    status text not null check (status in ('success', 'error', 'rate_limited')),
    http_status integer,
    message text not null,
    scores_written integer default 0,
    retry_count integer default 0,
    created_at timestamptz default now()
);

create table if not exists live_events (
    id bigint generated always as identity primary key,
    tournament_id bigint references tournaments(id) on delete cascade,
    player_id bigint references players(id) on delete cascade,
    player_name text not null,
    round_no integer not null check (round_no between 1 and 4),
    old_score integer not null,
    new_score integer not null,
    change integer not null,
    event_text text not null,
    created_at timestamptz not null default now()
);

create index if not exists live_events_created_at_idx on live_events (created_at desc);

alter table live_events enable row level security;

create policy "live_events_select_public"
    on live_events
    for select
    to anon, authenticated
    using (true);

create policy "live_events_insert_public"
    on live_events
    for insert
    to anon, authenticated
    with check (true);

create table if not exists app_settings (
    key text primary key,
    value text not null,
    updated_at timestamptz not null default now()
);

alter table app_settings enable row level security;

create policy "app_settings_select_public"
    on app_settings
    for select
    to anon, authenticated
    using (true);

create policy "app_settings_insert_public"
    on app_settings
    for insert
    to anon, authenticated
    with check (true);

create policy "app_settings_update_public"
    on app_settings
    for update
    to anon, authenticated
    using (true)
    with check (true);

alter table tournaments enable row level security;

create policy "tournaments_select_public"
    on tournaments for select to anon, authenticated using (true);

create policy "tournaments_insert_public"
    on tournaments for insert to anon, authenticated with check (true);

create policy "tournaments_update_public"
    on tournaments for update to anon, authenticated using (true) with check (true);

insert into tournaments (
    slug, tournament_name, display_title, datagolf_event_name, datagolf_tour,
    course_name, month_label, prize_text, excel_default_path, is_active
)
values
    ('us-open-2026', 'US Open', 'US Open 2026 Kupongen', 'U.S. Open', 'pga', null, 'June', '4.000 kr', 'US Open 2026 - Resultater.xlsx', true),
    ('the-open-2026', 'The Open', 'The Open 2026 Kupongen', 'The Open Championship', 'pga', 'Royal Birkdale', 'July', '4.000 kr', 'The Open 2026 - Resultater.xlsx', false),
    ('masters-2026', 'Masters', 'Masters 2026 Kupongen', 'Masters Tournament', 'pga', 'Augusta National', 'April', '4.000 kr', 'Masters 2026 - Resultater.xlsx', false),
    ('pga-championship-2026', 'PGA Championship', 'PGA Championship 2026 Kupongen', 'PGA Championship', 'pga', null, 'May', '4.000 kr', 'PGA Championship 2026 - Resultater.xlsx', false)
on conflict (slug) do nothing;

insert into app_settings (key, value, updated_at)
select 'active_tournament_id', id::text, now()
from tournaments
where slug = 'us-open-2026'
on conflict (key) do nothing;
