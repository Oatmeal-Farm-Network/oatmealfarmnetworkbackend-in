-- Migration: add all BusinessWebsite columns that may be missing from the cloud DB
-- Safe to run multiple times: each statement is gated by COL_LENGTH (NULL = column absent).

-- Background colors / page theming
IF COL_LENGTH('BusinessWebsite', 'ScreenBackgroundColor') IS NULL ALTER TABLE BusinessWebsite ADD ScreenBackgroundColor NVARCHAR(20) NULL;
IF COL_LENGTH('BusinessWebsite', 'PageBackgroundColor')   IS NULL ALTER TABLE BusinessWebsite ADD PageBackgroundColor   NVARCHAR(20) NULL;
IF COL_LENGTH('BusinessWebsite', 'BgImageURL')            IS NULL ALTER TABLE BusinessWebsite ADD BgImageURL            NVARCHAR(1000) NULL;
IF COL_LENGTH('BusinessWebsite', 'BgGradient')            IS NULL ALTER TABLE BusinessWebsite ADD BgGradient            NVARCHAR(500) NULL;

-- Width controls
IF COL_LENGTH('BusinessWebsite', 'BodyContentWidth')   IS NULL ALTER TABLE BusinessWebsite ADD BodyContentWidth   NVARCHAR(20) NULL DEFAULT '100%';
IF COL_LENGTH('BusinessWebsite', 'BodyBgWidth')        IS NULL ALTER TABLE BusinessWebsite ADD BodyBgWidth        NVARCHAR(20) NULL DEFAULT '100%';
IF COL_LENGTH('BusinessWebsite', 'HeaderBgWidth')      IS NULL ALTER TABLE BusinessWebsite ADD HeaderBgWidth      NVARCHAR(20) NULL DEFAULT '100%';
IF COL_LENGTH('BusinessWebsite', 'FooterBgWidth')      IS NULL ALTER TABLE BusinessWebsite ADD FooterBgWidth      NVARCHAR(20) NULL DEFAULT '100%';
IF COL_LENGTH('BusinessWebsite', 'HeaderContentWidth') IS NULL ALTER TABLE BusinessWebsite ADD HeaderContentWidth NVARCHAR(20) NULL DEFAULT '100%';
IF COL_LENGTH('BusinessWebsite', 'FooterContentWidth') IS NULL ALTER TABLE BusinessWebsite ADD FooterContentWidth NVARCHAR(20) NULL DEFAULT '100%';

-- H1 typography
IF COL_LENGTH('BusinessWebsite', 'H1Size')         IS NULL ALTER TABLE BusinessWebsite ADD H1Size        NVARCHAR(20)  NULL DEFAULT '40px';
IF COL_LENGTH('BusinessWebsite', 'H1Weight')       IS NULL ALTER TABLE BusinessWebsite ADD H1Weight      NVARCHAR(10)  NULL DEFAULT '800';
IF COL_LENGTH('BusinessWebsite', 'H1Color')        IS NULL ALTER TABLE BusinessWebsite ADD H1Color       NVARCHAR(20)  NULL DEFAULT '';
IF COL_LENGTH('BusinessWebsite', 'H1Align')        IS NULL ALTER TABLE BusinessWebsite ADD H1Align       NVARCHAR(10)  NULL DEFAULT 'left';
IF COL_LENGTH('BusinessWebsite', 'H1Underline')    IS NULL ALTER TABLE BusinessWebsite ADD H1Underline   BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H1Italic')       IS NULL ALTER TABLE BusinessWebsite ADD H1Italic      BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H1Rule')         IS NULL ALTER TABLE BusinessWebsite ADD H1Rule        BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H1RuleColor')    IS NULL ALTER TABLE BusinessWebsite ADD H1RuleColor   NVARCHAR(20)  NULL DEFAULT '';
IF COL_LENGTH('BusinessWebsite', 'H1MarginTop')    IS NULL ALTER TABLE BusinessWebsite ADD H1MarginTop   INT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H1MarginBottom') IS NULL ALTER TABLE BusinessWebsite ADD H1MarginBottom INT          NULL DEFAULT 8;
IF COL_LENGTH('BusinessWebsite', 'H1Font')         IS NULL ALTER TABLE BusinessWebsite ADD H1Font        NVARCHAR(200) NULL DEFAULT '';

