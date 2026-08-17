# Oatmeal Farm Network — Backend

A comprehensive FastAPI backend for the Oatmeal Farm Network platform, providing REST APIs for agricultural management, marketplace operations, user authentication, and AI-powered advisory services.

## Overview

This is a comprehensive, enterprise-scale backend for the Oatmeal Farm Network platform—a complete agricultural technology ecosystem serving farmers, agribusinesses, and supply chain participants. It includes **137+ API routers** and **2,000+ endpoints** organized across 15+ major domains.

**Core capabilities:**

- **Authentication & User Management** — JWT-based auth, user profiles, password recovery, platform subscriptions
- **Livestock & Animal Management** — breed tracking, herd health, reproduction, meat processing, animal records
- **Crop & Field Management** — precision agriculture, crop planning, soil testing, yield tracking, pest scouting, irrigation
- **Harvest & Produce** — produce tracking, harvest lots, cold chain logistics, perishable traceability, grain storage
- **Marketplace & E-Commerce** — product catalog, equipment rental, Stripe payments, vendor management, farm stand sales
- **Supply Chain** — delivery routing, supplier management, buyer CRM, procurement, provenance tracking
- **Events & Community** — multi-event management (auctions, fiber arts, conferences, competitions), sponsorships, vendor fairs
- **Financial & Accounting** — cash flow, crop budgets, farmer settlement, pricing, ESG reports
- **Content Management** — website builder, blogging, company features, news, document vault
- **HR & Operations** — job board, work orders, equipment maintenance, farm safety, notifications
- **Sustainability** — ESG reporting, certifications, compliance auditing, export regulations
- **AI Advisory System** — intelligent farm guidance via LangGraph and Google Gemini (`saige/` subdirectory)

## Project Structure

