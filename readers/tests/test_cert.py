"""cert Reader(#3) 테스트. 테스트 사진은 실제 견본이 아니라 코드로 그린 가짜 기록부이고, 값도 가짜다."""

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from ktl_contract.testing import check_reader, check_reader_rejects
from ktl_readers import cert
from ktl_readers.preprocess import extract_top_table

PAGE_W, PAGE_H = 1240, 1754                 # A4 150dpi 스캔 크기
TOP_TABLE = (110, 355, 1150, 730)           # 위쪽 표 좌상 x, y, 우하 x, y
BOTTOM_TABLE = (110, 810, 1150, 1600)       # 아래쪽 표 — 위쪽 표보다 큼
FAKE = {0: "MAKER CO", 3: "H AB-2024-3 H", 5: "A1B2C3D4E5"}   # 줄 번호 → 값 칸 글자 ('H'는 고정 글자 '제'·'호' 대신)


def draw_fake_record() -> np.ndarray:
    """기록부 양식을 흉내 낸 가짜 페이지: 위쪽 작은 표(7줄, 칸 이름 | 값) + 아래쪽 큰 표."""
    page = np.full((PAGE_H, PAGE_W, 3), 255, np.uint8)
    black = (0, 0, 0)
    x1, y1, x2, y2 = TOP_TABLE
    cv2.rectangle(page, (x1, y1), (x2, y2), black, 3)
    divider = x1 + round((x2 - x1) * 0.285)
    cv2.line(page, (divider, y1), (divider, y2), black, 2)
    row_height = (y2 - y1) / 7
    for row in range(7):
        y = round(y1 + row_height * row)
        if row:
            cv2.line(page, (x1, y), (x2, y), black, 2)
        cv2.putText(page, f"LABEL {row}", (x1 + 30, y + 38), cv2.FONT_HERSHEY_SIMPLEX, 0.8, black, 2)
        cv2.putText(page, FAKE.get(row, f"{row}{row}{row}"), (divider + 30, y + 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, black, 2)
    x1, y1, x2, y2 = BOTTOM_TABLE
    cv2.rectangle(page, (x1, y1), (x2, y2), black, 3)
    for y in range(y1 + 60, y2, 60):
        cv2.line(page, (x1, y), (x2, y), black, 2)
    return page


@pytest.fixture
def record_path(tmp_path):
    path = tmp_path / "record.png"
    cv2.imwrite(str(path), draw_fake_record())
    return path


def test_splits_top_table_into_seven_value_cells():
    table, _ = extract_top_table(draw_fake_record())
    cells = cert.split_value_cells(table)
    assert len(cells) == 7
    for cell, (x0, y0, x1, y1) in cells:
        assert cell.size and x0 > 0.25 * table.shape[1]          # 칸 이름 열은 빠지고 값 열만


def test_trim_fixed_ends_drops_first_and_last_letter():
    table, _ = extract_top_table(draw_fake_record())
    cell, _ = cert.split_value_cells(table)[3]
    trimmed = cert.trim_fixed_ends(cell)
    ink_cols = np.where((cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY) < 128).any(0))[0]
    text_width = ink_cols.max() - ink_cols.min()                       # 글자가 있는 폭 ('H AB-2024-3 H')
    assert trimmed.shape[1] < 0.85 * text_width                       # 앞뒤 'H' 만큼 줄어듦


def test_format_check_lowers_confidence():
    assert cert._check("approval_no", "제AB-2024-3호", 0.9) == 0.9
    assert cert._check("approval_no", "AB-2024", 0.9) <= 0.5          # 꼴이 안 맞으면 0.5 이하
    assert cert._check("serial", "A1B2C3D4E5", 0.9) == 0.9
    assert cert._check("serial", "A1", 0.9) <= 0.5


def test_format_check_on_synthetic_cert_numbers():
    assert cert._check("prev_receipt", "SYN-PREV-0001", 0.95) == 0.95
    assert cert._check("approval_no", "SYN-APP-0007", 0.95) == 0.95
    assert cert._check("serial", "SYN-SN-0001", 0.95) == 0.95
    assert cert._check("maker", "SYN MAKER 02", 0.95) == 0.95
    for key, misread in [("prev_receipt", "SYN-PREV-00O1"), ("approval_no", "SYN-APP-007"),
                         ("serial", "SYN-SN-0001|"), ("maker", "|"), ("maker", "02 MAKER")]:
        assert cert._check(key, misread, 0.99) <= 0.5, misread     # OCR가 흔히 틀리는 꼴은 0.5 이하


