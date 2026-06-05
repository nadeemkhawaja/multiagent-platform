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


def init_db():
    Base.metadata.create_all(bind=engine)


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
