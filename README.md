# The Open 2026 Fantasy Golf

Streamlit app for The Open 2026 at Royal Birkdale. Each team selects seven golfers; the five lowest scores count in each of four rounds.

## New Supabase project

This production baseline is intentionally built for a new, empty Supabase project. Old US Open data and the SQL files under `migrations/` are not required and must not be run on the new database.

Run exactly one SQL file in Supabase SQL Editor:

1. `schema.sql`

The script creates and seeds the active The Open 2026 tournament, creates rounds 1–4, enables row-level security, permits public reads, and blocks public writes.

## Secrets and key separation

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and set:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_ANON_KEY = "your-anon-key"
SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"
ADMIN_PASSWORD = "a-long-unique-password"
DATA_GOLF_API_KEY = "your-datagolf-key"
```

- `SUPABASE_ANON_KEY` is used for leaderboard, team detail, tournament lookup, and read-only DataGolf diagnostics. RLS limits it to `SELECT`.
- `SUPABASE_SERVICE_ROLE_KEY` is necessary because RLS intentionally blocks anonymous writes. It is used only after admin login or by the server-side sync/import routines: Excel import/reset, team/player/roster administration, manual scores, player status overrides, penalty freezing/overrides, active tournament writes, and DataGolf score/status sync.
- The service role key must exist only in local or deployed Streamlit secrets. The app never renders, logs, or sends it to browser code. Never commit `.streamlit/secrets.toml`.

## Missing-score rule

Each round has a configurable penalty: the highest official completed round score in the entire field plus `tournaments.missing_score_penalty` (default 2).

- An admin freezes the penalty only when the round is finished and the official completed scores are final.
- A frozen penalty is persisted in `tournament_rounds` and does not move with later feed changes.
- A penalty requires an explicit `CUT`, `WD`, or `DQ`; missing or delayed DataGolf data alone never triggers it.
- CUT preserves rounds 1–2 and applies from round 3.
- WD/DQ preserves any official completed score. A missing score in the effective or later round can use the frozen penalty.
- If fewer than five real scores exist, only the required counting places are filled. Four real scores use one penalty; three use two.
- Team detail labels a penalty as `Straff (CUT)`, `Straff (WD)`, or `Straff (DQ)`.
- Admin status and penalty overrides are append-only/audited in `admin_audit_log` and visible on the admin page.

## Excel import

The importer expects `data/The Open 2026 - Resultater.xlsx`, sheet `Ark1`:

- the current The Open template: participant names on the first tier row from column C;
- the legacy result layout is also accepted: rounds in B–E and team names on row 3 from G;
- column A: `Tier N` headers and player names;
- `X` in team columns marks selections;
- every team must have exactly seven golfers.

Validate without a database connection or write:

```powershell
python sample_data_loader.py --dry-run
```

Import only after the production database and secrets are approved:

```powershell
python sample_data_loader.py
```

## Local start and tests

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
streamlit run app.py
```

DataGolf read-only test and write sync:

```powershell
python datagolf_sync.py --test
python datagolf_sync.py --sync
```

The sync first requires an exact normalized match between the active tournament's `datagolf_event_name` and the event in the DataGolf response. A missing or different event aborts before any write. Player names support DataGolf's documented `Last, First` representation without fuzzy matching.

## Live feed

Fresh databases created from the current `schema.sql` already contain the live-feed tables. For the existing The Open production database created before this feature was added, run exactly one additive script in Supabase SQL Editor:

1. `migrations/003_live_feed.sql`

This migration does not change or delete tournaments, teams, players, rosters, or scores. The service-role sync stores a baseline for selected players, then creates an event only when `thru`, `today`, completion, or an explicit CUT/WD/DQ status changes. Repeated syncs are deduplicated by a database-enforced deterministic key. The public client can read the event list but cannot read sync state or write events.

The leaderboard refreshes the latest 15 stored events every 30 seconds without a full page reload. DataGolf's in-play feed does not expose an official player hole-by-hole log, so the app only attributes a hole result when the player advances exactly one hole between consecutive snapshots. If a sync skips multiple holes, no individual-hole event is invented.

For inline leaderboard team previews with live hole/status information, run this additive policy migration after `003_live_feed.sql`:

1. `migrations/004_public_live_state.sql`

It grants anon/authenticated users read-only access to the live snapshot table. Insert, update, and delete remain blocked; DataGolf continues to write with the server-only service role key.

## Deployment

Deploy the repository as a Streamlit app with `app.py` as the entry point. Add all five secrets in the host's secret manager. Do not place the service role key in source control, frontend configuration, screenshots, or logs.
