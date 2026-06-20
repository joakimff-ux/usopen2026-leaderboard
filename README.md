# US Open 2026 - Supabase golfapp

Regel: Hvert lag har 7 spillere. De 5 laveste scorene per lag per dag teller. De 2 dårligste droppes hver dag. Lavest totalscore leder.

## Kjør lokalt

1. Opprett tabeller i Supabase med `schema.sql`.
2. Kopier `.streamlit/secrets.toml.example` til `.streamlit/secrets.toml`.
3. Legg inn `SUPABASE_URL`, `SUPABASE_ANON_KEY` og `ADMIN_PASSWORD`.
4. Kjør:

```bash
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

## Første import

Gå til Admin -> Import fra Excel og trykk importknappen. Appen leser filen i `data/US Open 2026 - Resultater.xlsx` eller en opplastet Excel-fil.

## Lagbytter etter dag 2

Kjør `migrations/001_round_based_rosters.sql` i Supabase SQL editor én gang.

Deretter kan admin under **Laguttak**:
- redigere originalt lag for Dag 1–2
- bytte inntil 3 spillere for Dag 3–4 etter cut

Leaderboard bruker originalt lag for Dag 1–2 og oppdatert lag for Dag 3–4.

## Dagsrapport

Kjør `migrations/002_daily_comments.sql` i Supabase SQL editor.

Admin → **Dagsrapport** genererer norsk fantasy-kompis-rapport (uten OpenAI) med valgbar tone: Saklig, Morsom, Frekk eller Brutal. Lagrede kommentarer vises som **Dagens kommentar** over leaderboard.

## DataGolf sync-logg

Kjør `migrations/003_sync_log.sql` i Supabase SQL editor for API-feillogging og siste vellykkede synk.

Kjør `migrations/005_app_settings.sql` for persistent auto-sync-innstilling (`auto_sync_enabled`).
