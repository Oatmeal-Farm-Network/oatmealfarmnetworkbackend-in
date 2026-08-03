-- ════════════════════════════════════════════════════════════════════════════
-- Merge FieldScout into FieldNote so the Field Journal handles both.
--
-- Step 1: add Severity / Latitude / Longitude / ImageUrl columns to FieldNote.
-- Step 2: copy every FieldScout row into FieldNote as a Category-tagged journal
--         entry. The original FieldScout table is left intact for now so the
--         data is recoverable; drop it in a follow-up once you've verified.
--
-- Step 2 is wrapped in EXEC(...) so SQL Server defers binding the new column
-- names until *after* Step 1's ALTER TABLE statements have actually executed.
-- This makes the script safe to run as a single batch in tools (Azure Data
-- Studio, DBeaver, generic mssql clients) that don't honor `GO` separators.
--
-- Re-run safe: each step checks before mutating.
-- ════════════════════════════════════════════════════════════════════════════

-- ── Step 1: add new columns on FieldNote ────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE Name = N'Severity' AND Object_ID = Object_ID(N'FieldNote'))
BEGIN
    ALTER TABLE FieldNote ADD Severity VARCHAR(20) NULL;
END;

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE Name = N'Latitude' AND Object_ID = Object_ID(N'FieldNote'))
BEGIN
    ALTER TABLE FieldNote ADD Latitude DECIMAL(10, 7) NULL;
END;

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE Name = N'Longitude' AND Object_ID = Object_ID(N'FieldNote'))
BEGIN
    ALTER TABLE FieldNote ADD Longitude DECIMAL(10, 7) NULL;
END;

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE Name = N'ImageUrl' AND Object_ID = Object_ID(N'FieldNote'))
BEGIN
    ALTER TABLE FieldNote ADD ImageUrl VARCHAR(1000) NULL;
END;

-- ── Step 2: copy FieldScout → FieldNote (one-time, deferred-bind) ───────────
-- Idempotency guard: tag each migrated row with a sentinel in the Title so a
-- second run won't double-insert. Skip rows whose ScoutID already shows up in
-- a previously-migrated note title.
--
-- Wrapped in EXEC() so the parser doesn't try to bind Severity/Latitude/
-- Longitude/ImageUrl on FieldNote until after Step 1 has applied.
IF EXISTS (SELECT 1 FROM sysobjects WHERE name = 'FieldScout' AND xtype = 'U')
BEGIN
    EXEC('
        INSERT INTO FieldNote (
            FieldID, BusinessID, PeopleID,
            NoteDate, Category, Title, Content,
            Severity, Latitude, Longitude, ImageUrl,
            CreatedAt, UpdatedAt
        )
        SELECT
            s.FieldID,
            s.BusinessID,
            s.PeopleID,
            CAST(ISNULL(s.ObservedAt, s.CreatedAt) AS DATE) AS NoteDate,
            ISNULL(s.Category, ''Scouting'')                AS Category,
            CONCAT(
                ISNULL(s.Category, ''Scouting''),
                '' observation'',
                CASE WHEN s.Severity IS NOT NULL THEN '' ('' + s.Severity + '')'' ELSE '''' END,
                '' [scout#'', CAST(s.ScoutID AS VARCHAR(20)), '']''
            )                                               AS Title,
            ISNULL(s.Notes, '''')                           AS Content,
            s.Severity,
            s.Latitude,
            s.Longitude,
            s.ImageUrl,
            ISNULL(s.CreatedAt, GETUTCDATE())               AS CreatedAt,
            ISNULL(s.CreatedAt, GETUTCDATE())               AS UpdatedAt
        FROM FieldScout s
        WHERE NOT EXISTS (
            SELECT 1 FROM FieldNote n
            WHERE n.Title LIKE ''%[scout#'' + CAST(s.ScoutID AS VARCHAR(20)) + '']%''
        );
    ');
END;

-- After verifying the merge looks right in the UI, you can run this to
-- retire the old table. Left commented so the migration is non-destructive.
-- DROP TABLE FieldScout;
