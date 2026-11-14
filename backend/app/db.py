"""SQLite run history (SQLModel).

Every POST /api/v1/analyze response is stored verbatim in `analysis_runs.response_json`, so
GET /api/v1/analyses/{id} returns exactly what the analyze call returned. The DB path comes from
DATABASE_URL (default sqlite:///./turnkey.db, resolved relative to backend/).
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Column, Text, literal_column
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, create_engine, select

from .config import settings
from .models import AnalysisSummary, AnalyzeResponse


class AnalysisRun(SQLModel, table=True):
    __tablename__ = "analysis_runs"

    id: str = Field(primary_key=True, max_length=32)  # uuid4 hex
    created_at: str = Field(index=True)  # ISO-8601 UTC, same string as AnalyzeResponse.created_at
    business_type: str
    business_label: str
    city: str
    state: str
    property_count: int
    top_property_id: str | None = None
    top_address: str | None = None
    response_json: str = Field(sa_column=Column(Text, nullable=False))


_engine: Engine | None = None
_engine_url: str | None = None


def get_engine() -> Engine:
    """Engine for settings.database_url (recreated if the URL changes, e.g. in tests)."""
    global _engine, _engine_url
    if _engine is None or _engine_url != settings.database_url:
        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        _engine = create_engine(settings.database_url, connect_args=connect_args)
        _engine_url = settings.database_url
    return _engine


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def save_run(response: AnalyzeResponse) -> None:
    top = response.results[0] if response.results else None
    run = AnalysisRun(
        id=response.analysis_id,
        created_at=response.created_at,
        business_type=response.business_type,
        business_label=response.requirements.business_label,
        city=response.requirements.city,
        state=response.requirements.state,
        property_count=len(response.results),
        top_property_id=top.property_id if top else None,
        top_address=top.address if top else None,
        response_json=response.model_dump_json(),
    )
    with Session(get_engine()) as session:
        session.add(run)
        session.commit()


def list_runs(limit: int = 20) -> list[AnalysisSummary]:
    with Session(get_engine()) as session:
        rows = session.exec(
            select(AnalysisRun)
            # rowid breaks ties between runs created in the same millisecond (SQLite).
            .order_by(AnalysisRun.created_at.desc(), literal_column("rowid").desc())
            .limit(limit)
        ).all()
    return [
        AnalysisSummary(
            analysis_id=r.id, created_at=r.created_at, business_type=r.business_type,
            business_label=r.business_label, city=r.city, state=r.state, property_count=r.property_count,
            top_property_id=r.top_property_id, top_address=r.top_address,
        )
        for r in rows
    ]


def get_run(analysis_id: str) -> dict[str, Any] | None:
    with Session(get_engine()) as session:
        run = session.get(AnalysisRun, analysis_id)
    return json.loads(run.response_json) if run else None
