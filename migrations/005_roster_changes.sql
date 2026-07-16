-- Add append-only post-round-two roster changes without mutating team_players or scores.

begin;

create table if not exists roster_change_sets (
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

create unique index if not exists uq_roster_change_sets_active_tournament
    on roster_change_sets(tournament_id)
    where is_active = true;

create table if not exists roster_changes (
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

create index if not exists idx_roster_changes_tournament
    on roster_changes(tournament_id, change_set_id, team_id);

alter table roster_change_sets enable row level security;
alter table roster_changes enable row level security;

drop policy if exists public_read_roster_change_sets on roster_change_sets;
create policy public_read_roster_change_sets
    on roster_change_sets for select to anon, authenticated using (true);

drop policy if exists public_read_roster_changes on roster_changes;
create policy public_read_roster_changes
    on roster_changes for select to anon, authenticated using (true);

grant select on roster_change_sets, roster_changes to anon, authenticated;
revoke insert, update, delete on roster_change_sets, roster_changes from anon, authenticated;

commit;
