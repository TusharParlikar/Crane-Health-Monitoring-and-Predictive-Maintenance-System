"""Online scoring: per-machine sliding windows, the two models, health score and alert state."""
import threading
from collections import defaultdict, deque
from pathlib import Path

import joblib
import numpy as np

from crane.features import WINDOW, window_features


def iforest_tables(model):
    """Precompute each tree's leaf scores. sklearn's score_samples spends ~0.1 ms of Python overhead per tree
    on a single reading; plain leaf lookups take microseconds. Uses sklearn internals, so train.py checks the
    result against score_samples."""
    trees = [(est.tree_, feats, model._decision_path_lengths[i] + model._average_path_length_per_tree[i] - 1.0)
             for i, (est, feats) in enumerate(zip(model.estimators_, model.estimators_features_))]
    n = model._max_samples
    avg_depth = 2 * (np.log(n - 1) + np.euler_gamma) - 2 * (n - 1) / n  # expected depth of a random point
    return trees, len(trees) * avg_depth


def anomaly_score(tables, X):
    """Isolation Forest anomaly score (same as -score_samples): higher = more unusual."""
    trees, denom = tables
    X = np.asarray(X, dtype=np.float32)
    depth = sum(leaf[tree.apply(np.ascontiguousarray(X[:, feats]))] for tree, feats, leaf in trees)
    return 2.0 ** (-depth / denom)


class Scorer:
    def __init__(self, model_path):
        if not Path(model_path).exists():
            raise RuntimeError(f"No models at {model_path}. Train them first: python -m crane.train")
        b = joblib.load(model_path)
        self.anomaly, self.rul = b["anomaly_tables"], b["rul"].get_booster()
        self.threshold, self.rul_cap = b["threshold"], b["rul_cap"]
        self.service_days, self.persist = b["service_days"], b["persist"]
        # ponytail: windows live in process memory, so one API worker only; move them to Redis to scale out.
        # After a restart each window refills within WINDOW readings.
        self.windows = defaultdict(lambda: deque(maxlen=WINDOW))
        self.streaks = defaultdict(lambda: {"anomaly": 0, "service_due": 0})  # +n = on n times in a row, -n = off
        self.active = set()  # (machine_id, kind) alerts currently raised
        self.lock = threading.Lock()

    def score(self, machine_id, values):
        """Add one reading to the machine's window and score it.

        Returns (scores, events, active_kinds); events lists alert transitions as (kind, raised).
        """
        with self.lock:
            win = self.windows[machine_id]
            win.append(values)
            f = window_features(np.array(win))[None]
            a = float(anomaly_score(self.anomaly, f)[0])
            rul = float(np.clip(self.rul.inplace_predict(f)[0], 0, self.rul_cap))
            flagged = len(win) == WINDOW and a > self.threshold  # a part-filled window isn't judged
            # ponytail: simple heuristic (RUL share, halved while anomalous); calibrate against real failures
            health = 100 * rul / self.rul_cap * (0.5 if flagged else 1.0)

            # An alert is raised after `persist` readings in a row and cleared after `persist` clear ones,
            # so one noisy reading neither raises nor clears it.
            st, events = self.streaks[machine_id], []
            for kind, on in (("anomaly", flagged), ("service_due", rul < self.service_days)):
                st[kind] = max(st[kind], 0) + 1 if on else min(st[kind], 0) - 1
                key = (machine_id, kind)
                if st[kind] >= self.persist and key not in self.active:
                    self.active.add(key)
                    events.append((kind, True))
                elif st[kind] <= -self.persist and key in self.active:
                    self.active.discard(key)
                    events.append((kind, False))
            active = sorted(k for m, k in self.active if m == machine_id)

        scores = {"anomaly": flagged, "anomaly_score": round(a, 4), "rul_days": round(rul, 2), "health": round(health, 1)}
        return scores, events, active
