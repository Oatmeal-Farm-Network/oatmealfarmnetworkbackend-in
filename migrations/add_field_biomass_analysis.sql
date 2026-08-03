-- Stores per-field biomass estimates from satellite imagery and/or user uploads.
-- Source column distinguishes the two; multiple rows per field are kept for history.
IF NOT EXISTS (SELECT 1 FROM sysobjects WHERE name = 'FieldBiomassAnalysis' AND xtype = 'U')
BEGIN
    CREATE TABLE FieldBiomassAnalysis (
        AnalysisID         INT IDENTITY(1,1) PRIMARY KEY,
        FieldID            INT            NOT NULL,
        BusinessID         INT            NOT NULL,
        Source             VARCHAR(20)    NOT NULL,   -- 'satellite' | 'upload'
        BiomassKgHa        DECIMAL(10, 2) NULL,
        Confidence         DECIMAL(5, 3)  NULL,
        ImageUrl           VARCHAR(1000)  NULL,
        CapturedAt         DATETIME       NULL,
        ModelVersion       VARCHAR(50)    NULL,
        FeaturesJSON       NVARCHAR(MAX)  NULL,
        CreatedByPeopleID  INT            NULL,
        CreatedAt          DATETIME       NOT NULL DEFAULT GETUTCDATE()
    );

    CREATE INDEX IX_FieldBiomassAnalysis_FieldID    ON FieldBiomassAnalysis(FieldID);
    CREATE INDEX IX_FieldBiomassAnalysis_BusinessID ON FieldBiomassAnalysis(BusinessID);
    CREATE INDEX IX_FieldBiomassAnalysis_Field_Src  ON FieldBiomassAnalysis(FieldID, Source, CapturedAt DESC);
END;
