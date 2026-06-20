-- Live score change events for "Live hendelser på banen".
-- Run once in the Supabase SQL editor.

create table if not exists live_events (
    id bigint generated always as identity primary key,
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

drop policy if exists "live_events_select_public" on live_events;
drop policy if exists "live_events_insert_public" on live_events;

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
