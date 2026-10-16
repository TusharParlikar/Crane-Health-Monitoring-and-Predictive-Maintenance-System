"""Train the anomaly and RUL models offline and evaluate them in business terms.

    python -m crane.train  # writes models/crane_models.joblib and models/report.json
"""
import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from xgboost import XGBRegressor

from crane.features import FEATURE_NAMES, WINDOW, window_features
from crane.scoring import anomaly_score, iforest_tables
from crane.sim import DAYS_PER_STEP, run_to_failure

RUL_CAP = 60.0      # days; a 30-hour window can't tell 60 days from 100, so targets are clipped
SERVICE_DAYS = 7.0  # "service due" when predicted RUL drops below this
PERSIST = 3         # consecutive readings a condition must hold before an alert is raised or cleared
WORN = 0.7          # wear above this counts as a fault the anomaly model should catch

# Business costs: edit these to match the site.
COST_FALSE_ALARM = 1.0    # relative cost of flagging one healthy reading
COST_MISSED_FAULT = 10.0  # relative cost of missing one faulty reading
PLANNED_DOWNTIME = 0.5    # days lost to a planned service
UNPLANNED_DOWNTIME = 3.0  # days lost to a breakdown (emergency repair, spares, secondary damage)


def featurize(sig):
    return np.array([window_features(sig[max(0, i - WINDOW + 1): i + 1]) for i in range(len(sig))])


def stack(runs, feats):
    """Returns features, true RUL, fault label, and whether the window is full (the anomaly model only judges full ones)."""
    rul, fault, wear = (np.concatenate([r[k] for r in runs]) for k in (1, 2, 3))
    full = np.concatenate([np.arange(len(r[0])) >= WINDOW - 1 for r in runs])
    return np.concatenate(feats), rul, fault | (wear > WORN), full


def pick_threshold(scores, is_fault):
    """Anomaly threshold that minimises the total cost of false alarms and missed faults."""
    candidates = np.quantile(scores, np.linspace(0.5, 0.999, 300))
    cost = [COST_FALSE_ALARM * np.sum((scores > t) & ~is_fault) + COST_MISSED_FAULT * np.sum((scores <= t) & is_fault)
            for t in candidates]
    return float(candidates[int(np.argmin(cost))])


def service_trigger(rul_pred):
    """Index where the predictive policy calls a service (PERSIST readings below SERVICE_DAYS), or None."""
    streak = 0
    for i, due in enumerate(rul_pred < SERVICE_DAYS):
        streak = streak + 1 if due else 0
        if streak >= PERSIST:
            return i
    return None


def alert_raises(flags):
    """Indices where an alert is raised: PERSIST flags in a row raise it, PERSIST clear ones clear it (as online)."""
    raises, streak, active = [], 0, False
    for i, on in enumerate(flags):
        streak = max(streak, 0) + 1 if on else min(streak, 0) - 1
        if streak >= PERSIST and not active:
            active = True
            raises.append(i)
        elif streak <= -PERSIST:
            active = False
    return raises


