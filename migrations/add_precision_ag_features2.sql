-- Precision Ag Features Batch 2
-- Run once against the database

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FieldActivityLog')
BEGIN
    CREATE TABLE FieldActivityLog (
        ActivityID    INT IDENTITY(1,1) PRIMARY KEY,
        FieldID       INT NOT NULL,
        BusinessID    INT,
        PeopleID      INT,
        ActivityDate  DATE,
        ActivityType  VARCHAR(50),   -- Spray, Fertilize, Tillage, Irrigation, Harvest, Planting, Other
        Product       VARCHAR(255),
        Rate          DECIMAL(10,2),
        RateUnit      VARCHAR(50),
        OperatorName  VARCHAR(255),
        Notes         TEXT,
        CreatedAt     DATETIME DEFAULT GETDATE()
    );
END;
