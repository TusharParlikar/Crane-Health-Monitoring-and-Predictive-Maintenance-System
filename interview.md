# Explaining the Project: Crane Health Monitoring and Predictive Maintenance

Talking notes for interviews and demos. Read the sections in order. Each one answers the question a listener usually asks next.

---

## 1. The 30-second pitch

> "Cranes in ports, factories and construction sites break down without warning, and every breakdown stops work. I built a system where each crane sends its sensor readings (load, motor temperature, vibration, duty cycle) to an API every second. The API scores every reading on arrival with two models. One catches unusual behaviour as it happens, and the other forecasts how many days are left before the crane needs service. A live dashboard ranks the whole fleet by risk, so the maintenance team knows which machine to look at first. I measure success in business terms: missed faults, false alarms and downtime avoided, not only model accuracy."

---

## 2. What problem are we solving?

Industrial cranes (overhead, gantry, port and tower cranes) carry heavy loads all day. Their critical parts wear out: hoist motors, gearboxes, bearings, brakes and wire ropes. When one fails:

- **Work stops.** A port crane that is down stops ships being unloaded. A factory crane that is down can stop a production line.
- **Repairs cost more.** A part that fails can damage other parts. Emergency repairs need urgent spares and overtime labour.
- **Safety is at risk.** A crane failing under load can injure people.

Most sites maintain cranes in one of two ways, and both are weak:

| Approach | How it works | Problem |
|---|---|---|
| **Reactive** | Fix it after it breaks | Unplanned downtime, costly emergency repairs, safety risk |
| **Preventive (scheduled)** | Service every N hours or months | Healthy parts get replaced too early (waste), and faults between services are still missed |

**The problem in one line:** maintenance teams cannot see a crane's condition in real time, so they either wait for it to fail or service it on a fixed schedule that ignores its actual condition.

---

## 3. Why we need this (the solution)

**Predictive maintenance** means servicing a machine when its data shows it is actually degrading, not before and not after.

This system gives the maintenance team:

1. **Early warning.** The anomaly model flags unusual behaviour within seconds, for example vibration rising at a normal load.
2. **A planning horizon.** The remaining-useful-life (RUL) model says "service needed in ~X days", so repairs can be planned for a quiet shift instead of done in an emergency.
3. **Priorities.** Each machine gets a health score from 0 to 100 and a risk rank, so a team with limited people looks at the worst machine first.
4. **A record.** Every reading, score and alert is stored, which supports audits and root-cause analysis and gives data to retrain the models.

**Business value:**
- Less unplanned downtime (repairs are planned instead of emergencies)
- Lower maintenance cost (fewer unnecessary part changes, less secondary damage)
- Better safety (faults are caught before they fail under load)
- Longer machine life

---

## 4. How it works (the architecture)

```
Crane / simulator ──(1 reading/sec)──► FastAPI upload route
                                          │
                                   Pydantic validation
                                          │
                              Per-machine sliding window
                                          │
                     Feature engineering (rolling stats, trends, FFT)
                                          │
                        ┌─────────────────┴─────────────────┐
                Anomaly model                         RUL model
              (Isolation Forest)                      (XGBoost)
                        └─────────────────┬─────────────────┘
                          Health score + alerts → response
                                          │
                                     PostgreSQL
                                          │
                              Streamlit fleet dashboard
```

**Online path (each reading):** validate → add to that machine's window → build features → score with both models → return the result and save it.

**Offline path:** train the models on historical degradation data and save them with joblib. The API loads them once at startup.

---

## 5. Key design decisions (and why)

Interviewers usually care most about this section, so be ready to explain each choice.

| Decision | Why |
|---|---|
| **One API route that any client can call** | A real sensor gateway, the simulator and the dataset replay all use the same route, so the code tested in development is the code that runs in production |
| **Validate every reading with Pydantic** | Sensors send bad data (missing fields, impossible values). Rejecting it at the entry point keeps garbage out of the models and the database |
| **Per-machine sliding window** | One reading on its own says little. Trends over the last N seconds (rising temperature, growing vibration) carry the real signal |
| **Isolation Forest for anomalies** | Real fault data is rare and often unlabelled. Isolation Forest is unsupervised: it learns what "normal" looks like and flags readings that differ from it. It is also fast enough to score every second |
| **XGBoost for RUL** | It is strong on tabular features, fast to train, and easy to explain through feature importance. An LSTM is only added if it clearly beats XGBoost, because it is slower and harder to explain |
| **Train offline, score online** | Training is slow and done occasionally. Scoring must be fast and run on every reading. Keeping them separate keeps the API quick |
| **Cost-based evaluation** | A missed fault (the crane breaks) usually costs far more than a false alarm (a technician checks a healthy crane). The alert threshold is chosen to minimise total cost, not to maximise accuracy |
| **PostgreSQL** | Readings, scores and alerts are structured data that needs history queries, so a relational database fits |
| **Streamlit dashboard** | It gives a working live dashboard quickly in pure Python, so the time goes into the ML and the API, not front-end code |
| **Docker Compose** | The API, the database and the dashboard start with one command, on any machine |

