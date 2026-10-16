"""Crane simulator: gradual wear towards failure plus short injected faults.

Used both to generate training data and to drive the live client, so the
models are evaluated on the same physics they are trained on.
"""
import numpy as np

DAYS_PER_STEP = 1 / 24  # one reading = one simulated operating hour
RATED_LOAD = 50.0       # tonnes
FAULT_RATE = 0.004      # chance per step that a fault episode starts


class Crane:
    def __init__(self, rng, life_used=0.0):
        self.rng = rng
        self.life_steps = int(rng.uniform(30, 120) / DAYS_PER_STEP)
        self.shape = rng.uniform(1.5, 3.0)  # higher = wear shows up later, then faster
        self.t = int(life_used * self.life_steps)
        self.fault_left = 0
        self.fault_temp = self.fault_vib = 0.0

    @property
    def wear(self):
        """0 = new, 1 = failed."""
        return min(self.t / self.life_steps, 1.0) ** self.shape

    @property
    def rul_days(self):
        return max(self.life_steps - self.t, 0) * DAYS_PER_STEP

    @property
    def failed(self):
        return self.t >= self.life_steps

    def step(self):
        """Advance one step. Returns ((hoist_load, motor_temp, vibration, duty_cycle), in_fault)."""
        r = self.rng
        if self.fault_left == 0 and r.random() < FAULT_RATE:
            self.fault_left = int(r.integers(5, 20))
            self.fault_temp, self.fault_vib = r.uniform(8, 20), r.uniform(3, 8)
        fault = self.fault_left > 0
        self.fault_left -= fault
        w = self.wear
        duty = float(np.clip(r.normal(55, 15), 5, 100))
        load = float(np.clip(r.normal(0.8 * RATED_LOAD * duty / 100, 5), 0, 1.1 * RATED_LOAD))
        temp = 30 + 0.5 * load + 0.1 * duty + 30 * w + r.normal(0, 1.5) + fault * self.fault_temp
        vib = max(1.5 + 0.03 * load + 8 * w**2 + r.normal(0, 0.3) + fault * self.fault_vib, 0.0)
        self.t += 1
        return (load, float(temp), float(vib), duty), fault


def run_to_failure(rng):
    """One crane from new to failure. Returns signals (n, 4), true RUL days, fault flags, wear."""
    c = Crane(rng)
    X, rul, fault, wear = [], [], [], []
    while not c.failed:
        rul.append(c.rul_days)
        wear.append(c.wear)
        x, f = c.step()
        X.append(x)
        fault.append(f)
    return np.array(X), np.array(rul), np.array(fault), np.array(wear)
