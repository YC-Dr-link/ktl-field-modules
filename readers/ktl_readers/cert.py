"""OCR reader for the four fields on a calibration certificate."""

from __future__ import annotations

import re

from ktl_contract import ReadError, ReadResult, Value, Warning

from .ocr import OCRReader, OCRText, confidence_for


_FIELDS = {
    "prev_receipt": ("직전접수번호", ("prevreceipt", "previousreceipt", "직전접수번호")),
    "approval_no": ("형식승인번호", ("approvalno", "approvalnumber", "형식승인번호")),
    "maker": ("제조사", ("maker", "manufacturer", "제조사")),
    "serial": ("제조번호", ("serial", "serialno", "제조번호")),
}


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]", "", text.lower())


def _is_field_label(text: str) -> bool:
    normalized = _normalized(text)
    return any(
        alias in normalized and len(normalized) <= len(alias) + 4
        for _, aliases in _FIELDS.values()
        for alias in aliases
    )


def _bbox(text: OCRText) -> list[int]:
    return list(text.bbox)


class CertReader(OCRReader):
    name = "cert"

    def read(self, image_path: str, item: str) -> ReadResult:
        texts, _ = self.read_texts(image_path)
        values: list[Value] = []
        warnings: list[Warning] = []
        matched: set[int] = set()

        for key, (label, aliases) in _FIELDS.items():
            label_candidates = [
                (index, text)
                for index, text in enumerate(texts)
                if index not in matched and any(alias in _normalized(text.text) for alias in aliases)
            ]
            if not label_candidates:
                continue
            label_index, label_text = max(label_candidates, key=lambda pair: pair[1].score)
            matched.add(label_index)
            x1, y1, x2, y2 = label_text.bbox
            label_height = max(1, y2 - y1)
            label_center_x = (x1 + x2) / 2
            label_center_y = (y1 + y2) / 2
            candidates: list[tuple[float, int, OCRText]] = []
            for index, text in enumerate(texts):
                if index in matched or _is_field_label(text.text):
                    continue
                tx1, ty1, tx2, ty2 = text.bbox
                value_center_x = (tx1 + tx2) / 2
                value_center_y = (ty1 + ty2) / 2
                same_row = (
                    tx1 >= x2 - label_height
                    and abs(value_center_y - label_center_y) <= max(28, label_height * 1.4)
                )
                below_label = (
                    value_center_y > label_center_y
                    and value_center_y - label_center_y <= max(55, label_height * 2.5)
                    and abs(value_center_x - label_center_x) <= max(100, (x2 - x1) * 0.6)
                )
                if same_row or below_label:
                    distance = abs(value_center_y - label_center_y) + abs(value_center_x - label_center_x) * 0.2
                    candidates.append((distance, index, text))
            if not candidates:
                continue

            _, value_index, value_text = min(candidates, key=lambda candidate: candidate[0])
            matched.add(value_index)
            value = re.sub(r"\s+", " ", value_text.text).strip()
            # TODO(확인 필요): 실제 필증의 필드별 표기 형식은 합성 데이터만으로 확정할 수 없음.
            valid = bool(value and any(char.isalnum() for char in value))
            # 형식 미확인 상태에서는 오답 고신뢰도 방지를 위해 상한을 둔다.
            confidence = min(0.79, confidence_for(min(label_text.score, value_text.score), valid))
            if not valid:
                warnings.append(Warning("FORMAT_VALIDATION_FAILED", f"{label} 형식을 확인해 주세요."))
            values.append(
                Value(
                    key=key,
                    label=label,
                    value=value,
                    confidence=confidence,
                    bbox=_bbox(value_text),
                )
            )

        if not values:
            raise ReadError("필증에서 판독 가능한 항목을 찾지 못함")
        return ReadResult(values=values, warnings=warnings)