---

## 6. Data: where it comes from and why

| Source | Status | Use |
|---|---|---|
| **Simulator** ([crane/sim.py](crane/sim.py)) | Built | Each simulated crane wears out over 30–120 days. Temperature and vibration rise as it wears, load and duty cycle vary, and short fault episodes (spikes in heat and vibration) are injected at random. One reading = one simulated operating hour, so a crane's whole life plays out in 12–48 minutes of a live demo |
| **NASA C-MAPSS** | Next step | A well-known run-to-failure dataset (turbofan engines), to validate the RUL pipeline on real degradation |
| **CWRU bearing data** | Next step | Real labelled bearing vibration data (healthy vs faulty), to check the anomaly features on real faults |

**How the simulator works (be ready to explain):**
- Wear goes from 0 (new) to 1 (failed) along a curve, `(age / lifetime) ^ shape`. Most damage shows late in life, as in real machines.
- Temperature = base + load effect + duty effect + 30 °C × wear + noise. Vibration grows with wear squared, so it rises sharply near the end.
- Because the true remaining life is known for every reading, RUL error and "caught before failure" can be measured exactly.

**Be upfront about this:** there is no public run-to-failure dataset for cranes, and the current results come from the simulator. That proves the pipeline works end to end, but not how it would perform on a real crane. C-MAPSS and CWRU come from other machines, yet they show the same physics of wear, which makes them the next validation step.

---

## 7. Competition: who already does this?

Predictive maintenance is an established market. Know the main players:

**Crane makers' own monitoring**
- **Konecranes TRUCONNECT**: remote monitoring and condition data for Konecranes equipment
- **Liebherr** and other crane makers offer fleet telematics for their own machines

**Industrial asset-management platforms**
- **IBM Maximo Application Suite** (Monitor / Health / Predict)
- **Siemens Insights Hub** (formerly MindSphere)
- **GE Vernova Asset Performance Management** (formerly GE Digital APM / Predix)
- **AVEVA** and **Aspen Technology**: asset performance management for process industries

**Condition-monitoring specialists**
- **Augury**: AI machine health from vibration sensors
- **SKF**: bearing condition monitoring
- **Uptake**: predictive analytics for heavy equipment fleets

**Cloud building blocks**
- **Azure IoT**, **AWS IoT** with SageMaker: tools for building your own system (AWS retired its ready-made Lookout for Equipment service)

### How this project differs

Don't claim it beats these products. It is a portfolio project, not a commercial competitor. The honest positioning:

| Commercial platforms | This project |
|---|---|
| Often tied to one maker's equipment or a large vendor setup | Open, works with any client that can send an HTTP request |
| Expensive licences, long rollouts | Lightweight, runs with one `docker compose up` |
| Models are a black box | Every step is visible: features, models, thresholds |
| Accuracy is the headline number | Judged on business cost: missed faults, false alarms, downtime avoided |

**What to say:** "Big vendors solve this at enterprise scale. I built the core of such a system end to end, from ingestion and validation through real-time features and ML scoring to alerts and a dashboard, so I understand every piece and the trade-offs between them."

---

## 8. How success is measured

Measured by `python -m crane.train` on 20 simulated cranes the models never saw (28,780 readings), plus a live run of the API:

