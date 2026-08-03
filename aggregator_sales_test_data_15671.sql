-- ============================================================
-- Aggregator Sales Test Data for BusinessID = 15671 (Food World)
-- Tables: OFNAggregatorB2BAccount, OFNAggregatorB2BOrder, OFNAggregatorD2COrder
-- Run AFTER visiting the aggregator page once (to trigger ensure_tables)
-- ============================================================
SET NOCOUNT ON;

-- ── 1. B2B Buyer Accounts ─────────────────────────────────────────────────────
INSERT INTO OFNAggregatorB2BAccount
  (BusinessID, BuyerName, BuyerType, ContactName, ContactPhone, ContactEmail,
   DeliveryAddress, NetTermsDays, CreditLimit, Status, Notes)
VALUES
  (15671,'Green Leaf Grocery Chain','retail','Dana Kowalski','555-111-2222','dana@greenleaf.com',
   '88 Commerce Blvd, Newark, NJ 07102',30,50000.00,'active','5 locations in NJ — primary retail account'),

  (15671,'The Farm Table Restaurant Group','restaurant','Chef Marco Reyes','555-222-3333','marco@farmtable.com',
   '220 West 14th St, New York, NY 10011',14,15000.00,'active','3 Manhattan restaurants — weekly standing order'),

  (15671,'Metro Organic Distributors','distributor','Lisa Park','555-333-4444','lisa@metrorganic.com',
   '400 Industrial Way, Secaucus, NJ 07094',45,75000.00,'active','Re-distributor — serves 40+ stores in tri-state'),

  (15671,'NJ Public Schools Food Services','institution','Brad Thompson','555-444-5555','brad.thompson@njpsfood.gov',
   '1 Government Plaza, Trenton, NJ 08608',60,100000.00,'active','Institutional bulk buyer — seasonal contracts'),

  (15671,'Sunrise Natural Market','retail','Priya Nair','555-555-6666','priya@sunrisenatural.com',
   '72 Main Street, Montclair, NJ 07042',30,20000.00,'active','Independent health food store'),

  (15671,'Harbor View Hotel & Spa','restaurant','Kevin Walsh','555-666-7777','kevin@harborview.com',
   '1 Harbor Dr, Jersey City, NJ 07302',21,10000.00,'on_hold','Seasonal contract — paused for renovation'),

  (15671,'Brooklyn Bite Meal Kits','distributor','Asha Mehta','555-777-8888','asha@brooklynbite.com',
   '500 Atlantic Ave, Brooklyn, NY 11217',30,30000.00,'active','Meal kit company — 3-day lead time required');

-- ── 2. B2B Orders ─────────────────────────────────────────────────────────────
INSERT INTO OFNAggregatorB2BOrder
  (BusinessID, AccountID, OrderDate, CropType, QuantityKg, PricePerKg, TotalValue,
   DeliveryDate, Status, InvoiceNumber, PaymentStatus, Notes)
VALUES
  -- Green Leaf Grocery Chain
  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Green Leaf Grocery Chain'),
   '2026-05-01','Organic Strawberries',220,4.85,1067.00,'2026-05-03','delivered','INV-2026-0501','paid','Week 18 standing order'),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Green Leaf Grocery Chain'),
   '2026-05-08','Organic Strawberries',240,4.85,1164.00,'2026-05-10','delivered','INV-2026-0502','paid','Week 19 standing order'),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Green Leaf Grocery Chain'),
   '2026-05-15','Organic Strawberries',250,4.90,1225.00,'2026-05-17','dispatched','INV-2026-0503','unpaid','Week 20'),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Green Leaf Grocery Chain'),
   '2026-05-15','Organic Romaine Lettuce',80,3.20,256.00,'2026-05-17','dispatched','INV-2026-0504','unpaid',''),

  -- The Farm Table Restaurant Group
  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='The Farm Table Restaurant Group'),
   '2026-05-05','Organic Strawberries',45,5.50,247.50,'2026-05-06','delivered','INV-2026-0505','paid','Chef standing order'),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='The Farm Table Restaurant Group'),
   '2026-05-05','Organic Romaine Lettuce',30,3.80,114.00,'2026-05-06','delivered','INV-2026-0506','paid',''),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='The Farm Table Restaurant Group'),
   '2026-05-12','Organic Strawberries',50,5.50,275.00,'2026-05-13','delivered','INV-2026-0507','partial','50% deposit received'),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='The Farm Table Restaurant Group'),
   '2026-05-19','Organic Strawberries',50,5.50,275.00,'2026-05-20','placed','INV-2026-0508','unpaid',''),

  -- Metro Organic Distributors
  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Metro Organic Distributors'),
   '2026-04-28','Organic Strawberries',500,4.60,2300.00,'2026-05-01','delivered','INV-2026-0409','paid','Large bulk order'),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Metro Organic Distributors'),
   '2026-05-06','Organic Whole Wheat Flour',800,1.40,1120.00,'2026-05-09','delivered','INV-2026-0510','paid',''),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Metro Organic Distributors'),
   '2026-05-14','Organic Strawberries',480,4.65,2232.00,'2026-05-17','dispatched','INV-2026-0511','unpaid','Net 45'),

  -- NJ Public Schools Food Services
  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='NJ Public Schools Food Services'),
   '2026-05-02','Free-Range Eggs Grade A',200,7.80,1560.00,'2026-05-05','delivered','INV-2026-0512','paid','Monthly bulk'),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='NJ Public Schools Food Services'),
   '2026-05-02','Organic Whole Wheat Flour',1200,1.35,1620.00,'2026-05-05','delivered','INV-2026-0513','paid',''),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='NJ Public Schools Food Services'),
   '2026-06-01','Free-Range Eggs Grade A',200,7.80,1560.00,'2026-06-03','placed',NULL,'unpaid','June order — not yet invoiced'),

  -- Sunrise Natural Market
  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Sunrise Natural Market'),
   '2026-05-10','Organic Strawberries',60,5.20,312.00,'2026-05-12','delivered','INV-2026-0514','paid',''),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Sunrise Natural Market'),
   '2026-05-17','Organic Strawberries',65,5.20,338.00,'2026-05-19','picking',NULL,'unpaid','Picking in progress'),

  -- Brooklyn Bite Meal Kits
  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Brooklyn Bite Meal Kits'),
   '2026-05-13','Organic Strawberries',120,5.00,600.00,'2026-05-16','delivered','INV-2026-0515','paid',''),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Brooklyn Bite Meal Kits'),
   '2026-05-13','Organic Romaine Lettuce',90,3.60,324.00,'2026-05-16','delivered','INV-2026-0516','paid',''),

  (15671,(SELECT AccountID FROM OFNAggregatorB2BAccount WHERE BusinessID=15671 AND BuyerName='Brooklyn Bite Meal Kits'),
   '2026-05-20','Organic Strawberries',130,5.00,650.00,'2026-05-23','placed',NULL,'unpaid','');

