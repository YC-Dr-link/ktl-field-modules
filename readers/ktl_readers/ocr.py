"""Shared OCR helpers for the document and flowmeter readers."""

from __future__ import annotations

from dataclasses import dataclass

from ktl_contract import ReadError


@dataclass(frozen=True)
class OCRText:
    text: str
    score: float
    bbox: tuple[int, int, int, int]


class OCRReader:
    """Owns its OCR engine so reader instances do not share mutable state."""

    def __init__(self) -> None:
        self._engine = None
        self._engine_import_error: ImportError | None = None
        try:
            from rapidocr import RapidOCR
        except ImportError as error:
            self._engine_import_error = error
        else:
            self._engine = RapidOCR()

    def read_texts(self, image_path: str) -> tuple[list[OCRText], tuple[int, int]]:
        try:
            import numpy as np

            from .preprocess import load_image
        except ImportError as error:
            raise ReadError("OCR 이미지 처리 기능을 사용할 수 없습니다. readers[screen] 설치가 필요합니다.") from error

        image = load_image(image_path)
        if self._engine is None:
            raise ReadError("OCR 엔진을 사용할 수 없습니다. readers[screen] 설치가 필요합니다.") from self._engine_import_error

        result = self._engine(image)
        height, width = image.shape[:2]
        texts: list[OCRText] = []
        boxes = result.boxes if result.boxes is not None else []
        raw_texts = result.txts if result.txts is not None else []
        scores = result.scores if result.scores is not None else []
        for text, score, box in zip(raw_texts, scores, boxes):
            points = np.asarray(box)
            x1 = max(0, min(width - 1, int(np.floor(points[:, 0].min()))))
            y1 = max(0, min(height - 1, int(np.floor(points[:, 1].min()))))
            x2 = max(x1, min(width - 1, int(np.ceil(points[:, 0].max()))))
            y2 = max(y1, min(height - 1, int(np.ceil(points[:, 1].max()))))
            texts.append(OCRText(text=text.strip(), score=float(score), bbox=(x1, y1, x2, y2)))
        return texts, (width, height)


def confidence_for(score: float, valid: bool) -> float:
    """Keep syntactically invalid readings at or below the contract's 0.5 limit."""
    bounded_score = max(0.0, min(1.0, score))
    return bounded_score if valid else min(0.5, bounded_score)
