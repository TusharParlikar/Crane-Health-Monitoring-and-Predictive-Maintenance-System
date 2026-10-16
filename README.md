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

## Results

From `python -m crane.train` (100 simulated run-to-failure histories: 60 train, 20 validation, 20 test; the test set is 28,780 readings from cranes the models never saw):

| Metric | Result |
|---|---|
| Missed-fault rate (anomaly model, per reading) | 2.1% |
| False-alarm rate (per reading) | 13.9% |
| Injected fault episodes that raised an alert | 91 / 92 |
| False anomaly alerts (after the 3-in-a-row filter) | 3.5 per 1,000 healthy crane-hours; 82 of 154 alerts raised |
| RUL error (MAE, RUL capped at 60 days) | 9.9 days |
| Failures caught by a "service due" alert before breakdown | 20 / 20 |
| Average life left unused when serviced | 6.3 days |
| Downtime: reactive vs predictive | 60 vs 10 days (**83% avoided**) |
| Model scoring time | ~6 ms per reading |
| End-to-end latency (PostgreSQL, see [Test results](#test-results)) | p50 16 ms, p95 17 ms |

The anomaly threshold minimises cost with a missed fault costed at 10× a false alarm. That is why missed faults are rare and false alarms are higher: about half of all anomaly alerts are false, around one per crane every 12 days. Raise `COST_FALSE_ALARM` to trade some missed faults for fewer false alerts. Downtime assumes 0.5 days for a planned service and 3 days for a breakdown. All costs are constants at the top of [crane/train.py](crane/train.py); change them to match a real site.

**These numbers come from simulated data.** They show that the pipeline works end to end. They don't measure performance on real cranes.

## Test results

Tested on 2026-10-16/17 on a Windows 11 laptop. The API ran as one uvicorn worker on PostgreSQL 16.2, run locally because Docker isn't installed on that machine.

| Test | Result |
|---|---|
| `pytest` on SQLite | 13 / 13 passed |
| `pytest` on PostgreSQL 16.2 | 13 / 13 passed |
| Live demo: 10 cranes × 1 reading/s, 180 rounds | 1,800 / 1,800 accepted; p50 23 ms, p95 46 ms; alerts raised and cleared (8 anomaly, 3 service-due) |
| Max throughput, 1 client sending back-to-back | 54 readings/s; p50 16 ms, p95 17 ms |
| 4 parallel clients | 57 readings/s combined; p50 65 ms each |
| 8 parallel clients (run 3 times) | 50–66 readings/s combined; 8 of 4,000 uploads failed in the first run, 0 of 4,000 in each repeat |
| API restart | Active alerts restored from the database; the first reading after restart still reports them |
| Dashboard (rendered with Streamlit's test harness against the API) | No errors with 300 machines loaded |

**What this means:**
- One API process handles about **50–65 cranes** reporting every second. Adding parallel clients doesn't raise that, because scoring is Python and holds the GIL. Beyond that, run several workers with the windows moved to Redis.
- The 8 failed uploads never reached the server (it logged every request it received as `200 OK`), so they were client-side connection errors under burst load. They didn't reproduce in two reruns. A production client should retry.
- **Not tested:** the Docker image and `docker compose`, because Docker isn't installed on the test machine.

**Fixed during testing:** the first load test capped at 23 readings/s however many clients sent data. Profiling showed scikit-learn's `IsolationForest.score_samples` spent about 50 ms of Python overhead on each single reading. The API now looks up precomputed per-tree leaf scores, and training checks they match scikit-learn's own scores. That cut scoring from ~25 ms to ~6 ms and more than doubled throughput, with identical model output.
