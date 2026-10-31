"""B-3 Reader 공통 전처리: 사진 열기, 서류 회전, 서류 영역 찾아 자르기. 기기 화면(LCD) 자르기·회전은 screen.py."""

import cv2
import numpy as np

from ktl_contract import ReadError


def load_image(image_path: str) -> np.ndarray:
    """사진을 BGR 배열로 연다. 빈 파일·이미지가 아닌 파일이면 ReadError(에러)."""
    # cv2.imread는 윈도우에서 한글 경로를 못 읽는다 → 파일을 바이트로 읽고(np.fromfile) cv.imdecode 읽어오기
    try:
        data = np.fromfile(image_path, np.uint8)
    except OSError as error:
        raise ReadError(f"사진을 열 수 없음: {image_path}") from error
    image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if image is None:
        raise ReadError(f"사진을 열 수 없음: {image_path}")
    return image


def find_table_lines(image: np.ndarray) -> np.ndarray:
    """이진처리:표 전용 이진 처리후 가로 세로 막대를 이용해 후보정"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # 글자·선이 흰색(255)이 되도록 뒤집어서 이진화한다. 기준값은 Otsu가 자동으로 고른다.
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    height, width = binary.shape
    # 가로로 긴 막대(사진 폭의 1/20)로 열기 → 막대보다 짧은 글자는 지워지고 가로선만 남는다.
    horizontal_kernel = np.ones((1, max(20, width // 20)), np.uint8)
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    # 세로선도 같은 원리 (사진 높이의 1/30).
    vertical_kernel = np.ones((max(20, height // 30), 1), np.uint8)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)

    lines = cv2.bitwise_or(horizontal, vertical)
    # 선이 살짝 끊긴 곳을 두껍게 해서 이어 붙인다.
    return cv2.dilate(lines, np.ones((3, 3), np.uint8))


def order_corners(points: np.ndarray) -> np.ndarray:
    """open cv에서는 찾은 네모 박스의 좌표가 정렬되어야 하기에 정렬 해주는 함수"""
    points = points.reshape(4, 2).astype(np.float32)
    total = points.sum(axis=1)          # x + y: 좌상이 가장 작고 우하가 가장 큼
    diff = np.diff(points, axis=1)[:, 0]  # y - x: 우상이 가장 작고 좌하가 가장 큼
    return np.array([points[total.argmin()],  # 1. x+y 제일 작은 점 → 좌상
                     points[diff.argmin()],  # 2. y−x 제일 작은 점 → 우상
                     points[total.argmax()],  # 3. x+y 제일 큰 점  → 우하
                     points[diff.argmax()]],  # 4. y−x 제일 큰 점  → 좌하
                    np.float32)


def find_tables(lines: np.ndarray) -> list[tuple[int, int, np.ndarray]]:
    """선 마스크에서 큰 표들을 찾아 위에서부터 (y, 높이, 윤곽선) 목록으로 돌려준다."""
    height, width = lines.shape
    contours, _ = cv2.findContours(lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tables = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        # 표 크기 조건: 폭은 사진의 60% 이상, 높이는 10% 이상 (제목 밑줄 같은 선은 빠짐)
        if w > width * 0.6 and h > height * 0.1:
            tables.append((y, h, contour))
    return sorted(tables, key=lambda table: table[0])


def rotation_matrix(code: int, width: int, height: int) -> np.ndarray:
    """cv2.rotate(code)가 하는 좌표 이동을 3x3 행렬로 만든다 (원본 좌표 → 돌린 사진 좌표)."""
    if code == cv2.ROTATE_90_CLOCKWISE:   # (x, y) → (height-1-y, x)
        return np.array([[0, -1, height - 1],[1, 0, 0], [0, 0, 1]], np.float64)
    if code == cv2.ROTATE_180:            # (x, y) → (width-1-x, height-1-y)
        return np.array([[-1, 0, width - 1], [0, -1, height - 1], [0, 0, 1]], np.float64)
    raise ValueError(f"지원하지 않는 회전: {code}")


def fix_orientation(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """기록부가 바로 서도록 90°·180° 단위로 돌린다. (돌린 사진, 원본 → 돌린 사진 변환 행렬)을 돌려준다.

    기록부는 세로로 긴 A4이고, 위쪽 표(기기 정보)가 아래쪽 표(검사 이력)보다 작다.
    1) 가로로 누워 있으면 90° 돌려 세운다.
    2) 위·아래 큰 표 중 작은 표가 아래에 있으면 거꾸로 선 것 → 180° 돌린다.
    """
    matrix = np.eye(3)
    height, width = image.shape[:2]
    if width > height:
        matrix = rotation_matrix(cv2.ROTATE_90_CLOCKWISE, width, height) @ matrix
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    tables = find_tables(find_table_lines(image))
    if len(tables) >= 2:
        first_height, last_height = tables[0][1], tables[-1][1]
        if first_height > last_height:  # 작은 표가 아래에 있음 → 거꾸로
            height, width = image.shape[:2]
            matrix = rotation_matrix(cv2.ROTATE_180, width, height) @ matrix
            image = cv2.rotate(image, cv2.ROTATE_180)
    return image, matrix


def find_top_table(lines: np.ndarray) -> np.ndarray:
    """선 마스크에서 위쪽 큰 표의 꼭짓점 4개를 찾는다. 없으면 ReadError."""
    tables = find_tables(lines)
    if not tables:
        raise ReadError("표를 찾지 못함")
    _, _, top = tables[0]  # 가장 위에 있는 표
    hull = cv2.convexHull(top)
    corners = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
    if len(corners) != 4:  # 꼭짓점이 4개로 안 줄면 감싸는 최소 사각형으로 대신한다
        corners = cv2.boxPoints(cv2.minAreaRect(hull))
    return order_corners(corners)


def warp(image: np.ndarray, corners: np.ndarray, width: int = 1400) -> tuple[np.ndarray, np.ndarray]:
    """문서 상단 기록부 표 크롭"""
    top_left, top_right, bottom_right, bottom_left = corners
    box_width = (np.linalg.norm(top_right - top_left) + np.linalg.norm(bottom_right - bottom_left)) / 2 #기울기 보정 수평
    box_height = (np.linalg.norm(bottom_left - top_left) + np.linalg.norm(bottom_right - top_right)) / 2 #기울기 보정 수직
    height = round(width * box_height / box_width)  # 원래 가로세로 비율 유지
    target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32)
    matrix = cv2.getPerspectiveTransform(corners, target)
    return cv2.warpPerspective(image, matrix, (width, height)), matrix


def extract_top_table(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """기록부 사진 → 위쪽 표(기기 정보)를 바로 세워 반듯하게 자른 사진.

    (잘라 낸 표, 받은 사진 → 잘라 낸 표 변환 행렬)을 돌려준다.
    행렬의 역행렬로 표 안의 좌표를 받은 사진 좌표(계약의 bbox 기준)로 되돌릴 수 있다.
    """
    upright, rotation = fix_orientation(image)
    corners = find_top_table(find_table_lines(upright))
    table, perspective = warp(upright, corners)
    return table, perspective @ rotation
