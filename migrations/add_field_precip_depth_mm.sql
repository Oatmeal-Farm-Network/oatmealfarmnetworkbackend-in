-- Field Twin precip logs: explicit millimetre column (India).
-- DepthIn is retained for older rows that stored millimetres under the USA name.

IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'FieldPrecipLog')
AND NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'FieldPrecipLog' AND COLUMN_NAME = 'DepthMm'
)
BEGIN
    ALTER TABLE FieldPrecipLog ADD DepthMm DECIMAL(8,3) NULL;
    UPDATE FieldPrecipLog SET DepthMm = DepthIn WHERE DepthMm IS NULL;
END
