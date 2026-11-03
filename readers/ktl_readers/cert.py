"""cert Reader: 정도검사 기록부 사진 → 위쪽 표 → 값 칸 3개 → 칸마다 OCR.

흐름
1) load_image → extract_top_table (preprocess.py, 서류 회전·위쪽 표 자르기)
2) 표 선으로 7칸을 나누고, 칸 이름|값 경계 오른쪽만 쓴다
3) 필요한 3칸만 읽는다 (양식이 고정이라 몇 번째 줄인지로 값을 정한다)
   - 제조사(1행): 한글 → 한국어 모델
   - 형식승인번호(4행): 고정 글자 '제'·'호'를 잘라 내고 영문·숫자 모델로 가운데만 읽은 뒤 다시 붙인다
   - 제조번호(6행): 영문·숫자 모델
4) 형식이 안 맞으면 신뢰도 0.5 이하

OCR 엔진은 두 가지를 넣어 둔다 (어느 걸 쓸지는 아직 정하지 않음)
   "rapid"     : RapidOCR (기본 v6 + 한국어 v4). 1장 0.2초 정도
   "paddle_vl" : PaddleOCR-VL 0.9B. 더 정확하지만 CPU에서 칸 하나에 십수 초
"""

import os
import re

import cv2
import numpy as np

from ktl_contract import ReadError, ReadResult, Value

from .preprocess import extract_top_table, load_image

ENGINE = os.environ.get("KTL_CERT_OCR", "rapid")     # "rapid" | "paddle_vl"
FIELDS = {                                            # key: (몇 번째 줄, 화면 이름)
    "maker": (0, "제조사"),
    "approval_no": (3, "형식승인번호"),
    "serial": (5, "제조번호"),
}
# TODO(확인 필요): 직전접수번호(prev_receipt)는 기록부에 칸이 없다. 어디서 읽는지 확인 후 추가
APPROVAL = re.compile(r"[A-Z]+-\d{4}-\d+")            # TODO(확인 필요): 견본 4장 기준 꼴 (영문-연도-번호)
SERIAL = re.compile(r"[A-Z0-9]{6,}")
CELL_PAD = 6                                          # 칸 선을 피해서 안쪽만 자르는 여백(px)


def _line_positions(mask, axis):
    """선 마스크에서 선이 지나는 위치(가운데)들. axis=0이면 가로선의 y, 1이면 세로선의 x."""
    profile = mask.sum(axis=1 - axis) / 255
    hit = np.where(profile > 0.5 * profile.max())[0]
    groups = np.split(hit, np.where(np.diff(hit) > 3)[0] + 1)
    return [int(g.mean()) for g in groups if len(g)]


