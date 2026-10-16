"""Simulated crane fleet: every machine uploads one reading per interval and the round trip is timed.

    python -m crane.client --machines 10                 # live demo, one reading per machine per second
    python -m crane.client --interval 0 --rounds 200     # throughput benchmark
"""
import argparse
import time
from datetime import datetime, timezone

import httpx
import numpy as np

from crane.features import SIGNALS
from crane.sim import Crane


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--machines", type=int, default=10)
    p.add_argument("--interval", type=float, default=1.0, help="seconds between rounds (0 = as fast as possible)")
    p.add_argument("--rounds", type=int, default=0, help="stop after this many rounds (0 = run forever)")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--prefix", default="crane", help="machine ID prefix; give parallel clients different ones")
    a = p.parse_args()

    rng = np.random.default_rng(a.seed)
    # Start machines at different ages so the fleet has a mix of healthy and worn cranes.
    fleet = {f"{a.prefix}-{i:02d}": Crane(rng, life_used=rng.uniform(0, 0.95)) for i in range(1, a.machines + 1)}
    latencies, sent, start, rnd = [], 0, time.perf_counter(), 0

    with httpx.Client(base_url=a.api, timeout=10) as http:
        try:
            while not a.rounds or rnd < a.rounds:
                tick = time.perf_counter()
                for mid, crane in fleet.items():
                    values, _ = crane.step()
                    body = {"machine_id": mid, "timestamp": datetime.now(timezone.utc).isoformat(),
                            **dict(zip(SIGNALS, values))}
                    t0 = time.perf_counter()
                    try:
                        http.post("/readings", json=body).raise_for_status()
                    except httpx.HTTPError as e:
                        print(f"{mid}: upload failed: {e}")
                        continue
                    latencies.append((time.perf_counter() - t0) * 1000)
                    sent += 1
                    if crane.failed:  # repaired and back in service
                        print(f"{mid} reached end of life; replacing")
                        fleet[mid] = Crane(rng)
                rnd += 1
                if rnd % 10 == 0 and latencies:
                    print(f"round {rnd}: {sent} readings, p50 {np.percentile(latencies, 50):.1f} ms, "
                          f"p95 {np.percentile(latencies, 95):.1f} ms")
                time.sleep(max(0.0, a.interval - (time.perf_counter() - tick)))
        except KeyboardInterrupt:
            pass

    elapsed = time.perf_counter() - start
    if latencies:
        print(f"\n{sent} readings in {elapsed:.1f} s = {sent / elapsed:.1f} readings/s; "
              f"latency p50 {np.percentile(latencies, 50):.1f} ms, p95 {np.percentile(latencies, 95):.1f} ms")


if __name__ == "__main__":
    main()
