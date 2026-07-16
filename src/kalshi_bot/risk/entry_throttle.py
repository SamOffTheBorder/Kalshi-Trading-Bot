"""Rolling-window entry cap per series — the episode/cluster guard.

Motivated directly by backtest run #4's audit trail: all 23 entries over a
67-day window fired inside one ~15-hour trending episode on a single series
(KXBTC), repeatedly fading the same move at adjacent strikes. Per-trade caps
(Kelly, max_position_pct) bound each position but nothing bounded the
*episode* — one bad day dominated the whole run.

This throttle caps how many entries a single series can accumulate within a
rolling time window. It is mode-agnostic: the backtest engine and the future
paper/live loops call the same object the same way.
"""

from __future__ import annotations

from collections import defaultdict, deque


class EntryThrottle:
    """Allows at most `max_entries` per series within a rolling `window_s` seconds."""

    def __init__(self, *, max_entries: int, window_s: int) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self.max_entries = max_entries
        self.window_s = window_s
        self._entries: dict[str, deque[int]] = defaultdict(deque)

    def _prune(self, series_ticker: str, now_ts: int) -> None:
        entries = self._entries[series_ticker]
        while entries and entries[0] <= now_ts - self.window_s:
            entries.popleft()

    def allows(self, series_ticker: str, now_ts: int) -> bool:
        """True if a new entry on this series is within the rolling cap."""
        self._prune(series_ticker, now_ts)
        return len(self._entries[series_ticker]) < self.max_entries

    def record_entry(self, series_ticker: str, now_ts: int) -> None:
        """Record a filled entry. Call only after the order actually fills."""
        self._entries[series_ticker].append(now_ts)

    def entries_in_window(self, series_ticker: str, now_ts: int) -> int:
        self._prune(series_ticker, now_ts)
        return len(self._entries[series_ticker])
