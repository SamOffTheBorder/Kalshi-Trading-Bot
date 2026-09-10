from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from kalshi_bot.storage import PaperRun, PerpPaperEvent, PerpPaperPosition, create_all_tables


def test_perp_paper_storage_is_independent_from_binary_trades():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with Session(engine) as session:
        session.add(
            PaperRun(
                id="perp-run",
                domain="perp",
                mode="shadow",
                asset_ids=["BTC"],
                started_at=1,
                status="running",
                config_fingerprint="x",
            )
        )
        session.flush()
        position = PerpPaperPosition(
            paper_run_id="perp-run",
            asset_id="BTC",
            market_ticker="KXBTCPERP",
            signed_quantity=0.01,
            multiplier=1,
            entry_price=100_000,
            entry_ts=2,
        )
        session.add(position)
        session.flush()
        session.add(
            PerpPaperEvent(
                position_id=position.id,
                paper_run_id="perp-run",
                event_type="mark",
                observed_at=3,
                price=100_100,
                status="observed",
                quote_reference={"source": "kalshi"},
            )
        )
        session.commit()
        assert session.execute(select(PerpPaperPosition)).scalar_one().signed_quantity == 0.01
        assert session.execute(select(PerpPaperEvent)).scalar_one().event_type == "mark"
