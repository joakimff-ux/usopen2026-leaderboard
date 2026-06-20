-- RLS policies for app_settings (required when RLS is enabled on the table).
-- Run once in the Supabase SQL editor if upsert fails with code 42501.

alter table app_settings enable row level security;

drop policy if exists "app_settings_select_public" on app_settings;
drop policy if exists "app_settings_insert_public" on app_settings;
drop policy if exists "app_settings_update_public" on app_settings;

create policy "app_settings_select_public"
    on app_settings
    for select
    to anon, authenticated
    using (true);

create policy "app_settings_insert_public"
    on app_settings
    for insert
    to anon, authenticated
    with check (true);

create policy "app_settings_update_public"
    on app_settings
    for update
    to anon, authenticated
    using (true)
    with check (true);
