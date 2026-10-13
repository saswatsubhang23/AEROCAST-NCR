# AEROCAST NCR

> **Weather Forecasting, Air Quality Intelligence & Geospatial Digital-Twin for Delhi-NCR**

AEROCAST NCR is an environmental intelligence application engineered for the National Capital Region (Delhi-NCR). It integrates real-time meteorological observations, regulatory air-quality measurements, multi-coordinate batch geospatial analytics, synchronized 2D/3D atmospheric digital-twin visualizations, executive reporting, an offline machine-learning pipeline, and a local RAG-assisted AI copilot.

---

## 1. System Architecture & Folder Layout

The project is structured as a decoupled full-stack architecture comprising a high-performance Python FastAPI service, a Next.js 16 frontend, an offline machine-learning/historical data engine, and comprehensive documentation:

```
├── api/                           # Backend: FastAPI 0.143 (Python 3.12 - 3.14)
│   ├── app/
│   │   ├── api/                   # API route handlers (weather, air, twin, reports, assistant, etc.)
│   │   ├── core/                  # Configuration (pydantic-settings), locations, time utilities
│   │   ├── db/                    # SQLAlchemy engine & session management
│   │   ├── services/              # Domain logic: AQI calculator, batch PM2.5, hourly cache, status
│   │   ├── twin/                  # 2D/3D twin synchronization, inverse distance weighting (IDW), simulation
│   │   ├── assistant/             # Local LLM chat streaming & tool dispatch
│   │   ├── kb/                    # Knowledge base RAG & Chroma vector store
│   │   ├── reports/               # Executive PDF generation engine (fpdf2) & CSV serializers
│   │   ├── alerts/                # User alert evaluation & SQLite store
│   │   ├── history/               # Historical ingestion & cleaning engine (OpenAQ, xKDR, Open-Meteo)
│   │   ├── ml/                    # Offline ML training, feature engineering, and inference pipelines
│   │   └── training/              # One-click model training job orchestrator
│   ├── data/                      # Local runtime data (SQLite stores, vector DBs, models) [GIT-IGNORED]
│   ├── migrations/                # Alembic PostGIS schema migrations
│   ├── scripts/                   # Database setup scripts (PostgreSQL/PostGIS)
│   ├── tests/                     # 840+ unit, integration, and system tests (pytest)
│   ├── .env.example               # Backend environment variable template
│   ├── requirements.txt           # Production API dependencies
│   └── requirements-ml.txt        # Optional offline ML training & inference dependencies
│
├── web/                           # Frontend: Next.js 16.4 (Turbopack), React 19.3, TypeScript
│   ├── src/
│   │   ├── app/                   # App Router pages (/, /weather, /air-quality, /twin, /flow, /reports, etc.)
│   │   │   └── air-quality/batch/ # Multi-coordinate batch PM2.5 analysis & export UI
│   │   ├── components/            # Reusable UI, MapLibre/deck.gl layers, Three.js 3D scenes, ECharts
│   │   └── lib/                   # API clients, store management, coordinate math, spatial interpolators
│   ├── patches/                   # Version-controlled patches (@react-three/drei patch via patch-package)
│   ├── public/                    # Static web assets (worker scripts copied during postinstall)
│   ├── scripts/                   # Post-install hooks (copy-maplibre-worker.mjs)
│   ├── .env.example               # Frontend public environment variable template
│   └── package.json               # Frontend dependencies & scripts
│
├── docs/                          # Architectural specifications, data audits, and gap analyses
├── india_approx_5km_coordinate_grid.csv # High-density coordinate grid (~111k points across India, ~29 MB)
├── state_place_latitude_longitude.csv   # Sample state/district coordinate fixture (760 points)
├── start.bat                      # Windows launcher (starts FastAPI on :8000 & Next.js on :3000)
├── .env.example                   # Root guide to environment configuration
├── .gitattributes                 # Cross-platform line ending normalization (LF/CRLF)
└── .gitignore                     # Strict multi-tier ignore rules for caches, credentials, and data
```

---

## 2. Actual Implemented Features

