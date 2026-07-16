-- The Open 2026 — safe, additive migration for USOpen2026_FantasyGolf
-- Run ONCE in Supabase SQL Editor.
--
-- What this does:
--   1. Adds optional metadata columns to tournaments (no data loss)
--   2. Backfills US Open 2026 metadata where missing
--   3. Inserts The Open 2026 as a NEW tournament (is_active = false)
--
-- What this does NOT do:
--   - No DELETE, TRUNCATE, or DROP of tables
--   - Does not deactivate US Open 2026
--   - Does not touch teams, players, scores, or team_players

-- ---------------------------------------------------------------------------
-- 1. Extend tournaments with display / DataGolf / venue metadata
-- ---------------------------------------------------------------------------
alter table tournaments
    add column if not exists display_title text,
    add column if not exists datagolf_event_name text,
    add column if not exists course_name text,
    add column if not exists start_date date,
    add column if not exists end_date date;

-- ---------------------------------------------------------------------------
-- 2. Backfill US Open 2026 metadata (only where columns are still null)
-- ---------------------------------------------------------------------------
update tournaments
set
    display_title = coalesce(display_title, 'US Open 2026 Kupongen'),
    datagolf_event_name = coalesce(datagolf_event_name, 'U.S. Open'),
    course_name = coalesce(course_name, 'Oakmont Country Club')
where name = 'US Open 2026'
  and year = 2026;

-- Ensure US Open stays the active tournament until you switch manually in a later step
update tournaments
set is_active = true
where name = 'US Open 2026'
  and year = 2026
  and is_active is distinct from true;

-- ---------------------------------------------------------------------------
-- 3. Insert The Open 2026 (inactive — no roster/scores yet)
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
    select 1
    from tournaments
    where name = 'The Open 2026'
      and year = 2026
);

-- ---------------------------------------------------------------------------
-- 4. Verification queries (run separately after migration)
-- ---------------------------------------------------------------------------
-- select id, name, year, is_active, display_title, datagolf_event_name,
--        course_name, start_date, end_date
-- from tournaments
-- order by year, name;
--
-- select t.name, count(distinct tm.id) as teams, count(distinct p.id) as players
-- from tournaments t
-- left join teams tm on tm.tournament_id = t.id
-- left join players p on p.tournament_id = t.id
-- group by t.id, t.name
-- order by t.name;
