import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from crane.features import SIGNALS, window_features
from crane.sim import Crane
from crane.train import train

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("crane")
    train(n_runs=15, out=tmp / "models.joblib")
    os.environ["MODEL_PATH"] = str(tmp / "models.joblib")
    # TEST_DATABASE_URL runs the suite against PostgreSQL; it must point to an empty database
    os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp / 'test.db'}")
    from fastapi.testclient import TestClient
    from crane.api import app
    with TestClient(app) as c:
        yield c


def reading(machine="m1", i=0, **over):
    r = {"machine_id": machine, "timestamp": (T0 + timedelta(seconds=i)).isoformat(),
         "hoist_load": 20.0, "motor_temp": 45.0, "vibration": 2.0, "duty_cycle": 50.0}
    return {**r, **over}


def test_slope_feature_tracks_trend():
    ramp = np.column_stack([np.arange(30.0)] * 4)
    f = window_features(ramp)
    assert np.allclose(f[12:16], 1.0)  # slope of each signal is 1 per step


def test_reading_is_scored(client):
    r = client.post("/readings", json=reading())
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["health"] <= 100 and body["rul_days"] >= 0 and isinstance(body["anomaly"], bool)


def test_no_anomaly_while_window_fills(client):
    for i in range(29):  # WINDOW - 1 readings: too few to judge
        assert client.post("/readings", json=reading("fresh", i)).json()["anomaly"] is False


@pytest.mark.parametrize("bad", [
    {"hoist_load": -1}, {"duty_cycle": 101}, {"vibration": "loud"}, {"machine_id": ""},
    {"machine_id": "a b"}, {"extra": 1}, {"timestamp": "yesterday"},
])
def test_invalid_reading_rejected(client, bad):
    assert client.post("/readings", json=reading(**bad)).status_code == 422


def test_missing_field_rejected(client):
    r = reading()
    del r["motor_temp"]
    assert client.post("/readings", json=r).status_code == 422


def test_batch_and_csv(client):
    r = client.post("/readings/batch", json=[reading("m2", i) for i in range(5)])
    assert r.status_code == 200 and len(r.json()) == 5

    header = "machine_id,timestamp," + ",".join(SIGNALS)
    rows = [f"m3,{(T0 + timedelta(seconds=i)).isoformat()},20,45,2,50" for i in range(3)]
    r = client.post("/readings/csv", content="\n".join([header, *rows]), headers={"content-type": "text/csv"})
    assert r.status_code == 200 and len(r.json()) == 3

    r = client.post("/readings/csv", content=f"{header}\n{rows[0]}\nm3,{T0.isoformat()},-5,45,2,50",
                    headers={"content-type": "text/csv"})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][:2] == ["line", 3]


def test_worn_machine_ranks_first_and_alerts(client):
    rng = np.random.default_rng(1)
    cranes = {"new": Crane(rng, life_used=0.0), "worn": Crane(rng, life_used=0.98)}
    for i in range(30):
        for mid, c in cranes.items():
            values, _ = c.step()
            assert client.post("/readings", json=reading(mid, i, **dict(zip(SIGNALS, values)))).status_code == 200

    fleet = client.get("/fleet").json()
    ranked = [m["machine_id"] for m in fleet if m["machine_id"] in cranes]
    assert ranked == ["worn", "new"]
    worn = next(m for m in fleet if m["machine_id"] == "worn")
    assert "service_due" in worn["alerts"]
    assert any(a["machine_id"] == "worn" for a in client.get("/alerts", params={"active": True}).json())
    assert len(client.get("/machines/worn/readings").json()) == 30
    assert client.get("/machines/nope/readings").status_code == 404
