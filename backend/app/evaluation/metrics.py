"""Pure-Python evaluation metrics; no external numerical dependencies."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class BinaryMetrics:
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float
    recall: float
    f1: float
    false_accept_rate: float
    false_reject_rate: float
    accuracy: float

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def binary_classification_metrics(
    y_true: Sequence[int | bool],
    y_pred: Sequence[int | bool],
) -> BinaryMetrics:
    """Calculate metrics with 1=True as the positive class.

    Here FAR is FP/(FP+TN), and FRR is FN/(FN+TP). For speaker verification,
    define `True` as genuine/accepted when using the function; for deepfake
    detection, define `True` as fake/detected. State the label convention in
    benchmark reports so FAR/FRR are not misinterpreted.
    """
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have the same length")
    if not y_true:
        raise ValueError("At least one labelled example is required")
    if any(value not in (0, 1, False, True) for value in list(y_true) + list(y_pred)):
        raise ValueError("Labels must be boolean or 0/1")

    tp = sum(bool(t) and bool(p) for t, p in zip(y_true, y_pred))
    fp = sum(not bool(t) and bool(p) for t, p in zip(y_true, y_pred))
    tn = sum(not bool(t) and not bool(p) for t, p in zip(y_true, y_pred))
    fn = sum(bool(t) and not bool(p) for t, p in zip(y_true, y_pred))
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = _ratio(2 * precision * recall, precision + recall)
    return BinaryMetrics(
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        false_accept_rate=_ratio(fp, fp + tn),
        false_reject_rate=_ratio(fn, fn + tp),
        accuracy=_ratio(tp + tn, len(y_true)),
    )


def verification_far_frr(
    genuine_scores: Sequence[float],
    impostor_scores: Sequence[float],
    threshold: float,
) -> dict[str, float]:
    """Compute FAR/FRR assuming larger scores indicate a stronger speaker match."""
    if not genuine_scores or not impostor_scores:
        raise ValueError("Provide at least one genuine and one impostor score")
    if any(not 0.0 <= float(score) <= 1.0 for score in list(genuine_scores) + list(impostor_scores)):
        raise ValueError("Scores must be between 0 and 1")
    far = sum(float(score) >= threshold for score in impostor_scores) / len(impostor_scores)
    frr = sum(float(score) < threshold for score in genuine_scores) / len(genuine_scores)
    return {"threshold": float(threshold), "far": far, "frr": frr}


def estimate_equal_error_rate(
    genuine_scores: Sequence[float], impostor_scores: Sequence[float]
) -> dict[str, float]:
    """Estimate EER by selecting the threshold where FAR and FRR are closest."""
    if not genuine_scores or not impostor_scores:
        raise ValueError("Provide at least one genuine and one impostor score")
    candidates = sorted({0.0, 1.0, *(float(v) for v in genuine_scores), *(float(v) for v in impostor_scores)})
    points = [verification_far_frr(genuine_scores, impostor_scores, t) for t in candidates]
    best = min(points, key=lambda point: abs(point["far"] - point["frr"]))
    eer = (best["far"] + best["frr"]) / 2.0
    return {"eer": eer, "threshold": best["threshold"], "far": best["far"], "frr": best["frr"]}
