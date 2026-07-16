-- Upgrade existing Supabase database to current Fantasy Golf schema.
-- Safe / additive only: no DROP, TRUNCATE, or DELETE.
--
-- Targets databases that already contain US Open teams, players, rosters, and scores.
-- Run in Supabase SQL Editor AFTER inspecting which tables already exist.
--
-- Tables that need tournament_id for the current app:
--   teams      -> required (direct)
--   players    -> required (direct)
--   team_players -> NOT required (scoped via team_id -> teams.tournament_id)
--   scores       -> NOT required (scoped via player_id -> players.tournament_id)
--
-- Verification before/after (run manually):
--   select table_name, column_name
--   from information_schema.columns
--   where table_schema = 'public'
--     and table_name in ('tournaments','teams','players','team_players','scores')
--   order by table_name, ordinal_position;

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- 1. tournaments — create if missing, extend metadata if present
-- ---------------------------------------------------------------------------
create table if not exists tournaments (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    year int not null,
    num_rounds int not null default 4,
    counting_scores int not null default 5,
    dropped_scores int not null default 2,
    is_active boolean not null default true,
    display_title text,
    datagolf_event_name text,
    course_name text,
    start_date date,
    end_date date,
    created_at timestamptz not null default now()
);

alter table tournaments
    add column if not exists display_title text,
    add column if not exists datagolf_event_name text,
    add column if not exists course_name text,
    add column if not exists start_date date,
    add column if not exists end_date date,
    add column if not exists num_rounds int default 4,
    add column if not exists counting_scores int default 5,
    add column if not exists dropped_scores int default 2,
    add column if not exists is_active boolean default true,
    add column if not exists created_at timestamptz default now();

-- Seed / refresh US Open 2026 tournament row
insert into tournaments (
    name,
    year,
    num_rounds,
    counting_scores,
    dropped_scores,
    is_active,
    display_title,
    datagolf_event_name,
    course_name
)
select
    'US Open 2026',
    2026,
    4,
    5,
    2,
    true,
    'US Open 2026 Kupongen',
    'U.S. Open',
    'Oakmont Country Club'
where not exists (
    select 1 from tournaments where name = 'US Open 2026' and year = 2026
);

update tournaments
set
    display_title = coalesce(display_title, 'US Open 2026 Kupongen'),
    datagolf_event_name = coalesce(datagolf_event_name, 'U.S. Open'),
    course_name = coalesce(course_name, 'Oakmont Country Club'),
    num_rounds = coalesce(num_rounds, 4),
    counting_scores = coalesce(counting_scores, 5),
    dropped_scores = coalesce(dropped_scores, 2),
    is_active = coalesce(is_active, true)
where name = 'US Open 2026'
  and year = 2026;

-- ---------------------------------------------------------------------------
-- 2. teams.tournament_id
-- ---------------------------------------------------------------------------
do $$
begin
    if not exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'teams'
          and column_name = 'tournament_id'
    ) then
        alter table teams add column tournament_id uuid;
    end if;
end $$;

update teams t
set tournament_id = u.id
from tournaments u
where t.tournament_id is null
  and (
    (u.name = 'US Open 2026' and u.year = 2026)
    or (
        exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'tournaments' and column_name = 'slug'
        )
        and u.slug = 'us-open-2026'
    )
  );

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'teams_tournament_id_fkey'
    ) then
        alter table teams
            add constraint teams_tournament_id_fkey
            foreign key (tournament_id) references tournaments(id) on delete cascade;
    end if;
exception
    when duplicate_object then null;
end $$;

-- ---------------------------------------------------------------------------
-- 3. players.tournament_id
-- ---------------------------------------------------------------------------
do $$
begin
    if not exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'players'
          and column_name = 'tournament_id'
    ) then
        alter table players add column tournament_id uuid;
    end if;
end $$;

update players p
set tournament_id = u.id
from tournaments u
where p.tournament_id is null
  and (
    (u.name = 'US Open 2026' and u.year = 2026)
    or (
        exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'tournaments' and column_name = 'slug'
        )
        and u.slug = 'us-open-2026'
    )
  );

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'players_tournament_id_fkey'
    ) then
        alter table players
            add constraint players_tournament_id_fkey
            foreign key (tournament_id) references tournaments(id) on delete cascade;
    end if;
exception
    when duplicate_object then null;
end $$;

-- ---------------------------------------------------------------------------
-- 4. scores — align column names with current app (round, strokes)
--    Existing golf data may use round_no / score instead.
-- ---------------------------------------------------------------------------
do $$
begin
    if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'scores'
    ) then
        if not exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'scores' and column_name = 'round'
        ) then
            alter table scores add column round int;
        end if;

        if not exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'scores' and column_name = 'strokes'
        ) then
            alter table scores add column strokes int;
        end if;
    end if;
end $$;

do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'scores' and column_name = 'round_no'
    ) then
        execute $sql$
            update scores
            set round = round_no
            where round is null and round_no is not null
        $sql$;
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'scores' and column_name = 'score'
    ) then
        execute $sql$
            update scores
            set strokes = score
            where strokes is null and score is not null
        $sql$;
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- 5. team_players — optional tournament_id only if column already expected
--    Current app scopes rosters via teams; no index on team_players.tournament_id.
-- ---------------------------------------------------------------------------
do $$
begin
    if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'team_players'
    )
    and exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'team_players' and column_name = 'tournament_id'
    ) then
        execute $sql$
            update team_players tp
            set tournament_id = t.tournament_id
            from teams t
            where tp.team_id = t.id
              and tp.tournament_id is null
              and t.tournament_id is not null
        $sql$;
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- 6. Indexes — only after columns exist
-- ---------------------------------------------------------------------------
create index if not exists idx_teams_tournament on teams(tournament_id);
create index if not exists idx_players_tournament on players(tournament_id);

do $$
begin
    if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'team_players'
    ) then
        execute 'create index if not exists idx_team_players_team on team_players(team_id)';
        execute 'create index if not exists idx_team_players_player on team_players(player_id)';
    end if;

    if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'scores'
    ) then
        execute 'create index if not exists idx_scores_player on scores(player_id)';
        if exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'scores' and column_name = 'round'
        ) then
            execute 'create index if not exists idx_scores_round on scores(round)';
        end if;
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- 7. The Open 2026 — inactive seed (same as migration 001)
-- ---------------------------------------------------------------------------
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
    end_date
)
select
    'The Open 2026',
    2026,
    4,
    5,
    2,
    false,
    'The Open 2026 Kupongen',
    'The Open Championship',
    'Royal Birkdale',
    '2026-07-16'::date,
    '2026-07-19'::date
where not exists (
    select 1 from tournaments where name = 'The Open 2026' and year = 2026
);

-- Keep US Open active unless you switch manually later
update tournaments
set is_active = true
where name = 'US Open 2026'
  and year = 2026
  and is_active is distinct from true;