-- H2 typography
IF COL_LENGTH('BusinessWebsite', 'H2Size')         IS NULL ALTER TABLE BusinessWebsite ADD H2Size        NVARCHAR(20)  NULL DEFAULT '29px';
IF COL_LENGTH('BusinessWebsite', 'H2Weight')       IS NULL ALTER TABLE BusinessWebsite ADD H2Weight      NVARCHAR(10)  NULL DEFAULT '700';
IF COL_LENGTH('BusinessWebsite', 'H2Color')        IS NULL ALTER TABLE BusinessWebsite ADD H2Color       NVARCHAR(20)  NULL DEFAULT '';
IF COL_LENGTH('BusinessWebsite', 'H2Align')        IS NULL ALTER TABLE BusinessWebsite ADD H2Align       NVARCHAR(10)  NULL DEFAULT 'left';
IF COL_LENGTH('BusinessWebsite', 'H2Underline')    IS NULL ALTER TABLE BusinessWebsite ADD H2Underline   BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H2Italic')       IS NULL ALTER TABLE BusinessWebsite ADD H2Italic      BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H2Rule')         IS NULL ALTER TABLE BusinessWebsite ADD H2Rule        BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H2RuleColor')    IS NULL ALTER TABLE BusinessWebsite ADD H2RuleColor   NVARCHAR(20)  NULL DEFAULT '';
IF COL_LENGTH('BusinessWebsite', 'H2MarginTop')    IS NULL ALTER TABLE BusinessWebsite ADD H2MarginTop   INT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H2MarginBottom') IS NULL ALTER TABLE BusinessWebsite ADD H2MarginBottom INT          NULL DEFAULT 8;
IF COL_LENGTH('BusinessWebsite', 'H2Font')         IS NULL ALTER TABLE BusinessWebsite ADD H2Font        NVARCHAR(200) NULL DEFAULT '';

-- H3 typography
IF COL_LENGTH('BusinessWebsite', 'H3Size')         IS NULL ALTER TABLE BusinessWebsite ADD H3Size        NVARCHAR(20)  NULL DEFAULT '21px';
IF COL_LENGTH('BusinessWebsite', 'H3Weight')       IS NULL ALTER TABLE BusinessWebsite ADD H3Weight      NVARCHAR(10)  NULL DEFAULT '600';
IF COL_LENGTH('BusinessWebsite', 'H3Color')        IS NULL ALTER TABLE BusinessWebsite ADD H3Color       NVARCHAR(20)  NULL DEFAULT '';
IF COL_LENGTH('BusinessWebsite', 'H3Align')        IS NULL ALTER TABLE BusinessWebsite ADD H3Align       NVARCHAR(10)  NULL DEFAULT 'left';
IF COL_LENGTH('BusinessWebsite', 'H3Underline')    IS NULL ALTER TABLE BusinessWebsite ADD H3Underline   BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H3Italic')       IS NULL ALTER TABLE BusinessWebsite ADD H3Italic      BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H3Rule')         IS NULL ALTER TABLE BusinessWebsite ADD H3Rule        BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H3RuleColor')    IS NULL ALTER TABLE BusinessWebsite ADD H3RuleColor   NVARCHAR(20)  NULL DEFAULT '';
IF COL_LENGTH('BusinessWebsite', 'H3MarginTop')    IS NULL ALTER TABLE BusinessWebsite ADD H3MarginTop   INT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H3MarginBottom') IS NULL ALTER TABLE BusinessWebsite ADD H3MarginBottom INT          NULL DEFAULT 6;
IF COL_LENGTH('BusinessWebsite', 'H3Font')         IS NULL ALTER TABLE BusinessWebsite ADD H3Font        NVARCHAR(200) NULL DEFAULT '';

-- H4 typography
IF COL_LENGTH('BusinessWebsite', 'H4Size')         IS NULL ALTER TABLE BusinessWebsite ADD H4Size        NVARCHAR(20)  NULL DEFAULT '17px';
IF COL_LENGTH('BusinessWebsite', 'H4Weight')       IS NULL ALTER TABLE BusinessWebsite ADD H4Weight      NVARCHAR(10)  NULL DEFAULT '600';
IF COL_LENGTH('BusinessWebsite', 'H4Color')        IS NULL ALTER TABLE BusinessWebsite ADD H4Color       NVARCHAR(20)  NULL DEFAULT '';
IF COL_LENGTH('BusinessWebsite', 'H4Align')        IS NULL ALTER TABLE BusinessWebsite ADD H4Align       NVARCHAR(10)  NULL DEFAULT 'left';
IF COL_LENGTH('BusinessWebsite', 'H4Underline')    IS NULL ALTER TABLE BusinessWebsite ADD H4Underline   BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H4Italic')       IS NULL ALTER TABLE BusinessWebsite ADD H4Italic      BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H4Rule')         IS NULL ALTER TABLE BusinessWebsite ADD H4Rule        BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H4RuleColor')    IS NULL ALTER TABLE BusinessWebsite ADD H4RuleColor   NVARCHAR(20)  NULL DEFAULT '';
IF COL_LENGTH('BusinessWebsite', 'H4MarginTop')    IS NULL ALTER TABLE BusinessWebsite ADD H4MarginTop   INT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'H4MarginBottom') IS NULL ALTER TABLE BusinessWebsite ADD H4MarginBottom INT          NULL DEFAULT 4;
IF COL_LENGTH('BusinessWebsite', 'H4Font')         IS NULL ALTER TABLE BusinessWebsite ADD H4Font        NVARCHAR(200) NULL DEFAULT '';

