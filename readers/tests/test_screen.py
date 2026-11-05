"""화면(LCD) 자르기 테스트. 테스트 사진은 실제 견본이 아니라 코드로 그린 가짜 기기다."""

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from ktl_contract import ReadError
from ktl_readers import screen
from ktl_readers.screen import _expand_to_texts, _frame_quads, _widen_if_white, find_frame, identify_device
from ktl_readers.devices import PROFILES

W, H = 1000, 750


def cut(image, texts=None, read_text=None):
    """extract_screen의 안쪽 (OCR 대신 가짜 글자를 넣는다)."""
    return screen._one(image, texts, read_text, 800)


def cuts(image, texts=None, read_text=None):
    """extract_screens의 안쪽."""
    return screen._crops(image, texts, read_text, 800)
SCREEN = (330, 200, 690, 450)     # 화면 좌상 x, y, 우하 x, y


def draw_fake_device():
    """밝은 배경 + 진한 몸체 + 연두색 화면(글자 줄 몇 개) + 버튼."""
    image = np.full((H, W, 3), (215, 220, 215), np.uint8)
    cv2.rectangle(image, (260, 120), (760, 640), (55, 60, 58), -1)
    x1, y1, x2, y2 = SCREEN
    cv2.rectangle(image, (x1, y1), (x2, y2), (190, 215, 195), -1)
    cv2.putText(image, "FLOW", (x1 + 20, y1 + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 40, 30), 2)
    cv2.putText(image, "1.2345", (x1 + 20, y1 + 140), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (30, 40, 30), 4)
    cv2.putText(image, "L/min", (x1 + 240, y1 + 200), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 40, 30), 2)
    for bx in (330, 470, 610):
        cv2.circle(image, (bx + 40, 560), 30, (170, 175, 170), -1)
    return image


def corners(box):
    x1, y1, x2, y2 = box
    return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], np.float32)


def assert_maps_to_frame(matrix, screen, true_corners, tolerance):
    h, w = screen.shape[:2]
    mapped = cv2.perspectiveTransform(true_corners[None], matrix)[0]
    frame = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32)
    assert np.abs(mapped - frame).max() < tolerance * w


def test_finds_screen_on_fake_device():
    screen, matrix = cut(draw_fake_device())
    assert screen.shape[1] == 800
    assert_maps_to_frame(matrix, screen, corners(SCREEN), 0.03)


def test_finds_tilted_screen():
    image = draw_fake_device()
    rotation = cv2.getRotationMatrix2D((W / 2, H / 2), 5, 1.0)      # 5° 기울임
    tilted = cv2.warpAffine(image, rotation, (W, H), borderValue=(215, 220, 215))
    true = cv2.transform(corners(SCREEN)[None], rotation)[0]
    screen, matrix = cut(tilted)
    assert_maps_to_frame(matrix, screen, true, 0.04)


def test_no_screen_raises():
    with pytest.raises(ReadError):
        cut(np.full((H, W, 3), 128, np.uint8))


def test_known_device_falls_back_to_text_range_when_color_fails():
    flat = np.full((H, W, 3), 128, np.uint8)                          # 색으로는 화면을 못 찾는 사진
    texts = [text("Defender 510", (400, 620, 560, 650)),
             text("Cont. Measurement L/min", (330, 200, 690, 230)), text("Flow: 1.2345", (340, 300, 600, 340)),
             text("PAUSE|RESET", (340, 420, 560, 450))]
    screen, matrix = cut(flat, texts)
    assert_maps_to_frame(matrix, screen, corners((330, 200, 690, 450)), 0.1)
    with pytest.raises(ReadError):                                     # 기기도 모르면 그대로 실패
        cut(flat, [text("UNKNOWN 9000", (400, 100, 600, 130))])


def test_white_screen_is_widened_and_colored_is_not():
    image = np.full((H, W, 3), 200, np.uint8)
    quad = corners((400, 300, 600, 450))
    image[300:450, 400:600] = (245, 245, 245)                          # 흰 화면 (채도 낮음)
    wide = _widen_if_white(image, quad)
    assert np.ptp(wide[:, 0]) > np.ptp(quad[:, 0]) * 1.3
    image[300:450, 400:600] = (230, 200, 40)                           # 청록 화면 (채도 높음)
    assert np.array_equal(_widen_if_white(image, quad), quad)


def text(label, box):
    return label, corners(box)


def test_identify_device_is_lenient_and_ignores_camera_stamp():
    shape = (H, W, 3)
    assert identify_device([text("ZALICAT", (400, 600, 500, 630))], shape) == "alicat"     # 로고가 살짝 틀려도
    assert identify_device([text("Defender 510", (20, 700, 200, 730))], shape) is None     # 왼쪽 아래 도장 자리
    assert identify_device([text("UNKNOWN 9000", (400, 100, 600, 130))], shape) is None   # 모르는 기기


