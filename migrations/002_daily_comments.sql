-- Daily admin commentary for participants.
-- Run once in the Supabase SQL editor.

create table if not exists daily_comments (
    id bigint generated always as identity primary key,
    round_no integer not null check (round_no between 1 and 4),
    title text not null,
    body text not null,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique (round_no)
);
