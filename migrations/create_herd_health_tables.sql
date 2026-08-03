-- Herd Health Tables Migration
-- Run once per database instance

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthEvent')
CREATE TABLE HerdHealthEvent (
    EventID       INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID    INT NOT NULL,
    AnimalID      INT NULL,
    AnimalTag     NVARCHAR(50) NULL,
    EventDate     DATE NOT NULL,
    EventType     NVARCHAR(50) NULL,   -- Illness, Injury, Observation, Reproductive, Other
    Severity      NVARCHAR(20) NULL,   -- Critical, High, Medium, Low
    Title         NVARCHAR(200) NULL,
    Description   NVARCHAR(MAX) NULL,
    Treatment     NVARCHAR(MAX) NULL,
    ResolvedDate  DATE NULL,
    ResolvedNotes NVARCHAR(MAX) NULL,
    RecordedBy    NVARCHAR(100) NULL,
    CreatedAt     DATETIME DEFAULT GETUTCDATE(),
    UpdatedAt     DATETIME DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthVaccination')
CREATE TABLE HerdHealthVaccination (
    VaccinationID       INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID          INT NOT NULL,
    AnimalID            INT NULL,
    AnimalTag           NVARCHAR(50) NULL,
    GroupName           NVARCHAR(100) NULL,
    VaccineName         NVARCHAR(100) NULL,
    VaccineManufacturer NVARCHAR(100) NULL,
    VaccineType         NVARCHAR(100) NULL,   -- MLV, Killed, Toxoid, Recombinant
    AdministeredDate    DATE NULL,
    NextDueDate         DATE NULL,
    Dosage              NVARCHAR(50) NULL,
    Route               NVARCHAR(50) NULL,    -- IM, SQ, IN, Oral
    LotNumber           NVARCHAR(50) NULL,
    ExpirationDate      DATE NULL,
    AdministeredBy      NVARCHAR(100) NULL,
    Notes               NVARCHAR(MAX) NULL,
    CreatedAt           DATETIME DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthTreatment')
CREATE TABLE HerdHealthTreatment (
    TreatmentID      INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID       INT NOT NULL,
    AnimalID         INT NULL,
    AnimalTag        NVARCHAR(50) NULL,
    TreatmentDate    DATE NULL,
    Diagnosis        NVARCHAR(200) NULL,
    Medication       NVARCHAR(100) NULL,
    ActiveIngredient NVARCHAR(100) NULL,
    Dosage           NVARCHAR(100) NULL,
    Route            NVARCHAR(50) NULL,
    Frequency        NVARCHAR(50) NULL,
    DurationDays     INT NULL,
    WithdrawalDate   DATE NULL,
    WithdrawalMilk   DATE NULL,
    PrescribedBy     NVARCHAR(100) NULL,
    AdministeredBy   NVARCHAR(100) NULL,
    Cost             DECIMAL(10,2) NULL,
    Outcome          NVARCHAR(100) NULL,   -- Recovered, Ongoing, Died, Culled
    Notes            NVARCHAR(MAX) NULL,
    CreatedAt        DATETIME DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthVetVisit')
CREATE TABLE HerdHealthVetVisit (
    VisitID             INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID          INT NOT NULL,
    VisitDate           DATE NULL,
    VetName             NVARCHAR(100) NULL,
    ClinicName          NVARCHAR(100) NULL,
    VisitType           NVARCHAR(50) NULL,    -- Routine, Emergency, Follow-up, Consultation
    AffectedAnimals     NVARCHAR(MAX) NULL,
    ChiefComplaint      NVARCHAR(MAX) NULL,
    Findings            NVARCHAR(MAX) NULL,
    Diagnoses           NVARCHAR(MAX) NULL,
    ProceduresPerformed NVARCHAR(MAX) NULL,
    Prescriptions       NVARCHAR(MAX) NULL,
    FollowUpDate        DATE NULL,
    FollowUpNotes       NVARCHAR(MAX) NULL,
    Cost                DECIMAL(10,2) NULL,
    Notes               NVARCHAR(MAX) NULL,
    CreatedAt           DATETIME DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthMedication')
CREATE TABLE HerdHealthMedication (
    MedicationID     INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID       INT NOT NULL,
    MedicationName   NVARCHAR(100) NULL,
    ActiveIngredient NVARCHAR(100) NULL,
    Category         NVARCHAR(50) NULL,   -- Antibiotic, Vaccine, Antiparasitic, NSAID, Hormone, Supplement
    Manufacturer     NVARCHAR(100) NULL,
    LotNumber        NVARCHAR(50) NULL,
    ExpirationDate   DATE NULL,
    QuantityOnHand   DECIMAL(10,2) NULL,
    Unit             NVARCHAR(30) NULL,   -- mL, mg, tablets, vials, oz
    StorageReq       NVARCHAR(100) NULL,
    WithdrawalMeat   NVARCHAR(50) NULL,
    WithdrawalMilk   NVARCHAR(50) NULL,
    Prescription     BIT DEFAULT 0,
    ReorderPoint     DECIMAL(10,2) NULL,
    UnitCost         DECIMAL(10,2) NULL,
    Supplier         NVARCHAR(100) NULL,
    Notes            NVARCHAR(MAX) NULL,
    CreatedAt        DATETIME DEFAULT GETUTCDATE(),
    UpdatedAt        DATETIME DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthWeight')
CREATE TABLE HerdHealthWeight (
    WeightID           INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID         INT NOT NULL,
    AnimalID           INT NULL,
    AnimalTag          NVARCHAR(50) NULL,
    RecordDate         DATE NULL,
    WeightLbs          DECIMAL(8,2) NULL,
    WeightKg           DECIMAL(8,2) NULL,
    BodyConditionScore DECIMAL(3,1) NULL,   -- 1-9 Purina BCS scale
    FrameScore         INT NULL,
    RecordedBy         NVARCHAR(100) NULL,
    Method             NVARCHAR(50) NULL,   -- Scale, Tape, Visual
    Notes              NVARCHAR(MAX) NULL,
    CreatedAt          DATETIME DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthParasite')
CREATE TABLE HerdHealthParasite (
    ParasiteID     INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID     INT NOT NULL,
    AnimalID       INT NULL,
    AnimalTag      NVARCHAR(50) NULL,
    TestDate       DATE NULL,
    TestType       NVARCHAR(100) NULL,   -- FAMACHA, Fecal Float, McMaster, ELISA, Pooled Fecal
    FAMACHAScore   INT NULL,             -- 1-5
    EggCount       INT NULL,             -- EPG
    ParasiteType   NVARCHAR(100) NULL,   -- Haemonchus, Coccidia, Trichostrongylus, etc.
    TreatmentGiven NVARCHAR(100) NULL,
    Dewormer       NVARCHAR(100) NULL,
    DosageGiven    NVARCHAR(50) NULL,
    NextTestDate   DATE NULL,
    RecordedBy     NVARCHAR(100) NULL,
    Notes          NVARCHAR(MAX) NULL,
    CreatedAt      DATETIME DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthQuarantine')
CREATE TABLE HerdHealthQuarantine (
    QuarantineID      INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID        INT NOT NULL,
    AnimalID          INT NULL,
    AnimalTag         NVARCHAR(50) NULL,
    StartDate         DATE NULL,
    PlannedEndDate    DATE NULL,
    ActualEndDate     DATE NULL,
    Reason            NVARCHAR(200) NULL,   -- New Arrival, Illness, Exposure, Post-Travel
    Location          NVARCHAR(100) NULL,
    Status            NVARCHAR(20) NULL,    -- Active, Released, Extended
    MonitoringFreq    NVARCHAR(50) NULL,
    MonitoringNotes   NVARCHAR(MAX) NULL,
    ReleasedBy        NVARCHAR(100) NULL,
    ReleaseConditions NVARCHAR(MAX) NULL,
    Notes             NVARCHAR(MAX) NULL,
    CreatedAt         DATETIME DEFAULT GETUTCDATE(),
    UpdatedAt         DATETIME DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthMortality')
CREATE TABLE HerdHealthMortality (
    MortalityID        INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID         INT NOT NULL,
    AnimalID           INT NULL,
    AnimalTag          NVARCHAR(50) NULL,
    AnimalSpecies      NVARCHAR(50) NULL,
    DeathDate          DATE NULL,
    CauseOfDeath       NVARCHAR(200) NULL,
    DeathCategory      NVARCHAR(50) NULL,   -- Disease, Injury, Predator, Unknown, Culled, Natural
    Location           NVARCHAR(100) NULL,
    AgeAtDeath         NVARCHAR(50) NULL,
    WeightAtDeath      DECIMAL(8,2) NULL,
    PostMortemDone     BIT DEFAULT 0,
    PostMortemDate     DATE NULL,
    PostMortemFindings NVARCHAR(MAX) NULL,
    DisposalMethod     NVARCHAR(100) NULL,   -- Burial, Rendering, Composting, State Disposal
    InsuranceClaim     BIT DEFAULT 0,
    InsuranceAmount    DECIMAL(10,2) NULL,
    EstimatedValue     DECIMAL(10,2) NULL,
    ReportedTo         NVARCHAR(100) NULL,
    Notes              NVARCHAR(MAX) NULL,
    CreatedAt          DATETIME DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthLabResult')
CREATE TABLE HerdHealthLabResult (
    LabResultID     INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID      INT NOT NULL,
    AnimalID        INT NULL,
    AnimalTag       NVARCHAR(50) NULL,
    GroupName       NVARCHAR(100) NULL,
    SampleDate      DATE NULL,
    SampleType      NVARCHAR(100) NULL,   -- Blood, Feces, Milk, Tissue, Urine, Swab
    LabName         NVARCHAR(100) NULL,
    AccessionNumber NVARCHAR(50) NULL,
    TestType        NVARCHAR(100) NULL,   -- CBC, Chemistry Panel, Culture, PCR, Titer, BVD PI
    ResultDate      DATE NULL,
    Results         NVARCHAR(MAX) NULL,
    ReferenceRange  NVARCHAR(MAX) NULL,
    Interpretation  NVARCHAR(MAX) NULL,
    OrderedBy       NVARCHAR(100) NULL,
    AttachmentURL   NVARCHAR(500) NULL,
    Notes           NVARCHAR(MAX) NULL,
    CreatedAt       DATETIME DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthBiosecurity')
CREATE TABLE HerdHealthBiosecurity (
    BiosecurityID     INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID        INT NOT NULL,
    EventDate         DATE NULL,
    EventType         NVARCHAR(100) NULL,   -- Visitor, Delivery, Sale, Purchase, Vet Visit, Employee, Other
    PersonOrCompany   NVARCHAR(100) NULL,
    ContactInfo       NVARCHAR(200) NULL,
    Purpose           NVARCHAR(200) NULL,
    AnimalsContact    BIT DEFAULT 0,
    AreasAccessed     NVARCHAR(200) NULL,
    CleaningProtocol  BIT DEFAULT 0,
    PPEUsed           BIT DEFAULT 0,
    ProtocolsFollowed NVARCHAR(MAX) NULL,
    OriginLocation    NVARCHAR(100) NULL,
    HealthCertificate BIT DEFAULT 0,
    Notes             NVARCHAR(MAX) NULL,
    CreatedAt         DATETIME DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'HerdHealthVetContact')
CREATE TABLE HerdHealthVetContact (
    VetContactID   INT IDENTITY(1,1) PRIMARY KEY,
    BusinessID     INT NOT NULL,
    Name           NVARCHAR(100) NULL,
    ClinicName     NVARCHAR(100) NULL,
    Role           NVARCHAR(50) NULL,   -- Veterinarian, Vet Tech, Large Animal, Emergency, State Vet
    LicenseNumber  NVARCHAR(50) NULL,
    Phone          NVARCHAR(30) NULL,
    EmergencyPhone NVARCHAR(30) NULL,
    Email          NVARCHAR(100) NULL,
    Address        NVARCHAR(300) NULL,
    Specialties    NVARCHAR(200) NULL,
    Species        NVARCHAR(200) NULL,
    IsPreferred    BIT DEFAULT 0,
    IsEmergency    BIT DEFAULT 0,
    Notes          NVARCHAR(MAX) NULL,
    CreatedAt      DATETIME DEFAULT GETUTCDATE(),
    UpdatedAt      DATETIME DEFAULT GETUTCDATE()
);
