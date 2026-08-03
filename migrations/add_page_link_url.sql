-- Add LinkURL column to BusinessWebPage table.
-- Allows a page-row to act as a pure menu link (to another page, an anchor
-- on another page, or an external URL) instead of rendering its own content.
-- Run once in SQL Server Management Studio.

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'BusinessWebPage' AND COLUMN_NAME = 'LinkURL'
)
BEGIN
    ALTER TABLE BusinessWebPage ADD LinkURL NVARCHAR(500) NULL;
END
