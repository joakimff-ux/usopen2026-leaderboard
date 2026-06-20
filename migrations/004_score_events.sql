-- Live score change events for "Live hendelser på banen".
-- Run once in the Supabase SQL editor.

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
