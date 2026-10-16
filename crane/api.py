"""Ingestion and query API.

    uvicorn crane.api:app --reload
"""
import csv
import io
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select, update

from crane.db import Alert, Base, Reading, Session, as_dict, engine
from crane.scoring import Scorer

MAX_BATCH = 10_000
MAX_CSV_BYTES = 5_000_000
scorer: Scorer


class ReadingIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    machine_id: str = Field(min_length=1, max_length=64, pattern=r"^[\w.-]+$")
    timestamp: datetime
    hoist_load: float = Field(ge=0, le=100, description="tonnes")
    motor_temp: float = Field(ge=-40, le=250, description="°C")
    vibration: float = Field(ge=0, le=100, description="mm/s RMS")
    duty_cycle: float = Field(ge=0, le=100, description="% of time under load")


class ScoreOut(BaseModel):
    machine_id: str
    timestamp: datetime
    anomaly: bool
    anomaly_score: float
    rul_days: float = Field(description="predicted days until service is needed")
    health: float = Field(description="0 (failing) to 100 (healthy)")
    alerts: list[str] = Field(description="alerts active for this machine")
    latency_ms: float


ALERT_MESSAGES = {
    "anomaly": "Unusual behaviour for several readings in a row",
    "service_due": "Service needed within {rul:.1f} days",
}


@asynccontextmanager
async def lifespan(app):
    global scorer
    Base.metadata.create_all(engine)
    scorer = Scorer(os.getenv("MODEL_PATH", "models/crane_models.joblib"))
    with Session() as db:  # resume alerts left active before a restart
        scorer.active = {(a.machine_id, a.kind) for a in db.scalars(select(Alert).where(Alert.cleared_at.is_(None)))}
    yield


app = FastAPI(title="Crane Health Monitoring API", lifespan=lifespan)


def ingest(readings):
    out = []
    with Session() as db:
        for r in readings:
            t0 = time.perf_counter()
            values = [r.hoist_load, r.motor_temp, r.vibration, r.duty_cycle]
            scores, events, active = scorer.score(r.machine_id, values)
            db.add(Reading(machine_id=r.machine_id, ts=r.timestamp, hoist_load=r.hoist_load, motor_temp=r.motor_temp,
                           vibration=r.vibration, duty_cycle=r.duty_cycle, **scores))
            for kind, raised in events:
                if raised:
                    msg = ALERT_MESSAGES[kind].format(rul=scores["rul_days"])
                    db.add(Alert(machine_id=r.machine_id, kind=kind, message=msg, raised_at=r.timestamp))
                else:
                    db.execute(update(Alert).where(Alert.machine_id == r.machine_id, Alert.kind == kind,
                                                   Alert.cleared_at.is_(None)).values(cleared_at=r.timestamp))
            out.append(ScoreOut(machine_id=r.machine_id, timestamp=r.timestamp, alerts=active,
                                latency_ms=round((time.perf_counter() - t0) * 1000, 2), **scores))
        db.commit()
    return out


@app.post("/readings", response_model=ScoreOut)
def upload_reading(reading: ReadingIn):
    """Score one reading and store it with its result."""
    return ingest([reading])[0]


@app.post("/readings/batch", response_model=list[ScoreOut])
def upload_batch(readings: Annotated[list[ReadingIn], Field(max_length=MAX_BATCH)]):
    """Score many readings in order (JSON array)."""
    return ingest(readings)


@app.post("/readings/csv", response_model=list[ScoreOut],
          openapi_extra={"requestBody": {"content": {"text/csv": {"schema": {"type": "string"}}}}})
async def upload_csv(request: Request):
    """Score a CSV file sent as the request body; the header row must match the reading fields."""
    body = await request.body()
    if len(body) > MAX_CSV_BYTES:
        raise HTTPException(413, f"CSV larger than {MAX_CSV_BYTES} bytes")
    try:
        rows = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
        readings = []
        for line, row in enumerate(rows, start=2):
            try:
                readings.append(ReadingIn.model_validate(row))
            except ValidationError as e:
                raise RequestValidationError([{**err, "loc": ("line", line, *err["loc"])} for err in e.errors()])
    except UnicodeDecodeError:
        raise HTTPException(400, "CSV must be UTF-8")
    if len(readings) > MAX_BATCH:
        raise HTTPException(413, f"More than {MAX_BATCH} rows")
    return await run_in_threadpool(ingest, readings)


@app.get("/fleet")
def fleet():
    """Latest state of every machine, most at-risk first."""
    with Session() as db:
        latest_ids = select(func.max(Reading.id)).group_by(Reading.machine_id)
        rows = db.scalars(select(Reading).where(Reading.id.in_(latest_ids)).order_by(Reading.health)).all()
        alerts = db.execute(select(Alert.machine_id, Alert.kind).where(Alert.cleared_at.is_(None))).all()
    active = {}
    for m, k in alerts:
        active.setdefault(m, []).append(k)
    return [{"rank": i, **as_dict(r), "alerts": sorted(active.get(r.machine_id, []))} for i, r in enumerate(rows, 1)]


@app.get("/machines/{machine_id}/readings")
def machine_history(machine_id: str, limit: int = Query(300, ge=1, le=5000)):
    """Most recent readings and scores for one machine, oldest first."""
    with Session() as db:
        rows = db.scalars(select(Reading).where(Reading.machine_id == machine_id)
                          .order_by(Reading.id.desc()).limit(limit)).all()
    if not rows:
        raise HTTPException(404, f"No readings for machine {machine_id}")
    return [as_dict(r) for r in reversed(rows)]


@app.get("/alerts")
def alerts(active: bool = False, machine_id: str | None = None, limit: int = Query(200, ge=1, le=5000)):
    """Alert history, newest first. `active=true` returns only alerts not yet cleared."""
    q = select(Alert).order_by(Alert.id.desc()).limit(limit)
    if active:
        q = q.where(Alert.cleared_at.is_(None))
    if machine_id:
        q = q.where(Alert.machine_id == machine_id)
    with Session() as db:
        return [as_dict(a) for a in db.scalars(q)]


@app.get("/health")
def health():
    return {"status": "ok"}
