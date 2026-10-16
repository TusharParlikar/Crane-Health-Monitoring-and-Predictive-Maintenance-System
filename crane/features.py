"""Features from a machine's sliding window. Same code offline (training) and online (API)."""
import numpy as np

SIGNALS = ["hoist_load", "motor_temp", "vibration", "duty_cycle"]
WINDOW = 30  # readings kept per machine

FEATURE_NAMES = (
    [f"{s}_last" for s in SIGNALS]
    + [f"{s}_mean" for s in SIGNALS]
    + [f"{s}_std" for s in SIGNALS]
    + [f"{s}_slope" for s in SIGNALS]
    + ["vibration_high_freq_ratio"]
)


def window_features(w):
    """w: (n, 4) array of recent readings, oldest first, columns in SIGNALS order."""
    w = np.asarray(w, dtype=float)
    t = np.arange(len(w)) - (len(w) - 1) / 2
    slope = t @ (w - w.mean(0)) / max(t @ t, 1.0)  # least-squares trend per step
    vib = w[:, 2] - w[:, 2].mean()
    power = np.abs(np.fft.rfft(vib)) ** 2
    high_ratio = power[len(power) // 2:].sum() / (power.sum() + 1e-9)  # share of energy in the upper half of the spectrum
    return np.concatenate([w[-1], w.mean(0), w.std(0), slope, [high_ratio]])