def split_value_cells(table):
    """위쪽 표 → 줄마다 값 칸 (잘린 칸 사진, 표 안 좌표 (x0, y0, x1, y1)) 목록."""
    gray = cv2.cvtColor(table, cv2.COLOR_BGR2GRAY)
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 10)
    h, w = ink.shape
    rows = _line_positions(cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, w // 3), np.uint8)), 0)   # 긴 가로선
    cols = _line_positions(cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((h // 3, 1), np.uint8)), 1)   # 긴 세로선
    if len(rows) < 2 or len(cols) < 2:
        raise ReadError("표 칸을 나누지 못함")
    split = min(cols[1:], key=lambda x: abs(x - 0.29 * w))      # 칸 이름 | 값 경계 (양식상 표 폭의 약 29%)
    cells = []
    for y0, y1 in zip(rows, rows[1:]):
        box = (split + CELL_PAD, y0 + CELL_PAD, w - CELL_PAD, y1 - CELL_PAD)
        cells.append((table[box[1]:box[3], box[0]:box[2]], box))
    return cells


def trim_fixed_ends(cell):
    """'제 … 호'처럼 앞뒤 한 글자가 고정인 칸: 세로 투영으로 첫 빈틈 앞·마지막 빈틈 뒤를 잘라 낸다."""
    ink = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY) < 128
    ink[ink.mean(1) > 0.5, :] = False                           # 칸에 걸린 표 가로선 지우기 (빈틈을 다 덮어 버림)
    ink[:, ink.mean(0) > 0.8] = False                           # 세로선(칸 테두리) 지우기
    cols, rows = np.where(ink.any(0))[0], np.where(ink.any(1))[0]
    if len(cols) == 0:
        return cell
    x0, x1, y0, y1 = cols.min(), cols.max(), rows.min(), rows.max()
    height = y1 - y0
    blank = ~ink[:, x0:x1 + 1].any(0)                             # 검은 점이 하나도 없는 세로줄 = 빈틈
    edges = np.diff(np.concatenate([[0], blank.astype(int), [0]]))
    runs = [(s + x0, e + x0) for s, e in zip(np.where(edges == 1)[0], np.where(edges == -1)[0])]   # 빈틈 구간들

    def gaps_between(lo, hi):
        return [(e - s, (s + e) // 2) for s, e in runs if lo < (s + e) / 2 < hi]   # (폭, 가운데)

    left = gaps_between(x0 + 0.3 * height, x0 + 1.6 * height)
    right = gaps_between(x1 - 1.6 * height, x1 - 0.3 * height)
    a = max(left)[1] if left else None                  # 첫 글자(제) 뒤: 가장 넓은 빈틈 ('제'는 ㅈ|ㅔ 사이에도 좁은 빈틈이 있음)
    b = max(c for _, c in right) if right else None     # 끝 글자(호) 앞: 끝에서 가장 가까운 빈틈 ('호'는 위아래로 쌓여 안쪽 빈틈이 없음)
    a = a if a is not None else x0 + height
    b = b if b is not None else x1 - height
    return cell[max(0, y0 - CELL_PAD):y1 + CELL_PAD, max(0, a - 2):b + 3]


class _Rapid:
    """RapidOCR: 영문·숫자 칸은 기본 모델(v6), 한글 칸은 한국어 모델(v4)."""

    def __init__(self):
        from rapidocr import RapidOCR
        self.alnum = RapidOCR()
        self._korean = None

    @property
    def korean(self):
        """한국어 모델은 회사명을 처음 읽을 때 불러온다.
        TODO(확인 필요): 처음 실행 때 인터넷으로 내려받는다 → 오프라인 서버면 미리 넣어 둬야 함"""
        if self._korean is None:
            from rapidocr import RapidOCR
            from rapidocr.utils.typings import LangRec, ModelType, OCRVersion
            self._korean = RapidOCR(params={"Rec.lang_type": LangRec.KOREAN, "Rec.ocr_version": OCRVersion.PPOCRV4,
                                            "Rec.model_type": ModelType.MOBILE})
        return self._korean

    @staticmethod
    def _line(engine, image):
        result = engine(image, use_det=False, use_cls=False)        # 칸엔 한 줄뿐 → 글자 찾기 없이 읽기만
        return (result.txts or [""])[0].strip(), float((result.scores or [0.0])[0])

    def read(self, key, cell):
        if key == "maker":
            text, score = self._line(self.korean, cell)
            # ㈜ 기호를 '주'·'「'·'()'로 읽는다 → (주)로 맞춘다. TODO(확인 필요): 이름이 '주'로 시작하는 회사가 있으면 틀림
            return re.sub(r"^(㈜|\(주\)|\(\)|「|주)\s*", "(주)", text), score
        if key == "approval_no":
            text, score = self._line(self.alnum, trim_fixed_ends(cell))
            m = APPROVAL.search(text.replace(" ", ""))
            return (f"제{m.group()}호", score) if m else (text, min(score, 0.5))
        return self._line(self.alnum, cell)


class _PaddleVL:
    """PaddleOCR-VL 0.9B (CPU). 칸 사진을 그대로 주고 글자를 받는다. 점수가 없어서 형식 검사로만 신뢰도를 정한다."""

    def __init__(self):
        from paddleocr import DocVLM
        self.model = DocVLM(model_name="PaddleOCR-VL-0.9B", device="cpu")

    def read(self, key, cell):
        out = list(self.model.predict(input={"image": cell, "query": "OCR:"}, batch_size=1))
        text = str(out[0].get("result", "")).strip() if out else ""
        return text, 0.9


_engines = {}


def _engine():
    """ENGINE에 맞는 OCR을 처음 한 번만 만든다. paddle_vl이 안 깔려 있으면 rapid로."""
    name = ENGINE if ENGINE in ("rapid", "paddle_vl") else "rapid"
    if name not in _engines:
        try:
            _engines[name] = _PaddleVL() if name == "paddle_vl" else _Rapid()
        except ImportError:
            if name == "rapid":
                raise ReadError('OCR(rapidocr)가 설치되지 않음 — pip install -e "readers[screen]"') from None
            return _engine_rapid()
    return _engines[name]


def _engine_rapid():
    if "rapid" not in _engines:
        try:
            _engines["rapid"] = _Rapid()
        except ImportError:
            raise ReadError('OCR(rapidocr)가 설치되지 않음 — pip install -e "readers[screen]"') from None
    return _engines["rapid"]


def _check(key, text, confidence):
    """형식 검사. 안 맞으면 신뢰도 0.5 이하 (틀린 값을 높은 신뢰도로 내지 않기)."""
    ok = {"approval_no": re.fullmatch(rf"제{APPROVAL.pattern}호", text),
          "serial": SERIAL.fullmatch(text),
          "maker": len(text) >= 2}[key]
    return confidence if ok else min(confidence, 0.5)


def _to_photo_box(box, matrix):
    """표 안 좌표 → 받은 사진 좌표 [x1, y1, x2, y2] (계약의 bbox)."""
    x0, y0, x1, y1 = box
    corners = np.array([[[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]], np.float32)
    back = cv2.perspectiveTransform(corners, np.linalg.inv(matrix)).reshape(4, 2)
    (a, b), (c, d) = back.min(0), back.max(0)
    return [int(a), int(b), int(c), int(d)]


class CertReader:
    name = "cert"

    def read(self, image_path: str, item: str) -> ReadResult:
        image = load_image(image_path)
        table, matrix = extract_top_table(image)
        cells = split_value_cells(table)
        engine = _engine()
        values = []
        for key, (row, label) in FIELDS.items():
            if row >= len(cells):
                continue
            cell, box = cells[row]
            text, confidence = engine.read(key, cell)
            if not text:
                continue
            values.append(Value(key=key, label=label, value=text,
                                confidence=round(_check(key, text, confidence), 2), bbox=_to_photo_box(box, matrix)))
        if not values:
            raise ReadError("기록부에서 값을 읽지 못함")
        return ReadResult(values=values)
