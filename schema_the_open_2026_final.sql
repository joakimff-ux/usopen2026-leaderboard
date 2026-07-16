-- The Open 2026 Fantasy Golf -- clean Supabase production baseline
-- Run once in a NEW, EMPTY Supabase project.

begin;

create extension if not exists "pgcrypto";

create table tournaments (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    year int not null,
    num_rounds int not null default 4 check (num_rounds between 1 and 4),
    counting_scores int not null default 5 check (counting_scores >= 1),
    dropped_scores int not null default 2 check (dropped_scores >= 0),
    is_active boolean not null default false,
    display_title text not null,
    datagolf_event_name text not null,
    course_name text,
    start_date date,
    end_date date,
    missing_score_policy text not null default 'field_worst_plus_penalty'
        check (missing_score_policy in ('field_worst_plus_penalty')),
    missing_score_penalty int not null default 2 check (missing_score_penalty >= 0),
    created_at timestamptz not null default now(),
    unique (name, year),
    check (counting_scores + dropped_scores = 7),
    check (end_date is null or start_date is null or end_date >= start_date)
);

-- At most one tournament may be active.
create unique index uq_one_active_tournament
    on tournaments ((is_active))
    where is_active = true;

create table teams (
    id uuid primary key default gen_random_uuid(),
    tournament_id uuid not null references tournaments(id) on delete cascade,
    name text not null,
    created_at timestamptz not null default now(),
    unique (tournament_id, name)
);

create table players (
    id uuid primary key default gen_random_uuid(),
    tournament_id uuid not null references tournaments(id) on delete cascade,
    name text not null,
    tier int not null check (tier >= 1),
    created_at timestamptz not null default now(),
    unique (tournament_id, name)
);

create table team_players (
    id uuid primary key default gen_random_uuid(),
    team_id uuid not null references teams(id) on delete cascade,
    player_id uuid not null references players(id) on delete cascade,
    created_at timestamptz not null default now(),
    unique (team_id, player_id)
);

create table scores (
    id uuid primary key default gen_random_uuid(),
    player_id uuid not null references players(id) on delete cascade,
    round int not null check (round between 1 and 4),
    strokes int not null check (strokes between 50 and 100),
    source text not null default 'ADMIN' check (source in ('DATAGOLF', 'EXCEL', 'ADMIN')),
    is_official boolean not null default true,
    updated_at timestamptz not null default now(),
    unique (player_id, round)
);

-- Append-only status history. Missing DataGolf rows never create status events.
create table player_status_events (
    id uuid primary key default gen_random_uuid(),
    player_id uuid not null references players(id) on delete cascade,
    effective_round int not null check (effective_round between 1 and 4),
    status text not null check (status in ('ACTIVE', 'CUT', 'WD', 'DQ')),
    source text not null check (source in ('DATAGOLF', 'ADMIN')),
    note text,
    created_at timestamptz not null default now()
);

-- Latest DataGolf snapshot for each selected player and round. Public clients
-- may read it for hole/status display; only the service role may write it.
create table live_player_states (
    id uuid primary key default gen_random_uuid(),
    tournament_id uuid not null references tournaments(id) on delete cascade,
    player_id uuid not null references players(id) on delete cascade,
    round int not null check (round between 1 and 4),
    hole int check (hole between 1 and 18),
    is_finished boolean not null default false,
    round_score int check (round_score between -40 and 40),
    status text not null default 'ACTIVE' check (status in ('ACTIVE', 'CUT', 'WD', 'DQ')),
    source_updated_at text,
    updated_at timestamptz not null default now(),
    unique (tournament_id, player_id, round)
);

-- Append-only, fantasy-relevant live events. A deterministic key makes
-- repeated and concurrent syncs safe to deduplicate.
create table live_feed_events (
    id uuid primary key default gen_random_uuid(),
    tournament_id uuid not null references tournaments(id) on delete cascade,
    player_id uuid not null references players(id) on delete cascade,
    round int not null check (round between 1 and 4),
    hole int check (hole between 1 and 18),
    event_type text not null check (event_type in (
        'EAGLE', 'BIRDIE', 'BOGEY', 'DOUBLE_BOGEY_PLUS',
        'ROUND_COMPLETE', 'CUT', 'WD', 'DQ'
    )),
    hole_score int check (hole_score between -5 and 10),
    round_score int check (round_score between -40 and 40),
    source_updated_at text,
    dedupe_key text not null unique,
    created_at timestamptz not null default now()
);