```
.
├── routers/                         # API endpoint modules (137+ routers organized by domain)
│   │
│   ├── Core Business & Operations
│   │   ├── auth.py                  # JWT authentication
│   │   ├── businesses.py            # Business/vendor management
│   │   ├── users.py                 # User profiles & account management
│   │   ├── dashboard.py             # User dashboards
│   │   ├── platform_settings.py     # Platform configuration
│   │   ├── platform_subscriptions.py # Subscription management
│   │   └── platform_services.py     # Platform services
│   │
│   ├── Livestock & Animal Management
│   │   ├── livestock.py             # Animal management & knowledge base
│   │   ├── animals.py               # Detailed animal records
│   │   ├── herd_health.py           # Herd health tracking & reproduction
│   │   ├── meat.py                  # Meat processing & tracking
│   │   ├── processed_food.py        # Food processing workflows
│   │   └── ranches.py               # Ranch/facility management
│   │
│   ├── Crops & Plant Management
│   │   ├── plant_knowledgebase.py   # Crop disease & agronomy guidance
│   │   ├── crop_planning.py         # Crop planning workflows
│   │   ├── crop_rotation.py         # Crop rotation optimization
│   │   ├── crop_summary.py          # Crop status summaries
│   │   ├── crop_monitor_proxy.py    # Crop monitoring integration
│   │   ├── crop_budgets.py          # Crop budget planning
│   │   ├── seed_varieties.py        # Seed & variety management
│   │   ├── soil_tests.py            # Soil testing & analysis
│   │   └── chilling_hours.py        # Chilling hour tracking
│   │
│   ├── Precision Agriculture & Field Management
│   │   ├── precision_ag.py          # Core precision AG tools
│   │   ├── precision_ag_features.py # Advanced PA features
│   │   ├── field_maturity.py        # Field maturity assessment
│   │   ├── field_assessment_report.py # Field assessment reports
│   │   ├── field_health.py          # Field health monitoring
│   │   ├── field_health_alerts.py   # Health alerts & warnings
│   │   ├── field_activity.py        # Field activity logging
│   │   ├── climate_forecast.py      # Weather & climate forecasting
│   │   ├── weather.py               # Weather data integration
│   │   ├── irrigation.py            # Irrigation management
│   │   ├── spray_applications.py    # Pesticide/spray tracking
│   │   ├── scouting.py              # Field scouting reports
│   │   ├── harvest_scheduling.py    # Harvest scheduling
│   │   └── yield_records.py         # Yield tracking & analysis
│   │
│   ├── Produce & Harvest Management
│   │   ├── produce.py               # Produce tracking
│   │   ├── harvest_lots.py          # Harvest lot management
│   │   ├── harvest_bins.py          # Harvest bin tracking
│   │   ├── grain_bin.py             # Grain storage management
│   │   ├── scale_tickets.py         # Weighing & scale data
│   │   └── ingredient_knowledgebase.py # Food processing knowledge
│   │
│   ├── Cold Chain & Perishables
│   │   ├── cold_chain.py            # Cold chain logistics
│   │   ├── perishable_trace.py      # Perishable traceability
│   │   ├── ca_storage.py            # Controlled atmosphere storage
│   │   └── chilling_hours.py        # Chilling requirements
│   │
│   ├── Marketplace & E-Commerce
│   │   ├── marketplace.py           # E-commerce operations
│   │   ├── marketplace_catalog.py   # Product catalog management
│   │   ├── equipment_marketplace.py # Equipment rental/sales
│   │   ├── food_wanted.py           # Food sourcing platform
│   │   ├── sfproducts.py            # San Francisco region products
│   │   ├── stripe_payments.py       # Stripe payment integration
│   │   └── price_list.py            # Dynamic pricing
│   │
│   ├── Supply Chain & Distribution
│   │   ├── supply_chain.py          # Supply chain management
│   │   ├── supply_chain_events.py   # SC event tracking
│   │   ├── supply_chain_ai.py       # AI-powered SC insights
│   │   ├── delivery_routes.py       # Delivery routing
│   │   ├── buyer_crm.py             # Buyer relationship management
│   │   ├── supplier_directory.py    # Supplier management
│   │   ├── supplier_scorecard.py    # Supplier performance
│   │   ├── procurement.py           # Procurement workflows
│   │   ├── farm_inputs.py           # Input sourcing & inventory
│   │   ├── farm_stand.py            # Direct farm sales
│   │   └── provenance.py            # Product provenance tracking
│   │
│   ├── Events & Community
│   │   ├── events.py                # Main event management
│   │   ├── event_features.py        # Event feature configuration
│   │   ├── event_registration_cart.py # Registration shopping cart
│   │   ├── event_checkin.py         # Event check-in
│   │   ├── event_analytics.py       # Event analytics
│   │   ├── event_exports.py         # Event data exports
│   │   ├── event_booth_services.py  # Booth management
│   │   ├── event_floor_plan.py      # Floor plan visualization
│   │   ├── event_meals.py           # Event catering/meals
│   │   ├── event_mailing_list.py    # Event mailing lists
│   │   ├── event_sponsorship.py     # Sponsorship management
│   │   ├── event_promo_codes.py     # Promotional codes
│   │   ├── event_waitlist.py        # Waitlist management
│   │   ├── event_leads.py           # Lead capture
│   │   ├── event_testimonials.py    # Testimonials/feedback
│   │   ├── event_coi.py             # Conflict of interest
│   │   ├── event_fiber_arts.py      # Fiber arts event
│   │   ├── event_fleece.py          # Fleece festival
│   │   ├── event_halter.py          # Halter show event
│   │   ├── event_auction.py         # Auction event
│   │   ├── event_vendor_fair.py     # Vendor fair
│   │   ├── event_dining.py          # Dining event
│   │   ├── event_farm_tour.py       # Farm tour
│   │   ├── event_competition.py     # Competition event
│   │   ├── event_conference.py      # Conference
│   │   ├── event_broadcast.py       # Live broadcast
│   │   ├── event_simple.py          # Simple event
│   │   ├── event_spinoff.py         # Spinoff event
│   │   ├── my_registrations.py      # User event registrations
│   │   └── associations.py          # Member associations
│   │
│   ├── Financial & Accounting
│   │   ├── accounting.py            # General accounting
│   │   ├── cash_flow.py             # Cash flow tracking
│   │   ├── crop_budgets.py          # Crop budget planning
│   │   ├── farm_pl.py               # Farm profit & loss
│   │   ├── farmer_settlement.py     # Farmer payment settlement
│   │   ├── price_list.py            # Product pricing
│   │   └── stripe_payments.py       # Payment processing
│   │
│   ├── Content & Web Management
│   │   ├── website_builder.py       # Website builder
│   │   ├── website_ai.py            # AI-powered website features
│   │   ├── blog.py                  # Blog management
│   │   ├── company_features.py      # Company feature pages
│   │   ├── news.py                  # News & updates
│   │   ├── scraper_knowledge.py     # Web scraping service
│   │   ├── recipes_batches.py       # Recipe & batch management
│   │   └── document_vault.py        # Document storage
│   │
│   ├── HR & Administrative
│   │   ├── hr.py                    # Human resources
│   │   ├── job_board.py             # Job listings
│   │   ├── work_orders.py           # Work order management
│   │   ├── equipment_maintenance.py # Equipment maintenance
│   │   ├── farm_infrastructure.py   # Infrastructure management
│   │   ├── farm_safety.py           # Safety management
│   │   ├── notifications.py         # User notifications
│   │   └── meetings.py              # Meeting coordination
│   │
│   ├── Sustainability & Impact
│   │   ├── esg_reports.py           # ESG reporting
│   │   ├── certifications.py        # Organic/certification tracking
│   │   ├── compliance_audit.py      # Compliance auditing
│   │   ├── export_compliance.py     # Export regulations
│   │   └── esci.py                  # Environmental sustainability
│   │
│   ├── Advanced Operations
│   │   ├── csa.py                   # CSA program management
│   │   ├── csa_advanced.py          # Advanced CSA features
│   │   ├── land_leasing.py          # Land lease management
│   │   ├── grants.py                # Grant tracking
│   │   ├── education.py             # Educational programs
│   │   ├── mill.py                  # Grain mill operations
│   │   ├── outgrower.py             # Outgrower program
│   │   ├── packhouse_qc.py          # Pack house quality control
│   │   ├── nursery.py               # Plant nursery
│   │   ├── plant_tagging.py         # Plant identification
│   │   ├── iot_greenhouse.py        # IoT greenhouse monitoring
│   │   ├── picker_performance.py    # Harvest worker performance
│   │   ├── farm_kpi.py              # Farm KPI tracking
│   │   ├── market_alerts.py         # Market price alerts
│   │   ├── commodity_history.py     # India mandi prices (farmer.in) + optional US USDA/Yahoo
│   │   ├── field_health_alerts.py   # Field health warnings
│   │   ├── thaiyme.py               # Specialty crop (Thai herbs)
│   │   ├── food_aggregator.py       # Food aggregation
│   │   └── reports.py               # Custom reporting
│   │
│   └── Misc & Support
│       ├── forgot_password.py       # Password recovery
│       ├── services.py              # Platform services
│       └── nutrients.py             # Nutrient management
│
├── saige/                           # AI Agricultural Advisory System
│   ├── api.py                       # FastAPI endpoints for Saige
│   ├── graph.py                     # LangGraph workflow orchestration
│   ├── nodes.py                     # Workflow nodes (assessment, routing, advisory)
│   ├── rag.py                       # Firestore RAG/vector search
│   ├── llm.py                       # Google Gemini LLM integration
│   ├── redis_client.py              # Redis connection & pooling
│   ├── chat_history.py              # Firestore chat persistence
│   ├── message_buffer.py            # Redis message buffer
│   ├── models.py                    # FarmState & Pydantic models
│   ├── config.py                    # Configuration & feature flags
│   ├── jwt_auth.py                  # JWT verification
│   ├── weather.py                   # Weather API integration
│   ├── database.py                  # Azure SQL helpers
│   ├── seed_firestore.py            # Firestore data seeding
│   ├── sync_embeddings.py           # Embedding synchronization
│   ├── test_*.py                    # Integration & unit tests
│   └── README.md                    # Full Saige documentation
│
├── migrations/                      # Database schema migrations
│   └── *.sql                        # SQL migration scripts
│
├── main.py                          # FastAPI app initialization & middleware
├── models.py                        # SQLAlchemy & Pydantic models (50k+ lines)
├── database.py                      # Azure SQL database connection
├── auth.py                          # Authentication utilities
├── marketplace_*.py                 # Marketplace utilities
├── marketplace_stripe.py            # Stripe integration
├── event_emails.py                  # Event notification emails
├── external_apis.py                 # Third-party API integrations
├── requirements.txt                 # Python dependencies
├── Dockerfile                       # Cloud Run deployment
├── cloudbuild.yaml                  # GCP Cloud Build pipeline
├── .env.example                     # Environment variables template
└── server_all.py                    # Unified server launcher
```