def train(n_runs=100, out="models/crane_models.joblib", seed=0):
    rng = np.random.default_rng(seed)
    runs = [run_to_failure(rng) for _ in range(n_runs)]
    n_tr, n_val = int(0.6 * n_runs), int(0.2 * n_runs)
    tr, val, test = runs[:n_tr], runs[n_tr:n_tr + n_val], runs[n_tr + n_val:]
    feats = [featurize(r[0]) for r in runs]
    f_tr, f_val, f_test = feats[:n_tr], feats[n_tr:n_tr + n_val], feats[n_tr + n_val:]

    X, rul, bad, full = stack(tr, f_tr)
    # 100 trees: single-reading scoring cost grows with tree count (~0.1 ms per tree)
    anomaly = IsolationForest(n_estimators=100, random_state=seed).fit(X[full & ~bad])  # learns "normal" only
    rul_model = XGBRegressor(n_estimators=400, max_depth=6, learning_rate=0.05, subsample=0.8,
                             colsample_bytree=0.8, random_state=seed).fit(X, np.minimum(rul, RUL_CAP))

    tables = iforest_tables(anomaly)
    Xv, _, bad_v, full_v = stack(val, f_val)
    assert np.allclose(anomaly_score(tables, Xv[:2000]), -anomaly.score_samples(Xv[:2000])),         "fast anomaly scoring no longer matches sklearn; check iforest_tables against this sklearn version"
    threshold = pick_threshold(-anomaly.score_samples(Xv[full_v]), bad_v[full_v])

    # Evaluate on runs the models have never seen.
    Xt, rul_t, bad_t, full_t = stack(test, f_test)
    flagged = -anomaly.score_samples(Xt[full_t]) > threshold
    bad_full = bad_t[full_t]
    pred = np.clip(rul_model.predict(Xt), 0, RUL_CAP)
    err = pred - np.minimum(rul_t, RUL_CAP)
    near = rul_t < 30

    caught, unused_life = 0, []
    for r, f in zip(test, f_test):
        i = service_trigger(np.clip(rul_model.predict(f), 0, RUL_CAP))
        if i is not None:
            caught += 1
            unused_life.append(r[1][i])
    true_alerts = false_alerts = 0
    for r, f in zip(test, f_test):
        flags = -anomaly.score_samples(f) > threshold
        flags[:WINDOW - 1] = False
        is_bad = r[2] | (r[3] > WORN)
        hits = is_bad[alert_raises(flags)]
        true_alerts, false_alerts = true_alerts + hits.sum(), false_alerts + (~hits).sum()
    healthy_hours = (~bad_t).sum() * DAYS_PER_STEP * 24

    reactive = len(test) * UNPLANNED_DOWNTIME
    predictive = caught * PLANNED_DOWNTIME + (len(test) - caught) * UNPLANNED_DOWNTIME

    booster = rul_model.get_booster()
    t0 = time.perf_counter()
    for i in range(200):  # the same per-reading work the API does
        f = window_features(test[0][0][i:i + WINDOW])[None]
        anomaly_score(tables, f), booster.inplace_predict(f)
    score_ms = (time.perf_counter() - t0) / 200 * 1000

    report = {
        "runs": {"train": len(tr), "validation": len(val), "test": len(test), "test_readings": len(Xt)},
        "anomaly": {
            "threshold": round(threshold, 4),
            "false_alarm_rate": round(float(flagged[~bad_full].mean()), 4),
            "missed_fault_rate": round(float((~flagged[bad_full]).mean()), 4),
            "alerts_raised_true": int(true_alerts),
            "alerts_raised_false": int(false_alerts),
            "false_alerts_per_1000_healthy_hours": round(1000 * float(false_alerts) / healthy_hours, 2),
        },
        "rul_days": {
            "mae": round(float(np.abs(err).mean()), 2),
            "rmse": round(float(np.sqrt((err ** 2).mean())), 2),
            "mae_last_30_days": round(float(np.abs(err[near]).mean()), 2),
        },
        "maintenance": {
            "failures": len(test),
            "caught_before_failure": caught,
            "mean_unused_life_days": round(float(np.mean(unused_life)), 2) if unused_life else None,
            "downtime_reactive_days": reactive,
            "downtime_predictive_days": predictive,
            "downtime_avoided_pct": round(100 * (1 - predictive / reactive), 1),
        },
        "scoring_ms_per_reading": round(score_ms, 2),
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"anomaly": anomaly, "anomaly_tables": tables, "rul": rul_model, "threshold": threshold, "rul_cap": RUL_CAP,
                 "service_days": SERVICE_DAYS, "persist": PERSIST, "features": FEATURE_NAMES}, out)
    out.with_name("report.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=int, default=100, help="simulated run-to-failure histories")
    p.add_argument("--out", default="models/crane_models.joblib")
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    print(json.dumps(train(a.runs, a.out, a.seed), indent=2))
