"""Stateful, Home Assistant-independent pool filter recovery model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import math
from typing import Any

from .const import STATE_AWAITING_RESTART, STATE_NORMAL, STATE_RECOVERING

MAX_SAMPLES = 2048


def _iso(value: datetime) -> str:
    """Return a timezone-aware ISO timestamp."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse a stored timestamp."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _finite_pressure(value: float) -> float:
    """Validate and normalize a pressure sample."""
    pressure = float(value)
    if not math.isfinite(pressure) or pressure < 0:
        raise ValueError("pressure must be a finite, non-negative number")
    return pressure


@dataclass(slots=True)
class RecoverySample:
    """One down-sampled recovery observation."""

    elapsed_hours: float
    pressure: float

    def as_dict(self) -> dict[str, float]:
        """Serialize the sample."""
        return {
            "elapsed_hours": self.elapsed_hours,
            "pressure": self.pressure,
        }


@dataclass(slots=True)
class AnalyticsEngine:
    """Track one filter cycle and model manually marked bump recoveries."""

    offline_threshold: float = 2.0
    minimum_drop: float = 0.5
    sample_interval_seconds: int = 300
    state: str = STATE_NORMAL
    cycle_started_at: datetime | None = None
    bump_count: int = 0
    current_pressure: float | None = None
    pressure_before: float | None = None
    pressure_after: float | None = None
    bump_started_at: datetime | None = None
    recovery_started_at: datetime | None = None
    recovery_elapsed_hours: float | None = None
    last_recovery_hours: float | None = None
    tau_hours: float | None = None
    fit_quality: float | None = None
    saw_offline: bool = False
    samples: list[RecoverySample] = field(default_factory=list)

    def mark_bump(self, now: datetime, pressure: float) -> None:
        """Start watching for the pump-off and restart sequence of a bump."""
        pressure = _finite_pressure(pressure)
        self.state = STATE_AWAITING_RESTART
        self.bump_count += 1
        self.current_pressure = pressure
        self.pressure_before = pressure
        self.pressure_after = None
        self.bump_started_at = now
        self.recovery_started_at = None
        self.recovery_elapsed_hours = None
        self.last_recovery_hours = None
        self.tau_hours = None
        self.fit_quality = None
        self.saw_offline = pressure <= self.offline_threshold
        self.samples.clear()
        if self.cycle_started_at is None:
            self.cycle_started_at = now

    def mark_backwash(self, now: datetime, pressure: float | None = None) -> None:
        """Reset analytics for a new DE/filter cycle."""
        if pressure is not None:
            self.current_pressure = _finite_pressure(pressure)
        self.state = STATE_NORMAL
        self.cycle_started_at = now
        self.bump_count = 0
        self.pressure_before = None
        self.pressure_after = None
        self.bump_started_at = None
        self.recovery_started_at = None
        self.recovery_elapsed_hours = None
        self.last_recovery_hours = None
        self.tau_hours = None
        self.fit_quality = None
        self.saw_offline = False
        self.samples.clear()

    def handle_sample(self, now: datetime, pressure: float) -> bool:
        """Consume a pressure sample and return whether visible state changed."""
        pressure = _finite_pressure(pressure)
        changed = pressure != self.current_pressure
        self.current_pressure = pressure

        if self.cycle_started_at is None:
            self.cycle_started_at = now
            changed = True

        if self.state == STATE_AWAITING_RESTART:
            if pressure <= self.offline_threshold:
                if not self.saw_offline:
                    self.saw_offline = True
                    changed = True
                return changed

            if (
                self.saw_offline
                and self.pressure_before is not None
                and pressure <= self.pressure_before - self.minimum_drop
            ):
                self._start_recovery(now, pressure)
                return True
            return changed

        if self.state != STATE_RECOVERING:
            return changed

        if self.recovery_started_at is None or self.pressure_before is None:
            self.state = STATE_NORMAL
            return True

        elapsed = max(0.0, (now - self.recovery_started_at).total_seconds() / 3600)
        self.recovery_elapsed_hours = elapsed
        changed = True

        should_sample = not self.samples or (
            elapsed - self.samples[-1].elapsed_hours
            >= self.sample_interval_seconds / 3600
        )
        if should_sample:
            self._append_sample(elapsed, pressure)
            self._fit_recovery_model()

        if pressure >= self.pressure_before:
            if not should_sample:
                self._append_sample(elapsed, pressure)
                self._fit_recovery_model()
            self.last_recovery_hours = elapsed
            self.state = STATE_NORMAL

        return changed

    def _start_recovery(self, now: datetime, pressure: float) -> None:
        """Begin collecting recovery samples at the first post-offline pressure."""
        self.state = STATE_RECOVERING
        self.pressure_after = pressure
        self.recovery_started_at = now
        self.recovery_elapsed_hours = 0.0
        self.samples = [RecoverySample(0.0, pressure)]

    def _append_sample(self, elapsed_hours: float, pressure: float) -> None:
        """Append a sample while keeping storage bounded."""
        self.samples.append(RecoverySample(elapsed_hours, pressure))
        if len(self.samples) > MAX_SAMPLES:
            self.samples = [self.samples[0], *self.samples[-(MAX_SAMPLES - 1) :]]

    def _fit_recovery_model(self) -> None:
        """Fit P(t)=P_before-(P_before-P0)*exp(-t/tau)."""
        if self.pressure_before is None or self.pressure_after is None:
            return

        pressure_span = self.pressure_before - self.pressure_after
        if pressure_span <= 0:
            return

        points: list[tuple[float, float, float]] = []
        for sample in self.samples:
            remaining = self.pressure_before - sample.pressure
            if sample.elapsed_hours <= 0 or not 0 < remaining < pressure_span:
                continue
            log_ratio = math.log(remaining / pressure_span)
            points.append((sample.elapsed_hours, log_ratio, sample.pressure))

        if len(points) < 3:
            return

        denominator = sum(elapsed**2 for elapsed, _, _ in points)
        if denominator <= 0:
            return
        slope = (
            sum(elapsed * log_ratio for elapsed, log_ratio, _ in points)
            / denominator
        )
        if slope >= 0:
            return

        tau = -1.0 / slope
        if not math.isfinite(tau) or tau <= 0:
            return

        observed = [pressure for _, _, pressure in points]
        predicted = [
            self.pressure_before - pressure_span * math.exp(-elapsed / tau)
            for elapsed, _, _ in points
        ]
        mean_observed = sum(observed) / len(observed)
        total_variance = sum((value - mean_observed) ** 2 for value in observed)
        residual_variance = sum(
            (actual - expected) ** 2
            for actual, expected in zip(observed, predicted, strict=True)
        )

        self.tau_hours = round(tau, 3)
        self.fit_quality = (
            None
            if total_variance <= 0
            else round(max(0.0, min(1.0, 1 - residual_variance / total_variance)), 4)
        )

    @property
    def recovery_progress(self) -> float | None:
        """Return recovery progress from restart pressure to pre-bump pressure."""
        if (
            self.pressure_before is None
            or self.pressure_after is None
            or self.current_pressure is None
        ):
            return None
        span = self.pressure_before - self.pressure_after
        if span <= 0:
            return None
        progress = (self.current_pressure - self.pressure_after) / span * 100
        return round(max(0.0, min(100.0, progress)), 1)

    def cycle_age_hours(self, now: datetime) -> float | None:
        """Return the age of the current filter cycle."""
        if self.cycle_started_at is None:
            return None
        return round(
            max(0.0, (now - self.cycle_started_at).total_seconds() / 3600),
            2,
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize persistent engine state."""
        return {
            "state": self.state,
            "cycle_started_at": (
                _iso(self.cycle_started_at) if self.cycle_started_at else None
            ),
            "bump_count": self.bump_count,
            "current_pressure": self.current_pressure,
            "pressure_before": self.pressure_before,
            "pressure_after": self.pressure_after,
            "bump_started_at": (
                _iso(self.bump_started_at) if self.bump_started_at else None
            ),
            "recovery_started_at": (
                _iso(self.recovery_started_at) if self.recovery_started_at else None
            ),
            "recovery_elapsed_hours": self.recovery_elapsed_hours,
            "last_recovery_hours": self.last_recovery_hours,
            "tau_hours": self.tau_hours,
            "fit_quality": self.fit_quality,
            "saw_offline": self.saw_offline,
            "samples": [sample.as_dict() for sample in self.samples],
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        offline_threshold: float,
        minimum_drop: float,
        sample_interval_seconds: int,
    ) -> AnalyticsEngine:
        """Restore engine state, ignoring malformed optional fields."""
        valid_states = {STATE_NORMAL, STATE_AWAITING_RESTART, STATE_RECOVERING}
        state = data.get("state", STATE_NORMAL)
        if state not in valid_states:
            state = STATE_NORMAL

        samples: list[RecoverySample] = []
        for item in data.get("samples", [])[-MAX_SAMPLES:]:
            try:
                elapsed = float(item["elapsed_hours"])
                pressure = _finite_pressure(item["pressure"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(elapsed) and elapsed >= 0:
                samples.append(RecoverySample(elapsed, pressure))

        def optional_float(key: str) -> float | None:
            value = data.get(key)
            if value is None:
                return None
            try:
                converted = float(value)
            except (TypeError, ValueError):
                return None
            return converted if math.isfinite(converted) else None

        try:
            bump_count = max(0, int(data.get("bump_count", 0)))
        except (TypeError, ValueError):
            bump_count = 0

        return cls(
            offline_threshold=offline_threshold,
            minimum_drop=minimum_drop,
            sample_interval_seconds=sample_interval_seconds,
            state=state,
            cycle_started_at=_parse_datetime(data.get("cycle_started_at")),
            bump_count=bump_count,
            current_pressure=optional_float("current_pressure"),
            pressure_before=optional_float("pressure_before"),
            pressure_after=optional_float("pressure_after"),
            bump_started_at=_parse_datetime(data.get("bump_started_at")),
            recovery_started_at=_parse_datetime(data.get("recovery_started_at")),
            recovery_elapsed_hours=optional_float("recovery_elapsed_hours"),
            last_recovery_hours=optional_float("last_recovery_hours"),
            tau_hours=optional_float("tau_hours"),
            fit_quality=optional_float("fit_quality"),
            saw_offline=bool(data.get("saw_offline", False)),
            samples=samples,
        )
