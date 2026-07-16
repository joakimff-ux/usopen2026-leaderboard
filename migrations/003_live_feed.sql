-- Add the fantasy-relevant live feed to an existing The Open 2026 database.
-- Run once in Supabase SQL Editor. Existing teams, players and scores remain unchanged.

begin;

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

create index idx_live_player_states_tournament
    on live_player_states(tournament_id, player_id, round);
create index idx_live_feed_events_tournament
    on live_feed_events(tournament_id, created_at desc);

alter table live_player_states enable row level security;
alter table live_feed_events enable row level security;

create policy public_read_live_feed_events
    on live_feed_events for select to anon, authenticated using (true);

grant select on live_feed_events to anon, authenticated;
revoke insert, update, delete on live_feed_events from anon, authenticated;
revoke all on live_player_states from anon, authenticated;

commit;
