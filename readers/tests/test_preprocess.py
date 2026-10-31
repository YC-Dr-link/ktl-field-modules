"""공통 전처리(#2) 테스트. 테스트 사진은 실제 견본이 아니라 코드로 그린 가짜 기록부다."""

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from ktl_contract import ReadError
from ktl_readers.preprocess import extract_top_table, find_table_lines, load_image

PAGE_W, PAGE_H = 1240, 1754                 # A4 150dpi 스캔 크기
TOP_TABLE = (110, 355, 1150, 730)           # 위쪽 표(기기 정보) 좌상 x, y, 우하 x, y
BOTTOM_TABLE = (110, 810, 1150, 1600)       # 아래쪽 표(검사 이력) — 위쪽 표보다 큼


def draw_fake_record() -> np.ndarray:
    """기록부 양식을 흉내 낸 가짜 페이지: 제목 밑줄 + 위쪽 작은 표(7줄) + 아래쪽 큰 표."""
    page = np.full((PAGE_H, PAGE_W, 3), 255, np.uint8)
    black = (0, 0, 0)
    cv2.putText(page, "FAKE RECORD", (420, 250), cv2.FONT_HERSHEY_SIMPLEX, 1.6, black, 3)
    cv2.line(page, (310, 270), (940, 270), black, 3)

    x1, y1, x2, y2 = TOP_TABLE
    cv2.rectangle(page, (x1, y1), (x2, y2), black, 3)
    divider = x1 + round((x2 - x1) * 0.285)
    cv2.line(page, (divider, y1), (divider, y2), black, 2)
    row_height = (y2 - y1) / 7
    for row in range(7):
        y = round(y1 + row_height * row)
        if row:
            cv2.line(page, (x1, y), (x2, y), black, 2)
        cv2.putText(page, f"LABEL {row}", (x1 + 30, y + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, black, 2)
        cv2.putText(page, f"VALUE-2024-{row}0", (divider + 30, y + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, black, 2)

    x1, y1, x2, y2 = BOTTOM_TABLE
    cv2.rectangle(page, (x1, y1), (x2, y2), black, 3)
    for x in (300, 520, 760, 950):
        cv2.line(page, (x, y1), (x, y2), black, 2)
    for y in range(y1 + 60, y2, 60):
        cv2.line(page, (x1, y), (x2, y), black, 2)
    return page


def rotate_point(point, code, width, height):
    """사진을 cv2.rotate(code)로 돌렸을 때 점 (x, y)가 옮겨 가는 위치."""
    x, y = point
    if code is None:
        return x, y
    if code == cv2.ROTATE_90_CLOCKWISE:
        return height - 1 - y, x
    if code == cv2.ROTATE_180:
        return width - 1 - x, height - 1 - y
    return y, width - 1 - x  # ROTATE_90_COUNTERCLOCKWISE


# --- load_image ---

def test_empty_file_raises_read_error(tmp_path):
    empty = tmp_path / "empty.jpg"
    empty.write_bytes(b"")
    with pytest.raises(ReadError):
        load_image(str(empty))


def test_missing_file_raises_read_error(tmp_path):
    with pytest.raises(ReadError):
        load_image(str(tmp_path / "없는파일.png"))


def test_korean_path_opens(tmp_path):
    folder = tmp_path / "한글 폴더"
    folder.mkdir()
    path = folder / "기록부.png"
    cv2.imencode(".png", draw_fake_record())[1].tofile(str(path))
    assert load_image(str(path)).shape == (PAGE_H, PAGE_W, 3)


# --- find_table_lines ---

def test_lines_kept_and_text_removed():
    lines = find_table_lines(draw_fake_record())
    x1, y1, x2, _ = TOP_TABLE
    assert lines[y1, (x1 + x2) // 2] == 255                  # 표 윗변은 남음
    assert not lines[y1 + 15:y1 + 40, x1 + 30:x1 + 150].any()  # 첫 줄 "LABEL 0" 글자는 지워짐


# --- extract_top_table (완료 기준: 90° 회전 사진 정상 처리) ---

@pytest.mark.parametrize("code", [None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE],
                         ids=["0", "90", "180", "270"])
def test_top_table_found_in_any_rotation(code):
    page = draw_fake_record()
    upright_table, _ = extract_top_table(page)
    image = page if code is None else cv2.rotate(page, code)

    table, matrix = extract_top_table(image)

    # 돌린 사진에서도 똑같은 표가 나와야 한다
    assert table.shape == upright_table.shape
    assert np.abs(table.astype(int) - upright_table.astype(int)).mean() < 5

    # 변환 행렬이 표 꼭짓점을 잘라 낸 사진의 네 모서리로 보내야 한다 (bbox를 되돌릴 때 필요)
    x1, y1, x2, y2 = TOP_TABLE
    corners = [rotate_point(p, code, PAGE_W, PAGE_H) for p in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))]
    mapped = cv2.perspectiveTransform(np.array([corners], np.float32), matrix)[0]
    h, w = table.shape[:2]
    expected = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32)
    assert np.abs(mapped - expected).max() < 8


def test_blank_page_raises_read_error():
    blank = np.full((PAGE_H, PAGE_W, 3), 255, np.uint8)
    with pytest.raises(ReadError):
        extract_top_table(blank)