def _ocr(text, box, score=0.95):
    from ktl_readers.ocr import OCRText
    return OCRText(text=text, score=score, bbox=box)


def test_read_by_labels_pairs_label_with_value_below_or_right():
    texts = [
        _ocr("PREV. RECEIPT", (80, 150, 200, 165)), _ocr("SYN-PREV-0003", (80, 175, 260, 195)),       # 아래 줄
        _ocr("MAKER", (80, 320, 140, 335)), _ocr("SYN MAKER 04", (80, 345, 240, 365)),                # 값에 'MAKER'가 섞임
        _ocr("SERIAL", (80, 400, 150, 415)), _ocr("SYN-SN-00O3", (170, 400, 330, 416), 0.97),         # 같은 줄 오른쪽, 오독
        _ocr("All identifiers are generated test data.", (60, 500, 600, 515)),
    ]
    values = {v.key: v for v in cert.read_by_labels(texts)}
    assert set(values) == {"prev_receipt", "maker", "serial"}           # 라벨이 없는 칸은 안 낸다
    assert values["prev_receipt"].value == "SYN-PREV-0003" and values["prev_receipt"].confidence == 0.95
    assert values["maker"].value == "SYN MAKER 04" and values["maker"].label == "제조사"
    assert values["serial"].value == "SYN-SN-00O3" and values["serial"].confidence <= 0.5
    assert values["serial"].bbox == [170, 400, 330, 416]


def test_reader_falls_back_to_labels_when_no_record_table(monkeypatch, tmp_path):
    page = np.full((600, 800, 3), 255, np.uint8)                       # 표 선이 없는 사진
    path = tmp_path / "card.png"
    cv2.imwrite(str(path), page)

    class FakePageOCR:
        def read_texts(self, image_path):
            return [_ocr("APPROVAL NO.", (80, 230, 200, 245)), _ocr("SYN-APP-0O07", (80, 255, 250, 275))], (800, 600)

    reader = cert.CertReader()
    reader._page_ocr = FakePageOCR()
    result = check_reader(reader, str(path), "cert")
    assert [(v.key, v.value) for v in result.values] == [("approval_no", "SYN-APP-0O07")]
    assert result.values[0].confidence <= 0.5
    assert [w.code for w in result.warnings] == ["FORMAT_CHECK_FAILED"]


class FakeEngine:
    """OCR 대신 정해진 글자를 돌려준다 (OCR 없이 Reader 흐름만 확인)."""

    def read(self, key, cell):
        return {"maker": ("(주)가짜", 0.9), "approval_no": ("제AB-2024-3호", 0.95), "serial": ("A1B2C3D4E5", 0.99)}[key]


def test_reader_follows_contract(monkeypatch, record_path, tmp_path):
    monkeypatch.setattr(cert, "_engine", lambda: FakeEngine())
    result = check_reader(cert.CertReader(), str(record_path), "cert")
    values = {v.key: v for v in result.values}
    assert set(values) == {"maker", "approval_no", "serial"}
    x1, y1, x2, y2 = TOP_TABLE
    for v in values.values():                                          # bbox는 받은 사진 좌표, 위쪽 표 안
        assert x1 - 5 <= v.bbox[0] < v.bbox[2] <= x2 + 5 and y1 - 5 <= v.bbox[1] < v.bbox[3] <= y2 + 5
    empty = tmp_path / "empty.jpg"
    empty.write_bytes(b"")
    check_reader_rejects(cert.CertReader(), str(empty), "cert")


def test_reads_serial_and_approval_with_rapidocr():
    pytest.importorskip("rapidocr")
    table, _ = extract_top_table(draw_fake_record())
    cells = cert.split_value_cells(table)
    engine = cert._Rapid()
    assert engine.read("serial", cells[5][0])[0] == "A1B2C3D4E5"
    assert engine.read("approval_no", cells[3][0])[0] == "제AB-2024-3호"
