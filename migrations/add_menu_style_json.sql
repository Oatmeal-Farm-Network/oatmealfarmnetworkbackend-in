-- Add MenuStyleJSON column to BusinessWebsite table.
-- Stores per-site menu typography (top & sub levels) as a JSON blob.
-- Run once in SQL Server Management Studio.

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'BusinessWebsite' AND COLUMN_NAME = 'MenuStyleJSON'
)
BEGIN
    ALTER TABLE BusinessWebsite ADD MenuStyleJSON NVARCHAR(MAX) NULL;
END
