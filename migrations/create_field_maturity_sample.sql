-- ════════════════════════════════════════════════════════════════════════════
-- FieldMaturitySample — ground-truth ripeness/quality readings used to fit
-- the per-field maturity curve and predict the peak-antioxidant harvest date.
--
-- Every column is optional except SampleDate, FieldID, BusinessID — different
-- farms log different metrics depending on what tools they have:
--
--   • Brix              — refractometer, soluble solids (°Bx). Plateau ≈ ripe.
--   • Firmness          — penetrometer, kilograms-force. Drops as fruit softens.
--   • Anthocyanin       — handheld NIR (Felix F-750), mg/g fresh weight.
--                         Best direct proxy for berry antioxidant levels.
--   • pH                — titratable-acid drop indicates ripening.
--   • TitratableAcidity — % malic / citric acid, lab measurement.
--   • ColorScoreL/A/B   — colorimeter Lab values; A* climbs as red develops.
--   • DryMatterPct      — destructive lab measurement.
--   • SampleSize        — how many berries were measured (for averaging).
--   • LabName           — provenance: 'in-house refractometer', 'F-750', etc.
--
-- Re-run safe: only creates the table if it does not exist yet.
-- ════════════════════════════════════════════════════════════════════════════

IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name = 'FieldMaturitySample' AND xtype = 'U')
BEGIN
    CREATE TABLE FieldMaturitySample (
        SampleID            INT IDENTITY(1,1) PRIMARY KEY,
        FieldID             INT NOT NULL,
        BusinessID          INT NOT NULL,
        PeopleID            INT NULL,
        SampleDate          DATE NOT NULL,

        Cultivar            VARCHAR(100)  NULL,
        SampleSize          INT           NULL,
        LabName             VARCHAR(200)  NULL,

        BrixDegrees         DECIMAL(5, 2) NULL,   -- °Bx (typical 4–25)
        FirmnessKgF         DECIMAL(5, 2) NULL,   -- kgf
        AnthocyaninMgG      DECIMAL(7, 3) NULL,   -- mg / g fresh weight
        PH                  DECIMAL(4, 2) NULL,
        TitratableAcidityPct DECIMAL(5, 2) NULL,
        ColorScoreL         DECIMAL(6, 2) NULL,
        ColorScoreA         DECIMAL(6, 2) NULL,
        ColorScoreB         DECIMAL(6, 2) NULL,
        DryMatterPct        DECIMAL(5, 2) NULL,

        Notes               NVARCHAR(MAX) NULL,
        ImageUrl            VARCHAR(1000) NULL,
        CreatedAt           DATETIME      NOT NULL DEFAULT GETUTCDATE(),
        UpdatedAt           DATETIME      NOT NULL DEFAULT GETUTCDATE()
    );

    CREATE INDEX IX_FieldMaturitySample_FieldID_Date
        ON FieldMaturitySample (FieldID, SampleDate DESC);
    CREATE INDEX IX_FieldMaturitySample_BusinessID
        ON FieldMaturitySample (BusinessID);
END;

-- ── Optional: per-field harvest-target settings ─────────────────────────────
-- Where the farm wants the fruit to land, and when. The engine works backwards
-- from this. Cold-chain distance is in miles; if not set we surface that as a
-- known unknown rather than guessing.
IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name = 'FieldHarvestTarget' AND xtype = 'U')
BEGIN
    CREATE TABLE FieldHarvestTarget (
        TargetID            INT IDENTITY(1,1) PRIMARY KEY,
        FieldID             INT NOT NULL,
        BusinessID          INT NOT NULL,

        DestinationLabel    VARCHAR(200) NULL,    -- e.g. "Whole Foods - Austin DC"
        DestinationMiles    DECIMAL(7, 1) NULL,   -- one-way road miles, farm → DC
        ReceivingLagDays    INT NULL,             -- days from DC arrival to shelf
        ShelfTargetDate     DATE NULL,            -- when buyer wants fruit on shelf

        Notes               NVARCHAR(MAX) NULL,
        CreatedAt           DATETIME NOT NULL DEFAULT GETUTCDATE(),
        UpdatedAt           DATETIME NOT NULL DEFAULT GETUTCDATE()
    );

    CREATE INDEX IX_FieldHarvestTarget_FieldID
        ON FieldHarvestTarget (FieldID);
END;
