from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from kalshi_bot.execution.paper_audit import PaperAuditEnvelope
from kalshi_bot.storage import PaperAuditEvent, PaperRun, create_all_tables


def test_audit_envelope_and_storage_are_domain_neutral():
    envelope = PaperAuditEnvelope("run-1", "risk", "perp", "BTC", 100, "blocked", "stale_mark")
    assert envelope.as_dict()["reason"] == "stale_mark"
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as session:
        session.add(
            PaperRun(
                id="run-1",
                domain="perp",
                mode="shadow",
                asset_ids=["BTC"],
                started_at=1,
                status="running",
                config_fingerprint="x",
            )
        )
        session.add(PaperAuditEvent(**envelope.as_dict()))
        session.commit()
        assert session.execute(select(PaperAuditEvent)).scalar_one().domain == "perp"
