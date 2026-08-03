-- seed_oatmeal_ai.sql
-- Creates the "Oatmeal AI" Business account if it doesn't already exist,
-- then runs accounting setup (chart of accounts + current fiscal year).
--
-- Run once against the shared SQL Server database:
--   sqlcmd -S <server> -d <database> -U <user> -P <pass> -i seed_oatmeal_ai.sql
--
-- The POST /api/accounting/seed-oatmeal-ai endpoint does the same thing
-- if you prefer to trigger it via the API.
-- ─────────────────────────────────────────────────────────────────────────────

SET NOCOUNT ON;

-- 1. Create the Business row (idempotent)
IF NOT EXISTS (SELECT 1 FROM Business WHERE BusinessName = 'Oatmeal AI')
BEGIN
    DECLARE @TypeID INT;
    SELECT TOP 1 @TypeID = BusinessTypeID FROM businesstypelookup ORDER BY BusinessTypeID;

    INSERT INTO Business (BusinessTypeID, BusinessName, BusinessEmail, SubscriptionLevel, AccessLevel)
    VALUES (@TypeID, 'Oatmeal AI', 'info@oatmeal-ai.com', 1, 1);

    PRINT 'Oatmeal AI business created with BusinessID = ' + CAST(SCOPE_IDENTITY() AS NVARCHAR);
END
ELSE
BEGIN
    PRINT 'Oatmeal AI business already exists. BusinessID = ' +
          CAST((SELECT BusinessID FROM Business WHERE BusinessName = 'Oatmeal AI') AS NVARCHAR);
END

-- 2. Capture the BusinessID
DECLARE @BID INT;
SELECT @BID = BusinessID FROM Business WHERE BusinessName = 'Oatmeal AI';

-- 3. Initialize chart of accounts (idempotent — stored procedure skips if already seeded)
IF NOT EXISTS (SELECT 1 FROM Accounts WHERE BusinessID = @BID)
BEGIN
    EXEC CreateDefaultChartOfAccounts @BusinessID = @BID;
    PRINT 'Chart of accounts created for BusinessID ' + CAST(@BID AS NVARCHAR);
END
ELSE
    PRINT 'Chart of accounts already exists for BusinessID ' + CAST(@BID AS NVARCHAR);

-- 4. Create current fiscal year (idempotent)
DECLARE @Year INT = YEAR(GETDATE());
IF NOT EXISTS (SELECT 1 FROM FiscalYears WHERE BusinessID = @BID AND YearName = 'FY' + CAST(@Year AS NVARCHAR))
BEGIN
    INSERT INTO FiscalYears (BusinessID, YearName, StartDate, EndDate)
    VALUES (@BID, 'FY' + CAST(@Year AS NVARCHAR),
            CAST(@Year AS NVARCHAR) + '-01-01',
            CAST(@Year AS NVARCHAR) + '-12-31');

    DECLARE @FYID INT = SCOPE_IDENTITY();
    DECLARE @m INT = 1;
    WHILE @m <= 12
    BEGIN
        INSERT INTO FiscalPeriods (FiscalYearID, BusinessID, PeriodNumber, PeriodName, StartDate, EndDate)
        VALUES (
            @FYID, @BID, @m,
            DATENAME(MONTH, DATEFROMPARTS(@Year, @m, 1)) + ' ' + CAST(@Year AS NVARCHAR),
            DATEFROMPARTS(@Year, @m, 1),
            EOMONTH(DATEFROMPARTS(@Year, @m, 1))
        );
        SET @m = @m + 1;
    END
    PRINT 'Fiscal year FY' + CAST(@Year AS NVARCHAR) + ' created for BusinessID ' + CAST(@BID AS NVARCHAR);
END
ELSE
    PRINT 'Fiscal year already exists for BusinessID ' + CAST(@BID AS NVARCHAR);

PRINT 'Seed complete. Oatmeal AI BusinessID = ' + CAST(@BID AS NVARCHAR);
