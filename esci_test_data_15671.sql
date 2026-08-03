-- ============================================================
-- ESCI Test Data for BusinessID = 15671 (Food World / Food Aggregator)
-- Run against Oatmealailivedb
-- ============================================================
SET NOCOUNT ON;

-- ── 1. Settings ───────────────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM ESCI_Settings WHERE BusinessID = 15671)
  INSERT INTO ESCI_Settings
    (BusinessID, DefaultCurrency, ShipmentAlertLeadDays, QualityPassGrade,
     LowMarginThresholdPct, ExceptionEmailEnabled, ExceptionEmailTo)
  VALUES (15671, 'USD', 3, 'B', 12.0, 1, 'ops@foodworld.com');

-- ── 2. Suppliers ──────────────────────────────────────────────────────────────
INSERT INTO ESCI_SupplierProfile
  (BusinessID, SupplierName, ContactName, ContactEmail, ContactPhone,
   Country, Region, SupplierType, CertifiedOrganic, CertifiedGAP, GlobalGAP, Notes)
VALUES
  (15671,'Green Valley Farms',  'Maria Lopez',   'maria@greenvalley.com', '555-101-2020','USA','California','produce',1,1,0,'Primary organic produce supplier — 5-yr relationship'),
  (15671,'Sunrise Dairy Co',    'Tom Hendricks', 'tom@sunrisedairy.com',  '555-202-3030','USA','Vermont',   'dairy',  1,0,0,'Certified organic, pasture-raised'),
  (15671,'Blue Ridge Meats',    'Sarah Connors', 'sarah@blueridge.com',   '555-303-4040','USA','Virginia',  'meat',   0,1,0,'Grass-fed beef and pork'),
  (15671,'Coastal Seafood Co',  'James Wu',      'james@coastal.com',     '555-404-5050','USA','Maine',     'seafood',0,0,0,'Wild-caught Atlantic fish and shellfish'),
  (15671,'Heritage Grain Mill', 'Anna Schmidt',  'anna@heritagegrain.com','555-505-6060','USA','Kansas',    'grain',  0,1,0,'Heirloom and specialty grain varieties'),
  (15671,'Valley Fresh Eggs',   'Bob Martinez',  'bob@valleyeggs.com',    '555-606-7070','USA','Ohio',      'produce',0,1,0,'Free-range eggs, multiple grades');

-- ── 3. Contracts ──────────────────────────────────────────────────────────────
INSERT INTO ESCI_Contract
  (BusinessID, SupplierID, ProductName, ProductCategory, SKU,
   SeasonStart, SeasonEnd, CommittedVolume, Unit,
   PriceFloor, PriceCeiling, AgreePrice, Currency, Status)
VALUES
  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Green Valley Farms'),
   'Organic Strawberries','Produce','PRD-STW-001','2026-04-01','2026-07-31',5000,'lbs',1.80,2.60,2.20,'USD','active'),

  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Green Valley Farms'),
   'Organic Romaine Lettuce','Produce','PRD-ROM-002','2026-03-01','2026-10-31',3000,'cases',12.00,18.00,14.50,'USD','active'),

  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Sunrise Dairy Co'),
   'Organic Whole Milk','Dairy','DAI-MLK-001','2026-01-01','2026-12-31',10000,'gallons',4.50,6.00,5.25,'USD','active'),

  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Blue Ridge Meats'),
   'Grass-Fed Ground Beef','Meat','MEA-GRB-001','2026-01-01','2026-12-31',8000,'lbs',5.00,7.50,6.25,'USD','active'),

  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Coastal Seafood Co'),
   'Wild Atlantic Salmon','Seafood','SEA-SAL-001','2026-04-01','2026-09-30',2000,'lbs',8.00,12.00,10.00,'USD','active'),

  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Heritage Grain Mill'),
   'Whole Wheat Flour','Grain','GRN-WWF-001','2026-01-01','2026-12-31',20000,'lbs',0.45,0.75,0.60,'USD','active'),

  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Valley Fresh Eggs'),
   'Free-Range Eggs Grade A','Produce','EGG-GRA-001','2026-01-01','2026-12-31',50000,'dozen',2.80,4.00,3.40,'USD','active');

