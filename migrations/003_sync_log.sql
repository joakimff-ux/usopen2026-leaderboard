-- DataGolf sync API log.
-- Run once in the Supabase SQL editor.

create table if not exists sync_log (
    id bigint generated always as identity primary key,
    status text not null check (status in ('success', 'error', 'rate_limited')),
    http_status integer,
    message text not null,
    scores_written integer default 0,
    retry_count integer default 0,
    created_at timestamptz default now()
);

create index if not exists sync_log_created_at_idx on sync_log (created_at desc);
