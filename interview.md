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