-- ── 3. D2C Orders ─────────────────────────────────────────────────────────────
INSERT INTO OFNAggregatorD2COrder
  (BusinessID, Channel, ExternalOrderID, CustomerName, CustomerPhone, DeliveryAddress,
   CropType, QuantityKg, TotalValue, OrderDate, DeliverySLAMinutes, Status)
VALUES
  -- own_app orders
  (15671,'own_app','APP-10041','Rachel Green','555-010-0001','12 Elm St, Hoboken, NJ 07030',
   'Organic Strawberries',1.5,12.50,'2026-05-19 08:15',60,'delivered'),
  (15671,'own_app','APP-10042','Tom Hanks','555-010-0002','88 Park Ave, Hoboken, NJ 07030',
   'Organic Romaine Lettuce',1.0,8.00,'2026-05-19 09:30',60,'delivered'),
  (15671,'own_app','APP-10043','Sarah Connor','555-010-0003','45 River Rd, Hoboken, NJ 07030',
   'Free-Range Eggs Grade A',2.0,15.60,'2026-05-19 10:00',60,'out_for_delivery'),
  (15671,'own_app','APP-10044','Mike Tyson','555-010-0004','7 Garden St, Jersey City, NJ 07302',
   'Organic Strawberries',2.0,16.50,'2026-05-19 11:15',60,'placed'),

  -- zepto
  (15671,'zepto','ZPT-88120','Priya Sharma','555-020-0001','301 Washington St, Jersey City, NJ',
   'Organic Strawberries',0.5,5.25,'2026-05-19 07:45',10,'delivered'),
  (15671,'zepto','ZPT-88321','Raj Patel','555-020-0002','18 Newark Ave, Jersey City, NJ',
   'Organic Strawberries',0.5,5.25,'2026-05-19 09:20',10,'delivered'),
  (15671,'zepto','ZPT-88504','Meena Das','555-020-0003','92 Grove St, Jersey City, NJ',
   'Free-Range Eggs Grade A',1.0,8.20,'2026-05-19 12:10',10,'out_for_delivery'),

  -- swiggy
  (15671,'swiggy','SWG-44891','Carlos Rivera','555-030-0001','55 Hudson St, Hoboken, NJ',
   'Organic Strawberries',1.0,10.50,'2026-05-18 18:30',45,'delivered'),
  (15671,'swiggy','SWG-44902','Diana Prince','555-030-0002','120 Bloomfield Ave, Montclair, NJ',
   'Organic Romaine Lettuce',1.5,11.50,'2026-05-18 19:00',45,'delivered'),
  (15671,'swiggy','SWG-45110','Bruce Wayne','555-030-0003','1 Clifton Ave, Newark, NJ',
   'Organic Strawberries',2.0,21.00,'2026-05-19 13:00',45,'placed'),

  -- blinkit
  (15671,'blinkit','BLK-22041','Linda Park','555-040-0001','200 Valley Rd, Montclair, NJ',
   'Free-Range Eggs Grade A',2.0,16.50,'2026-05-19 08:05',15,'delivered'),
  (15671,'blinkit','BLK-22199','James Brown','555-040-0002','44 Broad St, Newark, NJ',
   'Organic Strawberries',1.0,10.50,'2026-05-19 10:40',15,'out_for_delivery'),

  -- amazon
  (15671,'amazon','AMZ-1192844','Peter Parker','555-050-0001','175 5th Ave, New York, NY 10010',
   'Organic Whole Wheat Flour',2.0,6.80,'2026-05-17 14:22',NULL,'delivered'),
  (15671,'amazon','AMZ-1193201','Mary Jane','555-050-0002','250 W 55th St, New York, NY 10019',
   'Organic Strawberries',1.0,10.99,'2026-05-18 09:15',NULL,'delivered'),
  (15671,'amazon','AMZ-1194502','Tony Stark','555-050-0003','890 5th Ave, New York, NY 10021',
   'Free-Range Eggs Grade A',3.0,24.99,'2026-05-19 07:00',NULL,'placed'),

  -- other (refunded example)
  (15671,'other','OTH-5512','Clark Kent','555-060-0001','344 Clinton St, Metropolis, NJ',
   'Organic Strawberries',1.0,10.50,'2026-05-16 11:00',NULL,'refunded');

PRINT 'Aggregator Sales test data inserted for BusinessID 15671.';