### Live Weather & Atmospheric Observations
- **Real-time Observations:** Fetches live temperature, humidity, surface pressure, wind speed, wind direction, boundary layer height (BLH), and cloud cover via Open-Meteo API.
- **7-Day Forecast:** Hourly and daily forecast series with temperature ranges and precipitation probabilities.
- **Atmospheric Profiling:** Visualizes planetary boundary layer height, temperature inversions, and vertical atmospheric levels.

### Regulatory Air Quality & CPCB AQI Calculation
- **Regulatory Monitoring Stations:** Direct live ingestion from OpenAQ v3 for continuous ambient air quality stations across Delhi-NCR.
- **CPCB AQI Standard:** Exact Indian National Air Quality Index (NAQI) calculation using sub-index breakpoints for PM2.5, PM10, NO2, SO2, CO, and O3.
- **Station-Level Breakdown:** Real-time pollutant concentrations, dominant pollutants, sensor staleness indicators, and station metadata.

### High-Density Batch Coordinate Analytics & Export
- **Batch PM2.5 Ingestion:** Enriches custom CSV uploads (supporting up to 100k+ coordinates) with Open-Meteo Air Quality forecasts.
- **Hourly Incremental Caching:** SQLite-backed persistent cache (`batch_hourly_cache.sqlite`) prevents redundant API calls and resumes interrupted fetches seamlessly.
- **Dual Export:** Export enriched datasets directly as CSV or structured, multi-page executive PDF reports.

### Synchronized Geospatial Digital Twin (2D & 3D)
- **Interactive 2D Geospatial Map:** MapLibre GL JS basemap combined with GPU-accelerated deck.gl overlay layers (station markers, wind vectors, heatmaps, and Inverse Distance Weighting interpolation).
- **Synchronized 3D Atmospheric Twin:** Three.js and React Three Fiber scene rendering real terrain elevation, animated 3D wind particle trajectories, planetary boundary layer ceilings, and ground-level pollutant concentrations.
- **Playback & Time-Scrubbing:** Synchronized timeline control allowing simultaneous forward/backward playback across 2D and 3D views.

### Local RAG Assistant & Document Knowledge Base
- **Private Local LLM:** Integration with local Ollama instances (e.g., `qwen3:8b`, `hermes3:8b`) with zero external cloud dependencies.
- **Vector Document Store:** Embedded document retrieval using Chroma DB and `nomic-embed-text` embeddings.
- **Domain RAG:** Grounded conversational answers citing indexed environmental and regulatory PDF documents.

### Executive Reporting & User Alerts
- **Automated PDF Reports:** Multi-page reporting generated via `fpdf2` featuring KPI scorecards, CPCB AQI categorization, geographic breakdowns, and health recommendations.
- **Custom Alert Engine:** User-configured threshold rules stored in SQLite, alerting on hazardous PM2.5 or adverse weather conditions.

### Offline Machine Learning & Historical Pipeline
- **Historical Ingestion:** Automated ingestion pipeline (`python -m app.history`) combining OpenAQ, xKDR (CPCB historical archive), and Open-Meteo reanalysis data into a local store.
- **Feature Engineering:** 90 engineered feature columns covering multi-horizon lags (1h to 72h) and meteorological interactions.
- **Multi-Model Training:** Offline training of Random Forest, XGBoost, LightGBM, and SVR regressors with stratified metric evaluations (`python -m app.ml train`).
- **One-Click Web Manager:** Manage and monitor training runs directly from the `/training` dashboard.

---

## 3. Technology Stack

| Layer | Technologies |
|---|---|
| **Backend Framework** | FastAPI 0.143, Uvicorn 0.54, Pydantic v2 / Pydantic-Settings |
| **HTTP & Networking** | HTTPX 0.28 (async upstream client with rate-limiting & exponential backoff) |
| **Data & Storage** | SQLite 3 (WAL mode), ChromaDB 1.5, SQLAlchemy 2.1, Alembic 1.20, Psycopg 3.3 |
| **Report Generation** | fpdf2 2.8, Pillow 12.3, pypdf 6.2 |
| **Machine Learning** | scikit-learn 1.9, XGBoost 3.4, LightGBM 4.7, NumPy 2.5, SciPy 1.18, Joblib 1.6 |
| **Frontend Framework** | Next.js 16.4 (Turbopack, App Router), React 19.3, TypeScript 5 |
| **Styling & UI** | Tailwind CSS v4, Lucide React, Radix UI Primitives, Framer Motion |
| **Geospatial & 3D** | MapLibre GL JS 6.13, deck.gl 9.4 (MapboxOverlay), Three.js 0.185, React Three Fiber 9.8, Drei 10.7 |
| **Data Visualization** | Apache ECharts 6.1 |
| **Testing & Quality** | Pytest 9.1, Pytest-Asyncio, Vitest 5.0, ESLint 9 |