-- Body typography
IF COL_LENGTH('BusinessWebsite', 'BodySize')        IS NULL ALTER TABLE BusinessWebsite ADD BodySize        NVARCHAR(20)  NULL DEFAULT '16px';
IF COL_LENGTH('BusinessWebsite', 'BodyLineHeight')  IS NULL ALTER TABLE BusinessWebsite ADD BodyLineHeight  NVARCHAR(10)  NULL DEFAULT '1.75';
IF COL_LENGTH('BusinessWebsite', 'BodyColor')       IS NULL ALTER TABLE BusinessWebsite ADD BodyColor       NVARCHAR(20)  NULL DEFAULT '';
IF COL_LENGTH('BusinessWebsite', 'BodyAlign')       IS NULL ALTER TABLE BusinessWebsite ADD BodyAlign       NVARCHAR(10)  NULL DEFAULT 'left';
IF COL_LENGTH('BusinessWebsite', 'BodyUnderline')   IS NULL ALTER TABLE BusinessWebsite ADD BodyUnderline   BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'BodyItalic')      IS NULL ALTER TABLE BusinessWebsite ADD BodyItalic      BIT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'BodyMarginTop')   IS NULL ALTER TABLE BusinessWebsite ADD BodyMarginTop   INT           NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'BodyMarginBottom')IS NULL ALTER TABLE BusinessWebsite ADD BodyMarginBottom INT          NULL DEFAULT 12;
IF COL_LENGTH('BusinessWebsite', 'BodyFont')        IS NULL ALTER TABLE BusinessWebsite ADD BodyFont        NVARCHAR(200) NULL DEFAULT '';

-- Links
IF COL_LENGTH('BusinessWebsite', 'LinkColor')     IS NULL ALTER TABLE BusinessWebsite ADD LinkColor     NVARCHAR(20) NULL DEFAULT '';
IF COL_LENGTH('BusinessWebsite', 'LinkUnderline') IS NULL ALTER TABLE BusinessWebsite ADD LinkUnderline BIT          NULL DEFAULT 1;

-- Dropdown nav
IF COL_LENGTH('BusinessWebsite', 'DropdownBgColor')     IS NULL ALTER TABLE BusinessWebsite ADD DropdownBgColor     NVARCHAR(50) NULL;
IF COL_LENGTH('BusinessWebsite', 'DropdownHoverColor')  IS NULL ALTER TABLE BusinessWebsite ADD DropdownHoverColor  NVARCHAR(50) NULL;
IF COL_LENGTH('BusinessWebsite', 'DropdownBgColor2')    IS NULL ALTER TABLE BusinessWebsite ADD DropdownBgColor2    NVARCHAR(50) NULL;
IF COL_LENGTH('BusinessWebsite', 'DropdownGradientDir') IS NULL ALTER TABLE BusinessWebsite ADD DropdownGradientDir NVARCHAR(20) NULL DEFAULT '135deg';

-- Image styling
IF COL_LENGTH('BusinessWebsite', 'ImageBorderRadius')   IS NULL ALTER TABLE BusinessWebsite ADD ImageBorderRadius   INT          NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'ImageShadowEnabled')  IS NULL ALTER TABLE BusinessWebsite ADD ImageShadowEnabled  BIT          NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'ImageShadowColor')    IS NULL ALTER TABLE BusinessWebsite ADD ImageShadowColor    NVARCHAR(40) NULL DEFAULT 'rgba(0,0,0,0.35)';
IF COL_LENGTH('BusinessWebsite', 'ImageShadowDistance') IS NULL ALTER TABLE BusinessWebsite ADD ImageShadowDistance INT          NULL DEFAULT 4;
IF COL_LENGTH('BusinessWebsite', 'ImageShadowBlur')     IS NULL ALTER TABLE BusinessWebsite ADD ImageShadowBlur     INT          NULL DEFAULT 8;
IF COL_LENGTH('BusinessWebsite', 'ImageShadowAngle')    IS NULL ALTER TABLE BusinessWebsite ADD ImageShadowAngle    INT          NULL DEFAULT 135;

