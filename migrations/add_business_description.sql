-- Add BusinessDescription column to Business table
-- Run once in SQL Server Management Studio

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'Business' AND COLUMN_NAME = 'BusinessDescription'
)
BEGIN
    ALTER TABLE Business ADD BusinessDescription NVARCHAR(MAX) NULL;
END
