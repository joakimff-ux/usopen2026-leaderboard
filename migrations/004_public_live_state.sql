-- Allow the public leaderboard to read live hole/status snapshots.
-- Run after migrations/003_live_feed.sql. Writes remain service-role-only.

begin;

drop policy if exists public_read_live_player_states on live_player_states;
create policy public_read_live_player_states
    on live_player_states for select to anon, authenticated using (true);

grant select on live_player_states to anon, authenticated;
revoke insert, update, delete on live_player_states from anon, authenticated;

commit;
