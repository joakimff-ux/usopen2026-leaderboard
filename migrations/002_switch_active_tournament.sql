-- Switch active tournament (run manually in Supabase SQL Editor)
-- Replace the UUID below with the target tournament id from:
--   select id, name, year, is_active from tournaments order by name;

-- Example: activate The Open 2026 (only after roster import and verification)
-- update tournaments set is_active = false where is_active = true;
-- update tournaments
-- set is_active = true
-- where name = 'The Open 2026' and year = 2026;

-- Example: switch back to US Open 2026
-- update tournaments set is_active = false where is_active = true;
-- update tournaments
-- set is_active = true
-- where name = 'US Open 2026' and year = 2026;
