"""Measure dust-reader field accuracy on the fictional synthetic dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ktl_contract import ReadError

from . import get_reader

SYNTHETIC_ROOT = Path(__file__).resolve().parents[1] / "synthetic" / "dust"
MIN_FIELD_ACCURACY = 0.85


@dataclass(frozen=True)
class Metrics:
    correct_fields: int
    expected_fields: int
    by_model: dict[str, tuple[int, int]]

    @property
    def accuracy(self) -> float:
        return self.correct_fields / self.expected_fields if self.expected_fields else 0.0


def evaluate() -> Metrics:
    reader = get_reader("dust", fake_fallback=False)
    correct = expected = 0
    by_model: dict[str, list[int]] = {}
    image_paths = sorted(SYNTHETIC_ROOT.glob("*.jpg"))
    if not image_paths:
        raise FileNotFoundError(f"먼지 합성 평가 이미지가 없습니다: {SYNTHETIC_ROOT}")

    for image_path in image_paths:
        answer = json.loads(image_path.with_suffix(".json").read_text(encoding="utf-8"))
        try:
            result = reader.read(str(image_path), answer["item"])
        except ReadError:
            result = None
        expected += 1
        model_counts = by_model.setdefault(answer["model"], [0, 0])
        model_counts[1] += 1
        if result is not None and any(
            value.key == "value" and value.value == answer["values"]["value"] for value in result.values
        ):
            correct += 1
            model_counts[0] += 1
    return Metrics(correct, expected, {model: (counts[0], counts[1]) for model, counts in by_model.items()})


def main() -> int:
    metrics = evaluate()
    print(f"dust: field accuracy {metrics.correct_fields}/{metrics.expected_fields} ({metrics.accuracy:.1%})")
    model_passed = True
    for model, (correct, expected) in sorted(metrics.by_model.items()):
        accuracy = correct / expected if expected else 0.0
        print(f"  {model}: {correct}/{expected} ({accuracy:.1%})")
        model_passed = model_passed and accuracy >= MIN_FIELD_ACCURACY
    if metrics.accuracy < MIN_FIELD_ACCURACY or not model_passed:
        print(f"FAIL: required minimum is {MIN_FIELD_ACCURACY:.0%}.")
        return 1
    print(f"PASS: meets the {MIN_FIELD_ACCURACY:.0%} threshold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
