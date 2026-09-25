from __future__ import annotations

import os
from dataclasses import dataclass
from itertools import product


DIFFICULTY_ORDER = ("easy", "medium", "hard")
REGION_BUDGETS = {"easy": 500, "medium": 750, "hard": 1050}
DENSITY_TARGETS = {
    "easy": (300, 275, 325, 250, 350),
    "medium": (450, 425, 400, 375, 350),
    "hard": (650, 600, 550, 500, 450),
}
DEFAULT_MAX_ATTEMPTS = 5
MAX_ATTEMPTS_LIMIT = 5


@dataclass(frozen=True)
class OptionCandidate:
    difficulty: str
    attempt: int
    density_target: int
    region_count: int
    artifact_key: str
    reconstruction_delta_e_00: float = 0.0
    boundary_recall: float = 1.0
    selected_boundary_retention: float = 1.0


def option_max_attempts() -> int:
    raw = os.getenv("PBN_OPTION_MAX_ATTEMPTS", str(DEFAULT_MAX_ATTEMPTS)).strip()
    try:
        requested = int(raw)
    except ValueError:
        requested = DEFAULT_MAX_ATTEMPTS
    return max(1, min(MAX_ATTEMPTS_LIMIT, requested))


def density_target(difficulty: str, attempt: int) -> int:
    return DENSITY_TARGETS[difficulty][attempt]


def coordinated_density_ceiling(
    difficulty: str,
    nominal_target: int,
    candidates: list[OptionCandidate],
    medium_observations: list[tuple[int, int]] | None = None,
) -> int:
    """Bracket the Medium compaction input needed for a 10%-distinct final count."""
    if difficulty != "medium":
        return nominal_target
    hard_counts = [item.region_count for item in candidates if item.difficulty == "hard"]
    if not hard_counts:
        return nominal_target
    maximum_distinct_medium = max(hard_counts) * 10 // 11
    observations = list(medium_observations or [])
    too_dense = [ceiling for ceiling, actual in observations if actual > maximum_distinct_medium]
    within_ceiling = [ceiling for ceiling, actual in observations if actual <= maximum_distinct_medium]
    if too_dense and within_ceiling:
        lower_input = max(within_ceiling)
        upper_input = min(too_dense)
        if lower_input < upper_input:
            return max(1, min(nominal_target, (lower_input + upper_input) // 2))
    return max(1, min(nominal_target, maximum_distinct_medium))


def select_option_candidates(candidates: list[OptionCandidate]) -> list[OptionCandidate]:
    by_difficulty = {
        difficulty: [item for item in candidates if item.difficulty == difficulty]
        for difficulty in DIFFICULTY_ORDER
    }
    best: tuple[tuple[int, ...], list[OptionCandidate]] | None = None
    choices = [by_difficulty[difficulty] + [None] for difficulty in DIFFICULTY_ORDER]
    for combination in product(*choices):
        selected = [item for item in combination if item is not None]
        if not selected or not _is_distinct(selected) or not _is_fidelity_ordered(selected):
            continue
        rank = _selection_rank(selected)
        if best is None or rank > best[0]:
            best = rank, selected
    if best is None:
        return []
    return sorted(best[1], key=lambda item: DIFFICULTY_ORDER.index(item.difficulty))


def has_complete_triplet(candidates: list[OptionCandidate]) -> bool:
    return len(select_option_candidates(candidates)) == len(DIFFICULTY_ORDER)


def has_optimal_triplet(candidates: list[OptionCandidate]) -> bool:
    selected = select_option_candidates(candidates)
    return len(selected) == len(DIFFICULTY_ORDER) and all(item.attempt == 1 for item in selected)


def _is_distinct(selected: list[OptionCandidate]) -> bool:
    ordered = sorted(selected, key=lambda item: DIFFICULTY_ORDER.index(item.difficulty))
    previous: int | None = None
    for item in ordered:
        if previous is not None and item.region_count * 10 < previous * 11:
            return False
        previous = item.region_count
    return True


def _is_fidelity_ordered(selected: list[OptionCandidate]) -> bool:
    ordered = sorted(selected, key=lambda item: DIFFICULTY_ORDER.index(item.difficulty))
    previous: OptionCandidate | None = None
    for item in ordered:
        if previous is not None:
            if item.reconstruction_delta_e_00 > previous.reconstruction_delta_e_00 + 0.25 + 1e-9:
                return False
            if (
                previous.difficulty == "medium"
                and item.difficulty == "hard"
                and item.boundary_recall + 1e-9 < previous.boundary_recall
            ):
                return False
            if item.selected_boundary_retention + 1e-9 < previous.selected_boundary_retention:
                return False
        previous = item
    return True


def _selection_rank(selected: list[OptionCandidate]) -> tuple[int, ...]:
    values = {item.difficulty: item.region_count for item in selected}
    hard = _bounded_density_score(values.get("hard"), REGION_BUDGETS["hard"])
    medium = _bounded_density_score(values.get("medium"), REGION_BUDGETS["medium"])
    easy = values.get("easy")
    easy_closeness = -abs(easy - DENSITY_TARGETS["easy"][0]) if easy is not None else -10_000
    easy_lower_tie = -easy if easy is not None else -10_000
    presence = tuple(1 if difficulty in values else 0 for difficulty in reversed(DIFFICULTY_ORDER))
    attempts = -sum(item.attempt for item in selected)
    reconstruction = -int(round(sum(item.reconstruction_delta_e_00 for item in selected) * 1_000_000))
    return (len(selected), *presence, hard, medium, easy_closeness, easy_lower_tie, reconstruction, attempts)


def _bounded_density_score(region_count: int | None, budget: int) -> int:
    if region_count is None:
        return -10_000
    if region_count <= budget:
        return region_count
    return budget - (region_count - budget)