## Quick Start

### Prerequisites

- Python 3.11+
- Redis 7+ (for Saige features)
- Azure SQL Server (optional, for core backend features)
- Google Cloud credentials (optional, for Saige AI advisory)

### Installation

```bash
# Clone and enter directory
git clone https://github.com/Oatmeal-Farm-Network/oatmealfarmnetworkbackend.git
cd oatmealfarmnetworkbackend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials
```

### Running the Backend

```bash
# Start main API server (port 8000)
uvicorn main:app --reload --port 8000
```

**API Documentation:** Visit `http://localhost:8000/docs`

### Running Saige AI Advisory (Optional)

```bash
# From the saige/ directory
cd saige
uvicorn api:app --reload --port 8001

# Or from root, run Saige routes integrated with main API
```

See [`saige/README.md`](saige/README.md) for full Saige setup and configuration.

## API Endpoints

All endpoints require JWT authentication via `Authorization: Bearer <token>` header (except health checks).

With **137+ routers**, there are **2,000+ endpoints** across the platform. Key endpoint categories:

| Domain | Module Count | Sample Endpoints | Purpose |
|---|---|---|---|
| **Livestock & Animals** | 6 | `/livestock/*`, `/animals/*`, `/herd-health/*` | Animal management, health tracking, meat processing |
| **Crops & Fields** | 15+ | `/crop-planning/*`, `/precision-ag/*`, `/soil-tests/*`, `/yield-records/*` | Crop planning, field health, precision agriculture |
| **Produce & Harvest** | 8 | `/produce/*`, `/harvest-lots/*`, `/grain-bin/*`, `/cold-chain/*` | Harvest management, storage, traceability |
| **Marketplace & Commerce** | 7 | `/marketplace/*`, `/equipment-marketplace/*`, `/farm-stand/*` | E-commerce, pricing, vendor management |
| **Supply Chain** | 10 | `/supply-chain/*`, `/delivery-routes/*`, `/procurement/*` | Routing, sourcing, buyer management |
| **Events & Community** | 32+ | `/events/*`, `/event-analytics/*`, `/event-registration/*` | Event management, sponsorships, registrations |
| **Financial** | 7 | `/accounting/*`, `/cash-flow/*`, `/farmer-settlement/*` | Accounting, budgeting, payments |
| **Content & Web** | 8 | `/website-builder/*`, `/blog/*`, `/news/*` | Website management, blogging, content |
| **HR & Operations** | 10+ | `/hr/*`, `/job-board/*`, `/work-orders/*` | HR management, operations, notifications |
| **Admin & Platform** | 5 | `/platform-settings/*`, `/compliance-audit/*`, `/esg-reports/*` | Configuration, compliance, reporting |

