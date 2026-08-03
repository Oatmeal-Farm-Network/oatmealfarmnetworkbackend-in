-- ════════════════════════════════════════════════════════════════════════════
-- FieldAssessmentReport — persisted Saige-authored consultant reports.
--
-- Each row is one snapshot the operator (or Saige on the operator's behalf)
-- generated. We keep both the parsed JSON the UI renders AND the raw LLM
-- text so a future migration / re-render can recover from a schema change
-- without re-spending tokens.
--
-- The ContextJSON column captures the data we sent to the LLM at the time
-- of generation; this lets us audit what Saige saw, and Saige's RAG can
-- look up "what did the field look like the last time we wrote a report?"
--
-- Re-run safe: only creates the table if it does not exist yet.
-- ════════════════════════════════════════════════════════════════════════════

IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name = 'FieldAssessmentReport' AND xtype = 'U')
BEGIN
    CREATE TABLE FieldAssessmentReport (
        ReportID         INT IDENTITY(1,1) PRIMARY KEY,
        FieldID          INT NOT NULL,
        BusinessID       INT NULL,
        PeopleID         INT NULL,
        GeneratedAt      DATETIME       NOT NULL DEFAULT GETUTCDATE(),

        -- Stable summary surface for fast list rendering / RAG retrieval.
        Headline         NVARCHAR(500)  NULL,   -- executive summary line
        OverallHealth    VARCHAR(20)    NULL,   -- good / fair / poor / unknown
        Confidence       VARCHAR(20)    NULL,   -- high / medium / low

        -- Full structured report the UI renders. Stored as JSON text so the
        -- schema can evolve without touching this table.
        ReportJSON       NVARCHAR(MAX)  NULL,
        -- Raw LLM output, kept for audit / fallback when JSON parsing fails.
        RawText          NVARCHAR(MAX)  NULL,
        -- Snapshot of the input data at generation time (for RAG + audit).
        ContextJSON      NVARCHAR(MAX)  NULL,

        DeletedAt        DATETIME       NULL
    );

    CREATE INDEX IX_FieldAssessmentReport_FieldID_GeneratedAt
        ON FieldAssessmentReport (FieldID, GeneratedAt DESC);
    CREATE INDEX IX_FieldAssessmentReport_BusinessID
        ON FieldAssessmentReport (BusinessID);
END;
