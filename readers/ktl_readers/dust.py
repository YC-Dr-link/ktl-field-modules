"""OCR reader for dust-monitor screens using both available screen crops."""

from __future__ import annotations

import math
import re

from ktl_contract import ReadError, ReadResult, Value, Warning

_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_OCR_CROP_WIDTH = 600
_ITEM_LABELS = {
    "span_film": "스팬필름",
    "span_1": "스팬 1",
    "span_2": "스팬 2",
    "mid_film": "중간필름",
    "linearity": "직선성",
    "meas_flow": "측정유량",
    "rep_1": "반복성 1",
    "rep_2": "반복성 2",
    "rep_3": "반복성 3",
    "blank_1": "공시험 1",
    "blank_2": "공시험 2",
    "blank_3": "공시험 3",
    "env": "온도 · 압력 · 습도",
}


def _number(text: str) -> str | None:
    value = re.sub(r"\s+", "", text)
    if not _NUMBER.fullmatch(value):
        return None
    try:
        return value if math.isfinite(float(value)) else None
    except ValueError:
        return None


def _read_crop(crop, source_to_crop, source_shape) -> tuple[str, float, list[int]] | None:
    import cv2
    import numpy as np

    from . import screen

    result = screen._ocr(crop)
    if result is None:
        raise ReadError("OCR 엔진을 사용할 수 없습니다. readers[screen] 설치가 필요합니다.")

    texts = result.txts if result.txts is not None else []
    scores = result.scores if result.scores is not None else []
    boxes = result.boxes if result.boxes is not None else []
    candidates: list[tuple[float, str, float, list[int]]] = []
    crop_to_source = np.linalg.inv(source_to_crop)
    for text, score, box in zip(texts, scores, boxes):
        value = _number(text)
        if value is None:
            continue

        points = np.asarray(box, dtype=np.float32).reshape(4, 2)
        source_points = cv2.perspectiveTransform(points[None, :, :], crop_to_source)[0]
        height, width = source_shape[:2]
        x1 = max(0, min(width - 1, int(np.floor(source_points[:, 0].min()))))
        y1 = max(0, min(height - 1, int(np.floor(source_points[:, 1].min()))))
        x2 = max(x1, min(width - 1, int(np.ceil(source_points[:, 0].max()))))
        y2 = max(y1, min(height - 1, int(np.ceil(source_points[:, 1].max()))))
        bounded_score = max(0.0, min(1.0, float(score)))
        prominence = max(1.0, float(np.ptp(points[:, 1]))) * bounded_score
        candidates.append((prominence, value, bounded_score, [x1, y1, x2, y2]))

    if not candidates:
        return None
    _, value, confidence, bbox = max(candidates, key=lambda candidate: candidate[0])
    return value, confidence, bbox


class DustReader:
    """Read the most prominent numeric screen value and reconcile both crops."""

    name = "dust"

    def __init__(self) -> None:
        try:
            import numpy as np

            from . import screen
        except ImportError:
            return
        if screen._engine is None:
            screen._ocr(np.zeros((48, 48, 3), dtype=np.uint8))

    def read(self, image_path: str, item: str) -> ReadResult:
        try:
            from . import screen
            from .preprocess import load_image
        except ImportError as error:
            raise ReadError("먼지 화면 판독 기능을 사용할 수 없습니다. readers[screen] 설치가 필요합니다.") from error

        image = load_image(image_path)
        crops = screen.extract_screens(image, width=_OCR_CROP_WIDTH)
        readings = [
            reading
            for crop, source_to_crop, _method in crops
            if (reading := _read_crop(crop, source_to_crop, image.shape)) is not None
        ]
        if not readings:
            raise ReadError("먼지 측정기 화면에서 숫자 값을 찾지 못함")

        warnings: list[Warning] = []
        if len(readings) > 1:
            if readings[0][0] != readings[1][0]:
                chosen = max(readings, key=lambda reading: reading[1])
                confidence = min(0.5, chosen[1])
                warnings.append(
                    Warning("OCR_VARIANTS_DISAGREE", "두 화면 자르기의 판독값이 다릅니다. 값을 확인해 주세요.")
                )
            else:
                chosen = max(readings, key=lambda reading: reading[1])
                confidence = min(reading[1] for reading in readings)
        else:
            chosen = readings[0]
            confidence = chosen[1]

        if _number(chosen[0]) == "0.000":
            warnings.append(Warning("PRE_MEASURE_SCREEN", "측정 전 화면(0.000)일 수 있습니다."))
        # TODO(확인 필요): 임시 categories.yaml의 dust 항목별 화면 필드 연결을 담당자에게 확인한다.
        return ReadResult(
            values=[
                Value(
                    key="value",
                    label=_ITEM_LABELS.get(item, "판독값"),
                    value=chosen[0],
                    confidence=confidence,
                    bbox=chosen[2],
                )
            ],
            warnings=warnings,
        )
