# Fantasy Golf Kupongen – Supabase golfapp

Regel: Hvert lag har 7 spillere. De 5 laveste scorene per lag per dag teller. De 2 dårligste droppes hver dag. Lavest totalscore leder.

Appen støtter flere turneringer (US Open, The Open, Masters, PGA Championship) via turneringskonfigurasjon i databasen.

## Kjør lokalt

1. Opprett tabeller i Supabase med `schema.sql` (ny installasjon) **eller** kjør migreringer (se under).
2. Kopier `.streamlit/secrets.toml.example` til `.streamlit/secrets.toml`.
3. Legg inn `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `ADMIN_PASSWORD` og `DATA_GOLF_API_KEY`.
4. Kjør:

```bash
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

## Migreringer (eksisterende database)

Kjør i Supabase SQL editor, i rekkefølge:

1. `migrations/001_round_based_rosters.sql` – lagbytter etter cut
2. `migrations/002_daily_comments.sql` – dagsrapport
3. `migrations/003_sync_log.sql` – DataGolf sync-logg
4. `migrations/005_app_settings.sql` + `006_app_settings_rls.sql` – persistent auto-sync
5. `migrations/007_live_events.sql` – live hendelser på banen
6. **`migrations/008_tournaments.sql`** – multi-turnering (bevarer eksisterende US Open-data)

## How to set up a new tournament

1. **Kjør migrering 008** hvis du ikke har `tournaments`-tabellen ennå. Eksisterende lag, spillere og scorer knyttes automatisk til `us-open-2026`.

2. **Opprett turnering** (hvis den ikke finnes fra mal):
   - Gå til **Admin → Turnering**
   - Velg mal (f.eks. `the-open-2026`) og klikk **Opprett turnering fra mal**

3. **Bytt aktiv turnering**:
   - Velg turnering i nedtrekkslisten (f.eks. *The Open 2026 Kupongen*)
   - Klikk **Bytt aktiv turnering**

4. **Rediger innstillinger** (valgfritt):
   - Visningstittel, DataGolf event name, bane, måned, premietekst
   - Spillere per lag, teller/droppes per dag, post-cut runde, maks bytter
   - Klikk **Lagre turneringsinnstillinger**

5. **Importer roster**:
   - Legg Excel-fil i `data/` (f.eks. `The Open 2026 - Resultater.xlsx`) **eller** last opp fil
   - Klikk **Importer Excel-roster for aktiv turnering**

6. **Importer DataGolf-felt** (valgfritt):
   - Klikk **Importer fullt DataGolf-felt for aktiv turnering**
   - Sjekk at DataGolf event name matcher (f.eks. `The Open Championship`)

7. **Sett opp laguttak** under **Admin → Laguttak** etter import.

8. **Test sync** under **Admin → Scorer** med «Sync all scores from DataGolf now».

### The Open 2026 (Royal Birkdale, July)

Malen `the-open-2026` er forhåndsutfylt med:

- Tittel: **The Open 2026 Kupongen**
- DataGolf event: **The Open Championship**
- Bane: **Royal Birkdale**
- Samme regler som US Open (7 spillere, 5 teller, 2 droppes, 3 bytter etter cut)

### Sikker tilbakestilling

Under **Admin → Turnering** kan du tilbakestille **kun aktiv turnering** (andre turneringer i databasen påvirkes ikke):

- **Reset scores only** – sletter scorer og live_events
- **Reset rosters only** – sletter laguttak (`team_players`)
- **Reset whole tournament** – sletter lag, spillere, scorer, kommentarer for aktiv turnering

Skriv `BEKREFT` i bekreftelsesfeltet før du trykker reset.

## Første import (legacy)

Gå til Admin → Importer fra Excel og trykk importknappen. Appen leser standard Excel-fil for aktiv turnering i `data/` eller en opplastet fil.

## Lagbytter etter dag 2

Etter migrering 001 kan admin under **Laguttak**:

- redigere originalt lag for Dag 1–2
- bytte inntil 3 spillere for Dag 3–4 etter cut

Leaderboard bruker originalt lag for Dag 1–2 og oppdatert lag for Dag 3–4.

## Dagsrapport

Admin → **Dagsrapport** genererer norsk fantasy-kompis-rapport (uten OpenAI) med valgbar tone: Saklig, Morsom, Frekk eller Brutal. Lagrede kommentarer vises som **Dagens kommentar** over leaderboard.

## Tester

```bash
python test_rosters.py
python test_live_events.py
python test_tournament.py
python test_app_settings.py
```

Test mot Supabase: `python test_app_settings_db.py`
