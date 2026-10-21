import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from app.ai.budget.config import BudgetConfig

PRECISION = 6


@dataclass(frozen=True)
class Reservation:
    request_id: str
    day: date
    amount_rub: float


class BudgetExhausted(Exception):
    def __init__(
        self, day: date, limit_rub: float, spent_rub: float, reserved_rub: float, requested_rub: float
    ):
        super().__init__(f"daily budget exhausted for {day.isoformat()}")
        self.day = day
        self.limit_rub = limit_rub
        self.spent_rub = spent_rub
        self.reserved_rub = reserved_rub
        self.requested_rub = requested_rub


class BudgetLedger:
    def __init__(
        self,
        config: BudgetConfig,
        path: Path | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.config = config
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._spent: dict[date, float] = {}
        self._reserved: dict[date, float] = {}
        self._exhausted: set[date] = set()
        self._load()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            day = date.fromisoformat(entry["day"])
            if entry["event"] == "exhausted":
                self._exhausted.add(day)
            else:
                self._spent[day] = self._spent.get(day, 0.0) + float(entry["cost_rub"])

    def _append(self, entry: dict) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def reserve(self, request_id: str, amount_rub: float) -> Reservation:
        with self._lock:
            day = self.config.day_of(self._clock())
            spent, reserved = self._spent.get(day, 0.0), self._reserved.get(day, 0.0)
            limit = self.config.daily_limit_rub
            if day in self._exhausted or round(spent + reserved + amount_rub, PRECISION) > limit:
                raise BudgetExhausted(day, limit, spent, reserved, amount_rub)
            self._reserved[day] = reserved + amount_rub
            return Reservation(request_id, day, amount_rub)

    def settle(
        self, reservation: Reservation, cost_rub: float, task: str, model_id: str, status: str
    ) -> None:
        with self._lock:
            day = reservation.day
            self._reserved[day] = max(0.0, self._reserved.get(day, 0.0) - reservation.amount_rub)
            self._spent[day] = self._spent.get(day, 0.0) + cost_rub
            self._append(
                {
                    "event": "settled",
                    "day": day.isoformat(),
                    "request_id": reservation.request_id,
                    "task": task,
                    "model_id": model_id,
                    "status": status,
                    "reserved_rub": round(reservation.amount_rub, PRECISION),
                    "cost_rub": round(cost_rub, PRECISION),
                    "at": self._clock().isoformat(),
                }
            )

    def mark_exhausted(self) -> None:
        with self._lock:
            now = self._clock()
            day = self.config.day_of(now)
            if day not in self._exhausted:
                self._exhausted.add(day)
                self._append({"event": "exhausted", "day": day.isoformat(), "at": now.isoformat()})

    def status(self) -> dict:
        with self._lock:
            day = self.config.day_of(self._clock())
            spent, reserved = self._spent.get(day, 0.0), self._reserved.get(day, 0.0)
            limit = self.config.daily_limit_rub
            exhausted = day in self._exhausted
            remaining = 0.0 if exhausted else max(0.0, limit - spent - reserved)
            return {
                "day": day.isoformat(),
                "limit_rub": limit,
                "spent_rub": round(spent, PRECISION),
                "reserved_rub": round(reserved, PRECISION),
                "remaining_rub": round(remaining, PRECISION),
                "exhausted": exhausted,
            }