def test_expand_includes_screen_text_but_not_logo():
    image = draw_fake_device()
    quad = corners((330, 260, 690, 450))                               # 위쪽 줄이 잘린 크롭
    profile = PROFILES["defender510"]
    grown = _expand_to_texts(image, quad, [text("Cont. Measurement L/min", (350, 215, 600, 240))], profile)
    assert grown[:, 1].min() < 215
    logo_inside = [text("Cont. Measurement", (350, 215, 600, 240)), text("Defender 510", (350, 236, 500, 250))]
    assert np.array_equal(_expand_to_texts(image, quad, logo_inside, profile), quad)     # 로고가 들어오면 취소


# ---- [이진] 흰 화면 + 검은 테두리 (화면과 몸체 색이 비슷한 기기) ----

WHITE = (300, 220, 700, 480)      # 흰 화면 좌상 x, y, 우하 x, y


def draw_white_device(gap=False):
    """밝은 회색 몸체 + 검은 테두리 + 흰 화면(글자 몇 줄). gap=True면 위쪽 테두리 가운데가 끊김."""
    image = np.full((H, W, 3), (200, 200, 200), np.uint8)
    x1, y1, x2, y2 = WHITE
    cv2.rectangle(image, (x1 - 25, y1 - 25), (x2 + 25, y2 + 25), (25, 25, 25), -1)
    cv2.rectangle(image, (x1, y1), (x2, y2), (245, 245, 245), -1)
    for i, line in enumerate(["Running", "count 1234567", "mg/cm2 0.123"]):
        cv2.putText(image, line, (x1 + 30, y1 + 60 + i * 70), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (40, 40, 40), 2)
    if gap:
        image[y1 - 25:y1, 480:520] = (245, 245, 245)                  # 테두리 40px 끊김 (화면과 이어짐)
    return image


WHITE_TEXTS = [text("Running", (330, 255, 480, 285)), text("count 1234567", (330, 300, 600, 330)),
               text("mg/cm2 0.123", (330, 345, 580, 375)), text("MEZUS 610", (330, 100, 520, 140))]   # 로고는 무리 밖


def test_frame_finds_white_screen_in_black_bezel():
    image = draw_white_device()
    quads = _frame_quads(image)
    assert len(quads) == 1
    assert np.abs(np.sort(quads[0], 0) - np.sort(corners(WHITE), 0)).max() < 0.02 * W


def test_frame_bridges_small_gap_in_bezel():
    assert len(_frame_quads(draw_white_device(gap=True))) == 1


def test_frame_rejects_non_rectangle_hole():
    image = np.full((H, W, 3), 200, np.uint8)
    cv2.rectangle(image, (200, 150), (800, 600), (25, 25, 25), -1)
    trapezoid = np.array([[300, 250], [700, 250], [600, 500], [400, 500]], np.int32)   # 사다리꼴 구멍
    cv2.fillConvexPoly(image, trapezoid, (245, 245, 245))
    assert _frame_quads(image) == []


def test_frame_needs_text_inside():
    image = draw_white_device()
    assert find_frame(image, [text("ELSEWHERE", (40, 40, 200, 80)), text("X", (60, 90, 120, 120))]) is None
    assert find_frame(image, WHITE_TEXTS) is not None


def test_white_screen_device_is_cropped_to_screen():
    image = draw_white_device()
    quad, how = screen._choose(image, WHITE_TEXTS, *screen._both(image, WHITE_TEXTS))
    assert "이진" in how or how == "합침"
    screen_, matrix = cut(image, WHITE_TEXTS)
    assert_maps_to_frame(matrix, screen_, corners(WHITE), 0.05)


# ---- [대조] 두 방식 결과 고르기 ----

def pick(monkeypatch, color, frame, texts=WHITE_TEXTS):
    monkeypatch.setattr(screen, "_color_quad", lambda *_: None if color is None else corners(color))
    monkeypatch.setattr(screen, "find_frame", lambda *_: None if frame is None else corners(frame))
    image = np.zeros((H, W, 3), np.uint8)
    return screen._choose(image, texts, *screen._both(image, texts))


