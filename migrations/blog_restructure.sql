-- =============================================================
-- Blog Table Restructure Migration
-- Run this once in SQL Server Management Studio
-- Migrates blog/blogcategories/blogphotos from PeopleID-based
-- legacy structure to a clean BusinessID-focused schema.
-- =============================================================

BEGIN TRANSACTION;

-- =============================================================
-- STEP 1: Add new columns to blog
-- =============================================================

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blog' AND COLUMN_NAME='BusinessID')
    ALTER TABLE blog ADD BusinessID INT NULL;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blog' AND COLUMN_NAME='Title')
    ALTER TABLE blog ADD Title NVARCHAR(500) NULL;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blog' AND COLUMN_NAME='Slug')
    ALTER TABLE blog ADD Slug NVARCHAR(500) NULL;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blog' AND COLUMN_NAME='CoverImage')
    ALTER TABLE blog ADD CoverImage NVARCHAR(500) NULL;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blog' AND COLUMN_NAME='Content')
    ALTER TABLE blog ADD Content NVARCHAR(MAX) NULL;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blog' AND COLUMN_NAME='IsPublished')
    ALTER TABLE blog ADD IsPublished BIT NOT NULL DEFAULT 0;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blog' AND COLUMN_NAME='IsFeatured')
    ALTER TABLE blog ADD IsFeatured BIT NOT NULL DEFAULT 0;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blog' AND COLUMN_NAME='CreatedAt')
    ALTER TABLE blog ADD CreatedAt DATETIME NULL;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blog' AND COLUMN_NAME='UpdatedAt')
    ALTER TABLE blog ADD UpdatedAt DATETIME NULL;

-- =============================================================
-- STEP 2: Migrate data into new blog columns
-- =============================================================

-- Populate BusinessID from BusinessAccess via PeopleID
UPDATE b
SET b.BusinessID = ba.BusinessID
FROM blog b
JOIN BusinessAccess ba ON ba.PeopleID = b.PeopleID
WHERE b.BusinessID IS NULL AND b.PeopleID IS NOT NULL;

-- Copy BlogHeadline → Title
UPDATE blog
SET Title = BlogHeadline
WHERE (Title IS NULL OR Title = '') AND BlogHeadline IS NOT NULL AND BlogHeadline != '';

