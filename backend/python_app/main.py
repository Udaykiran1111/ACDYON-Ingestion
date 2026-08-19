from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .ingestion import EmptySourceError, SourceBlockedError, SourceSchemaError, fetch_remoteok_detailed

ROOT = Path(__file__).parent
DB_PATH = Path(os.getenv("SQLITE_PATH", str(ROOT / "jobs.sqlite3")))
REVIEWER_TOKEN = os.getenv("REVIEWER_TOKEN", "local-reviewer-token")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Job Ingestion Control Room", lifespan=lifespan)
_allowed_origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins, allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["*"])



class RunResponse(BaseModel):
    run_id: str
    status: str


class SchedulePayload(BaseModel):
    cron: str = "0 * * * *"


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def init_db() -> None:
    with db() as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          source_id TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT NOT NULL,
          location TEXT NOT NULL, tags TEXT NOT NULL, source_url TEXT NOT NULL, ingested_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
          run_id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
          records_fetched INTEGER NOT NULL DEFAULT 0, records_parsed INTEGER NOT NULL DEFAULT 0,
          records_valid INTEGER NOT NULL DEFAULT 0, records_rejected INTEGER NOT NULL DEFAULT 0,
          records_inserted INTEGER NOT NULL DEFAULT 0, duplicate_count INTEGER NOT NULL DEFAULT 0,
          retry_count INTEGER NOT NULL DEFAULT 0, duration_ms INTEGER NOT NULL DEFAULT 0,
          error_code TEXT, error TEXT
        );
        CREATE TABLE IF NOT EXISTS progress (
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, phase TEXT NOT NULL,
          message TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schedules (
          name TEXT PRIMARY KEY, cron TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL
        );
        """)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        migrations = {
            "records_parsed": "ALTER TABLE runs ADD COLUMN records_parsed INTEGER NOT NULL DEFAULT 0",
            "records_valid": "ALTER TABLE runs ADD COLUMN records_valid INTEGER NOT NULL DEFAULT 0",
            "records_rejected": "ALTER TABLE runs ADD COLUMN records_rejected INTEGER NOT NULL DEFAULT 0",
            "duplicate_count": "ALTER TABLE runs ADD COLUMN duplicate_count INTEGER NOT NULL DEFAULT 0",
            "retry_count": "ALTER TABLE runs ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
            "duration_ms": "ALTER TABLE runs ADD COLUMN duration_ms INTEGER NOT NULL DEFAULT 0",
            "error_code": "ALTER TABLE runs ADD COLUMN error_code TEXT",
        }
        for name, statement in migrations.items():
            if name not in columns:
                connection.execute(statement)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_progress(run_id: str, phase: str, message: str) -> None:
    with db() as connection:
        connection.execute("INSERT INTO progress(run_id, phase, message, created_at) VALUES (?, ?, ?, ?)", (run_id, phase, message, now()))


def run_ingestion(run_id: str) -> None:
    started = now()
    started_at = datetime.now(timezone.utc)
    with db() as connection:
        connection.execute("INSERT INTO runs(run_id, status, started_at) VALUES (?, 'running', ?)", (run_id, started))
    add_progress(run_id, "started", "Run created")
    fetched = parsed = valid = rejected = duplicates = retries = inserted = 0
    error_code: str | None = None
    try:
        add_progress(run_id, "fetching", "Fetching the public RemoteOK feed")
        result = fetch_remoteok_detailed()
        fetched, parsed, valid, rejected, duplicates, retries = result.fetched, result.parsed, len(result.jobs), result.rejected, result.duplicate_count, result.retry_count
        add_progress(run_id, "parsed", f"Parsed {parsed}; valid {valid}; rejected {rejected}; duplicates {duplicates}")
        with db() as connection:
            for job in result.jobs:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO jobs(source_id, title, company, location, tags, source_url, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (job.source_id, job.title, job.company, job.location, json.dumps(job.tags), job.source_url, job.ingested_at),
                )
                inserted += cursor.rowcount
            status = "partial" if rejected else "success"
            duration = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
            connection.execute("UPDATE runs SET status=?, ended_at=?, records_fetched=?, records_parsed=?, records_valid=?, records_rejected=?, records_inserted=?, duplicate_count=?, retry_count=?, duration_ms=? WHERE run_id=?", (status, now(), fetched, parsed, valid, rejected, inserted, duplicates, retries, duration, run_id))
        add_progress(run_id, "completed", f"{status.title()}: {inserted} new listings inserted")
    except Exception as error:  # noqa: BLE001
        message = str(error)
        error_code = getattr(error, "code", "INGESTION_FAILED")
        status = "partial" if valid or rejected else "failed"
        duration = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        with db() as connection:
            connection.execute("UPDATE runs SET status=?, ended_at=?, records_fetched=?, records_parsed=?, records_valid=?, records_rejected=?, records_inserted=?, duplicate_count=?, retry_count=?, duration_ms=?, error_code=?, error=? WHERE run_id=?", (status, now(), fetched, parsed, valid, rejected, inserted, duplicates, retries, duration, error_code, message, run_id))
        add_progress(run_id, "failed", f"{error_code}: {message}")


def require_reviewer(token: str | None) -> None:
    if token != REVIEWER_TOKEN:
        raise HTTPException(status_code=403, detail="reviewer authorization required")


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return "<h1>Job Ingestion API</h1><p>Use the separate reviewer frontend for the dashboard.</p>"


@app.get("/api/dashboard")
def dashboard(x_reviewer_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_reviewer(x_reviewer_token)
    with db() as connection:
        jobs = [dict(row) | {"tags": json.loads(row["tags"])} for row in connection.execute("SELECT * FROM jobs ORDER BY ingested_at DESC LIMIT 100")]
        runs = [dict(row) for row in connection.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 20")]
    return {"jobs": jobs, "runs": runs, "latest": runs[0] if runs else None}


@app.get("/api/runs/{run_id}/progress")
def progress(run_id: str, x_reviewer_token: str | None = Header(default=None)) -> list[dict[str, Any]]:
    require_reviewer(x_reviewer_token)
    with db() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM progress WHERE run_id=? ORDER BY id", (run_id,))]


@app.post("/api/trigger", response_model=RunResponse)
def trigger(x_reviewer_token: str | None = Header(default=None)) -> RunResponse:
    require_reviewer(x_reviewer_token)
    run_id = uuid.uuid4().hex[:14]
    threading.Thread(target=run_ingestion, args=(run_id,), daemon=True).start()
    return RunResponse(run_id=run_id, status="running")


@app.get("/api/schedule")
def schedule_status(x_reviewer_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_reviewer(x_reviewer_token)
    with db() as connection:
        row = connection.execute("SELECT name, cron, enabled, updated_at FROM schedules WHERE name='remoteok' LIMIT 1").fetchone()
    return dict(row) if row else {"name": "remoteok", "cron": "0 * * * *", "enabled": 0, "updated_at": None}


@app.post("/api/schedule")
def schedule_create(payload: SchedulePayload, x_reviewer_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_reviewer(x_reviewer_token)
    with db() as connection:
        connection.execute("INSERT INTO schedules(name, cron, enabled, updated_at) VALUES ('remoteok', ?, 1, ?) ON CONFLICT(name) DO UPDATE SET cron=excluded.cron, enabled=1, updated_at=excluded.updated_at", (payload.cron, now()))
    return {"name": "remoteok", "cron": payload.cron, "enabled": 1}


@app.patch("/api/schedule/{action}")
def schedule_update(action: str, payload: SchedulePayload | None = None, x_reviewer_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_reviewer(x_reviewer_token)
    if action not in {"pause", "resume", "update"}:
        raise HTTPException(status_code=400, detail="action must be pause, resume, or update")
    with db() as connection:
        current = connection.execute("SELECT cron FROM schedules WHERE name='remoteok'").fetchone()
        cron = payload.cron if payload else (current["cron"] if current else "0 * * * *")
        enabled = 1 if action in {"resume", "update"} else 0
        connection.execute("INSERT INTO schedules(name, cron, enabled, updated_at) VALUES ('remoteok', ?, ?, ?) ON CONFLICT(name) DO UPDATE SET cron=excluded.cron, enabled=excluded.enabled, updated_at=excluded.updated_at", (cron, enabled, now()))
    return {"name": "remoteok", "cron": cron, "enabled": enabled}


@app.delete("/api/schedule")
def schedule_delete(x_reviewer_token: str | None = Header(default=None)) -> dict[str, bool]:
    require_reviewer(x_reviewer_token)
    with db() as connection:
        connection.execute("DELETE FROM schedules WHERE name='remoteok'")
    return {"deleted": True}


@app.post("/api/scheduled/ingestion")
def scheduled(x_cron_token: str | None = Header(default=None)) -> dict[str, Any]:
    if x_cron_token != REVIEWER_TOKEN:
        raise HTTPException(status_code=403, detail="cron authorization required")
    with db() as connection:
        schedule = connection.execute("SELECT enabled FROM schedules WHERE name='remoteok' LIMIT 1").fetchone()
    if not schedule or not schedule["enabled"]:
        return {"ok": True, "skipped": "schedule-disabled"}
    run_id = uuid.uuid4().hex[:14]
    run_ingestion(run_id)
    return {"ok": True, "run_id": run_id}
