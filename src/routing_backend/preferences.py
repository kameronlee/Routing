"""User preference models and descriptor mapping."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable


@dataclass(frozen=True)
class Preference:
    """Weights used by the routing cost function.

    Larger weights increase the optimizer's desire to avoid the corresponding
    disutility. Scenicness is represented internally as ``1 - scenic_score``, so
    increasing ``weight_scenic`` favors more scenic streets.
    """

    weight_cool: float = 1.0
    weight_scenic: float = 0.45
    weight_quiet: float = 0.45
    weight_slope: float = 0.35
    weight_time: float = 0.20
    weight_distance: float = 0.15
    weight_shade: float = 1.0
    uncertainty_penalty: float = 0.15
    comfort_threshold: float = 26.0

    def with_overrides(self, **weights: float | None) -> "Preference":
        """Return a copy with non-``None`` fields overridden."""

        clean = {key: value for key, value in weights.items() if value is not None}
        return replace(self, **clean)


def default_preference() -> Preference:
    """Return the balanced default preference profile."""

    return Preference()


def preference_from_descriptors(descriptors: Iterable[str] | None) -> Preference:
    """Map high-level user descriptors into a default preference profile.

    This deterministic mapping is intentionally simple. Later it can be swapped
    for a trained hyper-network that predicts weights from free-text context.
    """

    pref = default_preference()
    if not descriptors:
        return pref

    normalized = {descriptor.strip().lower() for descriptor in descriptors}
    overrides: dict[str, float] = {}

    if normalized & {"heat sensitive", "avoid heat", "coolest", "shade", "shade seeker"}:
        overrides["weight_cool"] = max(pref.weight_cool, 1.8)
        overrides["comfort_threshold"] = min(pref.comfort_threshold, 24.5)
    if normalized & {"noise averse", "quiet", "quietest", "low noise"}:
        overrides["weight_quiet"] = max(pref.weight_quiet, 1.5)
    if normalized & {"scenic", "green", "greenery", "pleasant", "park lover"}:
        overrides["weight_scenic"] = max(pref.weight_scenic, 1.3)
    if normalized & {"avoid hills", "mobility limited", "flat", "low slope"}:
        overrides["weight_slope"] = max(pref.weight_slope, 1.4)
    if normalized & {"in a hurry", "fast", "shortest", "commute"}:
        overrides["weight_time"] = max(pref.weight_time, 1.0)
        overrides["weight_distance"] = max(pref.weight_distance, 0.8)
    if normalized & {"explore", "relaxed", "wander"}:
        overrides["weight_time"] = min(pref.weight_time, 0.1)
        overrides["weight_distance"] = min(pref.weight_distance, 0.08)

    return pref.with_overrides(**overrides)