-- Derive Slug from Title (lowercase, hyphens, truncated)
UPDATE blog
SET Slug = LOWER(
    REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
        LEFT(Title, 200),
    ' ', '-'), ',', ''), '.', ''), '''', ''), '!', ''), '?', '')
)
WHERE Slug IS NULL AND Title IS NOT NULL;

-- Cover image: prefer BlogUpload, fall back to BlogImage1
UPDATE blog
SET CoverImage = COALESCE(NULLIF(LTRIM(RTRIM(BlogUpload)), ''), NULLIF(LTRIM(RTRIM(BlogImage1)), ''))
WHERE CoverImage IS NULL;

-- IsPublished from BlogDisplay
UPDATE blog
SET IsPublished = CASE WHEN BlogDisplay = 1 THEN 1 ELSE 0 END
WHERE IsPublished = 0 AND BlogDisplay IS NOT NULL;

-- CreatedAt from date parts
UPDATE blog
SET CreatedAt = TRY_CAST(
    CAST(COALESCE(BlogYear, YEAR(GETDATE())) AS VARCHAR) + '-' +
    RIGHT('0' + CAST(COALESCE(NULLIF(BlogMonth,0), 1) AS VARCHAR), 2) + '-' +
    RIGHT('0' + CAST(COALESCE(NULLIF(BlogDay,0), 1) AS VARCHAR), 2)
    AS DATETIME)
WHERE CreatedAt IS NULL;

UPDATE blog SET CreatedAt = GETDATE() WHERE CreatedAt IS NULL;
UPDATE blog SET UpdatedAt = GETDATE() WHERE UpdatedAt IS NULL;

-- Consolidate up to 20 text sections into Content
UPDATE blog SET Content =
    COALESCE(NULLIF(LTRIM(RTRIM(BlogText1)), ''), '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading2)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading2 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText2)),'') IS NOT NULL THEN CHAR(10)+BlogText2 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading3)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading3 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText3)),'') IS NOT NULL THEN CHAR(10)+BlogText3 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading4)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading4 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText4)),'') IS NOT NULL THEN CHAR(10)+BlogText4 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading5)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading5 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText5)),'') IS NOT NULL THEN CHAR(10)+BlogText5 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading6)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading6 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText6)),'') IS NOT NULL THEN CHAR(10)+BlogText6 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading7)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading7 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText7)),'') IS NOT NULL THEN CHAR(10)+BlogText7 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading8)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading8 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText8)),'') IS NOT NULL THEN CHAR(10)+BlogText8 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading9)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading9 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText9)),'') IS NOT NULL THEN CHAR(10)+BlogText9 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading10)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading10 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText10)),'') IS NOT NULL THEN CHAR(10)+BlogText10 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading11)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading11 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText11)),'') IS NOT NULL THEN CHAR(10)+BlogText11 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading12)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading12 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText12)),'') IS NOT NULL THEN CHAR(10)+BlogText12 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading13)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading13 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText13)),'') IS NOT NULL THEN CHAR(10)+BlogText13 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading14)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading14 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText14)),'') IS NOT NULL THEN CHAR(10)+BlogText14 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading15)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading15 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText15)),'') IS NOT NULL THEN CHAR(10)+BlogText15 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading16)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading16 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText16)),'') IS NOT NULL THEN CHAR(10)+BlogText16 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading17)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading17 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText17)),'') IS NOT NULL THEN CHAR(10)+BlogText17 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading18)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading18 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText18)),'') IS NOT NULL THEN CHAR(10)+BlogText18 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading19)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading19 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText19)),'') IS NOT NULL THEN CHAR(10)+BlogText19 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(PageHeading20)),'') IS NOT NULL THEN CHAR(10)+'## '+PageHeading20 ELSE '' END, '') +
    ISNULL(CASE WHEN NULLIF(LTRIM(RTRIM(BlogText20)),'') IS NOT NULL THEN CHAR(10)+BlogText20 ELSE '' END, '')
WHERE Content IS NULL OR Content = '';

-- =============================================================
-- STEP 3: Drop old blog columns
-- (drop default constraints first, then the columns)
-- =============================================================

DECLARE @sql NVARCHAR(MAX) = '';

-- Collect all default constraints on the columns we're dropping
SELECT @sql += 'ALTER TABLE blog DROP CONSTRAINT [' + dc.name + '];' + CHAR(10)
FROM sys.default_constraints dc
JOIN sys.columns c ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
WHERE OBJECT_NAME(dc.parent_object_id) = 'blog'
  AND c.name IN (
    'PeopleID','EventID','BlogCatID','BlogPageNumber',
    'BlogDay','BlogMonth','BlogYear','BlogHeadline','BlogUpload',
    'PageHeading1','BlogText1','BlogImage1','ImageOrientation1','ImageCaption1',
    'PageHeading2','BlogText2','BlogImage2','ImageOrientation2','ImageCaption2',
    'PageHeading3','BlogText3','BlogImage3','ImageOrientation3','ImageCaption3',
    'PageHeading4','BlogText4','BlogImage4','ImageOrientation4','ImageCaption4',
    'PageHeading5','BlogText5','BlogImage5','ImageOrientation5','ImageCaption5',
    'PageHeading6','BlogText6','BlogImage6','ImageOrientation6','ImageCaption6',
    'PageHeading7','BlogText7','BlogImage7','ImageOrientation7','ImageCaption7',
    'PageHeading8','BlogText8','BlogImage8','ImageOrientation8','ImageCaption8',
    'PageHeading9','BlogText9','BlogImage9','ImageOrientation9','ImageCaption9',
    'PageHeading10','BlogText10','BlogImage10','ImageOrientation10','ImageCaption10',
    'PageHeading11','BlogText11','BlogImage11','ImageOrientation11','ImageCaption11',
    'PageHeading12','BlogText12','BlogImage12','ImageOrientation12','ImageCaption12',
    'PageHeading13','BlogText13','BlogImage13','ImageOrientation13','ImageCaption13',
    'PageHeading14','BlogText14','BlogImage14','ImageOrientation14','ImageCaption14',
    'PageHeading15','BlogText15','BlogImage15','ImageOrientation15','ImageCaption15',
    'PageHeading16','BlogText16','BlogImage16','ImageOrientation16','ImageCaption16',
    'PageHeading17','BlogText17','BlogImage17','ImageOrientation17','ImageCaption17',
    'PageHeading18','BlogText18','BlogImage18','ImageOrientation18','ImageCaption18',
    'PageHeading19','BlogText19','BlogImage19','ImageOrientation19','ImageCaption19',
    'PageHeading20','BlogText20','BlogImage20','ImageOrientation20','ImageCaption20',
    'BlogDisplay','watermark','AuthorLink'
  );

EXEC sp_executesql @sql;

-- Now drop the columns
ALTER TABLE blog DROP COLUMN
    PeopleID, EventID, BlogPageNumber,
    BlogDay, BlogMonth, BlogYear, BlogHeadline, BlogUpload,
    PageHeading1, BlogText1, BlogImage1, ImageOrientation1, ImageCaption1,
    PageHeading2, BlogText2, BlogImage2, ImageOrientation2, ImageCaption2,
    PageHeading3, BlogText3, BlogImage3, ImageOrientation3, ImageCaption3,
    PageHeading4, BlogText4, BlogImage4, ImageOrientation4, ImageCaption4,
    PageHeading5, BlogText5, BlogImage5, ImageOrientation5, ImageCaption5,
    PageHeading6, BlogText6, BlogImage6, ImageOrientation6, ImageCaption6,
    PageHeading7, BlogText7, BlogImage7, ImageOrientation7, ImageCaption7,
    PageHeading8, BlogText8, BlogImage8, ImageOrientation8, ImageCaption8,
    PageHeading9, BlogText9, BlogImage9, ImageOrientation9, ImageCaption9,
    PageHeading10, BlogText10, BlogImage10, ImageOrientation10, ImageCaption10,
    PageHeading11, BlogText11, BlogImage11, ImageOrientation11, ImageCaption11,
    PageHeading12, BlogText12, BlogImage12, ImageOrientation12, ImageCaption12,
    PageHeading13, BlogText13, BlogImage13, ImageOrientation13, ImageCaption13,
    PageHeading14, BlogText14, BlogImage14, ImageOrientation14, ImageCaption14,
    PageHeading15, BlogText15, BlogImage15, ImageOrientation15, ImageCaption15,
    PageHeading16, BlogText16, BlogImage16, ImageOrientation16, ImageCaption16,
    PageHeading17, BlogText17, BlogImage17, ImageOrientation17, ImageCaption17,
    PageHeading18, BlogText18, BlogImage18, ImageOrientation18, ImageCaption18,
    PageHeading19, BlogText19, BlogImage19, ImageOrientation19, ImageCaption19,
    PageHeading20, BlogText20, BlogImage20, ImageOrientation20, ImageCaption20,
    BlogDisplay, watermark;

-- Keep AuthorLink (useful), add it back to keep if it was accidentally listed above
-- Note: AuthorLink is kept in the new schema — remove it from the DROP list if present

-- =============================================================
-- STEP 4: Restructure blogcategories
-- =============================================================

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogcategories' AND COLUMN_NAME='BusinessID')
    ALTER TABLE blogcategories ADD BusinessID INT NULL;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogcategories' AND COLUMN_NAME='IsGlobal')
    ALTER TABLE blogcategories ADD IsGlobal BIT NOT NULL DEFAULT 0;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogcategories' AND COLUMN_NAME='IsActive')
    ALTER TABLE blogcategories ADD IsActive BIT NOT NULL DEFAULT 1;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogcategories' AND COLUMN_NAME='CreatedAt')
    ALTER TABLE blogcategories ADD CreatedAt DATETIME DEFAULT GETDATE();

-- Migrate PeopleID → BusinessID
UPDATE bc
SET bc.BusinessID = ba.BusinessID
FROM blogcategories bc
JOIN BusinessAccess ba ON ba.PeopleID = bc.PeopleID
WHERE bc.BusinessID IS NULL AND bc.PeopleID IS NOT NULL;

-- Migrate BlogCategoryDisplay → IsActive
UPDATE blogcategories
SET IsActive = CASE WHEN BlogCategoryDisplay = 1 THEN 1 ELSE 0 END
WHERE BlogCategoryDisplay IS NOT NULL;

-- Drop old blogcategories columns
DECLARE @sql2 NVARCHAR(MAX) = '';
SELECT @sql2 += 'ALTER TABLE blogcategories DROP CONSTRAINT [' + dc.name + '];' + CHAR(10)
FROM sys.default_constraints dc
JOIN sys.columns c ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
WHERE OBJECT_NAME(dc.parent_object_id) = 'blogcategories'
  AND c.name IN ('PeopleID','EventID','BlogCategoryDisplay','watermark');
EXEC sp_executesql @sql2;

IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogcategories' AND COLUMN_NAME='PeopleID')
    ALTER TABLE blogcategories DROP COLUMN PeopleID;
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogcategories' AND COLUMN_NAME='EventID')
    ALTER TABLE blogcategories DROP COLUMN EventID;
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogcategories' AND COLUMN_NAME='BlogCategoryDisplay')
    ALTER TABLE blogcategories DROP COLUMN BlogCategoryDisplay;
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogcategories' AND COLUMN_NAME='watermark')
    ALTER TABLE blogcategories DROP COLUMN watermark;

-- Seed global network categories (only if blogcategories is empty of global ones)
IF NOT EXISTS (SELECT 1 FROM blogcategories WHERE IsGlobal = 1)
BEGIN
    INSERT INTO blogcategories (BusinessID, IsGlobal, BlogCategoryName, BlogCategoryOrder, IsActive, CreatedAt)
    VALUES
        (NULL, 1, 'General',        1,  1, GETDATE()),
        (NULL, 1, 'Farm News',      2,  1, GETDATE()),
        (NULL, 1, 'Recipes',        3,  1, GETDATE()),
        (NULL, 1, 'Seasonal',       4,  1, GETDATE()),
        (NULL, 1, 'Events',         5,  1, GETDATE()),
        (NULL, 1, 'Education',      6,  1, GETDATE()),
        (NULL, 1, 'Market Updates', 7,  1, GETDATE()),
        (NULL, 1, 'Community',      8,  1, GETDATE());
END

-- =============================================================
-- STEP 5: Restructure blogphotos
-- =============================================================

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogphotos' AND COLUMN_NAME='BlogID')
    ALTER TABLE blogphotos ADD BlogID INT NULL;

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogphotos' AND COLUMN_NAME='ImageCaption')
    ALTER TABLE blogphotos ADD ImageCaption NVARCHAR(500) NULL;

-- Drop Issue and watermark columns from blogphotos
DECLARE @sql3 NVARCHAR(MAX) = '';
SELECT @sql3 += 'ALTER TABLE blogphotos DROP CONSTRAINT [' + dc.name + '];' + CHAR(10)
FROM sys.default_constraints dc
JOIN sys.columns c ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
WHERE OBJECT_NAME(dc.parent_object_id) = 'blogphotos'
  AND c.name IN ('Issue','watermark');
EXEC sp_executesql @sql3;

IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogphotos' AND COLUMN_NAME='Issue')
    ALTER TABLE blogphotos DROP COLUMN Issue;
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='blogphotos' AND COLUMN_NAME='watermark')
    ALTER TABLE blogphotos DROP COLUMN watermark;

-- =============================================================
-- STEP 6: Drop BusinessBlogPosts and BusinessBlogCategories
-- =============================================================

IF EXISTS (SELECT * FROM sysobjects WHERE name='BusinessBlogCategories' AND xtype='U')
    DROP TABLE BusinessBlogCategories;

IF EXISTS (SELECT * FROM sysobjects WHERE name='BusinessBlogPosts' AND xtype='U')
    DROP TABLE BusinessBlogPosts;

-- =============================================================
-- STEP 7: Add indexes for performance
-- =============================================================

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_blog_BusinessID' AND object_id = OBJECT_ID('blog'))
    CREATE INDEX IX_blog_BusinessID ON blog (BusinessID);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_blog_BusinessID_IsPublished' AND object_id = OBJECT_ID('blog'))
    CREATE INDEX IX_blog_BusinessID_IsPublished ON blog (BusinessID, IsPublished);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_blog_BlogCatID' AND object_id = OBJECT_ID('blog'))
    CREATE INDEX IX_blog_BlogCatID ON blog (BlogCatID);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_blogcategories_BusinessID' AND object_id = OBJECT_ID('blogcategories'))
    CREATE INDEX IX_blogcategories_BusinessID ON blogcategories (BusinessID);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_blogphotos_BlogID' AND object_id = OBJECT_ID('blogphotos'))
    CREATE INDEX IX_blogphotos_BlogID ON blogphotos (BlogID, PhotoOrder);

COMMIT TRANSACTION;

-- =============================================================
-- Final schemas:
--
-- blog:
--   BlogID, BusinessID, BlogCatID, Title, Slug, Author,
--   AuthorLink, CoverImage, Content, IsPublished, IsFeatured,
--   CreatedAt, UpdatedAt
--
-- blogcategories:
--   BlogCatID, BusinessID (NULL=global), IsGlobal,
--   BlogCategoryName, BlogCategoryDescription,
--   BlogCategoryOrder, IsActive, CreatedAt
--
-- blogphotos:
--   PhotoID, BlogID, PhotoOrder, Image, ImageTitle, ImageCaption
-- =============================================================
