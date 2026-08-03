-- ── FIELD SCOUTING ───────────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name = 'FieldScout' AND xtype = 'U')
BEGIN
    CREATE TABLE FieldScout (
        ScoutID        INT IDENTITY(1,1) PRIMARY KEY,
        FieldID        INT            NOT NULL,
        BusinessID     INT            NOT NULL,
        PeopleID       INT            NULL,
        ObservedAt     DATETIME       NOT NULL DEFAULT GETUTCDATE(),
        Category       VARCHAR(50)    NOT NULL DEFAULT 'General',  -- Pest, Disease, Weed, Irrigation, General
        Severity       VARCHAR(20)    NULL,                        -- Low, Medium, High, Critical
        Notes          NVARCHAR(MAX)  NULL,
        Latitude       DECIMAL(10,7)  NULL,
        Longitude      DECIMAL(10,7)  NULL,
        ImageUrl       VARCHAR(1000)  NULL,
        CreatedAt      DATETIME       NOT NULL DEFAULT GETUTCDATE()
    );
    CREATE INDEX IX_FieldScout_FieldID    ON FieldScout(FieldID);
    CREATE INDEX IX_FieldScout_BusinessID ON FieldScout(BusinessID);
END;

-- ── SOIL SAMPLES ─────────────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name = 'FieldSoilSample' AND xtype = 'U')
BEGIN
    CREATE TABLE FieldSoilSample (
        SampleID       INT IDENTITY(1,1) PRIMARY KEY,
        FieldID        INT            NOT NULL,
        BusinessID     INT            NOT NULL,
        SampleDate     DATE           NULL,
        SampleLabel    VARCHAR(100)   NULL,
        Latitude       DECIMAL(10,7)  NULL,
        Longitude      DECIMAL(10,7)  NULL,
        Depth_cm       INT            NULL,       -- sample depth in cm
        pH             DECIMAL(4,2)   NULL,
        OrganicMatter  DECIMAL(5,2)   NULL,       -- %
        Nitrogen       DECIMAL(8,2)   NULL,       -- kg/ha or ppm
        Phosphorus     DECIMAL(8,2)   NULL,
        Potassium      DECIMAL(8,2)   NULL,
        Sulfur         DECIMAL(8,2)   NULL,
        Calcium        DECIMAL(8,2)   NULL,
        Magnesium      DECIMAL(8,2)   NULL,
        CEC            DECIMAL(6,2)   NULL,       -- cation exchange capacity
        Notes          NVARCHAR(MAX)  NULL,
        CreatedAt      DATETIME       NOT NULL DEFAULT GETUTCDATE()
    );
    CREATE INDEX IX_FieldSoilSample_FieldID    ON FieldSoilSample(FieldID);
    CREATE INDEX IX_FieldSoilSample_BusinessID ON FieldSoilSample(BusinessID);
END;

-- ── VARIABLE RATE PRESCRIPTIONS ──────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name = 'FieldPrescription' AND xtype = 'U')
BEGIN
    CREATE TABLE FieldPrescription (
        PrescriptionID INT IDENTITY(1,1) PRIMARY KEY,
        FieldID        INT            NOT NULL,
        BusinessID     INT            NOT NULL,
        Name           VARCHAR(255)   NOT NULL,
        Product        VARCHAR(255)   NULL,       -- fertilizer / chemical name
        Unit           VARCHAR(50)    NULL,       -- kg/ha, L/ha, etc.
        IndexKey       VARCHAR(20)    NULL,       -- NDVI, NDRE, etc.
        ZoneMethod     VARCHAR(50)    NULL,       -- Equidistant, Quantile, etc.
        NumZones       INT            NULL,
        ZoneRatesJSON  NVARCHAR(MAX)  NULL,       -- [{zone:1, rate:50}, ...]
        AnalysisDate   DATE           NULL,
        Notes          NVARCHAR(MAX)  NULL,
        CreatedAt      DATETIME       NOT NULL DEFAULT GETUTCDATE()
    );
    CREATE INDEX IX_FieldPrescription_FieldID    ON FieldPrescription(FieldID);
    CREATE INDEX IX_FieldPrescription_BusinessID ON FieldPrescription(BusinessID);
END;