-- ── 4. Shipments ──────────────────────────────────────────────────────────────
-- Received (past)
INSERT INTO ESCI_Shipment
  (BusinessID,SupplierID,ContractID,ShipmentRef,ProductName,ProductCategory,
   OrderedQty,ReceivedQty,Unit,Status,ExpectedDate,ReceivedDate,
   OriginLocation,DestLocation,CarrierName,TrackingNum,UnitCost,TotalCost)
VALUES
  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Green Valley Farms'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='PRD-STW-001'),
   'SHP-2026-001','Organic Strawberries','Produce',500,488,'lbs','received',
   '2026-05-01','2026-05-01','Watsonville, CA','Food World DC, NJ','FreshExpress','FE20260501A',2.20,1073.60),

  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Sunrise Dairy Co'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='DAI-MLK-001'),
   'SHP-2026-002','Organic Whole Milk','Dairy',800,800,'gallons','received',
   '2026-05-03','2026-05-03','Burlington, VT','Food World DC, NJ','DairyCold LLC','DC20260503B',5.25,4200.00),

  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Blue Ridge Meats'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='MEA-GRB-001'),
   'SHP-2026-003','Grass-Fed Ground Beef','Meat',600,595,'lbs','received',
   '2026-05-05','2026-05-06','Charlottesville, VA','Food World DC, NJ','ColdFreight Inc','CF20260506C',6.25,3718.75),

  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Heritage Grain Mill'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='GRN-WWF-001'),
   'SHP-2026-004','Whole Wheat Flour','Grain',2000,2000,'lbs','received',
   '2026-05-08','2026-05-08','Wichita, KS','Food World DC, NJ','GrainHaul Co','GH20260508D',0.60,1200.00),

  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Valley Fresh Eggs'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='EGG-GRA-001'),
   'SHP-2026-005','Free-Range Eggs Grade A','Produce',300,296,'dozen','received',
   '2026-05-10','2026-05-10','Columbus, OH','Food World DC, NJ','FarmFreight LLC','FF20260510E',3.40,1006.40),

  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Coastal Seafood Co'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='SEA-SAL-001'),
   'SHP-2026-006','Wild Atlantic Salmon','Seafood',180,175,'lbs','received',
   '2026-05-12','2026-05-13','Portland, ME','Food World DC, NJ','SeaFreight LLC','SF20260513F',10.00,1750.00),

-- In Transit
  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Green Valley Farms'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='PRD-ROM-002'),
   'SHP-2026-007','Organic Romaine Lettuce','Produce',150,NULL,'cases','in_transit',
   '2026-05-21',NULL,'Salinas, CA','Food World DC, NJ','FreshExpress','FE20260520G',14.50,2175.00),

  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Sunrise Dairy Co'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='DAI-MLK-001'),
   'SHP-2026-008','Organic Whole Milk','Dairy',800,NULL,'gallons','in_transit',
   '2026-05-22',NULL,'Burlington, VT','Food World DC, NJ','DairyCold LLC','DC20260521H',5.25,4200.00),

-- Delayed
  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Blue Ridge Meats'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='MEA-GRB-001'),
   'SHP-2026-009','Grass-Fed Ground Beef','Meat',400,NULL,'lbs','delayed',
   '2026-05-17',NULL,'Charlottesville, VA','Food World DC, NJ','ColdFreight Inc','CF20260517I',6.25,2500.00),

