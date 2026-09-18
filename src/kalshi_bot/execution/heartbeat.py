"""Durable foreground-runner liveness records."""

from __future__ import annotations

import socket
import time

from sqlalchemy.orm import Session

from kalshi_bot.storage import RunnerHeartbeat


def record_heartbeat(
    session: Session,
    *,
    runner_id: str,
    process_kind: str,
    pid: int | None,
    paper_run_id: str | None = None,
    status: str = "running",
    observed_at: int | None = None,
) -> RunnerHeartbeat:
    """Upsert the latest liveness evidence without inventing a process handle."""
    now = int(time.time()) if observed_at is None else observed_at
    row = session.get(RunnerHeartbeat, runner_id)
    if row is None:
        row = RunnerHeartbeat(
            runner_id=runner_id,
            paper_run_id=paper_run_id,
            process_kind=process_kind,
            pid=pid,
            host=socket.gethostname(),
            observed_at=now,
            available_at=int(time.time()),
            status=status,
        )
        session.add(row)
    else:
        row.paper_run_id = paper_run_id
        row.process_kind = process_kind
        row.pid = pid
        row.observed_at = now
        row.available_at = int(time.time())
        row.status = status
    return row
