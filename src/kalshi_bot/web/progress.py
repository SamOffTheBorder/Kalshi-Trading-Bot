"""Evidence-backed setup, collection, and testing progress for the dashboard."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from kalshi_bot.config.settings import Settings
from kalshi_bot.web import queries
from kalshi_bot.web.operations import Operation


@dataclass(frozen=True)
class ChecklistItem:
    key: str
    title: str
    status: str
    percent: float
    description: str
    evidence: str
    next_action: str | None = None
    data_collection: bool = False


@dataclass(frozen=True)
class ProgressStage:
    key: str
    title: str
    description: str
    percent: float
    items: list[ChecklistItem]


@dataclass(frozen=True)
class ProgressReport:
    overall_percent: float
    stages: list[ProgressStage]
    running_jobs: int
    attention_items: int


def _stage(key: str, title: str, description: str, items: list[ChecklistItem]) -> ProgressStage:
    percent = sum(item.percent for item in items) / len(items) if items else 0.0
    return ProgressStage(key, title, description, round(percent, 1), items)


def _job_item(
    jobs: list[Operation], *, name: str, title: str, description: str, next_action: str
) -> ChecklistItem:
    job = next((candidate for candidate in jobs if candidate.name == name), None)
    if job is None:
        return ChecklistItem(
            f"test-{name}",
            title,
            "not_started",
            0.0,
            description,
            "No result has been recorded in this dashboard session.",
            next_action,
        )
    if job.status == "running":
        return ChecklistItem(
            f"test-{name}",
            title,
            "running",
            50.0,
            description,
            f"Job {job.id} started {job.started_at}; it is still running.",
            "Wait for the result. This page can be refreshed safely.",
        )
    passed = job.status == "passed"
    return ChecklistItem(
        f"test-{name}",
        title,
        "complete" if passed else "attention",
        100.0,
        description,
        f"Job {job.id} {job.status} with exit code {job.exit_code}; finished {job.ended_at}.",
        None if passed else f"Open the saved output, fix the failures, then {next_action.lower()}",
    )


def build_progress_report(
    *,
    settings: Settings,
    root: Path,
    feeds: list[queries.FeedHealth],
    sampling: queries.SamplingQuality,
    readiness: queries.ValidationReadiness,
    validation: queries.ValidationStatus,
    backtest_runs: list[Any],
    paper_runs: list[queries.PaperRunSummary],
    jobs: list[Operation],
    capture_running: bool,
) -> ProgressReport:
    credentials_ready = bool(
        settings.kalshi_key_id is not None and settings.kalshi_private_key_path.exists()
    )
    launchers = ("start_dashboard.bat", "start_capture.bat", "start_paper_trading.bat")
    missing_launchers = [name for name in launchers if not (root / name).exists()]

    setup = _stage(
        "setup",
        "Setup",
        "Local configuration and safety prerequisites required before collection and testing.",
        [
            ChecklistItem(
                "setup-database",
                "Database schema",
                "complete",
                100.0,
                "The dashboard opened the configured database and created all additive tables.",
                f"Database path: {settings.db_path}",
            ),
            ChecklistItem(
                "setup-safe-mode",
                "Safe execution mode",
                "complete" if settings.paper_trading else "attention",
                100.0,
                "Paper mode prevents the dashboard test workflow from placing live orders.",
                "PAPER_TRADING is true (simulated fills only)."
                if settings.paper_trading
                else "PAPER_TRADING is false; this environment is configured for live execution.",
                None
                if settings.paper_trading
                else "Return PAPER_TRADING to true while building and testing.",
            ),
            ChecklistItem(
                "setup-credentials",
                "Kalshi data credentials",
                "complete" if credentials_ready else "attention",
                100.0 if credentials_ready else 0.0,
                "Authenticated capture requires both a key ID and a readable private-key file.",
                "Key ID is configured and the private-key file exists."
                if credentials_ready
                else "A key ID or private-key file is missing. Secret values are never displayed.",
                None
                if credentials_ready
                else "Add the missing Kalshi credential setting, then restart the dashboard.",
            ),
            ChecklistItem(
                "setup-registry",
                "Asset registry",
                "complete",
                100.0,
                "The validated registry defines which assets, domains, and lifecycle "
                "modes are supported.",
                f"{len(settings.crypto_registry)} configured crypto assets passed "
                "settings validation.",
            ),
            ChecklistItem(
                "setup-launchers",
                "One-click launchers",
                "complete" if not missing_launchers else "attention",
                100.0 if not missing_launchers else 0.0,
                "Dashboard, capture, and paper-trading launchers make the local "
                "workflow repeatable.",
                "All three launchers are present."
                if not missing_launchers
                else f"Missing: {', '.join(missing_launchers)}.",
                None if not missing_launchers else "Restore the missing launcher files.",
            ),
        ],
    )

    collection_items: list[ChecklistItem] = []
    live_feed_count = sum(feed.status == "live" for feed in feeds)
    externally_active = live_feed_count > 0
    collection_items.append(
        ChecklistItem(
            "collection-process",
            "Capture process",
            "running" if capture_running or externally_active else "attention",
            100.0 if capture_running else (75.0 if externally_active else 0.0),
            "Shows whether collection appears active. Fresh rows also count as evidence "
            "when capture was started outside this dashboard.",
            (
                "The dashboard-owned capture process is running."
                if capture_running
                else f"{live_feed_count} feed(s) are fresh, suggesting an external capture process."
                if externally_active
                else "No dashboard-owned process or fresh feed is visible."
            ),
            None
            if capture_running or externally_active
            else "Start all capture feeds from Data & capture.",
            True,
        )
    )
    for index, feed in enumerate(feeds):
        score = {"live": 100.0, "late": 60.0, "stale": 20.0, "empty": 0.0}[feed.status]
        state = (
            "complete"
            if feed.status == "live"
            else ("running" if feed.status == "late" else "attention")
        )
        age = "never" if feed.age_s is None else f"{feed.age_s:,} seconds ago"
        collection_items.append(
            ChecklistItem(
                f"collection-feed-{index}",
                feed.name,
                state,
                score,
                feed.detail,
                f"{feed.rows:,} rows across {feed.span_hours / 24:.2f} days; newest row was {age}.",
                None
                if feed.status == "live"
                else "Start or inspect capture and confirm new rows arrive at the "
                "expected cadence.",
                True,
            )
        )
    sampling_ok = bool(
        sampling.median_gap_s is not None
        and sampling.median_gap_s < 60
        and sampling.mean_per_window >= 2
    )
    collection_items.extend(
        [
            ChecklistItem(
                "collection-sampling",
                "Settlement-window sampling",
                "complete" if sampling_ok else "attention",
                100.0 if sampling_ok else (40.0 if sampling.median_gap_s is not None else 0.0),
                "KXBTC15M uses a 60-second BRTI average, so multiple observations per "
                "window are preferred.",
                f"Median gap: {sampling.median_gap_s or 'unavailable'} s; mean "
                f"samples/window: {sampling.mean_per_window:.2f}; gaps over 5 min: "
                f"{sampling.long_gaps}.",
                None
                if sampling_ok
                else "Reduce the capture interval and keep capture continuous until "
                "windows contain multiple readings.",
                True,
            ),
            ChecklistItem(
                "collection-validation-window",
                "Validation history window",
                "complete"
                if readiness.is_ready
                else "running"
                if readiness.brti_span_days > 0
                else "not_started",
                readiness.pct_complete,
                "Walk-forward validation needs a contiguous BRTI span matching the "
                "configured train, embargo, and test folds.",
                f"{readiness.brti_span_days:.2f} of {readiness.required_days:.2f} "
                f"required days captured; {readiness.overlap_days:.2f} days overlap "
                f"{readiness.markets_in_overlap:,} archived contracts.",
                None
                if readiness.is_ready
                else f"Keep collection running for about {readiness.days_remaining:.2f} "
                "more contiguous days.",
                True,
            ),
        ]
    )
    collection = _stage(
        "collection",
        "Data collection",
        "Live feed freshness, accumulated history, contract overlap, and settlement "
        "sampling quality.",
        collection_items,
    )

    completed_backtest = next((run for run in backtest_runs if run.status == "completed"), None)
    validation_executed = (
        validation.run_id is not None and validation.evidence_class == "validation"
    )
    validation_passed = validation.promotion_status == "passed"
    testing_items = [
        _job_item(
            jobs,
            name="tests",
            title="Automated unit/backtest suite",
            description="Runs the repository's non-integration regression suite and "
            "records its console output.",
            next_action="Run tests again from Operations.",
        ),
        _job_item(
            jobs,
            name="lint",
            title="Static code checks",
            description="Checks source and tests for import, syntax, style, and common "
            "correctness problems.",
            next_action="Run lint again from Operations.",
        ),
        ChecklistItem(
            "testing-backtest",
            "Recorded backtest",
            "complete" if completed_backtest else "not_started",
            100.0 if completed_backtest else 0.0,
            "A completed backtest proves the engine can consume stored data and persist metrics.",
            f"Latest completed run: #{completed_backtest.id} ({completed_backtest.strategy_name})."
            if completed_backtest
            else "No completed backtest is stored.",
            None
            if completed_backtest
            else "Run a backtest after enough aligned data is available.",
        ),
        ChecklistItem(
            "testing-validation",
            "Promotion validation",
            "complete"
            if validation_passed
            else "attention"
            if validation_executed
            else "not_started",
            100.0 if validation_executed else 0.0,
            "A validation-class run applies the out-of-sample promotion policy; "
            "execution and outcome are shown separately.",
            (
                f"Validation run #{validation.run_id} finished with promotion status "
                f"{validation.promotion_status}."
                if validation_executed
                else "No validation-class run is stored."
            ),
            None
            if validation_passed
            else (
                "Review the recorded failure reasons; a failed gate must not be treated "
                "as permission to trade."
                if validation_executed
                else "Finish the required data window, then run validation."
            ),
        ),
        ChecklistItem(
            "testing-paper",
            "Paper/shadow evidence",
            "complete" if paper_runs else "not_started",
            100.0 if paper_runs else 0.0,
            "A paper or shadow run exercises decisions, guards, and simulated fills "
            "without live orders.",
            f"{len(paper_runs)} recent paper/shadow run(s) are stored."
            if paper_runs
            else "No paper/shadow run evidence is stored.",
            None
            if paper_runs
            else "After validation, start a reviewed paper/shadow run and inspect its audit trail.",
        ),
    ]
    testing = _stage(
        "testing",
        "Testing & validation",
        "Executed checks and stored trading evidence. A completed failing check remains "
        "an attention item.",
        testing_items,
    )

    stages = [setup, collection, testing]
    all_items = [item for stage in stages for item in stage.items]
    return ProgressReport(
        overall_percent=round(sum(stage.percent for stage in stages) / len(stages), 1),
        stages=stages,
        running_jobs=sum(job.status == "running" for job in jobs),
        attention_items=sum(item.status == "attention" for item in all_items),
    )


def report_as_dict(report: ProgressReport) -> dict[str, Any]:
    return asdict(report)


__all__ = [
    "ChecklistItem",
    "ProgressReport",
    "ProgressStage",
    "build_progress_report",
    "report_as_dict",
]