-- Pending (upcoming)
  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Green Valley Farms'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='PRD-STW-001'),
   'SHP-2026-010','Organic Strawberries','Produce',600,NULL,'lbs','pending',
   '2026-05-28',NULL,'Watsonville, CA','Food World DC, NJ','FreshExpress',NULL,2.20,1320.00),

  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Heritage Grain Mill'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='GRN-WWF-001'),
   'SHP-2026-011','Whole Wheat Flour','Grain',3000,NULL,'lbs','pending',
   '2026-06-02',NULL,'Wichita, KS','Food World DC, NJ','GrainHaul Co',NULL,0.60,1800.00),

  (15671,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Coastal Seafood Co'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='SEA-SAL-001'),
   'SHP-2026-012','Wild Atlantic Salmon','Seafood',200,NULL,'lbs','pending',
   '2026-06-05',NULL,'Portland, ME','Food World DC, NJ','SeaFreight LLC',NULL,10.00,2000.00);

-- ── 5. Shipment Events ────────────────────────────────────────────────────────
INSERT INTO ESCI_ShipmentEvent (ShipmentID,BusinessID,EventType,OccurredAt,Location,TempC,Notes,RecordedBy)
VALUES
  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-001'),
   15671,'dispatched','2026-04-29 07:00','Watsonville, CA',4.0,'Loaded and sealed — reefer at 4°C','Green Valley Farms'),
  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-001'),
   15671,'checkpoint','2026-04-30 14:30','Barstow, CA',4.2,'Mid-route check — temp stable','FreshExpress Driver'),
  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-001'),
   15671,'delivered','2026-05-01 08:15','Food World DC, NJ',4.5,'Received — minor short 12 lbs noted','Receiving Dock'),

  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-003'),
   15671,'dispatched','2026-05-04 06:00','Charlottesville, VA',2.0,'Left facility on schedule','Blue Ridge Meats'),
  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-003'),
   15671,'delivered','2026-05-06 10:00','Food World DC, NJ',2.5,'Arrived 1 day late — carrier delay','Receiving Dock'),

  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-007'),
   15671,'dispatched','2026-05-19 05:30','Salinas, CA',3.0,'Departed on schedule','Green Valley Farms'),
  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-007'),
   15671,'checkpoint','2026-05-20 11:00','Flagstaff, AZ',3.5,'Temperature holding','FreshExpress Dispatch'),

  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-009'),
   15671,'dispatched','2026-05-15 07:00','Charlottesville, VA',2.0,'Departed — expected 2-day transit','Blue Ridge Meats'),
  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-009'),
   15671,'delay_reported','2026-05-17 14:00','Baltimore, MD',2.0,'Truck breakdown — awaiting replacement','ColdFreight Inc');

-- ── 6. Quality Tests ──────────────────────────────────────────────────────────
INSERT INTO ESCI_QualityTest
  (ShipmentID,BusinessID,TestedAt,Tester,Grade,PassFail,DefectPct,BrixLevel,MoisturePct,PesticideResult,MicrobialResult,Notes)