**Health Checks:**

```
GET  /                  # API info & version
GET  /health            # Shallow liveness probe
GET  /ready             # Deep readiness check (all dependencies)
GET  /health/redis      # Redis connectivity
GET  /health/firestore  # Firestore connectivity
```

See [`saige/README.md`](saige/README.md#api-reference) for detailed Saige API documentation.

## Configuration

### Environment Variables

Create a `.env` file in the project root (see `.env.example`):

```env
# --- Authentication ---
SECRET_KEY=your_jwt_secret_key              # HS256 secret (required)

# --- Database ---
DB_HOST=your_azure_sql_host
DB_PORT=1433
DB_USER=your_user
DB_PASSWORD=your_password
DB_NAME=your_database

# --- Saige AI Advisory (optional) ---
GOOGLE_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash-lite
FIRESTORE_DATABASE=charlie
REDIS_ENABLED=true
REDIS_URL=redis://localhost:6379/0

# --- CORS ---
FRONTEND_URL=http://localhost:3000
ALLOW_ALL_ORIGINS=false

# --- India commodity / mandi prices ---
COMMODITY_MARKET=india
# Optional override (default: farmer.in open Agmarknet feed)
# INDIA_MANDI_PRICES_URL=https://farmer.in/api/open/prices.json

# --- Weather (Open-Meteo) ---
WEATHER_UNITS=metric
# WEATHER_UNITS=imperial  # only if you need °F/mph/inch

# --- Scheduler (price fetch webhook) ---
# CRON_SECRET=long-random-string   # send as X-Cron-Secret on POST /api/commodity-prices/fetch

# --- Marketplace (optional) ---
STRIPE_SECRET_KEY=your_stripe_key
SENDGRID_API_KEY=your_sendgrid_key
```

See [`saige/README.md`](saige/README.md#configuration) for full Saige configuration details.

## Deployment

### Google Cloud Run

```bash
# Build and deploy
gcloud builds submit --config cloudbuild.yaml

# Manually deploy Dockerfile
gcloud run deploy oatmealfarmnetwork \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

**Production domains:**
- API: `https://oatmealfarmnewtorkbackend-802455386518.us-central1.run.app`
- Frontend: `https://www.oatmealfarmnetwork.com`

## Technologies

| Layer | Technology |
|---|---|
| API Framework | FastAPI, Uvicorn, Starlette |
| Database | Azure SQL Server (pymssql) |
| Authentication | JWT HS256 (python-jose) |
| **Saige AI** | LangGraph, Google Gemini, Firestore, Redis |
| Marketplace | Stripe, SendGrid |
| Cloud Platform | Google Cloud (Cloud Run, Firestore, Earth Engine) |
| Task Queue | Redis (Saige checkpoints & message buffer) |
| Vector Search | Firestore vector search + text-embedding-004 |
| Imagery Analysis | Google Earth Engine (biomass analysis, sentinel-2) |
| Email | SendGrid API |
| File Storage | Google Cloud Storage (images, documents) |

## Platform Scale

This is one of the most comprehensive agricultural software platforms:

- **137+ API routers** covering 15+ agricultural domains
- **2,000+ endpoints** across the platform
- **50K+ lines** in models.py alone (extensive domain model coverage)
- **40+ database migrations** for complex data schema evolution
- **Multi-tenancy support** for businesses, farms, and organizations
- **Enterprise event management** (32+ event types)
- **Real-time monitoring** via IoT greenhouse, precision ag, field health
- **Supply chain visibility** from farm to consumer
- **AI-powered advisory** with RAG-backed contextual guidance

## Key Features

### Saige AI Advisory System

The `saige/` subdirectory contains an AI-powered agricultural advisory system:

- **Multi-domain Advisory** — livestock, crops, weather, mixed queries
- **LangGraph Orchestration** — structured workflows with state management
- **RAG Integration** — Firestore vector search with domain-specific knowledge
- **Real-time Context** — live weather data, farm assessments
- **Chat History** — Firestore persistence + Redis message buffer

→ **Full documentation:** [`saige/README.md`](saige/README.md)

### Livestock & Animal Management

- Herd health tracking, reproduction monitoring
- Breed recommendations & knowledge base
- Meat processing workflows
- Animal photo/identification system
- Herd health accounting

### Precision Agriculture & Field Monitoring

- **Satellite Analysis** — Earth Engine integration for crop health, biomass estimation
- **Field Mapping** — precision ag tools, field boundaries
- **Real-time Monitoring** — IoT greenhouse sensors, soil tests
- **Health Alerts** — automated warnings for field anomalies
- **Yield Analysis** — historical yield tracking and optimization

### Events & Community

Comprehensive event management supporting:
- Auctions, livestock shows, fiber arts festivals
- Vendor fairs, conferences, competitions
- Sponsorship management, floor planning
- Registration, check-in, meal planning
- Broadcast/streaming capabilities

### Marketplace & E-Commerce

- Product catalog with categories
- Stripe payment integration
- Equipment rental marketplace
- Farm stand direct sales
- Vendor management & commission tracking

### Supply Chain & Traceability

- Delivery route optimization
- Supplier directory & scoring
- Buyer CRM for vendor relationships
- Cold chain logistics tracking
- Product provenance & traceability
- Export compliance documentation

### Financial & Accounting

- Cash flow tracking & forecasting
- Crop budget planning
- Farmer settlement & payments
- Price list management
- ESG reporting & sustainability metrics

### Content Management

- Website builder with AI assistance
- Blogging platform
- Company feature pages
- News aggregation
- Document vault for files

## Development

### Database Seeding

The repository includes multiple seed scripts to populate the database with realistic demo data for testing and development:

```bash
# General demo data (businesses, users, events)
python seed_demo_15671.py

# Livestock & animal management demo
python seed_livestock_15665.py

# Accounting demo data
python seed_accounting_15671.py

# Cold chain & logistics demo
python seed_cold_chain_15671.py
python seed_cold_chain_advanced_15671.py
python seed_cold_chain_recent_15671.py
python seed_cold_chain_shipments_maint_15671.py

# Precision agriculture demo
python seed_precision_ag_15671.py

# Supply chain demo
python seed_suppliers_15671.py

# Education, grants, orders demo
python seed_edu_15671.py
python seed_grants_15671.py
python seed_orders_15671.py

# Test data
python seed_test_data_15665.py
```

**Note:** Seed scripts populate specific domains. Run multiple seeds to build a comprehensive demo environment. The numeric suffixes (15671, 15665) reference demo business IDs.

### Utilities

```bash
# Upload local animal photos to cloud storage
python upload_local_animal_photos.py

# Database schema migrations (in migrations/ directory)
# Applied automatically or manually via your SQL client
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=.

# Run specific test file
pytest saige/test_api_flow.py -v
```

### Project Structure for Routers

Each router is a FastAPI APIRouter:

```python
from fastapi import APIRouter, Depends
from database import get_db

router = APIRouter(prefix="/my_resource", tags=["my_resource"])

@router.get("/")
def list_my_resources(db = Depends(get_db)):
    # Implementation
    pass

@router.post("/")
def create_my_resource(data: MyModel, db = Depends(get_db)):
    # Implementation
    pass
```

Then import in `main.py`:
```python
from routers import my_resource
app.include_router(my_resource.router)
```

## Security

**Never commit:**
- `.env` files (API keys, credentials)
- `credentials/` directories (service account JSONs)
- Database passwords or tokens

The `.gitignore` excludes sensitive files. Before pushing, verify:

```bash
git status  # Confirm no .env, credentials, or secrets staged
```

**Production Checklist:**
- [ ] Generate strong random `SECRET_KEY` (32+ chars)
- [ ] Set `ALLOW_ALL_ORIGINS=false` and specify `FRONTEND_URL`
- [ ] Enable `REDIS_SSL=true` for managed Redis
- [ ] Rotate API keys, JWT secrets, and service accounts regularly
- [ ] Use environment-specific `.env` files (never commit)

## Troubleshooting

| Issue | Solution |
|---|---|
| `401 Invalid or expired token` | Verify JWT in `Authorization: Bearer <token>` header |
| `500 JWT_SECRET is not configured` | Set `SECRET_KEY` in `.env` |
| Database connection fails | Check `DB_HOST`, `DB_USER`, `DB_PASSWORD` in `.env` |
| Saige endpoints 404 | Confirm Saige routers are registered in `main.py` |
| Redis connection timeout | Verify Redis is running (`redis-cli ping`), or set `REDIS_ENABLED=false` |
| Docker build fails | Ensure `requirements.txt` is up to date and Python 3.11+ |

## Support & Contributions

- **Issues:** Report bugs on [GitHub Issues](https://github.com/Oatmeal-Farm-Network/oatmealfarmnetworkbackend/issues)
- **Discussions:** Join community discussions on GitHub
- **Contributing:** See `CONTRIBUTING.md` (if available) for contribution guidelines

## License

[Add your license information here]

## Related Repositories

- **Frontend:** [oatmeal-farm-network-frontend](https://github.com/Oatmeal-Farm-Network/oatmeal-farm-network-frontend)
- **Documentation:** [oatmeal-farm-network-docs](https://github.com/Oatmeal-Farm-Network/oatmeal-farm-network-docs)
- **Saige AI:** See [`saige/README.md`](saige/README.md) for dedicated AI advisory documentation
