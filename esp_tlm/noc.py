from __future__ import annotations

from collections import defaultdict

from .types import Transaction


class MeshNoC:
    """6x6 XY-routed mesh with independent per-plane link serialization."""

    def __init__(self, rows: int, cols: int, planes: int, hop_ns: float, bytes_per_ns: float):
        self.rows, self.cols, self.planes = rows, cols, planes
        self.hop_ns, self.bytes_per_ns = hop_ns, bytes_per_ns
        self.available: dict[tuple[int, int, int], float] = defaultdict(float)
        self.packets = self.bytes = 0
        self.total_busy_ns = self.max_wait_ns = 0.0

    def _xy_path(self, source: int, target: int) -> list[tuple[int, int]]:
        sr, sc = divmod(source, self.cols)
        tr, tc = divmod(target, self.cols)
        node, path = source, []
        step = 1 if tc >= sc else -1
        for _ in range(abs(tc - sc)):
            nxt = node + step
            path.append((node, nxt))
            node = nxt
        step = self.cols if tr >= sr else -self.cols
        for _ in range(abs(tr - sr)):
            nxt = node + step
            path.append((node, nxt))
            node = nxt
        return path

    def transport(self, tx: Transaction) -> tuple[float, float]:
        """Return (arrival time, added delay), annotating queuing and hop delays."""
        path = self._xy_path(tx.source, tx.target)
        if not path:
            return tx.earliest_ns, 0.0
        serial_ns = tx.bytes / self.bytes_per_ns
        now = tx.earliest_ns
        for edge in path:
            plane = min(range(self.planes), key=lambda p: self.available[(p, *edge)])
            key = (plane, *edge)
            start = max(now, self.available[key])
            self.max_wait_ns = max(self.max_wait_ns, start - now)
            finish = start + serial_ns + self.hop_ns
            self.available[key] = finish
            self.total_busy_ns += serial_ns
            now = finish
        self.packets += 1
        self.bytes += tx.bytes
        return now, now - tx.earliest_ns
