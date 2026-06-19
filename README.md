# US Open 2026 Fantasy Golf

Streamlit fantasy golf competition app for the US Open 2026. Teams draft 7 golfers, count the best 5 scores each round, drop the worst 2, and compete over 4 rounds.

## Features

- Public leaderboard with round and tournament totals
- Team detail page showing counting and dropped players
- Admin tools for Excel import, roster management, score entry, and reset
- Supabase-backed persistence
- Golf-themed, mobile-friendly UI

## Competition rules

- Each team has exactly 7 golfers
- Lowest score is best
- Each round, only the 5 best golfer scores count
- The 2 worst golfer scores are dropped each round
- Tournament lasts 4 rounds
- Team score is the sum of the 5 counting scores each round
- Lowest total score wins

## Project files

- `app.py` — Streamlit application
- `schema.sql` — Supabase table definitions
- `sample_data_loader.py` — CLI import script
- `data/US Open 2026 - Resultater.xlsx` — source roster workbook
- `lib/` — database, import, scoring, auth, and styling helpers

## Setup

1. Create a Supabase project and run `schema.sql` in the SQL editor.
2. Fill in `.streamlit/secrets.toml`:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_ANON_KEY = "your-anon-key"
ADMIN_PASSWORD = "your-admin-password"
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Import the Excel roster:

```bash
python sample_data_loader.py
```

5. Run the app:

```bash
streamlit run app.py
```

## Excel format

The importer expects the workbook sheet `Ark1` with this layout:

- Row 3, columns B–E: `Dag 1` through `Dag 4`
- Row 3, columns G–N: team names
- Column A: tier labels (`Tier 1`, `Tier 2`, …) and player names
- Team columns: `X` marks for roster selections

All players in the workbook are imported, including unpicked players.

## Admin

Open the Admin page and log in with `ADMIN_PASSWORD`. From there you can:

- Upload and import a new Excel roster
- Add or remove teams and players
- Edit team rosters
- Enter scores for rounds 1–4
- Reset tournament data

## DataGolf live scoring

Configure `DATA_GOLF_API_KEY` in `.streamlit/secrets.toml`.

Admin page:

- **Sync Live Scores Now** — one-time sync from DataGolf
- **Enable Auto Sync** — sync every 5 minutes

CLI:

```bash
python datagolf_sync.py --test
python datagolf_sync.py --sync
```

The sync matches DataGolf `player_name` values to Supabase players using case-insensitive, trimmed name matching and upserts round scores without creating duplicates.
