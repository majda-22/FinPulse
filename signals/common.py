from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import math
import re
from typing import Iterable, Mapping, Sequence

import numpy as np


TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9']+")


def clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def safe_float(value: object | None) -> float | None:
    if value is None:
        return None
    return float(value)


def safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator / denominator)


def cosine_similarity(vec1: Sequence[float], vec2: Sequence[float]) -> float:
    a = np.asarray(vec1, dtype=float)
    b = np.asarray(vec2, dtype=float)

    if a.ndim != 1 or b.ndim != 1:
        raise ValueError("cosine_similarity expects 1D vectors")
    if a.shape[0] != b.shape[0]:
        raise ValueError("cosine_similarity requires vectors with the same dimension")

    a_norm = float(np.linalg.norm(a))
    b_norm = float(np.linalg.norm(b))
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0

    similarity = float(np.dot(a, b) / (a_norm * b_norm))
    return max(-1.0, min(1.0, similarity))


def cosine_distance_01(vec1: Sequence[float], vec2: Sequence[float]) -> float:
    return clip01((1.0 - cosine_similarity(vec1, vec2)) / 2.0)


def cosine_similarity_01(vec1: Sequence[float], vec2: Sequence[float]) -> float:
    return clip01((1.0 + cosine_similarity(vec1, vec2)) / 2.0)


def mean_or_none(values: Iterable[float | None]) -> float | None:
    defined = [float(value) for value in values if value is not None]
    if not defined:
        return None
    return float(sum(defined) / len(defined))


def days_between(current: date | datetime, previous: date | datetime) -> int:
    current_date = current.date() if isinstance(current, datetime) else current
    previous_date = previous.date() if isinstance(previous, datetime) else previous
    return max((current_date - previous_date).days, 1)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def tfidf_cosine_similarity(text_a: str, text_b: str) -> float:
    return tfidf_cosine_similarity_many([text_a, text_b])[0][1]


def tfidf_cosine_similarity_many(texts: Sequence[str]) -> list[tuple[int, int, float]]:
    if len(texts) < 2:
        return []

    counters = [Counter(tokenize(text)) for text in texts]
    vocabulary = sorted({token for counter in counters for token in counter})
    if not vocabulary:
        return [(0, 1, 0.0)] if len(texts) == 2 else []

    doc_count = len(counters)
    idf = {
        token: math.log((1.0 + doc_count) / (1.0 + sum(1 for counter in counters if token in counter))) + 1.0
        for token in vocabulary
    }

    vectors: list[np.ndarray] = []
    for counter in counters:
        token_total = sum(counter.values())
        if token_total == 0:
            vectors.append(np.zeros(len(vocabulary), dtype=float))
            continue
        vectors.append(
            np.asarray(
                [
                    (counter[token] / token_total) * idf[token]
                    for token in vocabulary
                ],
                dtype=float,
            )
        )

    results: list[tuple[int, int, float]] = []
    for left_index in range(len(vectors)):
        for right_index in range(left_index + 1, len(vectors)):
            results.append(
                (
                    left_index,
                    right_index,
                    clip01(_cosine_similarity_from_arrays(vectors[left_index], vectors[right_index])),
                )
            )
    return results


def weighted_average(
    components: Mapping[str, float | None],
    weights: Mapping[str, float],
) -> tuple[float | None, dict[str, float]]:
    weighted_sum = 0.0
    total_weight = 0.0
    defined: dict[str, float] = {}

    for name, weight in weights.items():
        value = components.get(name)
        if value is None:
            continue
        weighted_sum += float(value) * float(weight)
        total_weight += float(weight)
        defined[name] = float(value)

    if total_weight == 0.0:
        return None, defined
    return clip01(weighted_sum / total_weight), defined


def coverage_ratio(
    components: Mapping[str, float | None],
    *,
    expected_count: int,
) -> float:
    if expected_count <= 0:
        return 0.0
    defined_count = sum(1 for value in components.values() if value is not None)
    return clip01(defined_count / expected_count)


def _cosine_similarity_from_arrays(a: np.ndarray, b: np.ndarray) -> float:
    a_norm = float(np.linalg.norm(a))
    b_norm = float(np.linalg.norm(b))
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0
    similarity = float(np.dot(a, b) / (a_norm * b_norm))
    return max(-1.0, min(1.0, similarity))

