import os
import json
import math
from sqlalchemy import create_engine, event, text, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta

# Anchored to this file, not the process cwd. A cwd-relative "./orchestrator.db"
# silently pointed at a *different* database whenever the backend was launched
# from anywhere but backend/ — and raised "unable to open database file" when
# that cwd wasn't writable, which surfaced as a phantom agent error. Overridable
# with ORCHESTRATOR_DB for tests or a relocated data dir.
DB_PATH = os.getenv("ORCHESTRATOR_DB") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "orchestrator.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30}
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """Make concurrent writers survive each other.

    Four things write this file: the FastAPI request handlers, the APScheduler
    jobs, the 10-minute risk check, and an 8-worker thread pool inside the
    agents. In SQLite's default rollback-journal mode a reader blocks a writer
    outright, and with no busy timeout the loser raises immediately instead of
    waiting — which is how 109 of 619 Technologia runs died on their final
    `UPDATE agent_data`. The signals were computed and then thrown away at the
    last step, and the run still recorded status=idle.

    WAL lets readers and one writer proceed concurrently; busy_timeout makes a
    contended write wait its turn rather than discarding a completed run.
    """
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class AgentData(Base):
    __tablename__ = "agent_data"
    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String, index=True)
    key = Column(String, index=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemLog(Base):
    __tablename__ = "system_logs"
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, index=True)
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


# ── Orchestrator history (durable across restarts) ───────────────────────────
class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    message = Column(Text)
    color = Column(String)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(Integer, primary_key=True)
    agent_id = Column(String, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String)           # idle | error
    error = Column(Text, nullable=True)
    # Per-run telemetry, aggregated by tracing.py while the run is open
    llm_calls = Column(Integer, default=0)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    llm_ms = Column(Integer, default=0)
    stages = Column(Text, nullable=True)   # JSON {stage_name: ms}


class AgentState(Base):
    __tablename__ = "agent_state"
    agent_id = Column(String, primary_key=True)
    restarts = Column(Integer, default=0)
    last_run = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)


class Config(Base):
    """Simple key/value store for user-editable settings (schedules, recipient, etc.)."""
    __tablename__ = "config"
    key = Column(String, primary_key=True)
    value = Column(Text)


class Approval(Base):
    """Human-in-the-loop approval queue: agents park an action here instead of
    executing it; the user approves/denies from the dashboard or API."""
    __tablename__ = "approvals"
    id = Column(Integer, primary_key=True)
    agent_id = Column(String, index=True)
    kind = Column(String, index=True)         # e.g. "send_email"
    title = Column(Text)
    payload = Column(Text, nullable=True)     # JSON for the action handler
    status = Column(String, default="pending", index=True)  # pending | approved | denied
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    decided_at = Column(DateTime, nullable=True)


class Memory(Base):
    """Long-term agent memory, recalled by recency (no local embedding model
    in this stack). `embedding` is unused but kept as a nullable column so
    existing databases don't need a migration."""
    __tablename__ = "memories"
    id = Column(Integer, primary_key=True)
    agent_id = Column(String, index=True)
    kind = Column(String, index=True, default="note")
    text = Column(Text)
    meta = Column(Text, nullable=True)        # JSON dict
    embedding = Column(Text, nullable=True)   # unused; kept for schema compatibility
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# Columns added after a table already exists on disk — create_all() never
# ALTERs, so init_db() patches these in for pre-existing databases.
_NEW_COLUMNS = {
    "agent_runs": {
        "llm_calls": "INTEGER DEFAULT 0",
        "tokens_in": "INTEGER DEFAULT 0",
        "tokens_out": "INTEGER DEFAULT 0",
        "llm_ms": "INTEGER DEFAULT 0",
        "stages": "TEXT",
    },
}