def test_pick_rules(monkeypatch):
    big, fit = (290, 210, 710, 490), WHITE
    assert pick(monkeypatch, big, fit)[1] == "같음-이진"              # 같은 화면, 크기 비슷 → 더 딱 맞는 액자
    assert pick(monkeypatch, (200, 120, 800, 600), fit)[1] == "같음-베이스"   # 색이 훨씬 넓음 → 색
    quad, how = pick(monkeypatch, (300, 140, 700, 380), fit)          # 베이스=위쪽, 이진=아래쪽 → 합침
    assert how == "합침" and quad[:, 1].min() <= 141 and quad[:, 1].max() >= 479
    assert pick(monkeypatch, (20, 600, 150, 700), fit)[1] == "다름-이진"  # 색이 엉뚱한 곳 → 글자 많은 액자
    assert pick(monkeypatch, None, fit)[1] == "이진만"
    assert pick(monkeypatch, fit, None)[1] == "베이스만"
    with pytest.raises(ReadError):
        pick(monkeypatch, None, None)


# ---- 둘 다 받기 (Reader가 두 크롭을 읽고 값 대조) ----

def test_extract_screens_gives_both_when_both_found():
    image = draw_white_device()
    crops = cuts(image, WHITE_TEXTS)
    assert [name for *_, name in crops][:1] == ["이진"] and len(crops) == 2      # 고른 쪽(이진)이 먼저
    for crop, matrix, _ in crops:
        assert crop.shape[1] == 800
        assert_maps_to_frame(matrix, crop, corners(WHITE), 0.05)


def test_extract_screens_gives_base_only_without_black_border():
    crops = cuts(draw_fake_device())                       # 글자 없음 → 이진은 안 돌림
    assert [name for *_, name in crops] == ["베이스"]
    with pytest.raises(ReadError):
        cuts(np.full((H, W, 3), 128, np.uint8))


# ---- 옆으로 누운 화면 세우기 ----

def lay_down(code):
    """흰 화면 기기 사진과 글자 박스를 통째로 90° 돌린다. code=시계방향이면 글자가 위→아래로 읽힘."""
    image = draw_white_device()
    rotated = cv2.rotate(image, code)
    h, w = image.shape[:2]
    if code == cv2.ROTATE_90_CLOCKWISE:
        move = lambda p: np.stack([h - 1 - p[:, 1], p[:, 0]], 1)           # (x, y) → (h-1-y, x)
    else:
        move = lambda p: np.stack([p[:, 1], w - 1 - p[:, 0]], 1)           # (x, y) → (y, w-1-x)
    texts = [(t, move(box).astype(np.float32)) for t, box in WHITE_TEXTS]
    upright = move(corners(WHITE))                                          # 원래 화면의 좌상·우상·우하·좌하가 간 자리
    return rotated, texts, upright.astype(np.float32)


def text_on_top_left(crop):
    """가짜 OCR: 바로 선 화면이면 글자 줄(어두운 점)이 왼쪽 위에 몰려 있다."""
    h, w = crop.shape[:2]
    return [("x", float((cv2.cvtColor(crop[: h // 2, : w // 2], cv2.COLOR_BGR2GRAY) < 100).mean()))]


def test_sideways_screen_is_stood_up():
    rotated, texts, upright = lay_down(cv2.ROTATE_90_CLOCKWISE)
    crop, matrix = cut(rotated, texts)                          # 기본 방향 = 이 방향
    assert crop.shape[1] > crop.shape[0]                                   # 가로로 긴 화면으로 섬
    assert_maps_to_frame(matrix, crop, upright, 0.05)


def test_sideways_direction_from_read_text():
    rotated, texts, upright = lay_down(cv2.ROTATE_90_COUNTERCLOCKWISE)     # 기본과 반대로 누움
    crop, matrix = cut(rotated, texts, text_on_top_left)
    assert_maps_to_frame(matrix, crop, upright, 0.05)
    for crop, matrix, _ in cuts(rotated, texts, text_on_top_left):
        assert_maps_to_frame(matrix, crop, upright, 0.05)


def test_upright_screen_is_not_turned():
    crop, matrix = cut(draw_white_device(), WHITE_TEXTS, text_on_top_left)
    assert_maps_to_frame(matrix, crop, corners(WHITE), 0.05)


# ---- 입구: 사진만 넣기 (rapidocr가 깔려 있을 때만) ----

def test_entry_takes_image_only():
    pytest.importorskip("rapidocr")
    from ktl_readers.screen import extract_screen, extract_screens, locate_screen
    image = draw_white_device()
    crops = {name: (crop, matrix) for crop, matrix, name in extract_screens(image)}
    assert set(crops) == {"베이스", "이진"} and all(crop.shape[1] == 800 for crop, _ in crops.values())
    assert_maps_to_frame(crops["이진"][1], crops["이진"][0], corners(WHITE), 0.05)
    # 로고 글자가 없어 기기를 모르면 베이스는 흰 화면을 넓혀 잡는다 → 하나만 고르면 베이스(넓은 쪽)가 될 수 있음 (프로토타입 한계)
    crop, matrix = extract_screen(image)
    assert crop.shape[1] == 800
    quad, how = locate_screen(image)
    assert quad.shape == (4, 2) and how
