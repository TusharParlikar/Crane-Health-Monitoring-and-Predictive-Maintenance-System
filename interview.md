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
