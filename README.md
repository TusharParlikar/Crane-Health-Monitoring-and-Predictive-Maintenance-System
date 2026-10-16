# Real-Time Crane Health Monitoring and Predictive Maintenance System

A predictive maintenance system built around a real-time ingestion API. Any client (a sensor gateway, a script or a simulator) uploads a crane's sensor reading every second. The API scores each reading on arrival with two models and returns the result: an anomaly flag, a health score and a "service needed in X days" forecast. A live dashboard ranks the fleet by risk.

See [interview.md](interview.md) for the problem, motivation, competition and design reasoning, and [project.md](project.md) for the original brief.

## How it works

```mermaid
flowchart LR
    C[Client / sensor gateway / simulator] -->|reading every second| API[FastAPI upload route]
    API --> V[Validation - Pydantic]
    V --> W[Per-machine sliding window]
    W --> F[Feature engineering]
    F --> A[Anomaly model - Isolation Forest]
    F --> R[RUL model - XGBoost]
    A --> S[Health score + alerts]
    R --> S
    S -->|response| C
    S --> DB[(PostgreSQL)]
    DB --> D[Streamlit fleet dashboard]
```

1. A reading has a `machine_id`, a `timestamp` and four signals: `hoist_load` (t), `motor_temp` (°C), `vibration` (mm/s RMS) and `duty_cycle` (%).
2. The API validates it (types, ranges, required fields, no unknown fields) and appends it to that machine's 30-reading window.
3. It builds 17 features from the window: last value, mean, standard deviation and trend for each signal, plus the share of vibration energy in the upper half of the spectrum.
4. **Isolation Forest** flags unusual behaviour. **XGBoost** predicts remaining useful life (RUL) in days.
5. Health score (0–100) = predicted RUL as a share of 60 days, halved while the reading is flagged as anomalous.
6. An alert (`anomaly` or `service_due` when RUL < 7 days) is raised after 3 readings in a row and cleared after 3 clear readings, so one noisy reading doesn't flip it.
7. The reading, its scores and any alerts are stored. The dashboard refreshes from the API every 3 minutes (`REFRESH_SECONDS` in [crane/dashboard.py](crane/dashboard.py)); reload the page to refresh sooner.

## Quick start

### Docker (API + PostgreSQL + dashboard + simulator)

```bash
docker compose up --build
```

- Dashboard: http://localhost:8501
- API docs: http://localhost:8000/docs

The image trains the models during the build (about a minute). The simulator starts 10 cranes at different ages, so some are already worn.

### Local (SQLite, no Docker)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m crane.train                          # train + evaluate, writes models/
uvicorn crane.api:app                          # API on :8000, stores data in crane.db
python -m crane.client --machines 10           # simulated fleet, 1 reading/machine/second
streamlit run crane/dashboard.py               # dashboard on :8501
```

Set `DATABASE_URL` to use PostgreSQL instead, for example `postgresql+psycopg://user:pass@host:5432/crane`.

### Tests

```bash
pytest                                                    # SQLite
TEST_DATABASE_URL=postgresql+psycopg://user@host/empty_db pytest   # PostgreSQL (empty database)
```

## API

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/readings` | Score one reading |
| `POST` | `/readings/batch` | Score a JSON array of readings in order (max 10,000) |
| `POST` | `/readings/csv` | Score a CSV body (`Content-Type: text/csv`); header row = reading fields |
| `GET` | `/fleet` | Latest state of every machine, most at-risk first |
| `GET` | `/machines/{id}/readings?limit=300` | Reading and score history for one machine |
| `GET` | `/alerts?active=true&machine_id=` | Alert history, or only the active alerts |
| `GET` | `/health` | Liveness check |

Example:

```bash
curl -X POST localhost:8000/readings -H "Content-Type: application/json" -d '{
  "machine_id": "crane-01", "timestamp": "2026-10-16T12:00:00Z",
  "hoist_load": 22.5, "motor_temp": 48.1, "vibration": 2.3, "duty_cycle": 55
}'
```

```json
{"machine_id": "crane-01", "timestamp": "2026-10-16T12:00:00Z", "anomaly": false, "anomaly_score": 0.4521,
 "rul_days": 54.6, "health": 91.0, "alerts": [], "latency_ms": 71.52}
```

Invalid readings return `422` with the field and the reason. CSV errors also give the line number. The anomaly flag stays `false` until a machine has 30 readings, because a part-filled window can't be judged fairly. (The first call's latency includes model warm-up.)
