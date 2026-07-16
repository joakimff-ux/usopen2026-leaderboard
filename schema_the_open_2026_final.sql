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

-- Append-only post-round-two roster revisions. team_players always remains
-- the original roster used for rounds 1 and 2.
create table roster_change_sets (
    id uuid primary key default gen_random_uuid(),
    tournament_id uuid not null references tournaments(id) on delete cascade,
    round_from int not null default 3 check (round_from = 3),
    is_active boolean not null default false,
    is_locked boolean not null default true,
    created_at timestamptz not null default now(),
    created_by text not null,
    unlocked_at timestamptz,
    unlocked_by text
);

create unique index uq_roster_change_sets_active_tournament
    on roster_change_sets(tournament_id)
    where is_active = true;

create table roster_changes (
    id uuid primary key default gen_random_uuid(),
    change_set_id uuid not null references roster_change_sets(id) on delete cascade,
    tournament_id uuid not null references tournaments(id) on delete cascade,
    team_id uuid not null references teams(id),
    round_from int not null default 3 check (round_from = 3),
    old_player_id uuid not null references players(id),
    new_player_id uuid not null references players(id),
    changed_at timestamptz not null default now(),
    changed_by text not null,
    unique (change_set_id, team_id, old_player_id),
    check (old_player_id <> new_player_id)
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
create index idx_roster_changes_tournament
    on roster_changes(tournament_id, change_set_id, team_id);
create index idx_scores_player on scores(player_id);
create index idx_scores_round on scores(round);
create index idx_player_status_events_player on player_status_events(player_id, created_at desc);
create index idx_live_player_states_tournament on live_player_states(tournament_id, player_id, round);
create index idx_live_feed_events_tournament on live_feed_events(tournament_id, created_at desc);
create index idx_tournament_rounds_tournament on tournament_rounds(tournament_id, round);
create index idx_admin_audit_created on admin_audit_log(created_at desc);

-- Atomic service-role-only replacement of the active round-three roster revision.
create or replace function save_roster_changes_atomic(
    p_tournament_id uuid,
    p_round_from int,
    p_changed_by text,
    p_changes jsonb
) returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
    v_change_set_id uuid;
begin
    if p_round_from <> 3 then
        raise exception 'Roster changes must start in round 3.';
    end if;
    if nullif(trim(p_changed_by), '') is null then
        raise exception 'changed_by is required.';
    end if;
    if p_changes is null or jsonb_typeof(p_changes) <> 'array' then
        raise exception 'Roster changes must be a JSON array.';
    end if;

    perform 1 from tournaments where id = p_tournament_id for update;
    if not found then
        raise exception 'Tournament not found.';
    end if;
    if not exists (
        select 1 from tournament_rounds
        where tournament_id = p_tournament_id and round = 2 and state = 'FINALIZED'
    ) then
        raise exception 'Round 2 must be finalized before roster changes.';
    end if;
    if exists (
        select 1 from scores s
        join players p on p.id = s.player_id
        where p.tournament_id = p_tournament_id and s.round = 3
    ) or exists (
        select 1 from live_player_states
        where tournament_id = p_tournament_id
          and round = 3
          and (hole is not null or is_finished = true)
    ) then
        raise exception 'The roster-change window is closed because round 3 has started.';
    end if;
    if exists (
        select 1
        from jsonb_to_recordset(p_changes)
            as x(team_id uuid, old_player_id uuid, new_player_id uuid)
        group by x.team_id
        having count(*) > 3
    ) then
        raise exception 'A team may have at most three roster changes.';
    end if;
    if exists (
        select 1
        from jsonb_to_recordset(p_changes)
            as x(team_id uuid, old_player_id uuid, new_player_id uuid)
        group by x.team_id, x.old_player_id
        having count(*) > 1
    ) or exists (
        select 1
        from jsonb_to_recordset(p_changes)
            as x(team_id uuid, old_player_id uuid, new_player_id uuid)
        group by x.team_id, x.new_player_id
        having count(*) > 1
    ) then
        raise exception 'Duplicate players are not allowed within a team.';
    end if;
    if exists (
        select 1
        from jsonb_to_recordset(p_changes)
            as x(team_id uuid, old_player_id uuid, new_player_id uuid)
        left join teams t
          on t.id = x.team_id and t.tournament_id = p_tournament_id
        left join team_players old_roster
          on old_roster.team_id = x.team_id
         and old_roster.player_id = x.old_player_id
        left join players incoming
          on incoming.id = x.new_player_id
         and incoming.tournament_id = p_tournament_id
        where t.id is null
           or old_roster.id is null
           or incoming.id is null
           or x.old_player_id = x.new_player_id
    ) then
        raise exception 'Roster change contains an invalid team or player.';
    end if;
    if exists (
        select 1
        from jsonb_to_recordset(p_changes)
            as x(team_id uuid, old_player_id uuid, new_player_id uuid)
        join team_players current_roster
          on current_roster.team_id = x.team_id
         and current_roster.player_id = x.new_player_id
    ) then
        raise exception 'The incoming player is already in the original team roster.';
    end if;

    update roster_change_sets
    set is_active = false
    where tournament_id = p_tournament_id and is_active = true;

    insert into roster_change_sets (
        tournament_id, round_from, is_active, is_locked, created_by
    ) values (
        p_tournament_id, 3, true, false, p_changed_by
    ) returning id into v_change_set_id;

    insert into roster_changes (
        change_set_id, tournament_id, team_id, round_from,
        old_player_id, new_player_id, changed_by
    )
    select
        v_change_set_id, p_tournament_id, x.team_id, 3,
        x.old_player_id, x.new_player_id, p_changed_by
    from jsonb_to_recordset(p_changes)
        as x(team_id uuid, old_player_id uuid, new_player_id uuid);

    return v_change_set_id;
end;
$$;

revoke all on function save_roster_changes_atomic(uuid, int, text, jsonb)
    from public, anon, authenticated;
grant execute on function save_roster_changes_atomic(uuid, int, text, jsonb)
    to service_role;

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
alter table roster_change_sets enable row level security;
alter table roster_changes enable row level security;
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
create policy public_read_roster_change_sets on roster_change_sets for select to anon, authenticated using (true);
create policy public_read_roster_changes on roster_changes for select to anon, authenticated using (true);
create policy public_read_scores on scores for select to anon, authenticated using (true);
create policy public_read_player_status_events on player_status_events for select to anon, authenticated using (true);
create policy public_read_live_player_states on live_player_states for select to anon, authenticated using (true);
create policy public_read_live_feed_events on live_feed_events for select to anon, authenticated using (true);
create policy public_read_tournament_rounds on tournament_rounds for select to anon, authenticated using (true);

grant select on tournaments, teams, players, team_players, scores,
    player_status_events, live_player_states, live_feed_events,
    tournament_rounds, roster_change_sets, roster_changes to anon, authenticated;
revoke insert, update, delete on tournaments, teams, players, team_players,
    scores, player_status_events, live_player_states, live_feed_events,
    tournament_rounds, roster_change_sets, roster_changes, admin_audit_log
    from anon, authenticated;
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
