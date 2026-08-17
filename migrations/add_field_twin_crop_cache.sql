-- Field Twin — SoilGrids cache + crop-source grower decisions (India; no USDA CDL)
--
-- REQUIRED for production: apply this migration explicitly.
-- routers/field_twin.py may call SQLAlchemy create_all as a local bootstrap
-- for missing tables, but create_all does NOT reliably create these unique
-- indexes on an existing database. Deploy checklists must run this script.

IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name = 'FieldExternalDataCache' AND xtype = 'U')
BEGIN
    CREATE TABLE FieldExternalDataCache (
        CacheID       INT IDENTITY(1,1) PRIMARY KEY,
        FieldID       INT            NOT NULL,
        Provider      VARCHAR(50)    NOT NULL,
        LocationHash  VARCHAR(64)    NOT NULL,
        BoundaryHash  VARCHAR(64)    NULL,
        DataVersion   VARCHAR(40)    NOT NULL DEFAULT '1',
        PayloadJSON   NVARCHAR(MAX)  NULL,
        FetchedAt     DATETIME       NULL,
        ExpiresAt     DATETIME       NULL,
        LastAttemptAt DATETIME       NULL,
        LastError     VARCHAR(500)   NULL
    );
    CREATE INDEX IX_FieldExternalDataCache_FieldID ON FieldExternalDataCache(FieldID);
    CREATE UNIQUE INDEX UX_FieldExternalDataCache_Lookup
        ON FieldExternalDataCache(FieldID, Provider, LocationHash, DataVersion);
END

IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name = 'FieldCropSourceDecision' AND xtype = 'U')
BEGIN
    CREATE TABLE FieldCropSourceDecision (
        DecisionID             INT IDENTITY(1,1) PRIMARY KEY,
        FieldID                INT            NOT NULL,
        BusinessID             INT            NOT NULL,
        SeasonYear             INT            NOT NULL,
        SelectedSource         VARCHAR(40)    NOT NULL,
        SelectedCrop           VARCHAR(255)   NOT NULL,
        RecordedCropAtDecision VARCHAR(255)   NULL,
        DetectedCropAtDecision VARCHAR(255)   NULL,
        CDLCode                INT            NULL,
        DecidedByPeopleID      INT            NULL,
        DecidedAt              DATETIME       NULL
    );
    CREATE INDEX IX_FieldCropSourceDecision_FieldID ON FieldCropSourceDecision(FieldID);
    CREATE INDEX IX_FieldCropSourceDecision_BusinessID ON FieldCropSourceDecision(BusinessID);
    CREATE UNIQUE INDEX UX_FieldCropSourceDecision_FieldYear
        ON FieldCropSourceDecision(FieldID, SeasonYear);
END
