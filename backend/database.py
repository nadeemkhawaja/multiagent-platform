import os
import json
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./orchestrator.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
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
class ResourceSample(Base):
    __tablename__ = "resource_samples"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    cpu = Column(Float)
    ram = Column(Float)
    disk = Column(Float)
    gpu = Column(Float)
    threads = Column(Integer)


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
    """Long-term agent memory: text + optional embedding vector (JSON-encoded).
    Embeddings come from a local Ollama embed model; rows without one are still
    usable via recency-based recall."""
    __tablename__ = "memories"
    id = Column(Integer, primary_key=True)
    agent_id = Column(String, index=True)
    kind = Column(String, index=True, default="note")
    text = Column(Text)
    meta = Column(Text, nullable=True)        # JSON dict
    embedding = Column(Text, nullable=True)   # JSON list[float]
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


# ── Agent data helpers (used by agents 9-12) ─────────────────────────────────
def save_agent_data(agent_id: str, data: dict):
    """Save agent output — each top-level key in data becomes a separate AgentData row.
    e.g. save_agent_data("morning_brief", {"brief": {...}}) → key="brief" row."""
    db = SessionLocal()
    try:
        for key, value in data.items():
            rec = db.query(AgentData).filter_by(agent_name=agent_id, key=key).first()
            payload = json.dumps(value)
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
