-- Persist a manual admin-controlled roster-change window.

begin;

alter table tournaments
    add column if not exists roster_change_window_open boolean not null default false;

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
        select 1 from tournaments
        where id = p_tournament_id and roster_change_window_open = true
    ) then
        raise exception 'The roster-change window is closed.';
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
        tournament_id,
        round_from,
        is_active,
        is_locked,
        created_by
    ) values (
        p_tournament_id,
        3,
        true,
        false,
        p_changed_by
    ) returning id into v_change_set_id;

    insert into roster_changes (
        change_set_id,
        tournament_id,
        team_id,
        round_from,
        old_player_id,
        new_player_id,
        changed_by
    )
    select
        v_change_set_id,
        p_tournament_id,
        x.team_id,
        3,
        x.old_player_id,
        x.new_player_id,
        p_changed_by
    from jsonb_to_recordset(p_changes)
        as x(team_id uuid, old_player_id uuid, new_player_id uuid);

    return v_change_set_id;
end;
$$;

revoke all on function save_roster_changes_atomic(uuid, int, text, jsonb)
    from public, anon, authenticated;
grant execute on function save_roster_changes_atomic(uuid, int, text, jsonb)
    to service_role;

update roster_change_sets
set is_locked = false
where is_active = true;

notify pgrst, 'reload schema';

commit;
