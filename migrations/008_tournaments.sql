-- Multi-tournament support. Preserves existing US Open data via backfill.
-- Run once in the Supabase SQL editor.

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

alter table teams add column if not exists tournament_id bigint references tournaments(id) on delete cascade;
alter table players add column if not exists tournament_id bigint references tournaments(id) on delete cascade;
alter table team_players add column if not exists tournament_id bigint references tournaments(id) on delete cascade;
alter table scores add column if not exists tournament_id bigint references tournaments(id) on delete cascade;
alter table daily_comments add column if not exists tournament_id bigint references tournaments(id) on delete cascade;
alter table live_events add column if not exists tournament_id bigint references tournaments(id) on delete cascade;
alter table sync_log add column if not exists tournament_id bigint references tournaments(id) on delete set null;

insert into tournaments (
    slug,
    tournament_name,
    display_title,
    datagolf_event_name,
    datagolf_tour,
    course_name,
    month_label,
    prize_text,
    excel_default_path,
    is_active
)
values (
    'us-open-2026',
    'US Open',
    'US Open 2026 Kupongen',
    'U.S. Open',
    'pga',
    null,
    'June',
    '4.000 kr',
    'US Open 2026 - Resultater.xlsx',
    true
)
on conflict (slug) do nothing;

insert into tournaments (
    slug,
    tournament_name,
    display_title,
    datagolf_event_name,
    datagolf_tour,
    course_name,
    month_label,
    prize_text,
    excel_default_path,
    is_active
)
values (
    'the-open-2026',
    'The Open',
    'The Open 2026 Kupongen',
    'The Open Championship',
    'pga',
    'Royal Birkdale',
    'July',
    '4.000 kr',
    'The Open 2026 - Resultater.xlsx',
    false
)
on conflict (slug) do nothing;

insert into tournaments (
    slug, tournament_name, display_title, datagolf_event_name, datagolf_tour,
    month_label, prize_text, excel_default_path, is_active
)
values
    ('masters-2026', 'Masters', 'Masters 2026 Kupongen', 'Masters Tournament', 'pga', 'April', '4.000 kr', 'Masters 2026 - Resultater.xlsx', false),
    ('pga-championship-2026', 'PGA Championship', 'PGA Championship 2026 Kupongen', 'PGA Championship', 'pga', 'May', '4.000 kr', 'PGA Championship 2026 - Resultater.xlsx', false)
on conflict (slug) do nothing;

do $$
declare
    us_open_id bigint;
begin
    select id into us_open_id from tournaments where slug = 'us-open-2026' limit 1;
    if us_open_id is null then
        return;
    end if;

    update teams set tournament_id = us_open_id where tournament_id is null;
    update players set tournament_id = us_open_id where tournament_id is null;
    update team_players set tournament_id = us_open_id where tournament_id is null;
    update scores set tournament_id = us_open_id where tournament_id is null;
    update daily_comments set tournament_id = us_open_id where tournament_id is null;
    update live_events set tournament_id = us_open_id where tournament_id is null;
end $$;

insert into app_settings (key, value, updated_at)
select 'active_tournament_id', id::text, now()
from tournaments
where slug = 'us-open-2026'
on conflict (key) do update
set value = excluded.value,
    updated_at = excluded.updated_at;

alter table teams drop constraint if exists teams_name_key;
create unique index if not exists teams_tournament_name_idx on teams (tournament_id, name);

alter table players drop constraint if exists players_name_key;
create unique index if not exists players_tournament_name_idx on players (tournament_id, name);

alter table daily_comments drop constraint if exists daily_comments_round_no_key;
create unique index if not exists daily_comments_tournament_round_idx on daily_comments (tournament_id, round_no);

alter table scores drop constraint if exists scores_player_id_round_no_key;
create unique index if not exists scores_tournament_player_round_idx on scores (tournament_id, player_id, round_no);

alter table tournaments enable row level security;

drop policy if exists "tournaments_select_public" on tournaments;
drop policy if exists "tournaments_insert_public" on tournaments;
drop policy if exists "tournaments_update_public" on tournaments;

create policy "tournaments_select_public"
    on tournaments for select to anon, authenticated using (true);

create policy "tournaments_insert_public"
    on tournaments for insert to anon, authenticated with check (true);

create policy "tournaments_update_public"
    on tournaments for update to anon, authenticated using (true) with check (true);
