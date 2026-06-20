-- Persistent app settings (e.g. auto-sync toggle).
-- Run once in the Supabase SQL editor.

create table if not exists app_settings (
    key text primary key,
    value text not null,
    updated_at timestamptz not null default now()
);