---

## 4. Prerequisites & Environment Setup

### Supported Runtime Versions
- **Python:** 3.12, 3.13, or 3.14 (64-bit)
- **Node.js:** 20.x or 22.x LTS
- **npm:** 10.x+
- **Ollama (Optional):** Required for AI assistant and knowledge base embeddings

---

### Step 1: Backend Installation & Setup

1. Open a terminal and navigate to the `api` directory:
   ```bash
   cd api
   ```

2. Create and activate a Python virtual environment:
   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install API dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   *(Optional: If you intend to run offline model training or local ML inference, install `pip install -r requirements-ml.txt`)*

4. Configure environment variables:
   ```bash
   # Windows
   copy .env.example .env

   # Linux / macOS
   cp .env.example .env
   ```
   Open `api/.env` and supply your credentials (see [Environment Variables](#6-environment-variables)).

---

### Step 2: Frontend Installation & Setup

1. Open a new terminal and navigate to the `web` directory:
   ```bash
   cd web
   ```

2. Install dependencies (this automatically applies the `@react-three/drei` patch and copies the MapLibre worker):
   ```bash
   npm install
   ```

3. Configure frontend environment variables:
   ```bash
   # Windows
   copy .env.example .env.local

   # Linux / macOS
   cp .env.example .env.local
   ```
   *(Optional: Set `NEXT_PUBLIC_CARTO_API_KEY` if using custom CARTO basemaps)*

---

## 5. Running the Application

### One-Click Launch (Windows)
Double-click `start.bat` in the project root. This spawns both the FastAPI backend and Next.js frontend in separate terminal windows.

### Manual Launch

**Start Backend:**
```bash
cd api
.venv\Scripts\activate       # Linux/macOS: source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```
- **Backend API:** [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

**Start Frontend:**
```bash
cd web
npm run dev
```
- **Web Application:** [http://localhost:3000](http://localhost:3000)

**Frontend Production Build:**
```bash
cd web
npm run build
npm start
```

---

## 6. Environment Variables

All secrets and environment-specific settings are maintained in local `.env` and `.env.local` files, which are strictly git-ignored.

### Backend (`api/.env`)

| Variable | Required | Default / Placeholder | Description |
|---|---|---|---|
| `ENVIRONMENT` | No | `development` | Runtime mode (`development`, `production`, `test`) |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `AQ_API_KEY` | **Recommended** | *(empty)* | OpenAQ v3 API key ([Free Registration](https://explore.openaq.org/register)) |
| `DATABASE_URL` | No | `postgresql+psycopg://aerocast:CHANGE_ME@localhost:5432/aerocast` | PostgreSQL/PostGIS connection (fallback to SQLite) |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Endpoint for local Ollama server |
| `OLLAMA_MODEL` | No | `qwen3:8b-q4_K_M` | Chat model name (e.g. `qwen3:8b`, `hermes3:8b`) |
| `OLLAMA_EMBED_MODEL`| No | `nomic-embed-text` | Embedding model for document knowledge base |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Comma-separated list of allowed browser origins |
| `OPEN_METEO_API_KEY`| No | *(empty)* | Optional commercial Open-Meteo key (free public tier used by default) |
| `INDIA_AQI_API_KEY` | No | *(empty)* | Optional xKDR key for historical CPCB data ingestion |
| `ML_FORECAST_URL` | No | *(empty)* | Optional external pollution-forecasting API |
| `ML_LOCAL_MODEL_DIR`| No | `""` | Local directory containing offline trained models |

### Frontend (`web/.env.local`)

| Variable | Required | Default / Placeholder | Description |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | No | `http://localhost:8000` | Backend API URL |
| `NEXT_PUBLIC_CARTO_API_KEY` | No | *(empty)* | CARTO basemap access token (restrict in CARTO dashboard) |

---

## 7. Verification, Tests & Quality Checks

Run the automated test suites to verify that both backend and frontend pass all quality gates:

### Backend Tests (pytest)
```bash
cd api
.venv\Scripts\python -m pytest -q
```
*Result: 845 passing tests covering route dispatch, CPCB AQI logic, batch PM2.5 enrichment, digital twin synchronization, and report exports.*

### Frontend Tests (vitest)
```bash
cd web
npm run test
```
*Result: 164 passing tests across 19 test suites covering twin state, field math, geometry, and component stores.*

### Frontend Type Check & Build
```bash
cd web
npx tsc --noEmit
npm run build
```

---

## 8. Database, Migrations & Offline ML Pipelines

### Database Setup & PostGIS (Optional)
AEROCAST runs completely without PostgreSQL by using local SQLite and Chroma storage. If you choose to enable PostgreSQL with PostGIS:
1. Initialize the database using `api/scripts/setup_local_postgres.sql`.
2. Run Alembic schema migrations:
   ```bash
   cd api
   alembic upgrade head
   ```

### Historical Data Pipeline
To build or update historical data stores:
```bash
cd api
.venv\Scripts\python -m app.history check-db     # Verify DB connectivity
.venv\Scripts\python -m app.history sources      # Probe upstream sources
.venv\Scripts\python -m app.history all          # Full pipeline: discover, ingest, clean, features
```

### Offline Machine Learning
```bash
cd api
pip install -r requirements-ml.txt
python -m app.ml targets --coverage ../docs/data/coverage-report.json
python -m app.ml train
python -m app.ml report
```

---

## 9. Large Asset Management (`.csv` Datasets)

The repository root includes coordinate datasets used for batch spatial sampling and validation:
- `state_place_latitude_longitude.csv` (~20 KB): 760 sampling points across Indian states and districts (tracked in Git).
- `india_approx_5km_coordinate_grid.csv` (~29.3 MB, 111,190 rows): High-resolution 5km spatial grid covering India.

> [!NOTE]
> `india_approx_5km_coordinate_grid.csv` is currently version-controlled directly. At 29.3 MB, it is below GitHub's 50 MB warning threshold and 100 MB hard file limit. If your organization prefers to keep the repository clone size minimal, this file can either be tracked via **Git LFS** (`git lfs track "*.csv"`) or hosted as an external GitHub Release asset.

---

## 10. Known Limitations & Scientific Provenance

In accordance with scientific and operational integrity principles:
1. **No Live Dispersion Simulation:** The 2D and 3D digital twins utilize verified meteorological wind vectors and Inverse Distance Weighting (IDW) interpolation from real regulatory monitors. They do **not** run real-time CFD or CALPUFF dispersion physics engines in the browser.
2. **OpenAQ Latency:** Real-world regulatory air quality monitors occasionally experience reporting delays (from 1 to 24+ hours). AEROCAST honest badges explicitly display data timestamps and mark sensors as "stale" when they lag.
3. **Forecasting Availability:** Without an active external ML forecasting service (`ML_FORECAST_URL`) or local trained models (`ML_LOCAL_MODEL_DIR`), pollution forecasts are displayed honestly as "Unavailable" rather than simulated or fabricated.
4. **Authentication:** The current build is designed for local, air-gapped, or intranet deployment without an integrated multi-tenant user authentication layer.

---

## 11. Security & Contribution Guidelines

- **Never Commit Secrets:** Do not commit `.env`, `.env.local`, API keys, certificates, or database credentials. Ensure all templates use placeholders only.
- **Map Tile Security:** When deploying `NEXT_PUBLIC_CARTO_API_KEY`, restrict the token to your specific domain names in the CARTO dashboard.
- **Reporting Vulnerabilities:** If you discover a security vulnerability, please open a private security advisory on GitHub rather than a public issue.

---

## 12. License

This repository does not currently include an open-source license. All rights are reserved by the original author. For licensing inquiries or distribution rights, contact the repository maintainer.