-- Footer extras
IF COL_LENGTH('BusinessWebsite', 'FooterBgImageURL')    IS NULL ALTER TABLE BusinessWebsite ADD FooterBgImageURL    NVARCHAR(1000) NULL;
IF COL_LENGTH('BusinessWebsite', 'FooterHeight')        IS NULL ALTER TABLE BusinessWebsite ADD FooterHeight        INT            NULL DEFAULT 200;
IF COL_LENGTH('BusinessWebsite', 'FooterBottomRadius')  IS NULL ALTER TABLE BusinessWebsite ADD FooterBottomRadius  INT            NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'CopyrightBarBgColor') IS NULL ALTER TABLE BusinessWebsite ADD CopyrightBarBgColor NVARCHAR(20)   NULL;
IF COL_LENGTH('BusinessWebsite', 'FooterJSON')          IS NULL ALTER TABLE BusinessWebsite ADD FooterJSON          NVARCHAR(MAX)  NULL;

-- Top bar
IF COL_LENGTH('BusinessWebsite', 'TopBarEnabled')   IS NULL ALTER TABLE BusinessWebsite ADD TopBarEnabled   BIT          NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebsite', 'TopBarHTML')       IS NULL ALTER TABLE BusinessWebsite ADD TopBarHTML      NVARCHAR(MAX) NULL;
IF COL_LENGTH('BusinessWebsite', 'TopBarBgColor')    IS NULL ALTER TABLE BusinessWebsite ADD TopBarBgColor   NVARCHAR(20)  NULL DEFAULT '#f8f5ef';
IF COL_LENGTH('BusinessWebsite', 'TopBarTextColor')  IS NULL ALTER TABLE BusinessWebsite ADD TopBarTextColor NVARCHAR(20)  NULL DEFAULT '#333333';
IF COL_LENGTH('BusinessWebsite', 'TopBarAlign')      IS NULL ALTER TABLE BusinessWebsite ADD TopBarAlign     NVARCHAR(10)  NULL DEFAULT 'right';

-- Header / nav
IF COL_LENGTH('BusinessWebsite', 'HeaderBannerURL')     IS NULL ALTER TABLE BusinessWebsite ADD HeaderBannerURL     NVARCHAR(1000) NULL;
IF COL_LENGTH('BusinessWebsite', 'HeaderBannerBgColor') IS NULL ALTER TABLE BusinessWebsite ADD HeaderBannerBgColor NVARCHAR(20)   NULL;
IF COL_LENGTH('BusinessWebsite', 'HeaderHeight')        IS NULL ALTER TABLE BusinessWebsite ADD HeaderHeight        INT            NULL DEFAULT 120;
IF COL_LENGTH('BusinessWebsite', 'ShowSiteName')        IS NULL ALTER TABLE BusinessWebsite ADD ShowSiteName        BIT            NULL DEFAULT 1;
IF COL_LENGTH('BusinessWebsite', 'HeaderLayout')        IS NULL ALTER TABLE BusinessWebsite ADD HeaderLayout        NVARCHAR(20)   NULL DEFAULT 'banner_top';
IF COL_LENGTH('BusinessWebsite', 'NavBgImageURL')       IS NULL ALTER TABLE BusinessWebsite ADD NavBgImageURL       NVARCHAR(1000) NULL;
IF COL_LENGTH('BusinessWebsite', 'NavTextColor')        IS NULL ALTER TABLE BusinessWebsite ADD NavTextColor        NVARCHAR(20)   NULL DEFAULT '#FFFFFF';

-- Favicon
IF COL_LENGTH('BusinessWebsite', 'FaviconURL') IS NULL ALTER TABLE BusinessWebsite ADD FaviconURL NVARCHAR(1000) NULL;

-- SEO / meta
IF COL_LENGTH('BusinessWebsite', 'OgImageURL')    IS NULL ALTER TABLE BusinessWebsite ADD OgImageURL    NVARCHAR(1000) NULL;
IF COL_LENGTH('BusinessWebsite', 'SeoExtrasJSON') IS NULL ALTER TABLE BusinessWebsite ADD SeoExtrasJSON NVARCHAR(MAX)  NULL;
IF COL_LENGTH('BusinessWebsite', 'MenuStyleJSON') IS NULL ALTER TABLE BusinessWebsite ADD MenuStyleJSON NVARCHAR(MAX)  NULL;

-- BusinessWebPage columns that may be new
IF COL_LENGTH('BusinessWebPage', 'ParentPageID') IS NULL ALTER TABLE BusinessWebPage ADD ParentPageID INT          NULL;
IF COL_LENGTH('BusinessWebPage', 'IsNavHeading') IS NULL ALTER TABLE BusinessWebPage ADD IsNavHeading BIT          NULL DEFAULT 0;
IF COL_LENGTH('BusinessWebPage', 'LinkURL')      IS NULL ALTER TABLE BusinessWebPage ADD LinkURL      NVARCHAR(500) NULL;
IF COL_LENGTH('BusinessWebPage', 'UpdatedAt')    IS NULL ALTER TABLE BusinessWebPage ADD UpdatedAt    DATETIME      NULL;

PRINT 'Migration complete.';