-- One row per tournament round. A frozen penalty never changes unless an
-- explicit admin override is recorded.
create table tournament_rounds (
    id uuid primary key default gen_random_uuid(),
    tournament_id uuid not null references tournaments(id) on delete cascade,
    round int not null check (round between 1 and 4),
    state text not null default 'OPEN' check (state in ('OPEN', 'FINALIZED')),
    official_worst_score int check (official_worst_score between 50 and 100),
    missing_score_penalty int not null default 2 check (missing_score_penalty >= 0),
    penalty_score int check (penalty_score between 50 and 200),
    frozen_at timestamptz,
    is_override boolean not null default false,
    override_reason text,
    updated_at timestamptz not null default now(),
    unique (tournament_id, round),
    check (
        (state = 'OPEN' and penalty_score is null and frozen_at is null)
        or
        (state = 'FINALIZED' and penalty_score is not null and frozen_at is not null)
    ),
    check (not is_override or nullif(trim(override_reason), '') is not null)
);

-- Service-role-only audit trail for admin overrides and status changes.
create table admin_audit_log (
    id uuid primary key default gen_random_uuid(),
    action text not null,
    entity_type text not null,
    entity_id text,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index idx_teams_tournament on teams(tournament_id);
create index idx_players_tournament on players(tournament_id);
create index idx_team_players_team on team_players(team_id);
create index idx_team_players_player on team_players(player_id);
create index idx_scores_player on scores(player_id);
create index idx_scores_round on scores(round);
create index idx_player_status_events_player on player_status_events(player_id, created_at desc);
create index idx_live_player_states_tournament on live_player_states(tournament_id, player_id, round);
create index idx_live_feed_events_tournament on live_feed_events(tournament_id, created_at desc);
create index idx_tournament_rounds_tournament on tournament_rounds(tournament_id, round);
create index idx_admin_audit_created on admin_audit_log(created_at desc);

insert into tournaments (
    name,
    year,
    num_rounds,
    counting_scores,
    dropped_scores,
    is_active,
    display_title,
    datagolf_event_name,
    course_name,
    start_date,
    end_date,
    missing_score_policy,
    missing_score_penalty
)
values (
    'The Open 2026',
    2026,
    4,
    5,
    2,
    true,
    'The Open 2026 Kupongen',
    'The Open Championship',
    'Royal Birkdale',
    '2026-07-16'::date,
    '2026-07-19'::date,
    'field_worst_plus_penalty',
    2
);

insert into tournament_rounds (tournament_id, round, missing_score_penalty)
select id, round_num, missing_score_penalty
from tournaments
cross join generate_series(1, 4) as rounds(round_num)
where name = 'The Open 2026' and year = 2026;

alter table tournaments enable row level security;
alter table teams enable row level security;
alter table players enable row level security;
alter table team_players enable row level security;
alter table scores enable row level security;
alter table player_status_events enable row level security;
alter table live_player_states enable row level security;
alter table live_feed_events enable row level security;
alter table tournament_rounds enable row level security;
alter table admin_audit_log enable row level security;

create policy public_read_tournaments on tournaments for select to anon, authenticated using (true);
create policy public_read_teams on teams for select to anon, authenticated using (true);
create policy public_read_players on players for select to anon, authenticated using (true);
create policy public_read_team_players on team_players for select to anon, authenticated using (true);
create policy public_read_scores on scores for select to anon, authenticated using (true);
create policy public_read_player_status_events on player_status_events for select to anon, authenticated using (true);
create policy public_read_live_player_states on live_player_states for select to anon, authenticated using (true);
create policy public_read_live_feed_events on live_feed_events for select to anon, authenticated using (true);
create policy public_read_tournament_rounds on tournament_rounds for select to anon, authenticated using (true);

grant select on tournaments, teams, players, team_players, scores,
    player_status_events, live_player_states, live_feed_events,
    tournament_rounds to anon, authenticated;
revoke insert, update, delete on tournaments, teams, players, team_players,
    scores, player_status_events, live_player_states, live_feed_events,
    tournament_rounds, admin_audit_log from anon, authenticated;
revoke all on admin_audit_log from anon, authenticated;

commit;

-- Read-only verification queries to run after setup:
-- select table_name from information_schema.tables
-- where table_schema = 'public'
-- order by table_name;
--
-- select name, year, is_active, display_title, datagolf_event_name,
--        course_name, start_date, end_date, missing_score_policy,
--        missing_score_penalty
-- from tournaments;
--
-- select round, state, penalty_score, frozen_at
-- from tournament_rounds
-- order by round;
--
-- select count(*) as teams from teams;
-- select count(*) as players from players;
-- select count(*) as scores from scores;