VALUES
  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-001'),
   15671,'2026-05-01 09:00','QC Team A','A','pass',2.4,9.8,88.0,'clear','clear','Slight short on qty; quality excellent'),

  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-002'),
   15671,'2026-05-03 10:30','QC Team B','A','pass',0.0,NULL,NULL,'clear','clear','Full delivery, all seals intact'),

  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-003'),
   15671,'2026-05-06 11:00','QC Team A','B','pass',1.7,NULL,68.0,'clear','clear','5 lbs trim loss; otherwise acceptable'),

  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-004'),
   15671,'2026-05-08 14:00','QC Team C','A','pass',0.5,NULL,12.5,'clear','clear','Excellent quality, full weight'),

  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-005'),
   15671,'2026-05-10 09:30','QC Team B','B','pass',1.3,NULL,73.0,'clear','clear','4 cartons with minor shell damage — accepted'),

  ((SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-006'),
   15671,'2026-05-13 08:00','QC Team A','C','fail',12.0,NULL,NULL,'clear','detected','HIGH FAIL: 12% defect, microbial detection — rejected');

-- ── 7. Exceptions ─────────────────────────────────────────────────────────────
INSERT INTO ESCI_Exception
  (BusinessID,ShipmentID,SupplierID,ExceptionType,Severity,Status,Title,Detail,DetectedAt,AssignedTo)
VALUES
  (15671,
   (SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-009'),
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Blue Ridge Meats'),
   'delay','critical','open',
   'Ground beef shipment SHP-2026-009 now 2 days late',
   'Truck breakdown in Baltimore. Replacement truck dispatched but ETA unknown. Cold chain integrity at risk — product has been in transit 4+ days.',
   '2026-05-17 15:00','Sarah Connors'),

  (15671,
   (SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-006'),
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Coastal Seafood Co'),
   'quality_failure','critical','open',
   'Salmon SHP-2026-006 failed QC — microbial detection',
   'QC test detected microbial contamination. Entire lot of 175 lbs quarantined. Replacement order needed immediately. Supplier notified.',
   '2026-05-13 08:30','James Wu'),

  (15671,
   NULL,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Green Valley Farms'),
   'short_shipment','medium','open',
   'Strawberry delivery SHP-2026-001 short 12 lbs',
   'Received 488 lbs against 500 lbs ordered. Supplier to issue credit or top-up on next delivery.',
   '2026-05-01 09:30','Maria Lopez'),

  (15671,
   NULL,
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Coastal Seafood Co'),
   'price_variance','medium','resolved',
   'Salmon invoice price above contract ceiling',
   'Invoice at $11.50/lb exceeded contract ceiling of $12.00. Allowed but flagged — market price spike due to harvest disruption.',
   '2026-05-13 12:00','James Wu'),

  (15671,
   (SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-003'),
   (SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Blue Ridge Meats'),
   'delay','low','resolved',
   'Ground beef SHP-2026-003 arrived 1 day late',
   'Carrier delay — truck mechanical issue. Product integrity maintained. No financial impact.',
   '2026-05-06 06:00',NULL);

-- ── 8. Exception Notes ────────────────────────────────────────────────────────
INSERT INTO ESCI_ExceptionNote (ExceptionID,BusinessID,AuthorName,NoteText,CreatedAt)
VALUES
  ((SELECT ExceptionID FROM ESCI_Exception WHERE BusinessID=15671 AND Title LIKE 'Ground beef shipment SHP-2026-009%'),
   15671,'ops@foodworld.com','Contacted ColdFreight dispatcher. Replacement truck en route, ETA +6 hrs. Monitoring temp probe data remotely.','2026-05-17 16:30'),

  ((SELECT ExceptionID FROM ESCI_Exception WHERE BusinessID=15671 AND Title LIKE 'Ground beef shipment SHP-2026-009%'),
   15671,'ops@foodworld.com','New truck confirmed. Product still at 2°C per probe. Will accept if delivered by tomorrow 08:00.','2026-05-18 09:00'),

  ((SELECT ExceptionID FROM ESCI_Exception WHERE BusinessID=15671 AND Title LIKE 'Salmon SHP-2026-006%'),
   15671,'ops@foodworld.com','Quarantine confirmed. Health dept notified per SOP. Coastal Seafood sending replacement order — ETA June 5.','2026-05-13 10:00'),

  ((SELECT ExceptionID FROM ESCI_Exception WHERE BusinessID=15671 AND Title LIKE 'Salmon SHP-2026-006%'),
   15671,'james@coastal.com','We are covering replacement at no charge. Root cause under investigation — likely icing failure at Portland dock.','2026-05-14 08:00');

-- ── 9. Yield Forecasts ────────────────────────────────────────────────────────
INSERT INTO ESCI_YieldForecast
  (BusinessID,SupplierID,ProductName,Season,HarvestStart,HarvestEnd,ForecastQty,Unit,ConfidencePct,ActualQty,Notes)
VALUES
  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Green Valley Farms'),
   'Organic Strawberries','Spring 2026','2026-04-01','2026-07-15',5200,'lbs',82,2950,'On track — warm April boosted early yield'),

  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Green Valley Farms'),
   'Organic Romaine Lettuce','Spring 2026','2026-03-15','2026-06-30',3400,'cases',75,1800,'Slightly behind — heat stress in May'),

  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Blue Ridge Meats'),
   'Grass-Fed Ground Beef','Q2 2026','2026-04-01','2026-06-30',4200,'lbs',88,2400,'On track'),

  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Heritage Grain Mill'),
   'Whole Wheat Flour','Summer 2026','2026-06-01','2026-08-31',22000,'lbs',70,NULL,'Forecast only — harvest not started'),

  (15671,(SELECT SupplierID FROM ESCI_SupplierProfile WHERE BusinessID=15671 AND SupplierName='Coastal Seafood Co'),
   'Wild Atlantic Salmon','Spring Run 2026','2026-04-15','2026-06-30',2200,'lbs',65,1150,'Below forecast — run weaker than expected');

-- ── 10. Demand Forecasts ──────────────────────────────────────────────────────
INSERT INTO ESCI_DemandForecast
  (BusinessID,ProductName,ProductCategory,CustomerSegment,PeriodType,PeriodStart,PeriodEnd,ForecastQty,Unit,ActualQty,ConfidencePct,Notes)
VALUES
  -- Past weeks (with actuals)
  (15671,'Organic Strawberries','Produce','Retail','weekly','2026-04-21','2026-04-27',480,'lbs',502,88,''),
  (15671,'Organic Strawberries','Produce','Retail','weekly','2026-04-28','2026-05-04',500,'lbs',488,88,''),
  (15671,'Organic Strawberries','Produce','Retail','weekly','2026-05-05','2026-05-11',520,'lbs',531,88,''),
  (15671,'Organic Strawberries','Produce','Retail','weekly','2026-05-12','2026-05-18',540,'lbs',558,85,''),

  (15671,'Organic Whole Milk','Dairy','Foodservice','weekly','2026-04-28','2026-05-04',780,'gallons',800,90,''),
  (15671,'Organic Whole Milk','Dairy','Foodservice','weekly','2026-05-05','2026-05-11',800,'gallons',815,90,''),
  (15671,'Organic Whole Milk','Dairy','Foodservice','weekly','2026-05-12','2026-05-18',820,'gallons',798,90,''),

  (15671,'Grass-Fed Ground Beef','Meat','Retail','weekly','2026-05-05','2026-05-11',580,'lbs',595,85,''),
  (15671,'Grass-Fed Ground Beef','Meat','Retail','weekly','2026-05-12','2026-05-18',600,'lbs',NULL,85,'In transit — delayed'),

  -- Future weeks (no actuals)
  (15671,'Organic Strawberries','Produce','Retail','weekly','2026-05-19','2026-05-25',560,'lbs',NULL,83,'Peak berry season'),
  (15671,'Organic Strawberries','Produce','Retail','weekly','2026-05-26','2026-06-01',580,'lbs',NULL,80,''),
  (15671,'Organic Romaine Lettuce','Produce','Foodservice','weekly','2026-05-19','2026-05-25',140,'cases',NULL,72,''),
  (15671,'Organic Romaine Lettuce','Produce','Foodservice','weekly','2026-05-26','2026-06-01',145,'cases',NULL,72,''),
  (15671,'Wild Atlantic Salmon','Seafood','Foodservice','weekly','2026-06-02','2026-06-08',190,'lbs',NULL,68,'Replacement order arriving June 5'),
  (15671,'Grass-Fed Ground Beef','Meat','Retail','weekly','2026-05-19','2026-05-25',610,'lbs',NULL,82,''),
  (15671,'Whole Wheat Flour','Grain','Wholesale','weekly','2026-06-02','2026-06-08',2800,'lbs',NULL,88,''),
  (15671,'Free-Range Eggs Grade A','Produce','Retail','weekly','2026-05-19','2026-05-25',290,'dozen',NULL,91,'');

-- ── 11. Margin Records ────────────────────────────────────────────────────────
INSERT INTO ESCI_MarginRecord
  (BusinessID,ShipmentID,ContractID,ProductName,ProductCategory,
   PeriodStart,PeriodEnd,Qty,Unit,LandedCostUnit,SalePriceUnit,Currency,Notes)
VALUES
  -- November
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='PRD-STW-001'),
   'Organic Strawberries','Produce','2025-11-01','2025-11-30',420,'lbs',2.20,3.20,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='DAI-MLK-001'),
   'Organic Whole Milk','Dairy','2025-11-01','2025-11-30',750,'gallons',5.25,7.80,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='MEA-GRB-001'),
   'Grass-Fed Ground Beef','Meat','2025-11-01','2025-11-30',550,'lbs',6.25,9.50,'USD',''),

  -- December
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='PRD-STW-001'),
   'Organic Strawberries','Produce','2025-12-01','2025-12-31',380,'lbs',2.40,3.60,'USD','Holiday pricing'),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='DAI-MLK-001'),
   'Organic Whole Milk','Dairy','2025-12-01','2025-12-31',800,'gallons',5.40,8.10,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='MEA-GRB-001'),
   'Grass-Fed Ground Beef','Meat','2025-12-01','2025-12-31',600,'lbs',6.50,10.20,'USD','Strong holiday demand'),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='SEA-SAL-001'),
   'Wild Atlantic Salmon','Seafood','2025-12-01','2025-12-31',160,'lbs',10.00,16.50,'USD','Holiday premium'),

  -- January
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='DAI-MLK-001'),
   'Organic Whole Milk','Dairy','2026-01-01','2026-01-31',760,'gallons',5.25,7.50,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='MEA-GRB-001'),
   'Grass-Fed Ground Beef','Meat','2026-01-01','2026-01-31',520,'lbs',6.25,8.80,'USD','Jan slowdown'),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='GRN-WWF-001'),
   'Whole Wheat Flour','Grain','2026-01-01','2026-01-31',1800,'lbs',0.60,0.92,'USD',''),

  -- February
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='DAI-MLK-001'),
   'Organic Whole Milk','Dairy','2026-02-01','2026-02-28',740,'gallons',5.25,7.40,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='MEA-GRB-001'),
   'Grass-Fed Ground Beef','Meat','2026-02-01','2026-02-28',540,'lbs',6.25,9.00,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='GRN-WWF-001'),
   'Whole Wheat Flour','Grain','2026-02-01','2026-02-28',2000,'lbs',0.60,0.94,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='EGG-GRA-001'),
   'Free-Range Eggs Grade A','Produce','2026-02-01','2026-02-28',280,'dozen',3.40,5.20,'USD',''),

  -- March
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='DAI-MLK-001'),
   'Organic Whole Milk','Dairy','2026-03-01','2026-03-31',780,'gallons',5.25,7.60,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='MEA-GRB-001'),
   'Grass-Fed Ground Beef','Meat','2026-03-01','2026-03-31',560,'lbs',6.25,9.20,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='PRD-ROM-002'),
   'Organic Romaine Lettuce','Produce','2026-03-01','2026-03-31',120,'cases',14.50,22.00,'USD','Spring kickoff'),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='EGG-GRA-001'),
   'Free-Range Eggs Grade A','Produce','2026-03-01','2026-03-31',295,'dozen',3.40,5.10,'USD',''),

  -- April
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='PRD-STW-001'),
   'Organic Strawberries','Produce','2026-04-01','2026-04-30',490,'lbs',2.20,3.40,'USD','Season opening'),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='DAI-MLK-001'),
   'Organic Whole Milk','Dairy','2026-04-01','2026-04-30',800,'gallons',5.25,7.80,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='MEA-GRB-001'),
   'Grass-Fed Ground Beef','Meat','2026-04-01','2026-04-30',580,'lbs',6.25,9.50,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='SEA-SAL-001'),
   'Wild Atlantic Salmon','Seafood','2026-04-01','2026-04-30',175,'lbs',10.00,15.80,'USD',''),
  (15671,NULL,(SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='EGG-GRA-001'),
   'Free-Range Eggs Grade A','Produce','2026-04-01','2026-04-30',300,'dozen',3.40,5.20,'USD',''),

  -- May (partial — through shipments received)
  (15671,
   (SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-001'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='PRD-STW-001'),
   'Organic Strawberries','Produce','2026-05-01','2026-05-31',488,'lbs',2.20,3.50,'USD',''),
  (15671,
   (SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-002'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='DAI-MLK-001'),
   'Organic Whole Milk','Dairy','2026-05-01','2026-05-31',800,'gallons',5.25,7.90,'USD',''),
  (15671,
   (SELECT ShipmentID FROM ESCI_Shipment WHERE BusinessID=15671 AND ShipmentRef='SHP-2026-003'),
   (SELECT ContractID FROM ESCI_Contract WHERE BusinessID=15671 AND SKU='MEA-GRB-001'),
   'Grass-Fed Ground Beef','Meat','2026-05-01','2026-05-31',595,'lbs',6.50,9.60,'USD','Slight cost increase — carrier surcharge');

-- ── 12. Market Prices (benchmark) ────────────────────────────────────────────
INSERT INTO ESCI_MarketPrice
  (BusinessID,Commodity,PriceDate,PricePerUnit,Unit,Market,Source,Notes)
VALUES
  (15671,'Organic Strawberries','2026-05-01',2.45,'lbs','Northeast Wholesale','USDA AMS','Mid-season benchmark'),
  (15671,'Organic Strawberries','2026-05-08',2.55,'lbs','Northeast Wholesale','USDA AMS',''),
  (15671,'Organic Strawberries','2026-05-15',2.60,'lbs','Northeast Wholesale','USDA AMS','Peak season pricing'),
  (15671,'Organic Whole Milk',  '2026-05-01',5.60,'gallons','Northeast','USDA NASS',''),
  (15671,'Organic Whole Milk',  '2026-05-08',5.65,'gallons','Northeast','USDA NASS',''),
  (15671,'Grass-Fed Ground Beef','2026-05-01',7.20,'lbs','USDA National','USDA AMS',''),
  (15671,'Grass-Fed Ground Beef','2026-05-08',7.35,'lbs','USDA National','USDA AMS',''),
  (15671,'Wild Atlantic Salmon', '2026-05-01',11.80,'lbs','Boston Fish Pier','USDA AMS','Harvest pressure'),
  (15671,'Wild Atlantic Salmon', '2026-05-08',12.10,'lbs','Boston Fish Pier','USDA AMS',''),
  (15671,'Whole Wheat Flour',    '2026-05-01',0.68,'lbs','Chicago Board of Trade','CME',''),
  (15671,'Free-Range Eggs Grade A','2026-05-01',3.90,'dozen','Northeast','USDA AMS',''),
  (15671,'Free-Range Eggs Grade A','2026-05-08',3.85,'dozen','Northeast','USDA AMS','');

-- ── 13. Escalation Rules ─────────────────────────────────────────────────────
INSERT INTO ESCI_EscalationRule (BusinessID,Severity,HoursUntilEscalate,EscalateTo,IsActive)
VALUES
  (15671,'critical',4, 'ops@foodworld.com',1),
  (15671,'high',    12,'ops@foodworld.com',1),
  (15671,'medium',  48,'manager@foodworld.com',1);

PRINT 'ESCI test data inserted successfully for BusinessID 15671.';
