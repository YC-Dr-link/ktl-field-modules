"""OCR reader for the reference flowmeter's displayed flow value."""

from __future__ import annotations

import math
import re

from ktl_contract import ReadError, ReadResult, Value, Warning

from .ocr import OCRReader, OCRText, confidence_for

_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _center_y(text: OCRText) -> float:
    return (text.bbox[1] + text.bbox[3]) / 2


def _center_x(text: OCRText) -> float:
    return (text.bbox[0] + text.bbox[2]) / 2


def _is_valid_flow(text: str) -> bool:
    if not _NUMBER.fullmatch(text):
        return False
    try:
        number = float(text)
    except ValueError:
        return False
    # TODO(확인 필요): 기준 유량계 기종별 허용 상한은 공동 문서에서 확인되지 않음.
    return math.isfinite(number) and number >= 0


class FlowmeterReader(OCRReader):
    name = "flowmeter"

    def read(self, image_path: str, item: str) -> ReadResult:
        texts, (_, image_height) = self.read_texts(image_path)
        labels = [text for text in texts if "flow" in _normalized(text.text)]
        if not labels:
            raise ReadError("유량 화면에서 FLOW 항목을 찾지 못함")

        label = max(labels, key=lambda text: text.score)
        label_y = _center_y(label)
        label_x = _center_x(label)
        candidates = [
            text
            for text in texts
            if text is not label
            and text.bbox[1] >= label.bbox[1]
            and _center_y(text) - label_y <= max(140, image_height * 0.35)
            and abs(_center_x(text) - label_x) <= image_height * 0.5
        ]
        if not candidates:
            raise ReadError("유량 화면에서 FLOW 값을 찾지 못함")

        numeric_candidates = [text for text in candidates if _NUMBER.fullmatch(text.text.strip())]
        flow_text = min(
            numeric_candidates or candidates,
            key=lambda text: abs(_center_y(text) - label_y) + 0.35 * abs(_center_x(text) - label_x),
        )
        raw_value = re.sub(r"\s+", "", flow_text.text)
        valid = _is_valid_flow(raw_value)
        confidence = confidence_for(min(label.score, flow_text.score), valid)
        warnings = [] if valid else [Warning("FORMAT_VALIDATION_FAILED", "유량 숫자 형식 또는 범위를 확인해 주세요.")]

        return ReadResult(
            values=[
                Value(
                    key="flow",
                    label="유량",
                    value=raw_value,
                    unit="L/min",
                    confidence=confidence,
                    bbox=list(flow_text.bbox),
                )
            ],
            warnings=warnings,
        )
