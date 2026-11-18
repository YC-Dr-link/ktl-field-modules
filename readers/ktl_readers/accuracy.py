"""Measure exact field accuracy and high-confidence errors on synthetic samples.

Run from the repository root with ``python -m ktl_readers.accuracy``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ktl_contract import ReadError

from . import get_reader

SYNTHETIC_ROOT = Path(__file__).resolve().parents[1] / "synthetic"
MIN_FIELD_ACCURACY = 0.90
MAX_HIGH_CONFIDENCE_ERROR_RATE = 0.01


@dataclass(frozen=True)
class Metrics:
    correct_fields: int
    expected_fields: int
    high_confidence_errors: int
    mismatches: tuple[str, ...]

    @property
    def accuracy(self) -> float:
        return self.correct_fields / self.expected_fields if self.expected_fields else 0.0

    @property
    def high_confidence_error_rate(self) -> float:
        return self.high_confidence_errors / self.expected_fields if self.expected_fields else 0.0


def evaluate(name: str) -> Metrics:
    reader = get_reader(name, fake_fallback=False)
    correct = expected = high_confidence_errors = 0
    mismatches: list[str] = []
    image_paths = sorted((SYNTHETIC_ROOT / name).glob("*.jpg"))
    if not image_paths:
        raise FileNotFoundError(f"합성 평가 이미지가 없습니다: {SYNTHETIC_ROOT / name}")

    for image_path in image_paths:
        answer_path = image_path.with_suffix(".json")
        truth = json.loads(answer_path.read_text(encoding="utf-8"))
        try:
            result = reader.read(str(image_path), truth["item"])
        except ReadError:
            result = None

        predicted = {value.key: value for value in result.values} if result is not None else {}
        for key, expected_value in truth["values"].items():
            expected += 1
            prediction = predicted.get(key)
            if prediction is None:
                mismatches.append(f"{image_path.name}:{key} expected={expected_value!r} got=<missing>")
                continue
            if prediction.value == expected_value:
                correct += 1
            else:
                mismatches.append(
                    f"{image_path.name}:{key} expected={expected_value!r} "
                    f"got={prediction.value!r} confidence={prediction.confidence:.3f}"
                )
                if prediction.confidence >= 0.8:
                    high_confidence_errors += 1

    return Metrics(correct, expected, high_confidence_errors, tuple(mismatches))


def main() -> int:
    results = {name: evaluate(name) for name in ("cert", "flowmeter")}
    all_correct = sum(result.correct_fields for result in results.values())
    all_expected = sum(result.expected_fields for result in results.values())
    all_high_errors = sum(result.high_confidence_errors for result in results.values())

    for name, result in results.items():
        print(
            f"{name}: field accuracy {result.correct_fields}/{result.expected_fields} "
            f"({result.accuracy:.1%}); incorrect confidence >= 0.8 "
            f"{result.high_confidence_errors}/{result.expected_fields} "
            f"({result.high_confidence_error_rate:.1%})"
        )
        for mismatch in result.mismatches:
            print(f"  mismatch: {mismatch}")
    overall_accuracy = all_correct / all_expected if all_expected else 0.0
    overall_high_error_rate = all_high_errors / all_expected if all_expected else 0.0
    print(
        f"overall: field accuracy {all_correct}/{all_expected} ({overall_accuracy:.1%}); "
        f"incorrect confidence >= 0.8 {all_high_errors}/{all_expected} "
        f"({overall_high_error_rate:.1%})"
    )

    passed = all(
        result.accuracy >= MIN_FIELD_ACCURACY
        and result.high_confidence_error_rate <= MAX_HIGH_CONFIDENCE_ERROR_RATE
        for result in results.values()
    )
    if not passed:
        print("FAIL: at least one reader does not meet the configured thresholds.")
        return 1
    print("PASS: both readers meet the configured thresholds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