| Metric | Result | How to say it |
|---|---|---|
| Missed-fault rate | 2.1% of faulty readings | "It almost never misses a fault" |
| False-alarm rate | 13.9% of healthy readings | "That's the price of missing almost nothing, and the 3-in-a-row alert rule filters most of it" |
| Fault episodes alerted | 91 / 92 | |
| False alerts | ~3.5 per 1,000 healthy crane-hours (about 1 per crane every 12 days); about half of all alerts | Be honest: half the alerts are false at a 10:1 cost ratio, and the ratio is a single setting |
| RUL error | MAE 9.9 days (RUL capped at 60) | "Accurate enough to plan a service week, not a service hour" |
| Failures caught before breakdown | 20 / 20 | Each crane was serviced with about 6 days of life left |
| Downtime | 60 days reactive vs 10 days predictive = **83% avoided** | Assumes 3 days per breakdown, 0.5 days per planned service |
| Model scoring time | ~6 ms per reading | |
| End-to-end latency | p50 16 ms, p95 17 ms (PostgreSQL) | Far below the 1-second upload interval |
| Capacity | ~50–65 readings/s per API process | "One process handles a 50-crane site; beyond that, Redis plus more workers" |

Always add: *"These are on simulated data, so they show the system works, not how accurate it would be on real cranes."*

---

## 9. Likely interview questions

**Q: Why not just set fixed thresholds, like "alert if temperature > 90 °C"?**
Fixed thresholds miss combinations. A temperature that is fine at full load is suspicious at no load. Trends also matter: a slow climb is a warning long before a limit is crossed. The models learn these patterns; fixed thresholds can't.

**Q: How do you handle false alarms?**
Each alert threshold is set from the cost trade-off, not left at a default. Alerts can also require the anomaly to persist over several readings before they fire, which filters one-off sensor noise.

**Q: What happens with bad or missing sensor data?**
Pydantic rejects readings with wrong types, missing fields or out-of-range values before they reach the models, and the client gets a clear error.

**Q: How would you scale this to thousands of cranes?**
The per-machine windows currently live in API memory, which works for a single process. To scale out, move the window state to Redis, put a message queue (Kafka) in front of the scoring step, run several API workers behind a load balancer, and move readings to a time-series database such as TimescaleDB.

**Q: How do the models stay accurate over time?**
Every reading and result is stored, so models can be retrained on new data. Watching for drift (feature distributions moving away from the training data) shows when retraining is needed.

**Q: Why XGBoost instead of deep learning?**
On tabular, engineered features XGBoost is usually as good or better, much faster, and easier to explain to a maintenance engineer. An LSTM is only kept if it measurably improves results.

**Q: Your data isn't from cranes. Is that a problem?**
It's a known limitation, and I'd say so. The pipeline doesn't depend on the dataset. Wear shows up the same way in the signals (trends, vibration patterns), and the system is built to be retrained on real crane data.

**Q: What was the hardest part?**
Three real problems came up while building it:
1. **Latency.** The first version took ~56 ms just to score a reading. Timing each step showed Isolation Forest costs about 0.1 ms per tree for a single row, so 200 trees took ~22 ms. Halving to 100 trees halved the cost and barely changed accuracy. Then load testing on PostgreSQL showed throughput stuck at 23 readings/s whether 1 or 4 clients were sending. Profiling found scikit-learn's `score_samples` spends about 50 ms of Python overhead on each single reading, and Python's GIL serialises it. The fix was to precompute each tree's leaf scores at training time and score with fast lookups, with an assertion in training that the result matches scikit-learn exactly. Scoring went from ~25 ms to ~6 ms and throughput to ~55 readings/s, with identical model output. Lesson: measure before optimising, since the feature code (0.14 ms) was never the problem.
2. **False anomalies on new machines.** The first reading from every new crane was flagged as an anomaly. With only one reading in the window, spread and trend are zero, which looks nothing like training data. Every machine would have raised a false alert after each API restart. The fix: the anomaly model only judges full 30-reading windows, both in training and online, with a test that locks this in.
3. **Alert flapping.** A condition that flickers on and off would raise and clear alerts constantly. Alerts now need 3 readings in a row to raise and 3 clear readings to clear (hysteresis).

**Q: How do you know the system actually helps?**
The training script replays unseen cranes from new to failure under both policies. Reactive means every crane breaks down (3 days down). Predictive means a crane is serviced when a "service due" alert fires (0.5 days down). All 20 were caught before failure, cutting downtime by 83%.

---

## 10. Limitations and next steps

- Models are trained on simulated data only; C-MAPSS / CWRU replay is next, and real crane data after that
- About half of the anomaly alerts are false at the current 10:1 cost setting
- Sliding windows are held in memory, so one API instance only (Redis for scale-out)
- No authentication on upload routes yet (needed before real deployment)
- Health score is a simple heuristic (RUL share, halved while anomalous)
- Next: WebSocket live updates, drift monitoring, automated retraining, maintenance work-order integration