def _ensure_columns(bind):
    from sqlalchemy import inspect, text
    insp = inspect(bind)
    with bind.connect() as conn:
        for table, cols in _NEW_COLUMNS.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
            conn.commit()


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_columns(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Config helpers ───────────────────────────────────────────────────────────
def get_config(key: str, default=None):
    db = SessionLocal()
    try:
        rec = db.query(Config).filter_by(key=key).first()
        if not rec:
            return default
        try:
            return json.loads(rec.value)
        except (json.JSONDecodeError, TypeError):
            return rec.value
    finally:
        db.close()


def set_config(key: str, value):
    db = SessionLocal()
    try:
        payload = value if isinstance(value, str) else json.dumps(value)
        rec = db.query(Config).filter_by(key=key).first()
        if rec:
            rec.value = payload
        else:
            db.add(Config(key=key, value=payload))
        db.commit()
    finally:
        db.close()


def delete_config(*keys: str) -> int:
    """Remove config rows outright. `set_config(key, None)` is NOT the same
    thing: it stores the JSON literal null, and get_config then returns None
    instead of the caller's default — so every `float(get_config(k, DEFAULT))`
    downstream raises on a key that was meant to be reset."""
    db = SessionLocal()
    try:
        n = db.query(Config).filter(Config.key.in_(keys)).delete(synchronize_session=False)
        db.commit()
        return n
    finally:
        db.close()


def delete_agent_data(agent_id: str, *keys: str) -> int:
    """Drop stored rows for an agent — named keys, or all of them when none are
    named. Used by the Alpha Wolf reset and by scripts/reset_trading.py."""
    db = SessionLocal()
    try:
        q = db.query(AgentData).filter_by(agent_name=agent_id)
        if keys:
            q = q.filter(AgentData.key.in_(keys))
        n = q.delete(synchronize_session=False)
        db.commit()
        return n
    finally:
        db.close()


def all_config() -> dict:
    db = SessionLocal()
    try:
        out = {}
        for rec in db.query(Config).all():
            try:
                out[rec.key] = json.loads(rec.value)
            except (json.JSONDecodeError, TypeError):
                out[rec.key] = rec.value
        return out
    finally:
        db.close()


def _sanitize_json_floats(obj):
    """Recursively replace NaN/Infinity with None. json.dumps() happily
    serializes float('nan') as the non-standard `NaN` token (allow_nan=True
    by default) and json.loads() reads it right back — but the FastAPI/
    Starlette response encoder rejects it (allow_nan=False), which 500s any
    endpoint that returns saved data containing one. LLM-generated JSON or
    a stray division can produce these upstream; this is the one place all
    agent output passes through before it's persisted."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize_json_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json_floats(v) for v in obj]
    return obj


# ── Agent data helpers (used by agents 9-12) ─────────────────────────────────
def save_agent_data(agent_id: str, data: dict):
    """Save agent output — each top-level key in data becomes a separate AgentData row.
    e.g. save_agent_data("morning_brief", {"brief": {...}}) → key="brief" row."""
    db = SessionLocal()
    try:
        for key, value in data.items():
            rec = db.query(AgentData).filter_by(agent_name=agent_id, key=key).first()
            payload = json.dumps(_sanitize_json_floats(value))
            if rec:
                rec.value = payload
                rec.updated_at = datetime.utcnow()
            else:
                db.add(AgentData(agent_name=agent_id, key=key, value=payload))
        db.commit()
    finally:
        db.close()


def get_agent_data(agent_id: str) -> dict:
    """Return all AgentData rows for agent_id as a dict keyed by row.key."""
    db = SessionLocal()
    try:
        records = db.query(AgentData).filter_by(agent_name=agent_id).all()
        result = {}
        for r in records:
            try:
                result[r.key] = json.loads(r.value)
            except (json.JSONDecodeError, TypeError):
                result[r.key] = r.value
        return result
    finally:
        db.close()


def prune_history(keep_events: int = 2000, keep_runs: int = 1000) -> dict:
    """Cap the append-only tables, and drop the orphaned telemetry table.

    `resource_samples` had 100,322 rows and is the bulk of a 13 MB database, but
    nothing in the codebase reads or writes it any more — it is left over from a
    removed feature, so it is dead weight rather than a live leak. `events` and
    `agent_runs` ARE still appended to on every tick and had no bound at all.

    Row caps rather than time windows: they keep the recent history that the UI
    actually renders regardless of how long the app sat idle.
    """
    out = {}
    db = SessionLocal()
    try:
        for name, model, keep in (("events", Event, keep_events),
                                  ("agent_runs", AgentRun, keep_runs)):
            total = db.query(model).count()
            if total <= keep:
                out[name] = 0
                continue
            # Delete by id below the cutoff — one statement, no row loading.
            ids = [r[0] for r in db.query(model.id).order_by(model.id.desc())
                   .limit(keep).all()]
            cutoff = min(ids) if ids else 0
            out[name] = db.query(model).filter(model.id < cutoff).delete(
                synchronize_session=False)
        db.commit()
        # Dead table: reclaim the space rather than carrying it forever.
        db.execute(text("DROP TABLE IF EXISTS resource_samples"))
        db.commit()
    finally:
        db.close()
    return out


def reap_stale_runs(max_age_hours: int = 6) -> int:
    """Close out runs a previous process abandoned, and report how many.

    A run row is opened at start and closed at finish, so a process that dies
    mid-run leaves it at status=running forever. 124 had piled up, which quietly
    corrupts every question worth asking of this table: the run history shows work
    still in flight, average durations are unusable, and a staleness check reads a
    dead run as a live one — so an agent that stopped producing looks busy rather
    than broken.
    """
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        stale = db.query(AgentRun).filter(
            AgentRun.status == "running",
            AgentRun.finished_at.is_(None),
            AgentRun.started_at < cutoff,
        ).all()
        for run in stale:
            run.status = "error"
            run.finished_at = run.started_at
            run.error = (run.error or "") + "abandoned — process exited before the run finished"
        db.commit()
        return len(stale)
    finally:
        db.close()
