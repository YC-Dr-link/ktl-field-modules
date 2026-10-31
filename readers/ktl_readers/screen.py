"""기기 화면(LCD) 영역 찾아 자르기. 서류 쪽 extract_top_table과 같은 모양으로 (잘린 화면, 변환 행렬)을 돌려준다.

두 방식을 따로 돌린다. 둘 다 받으려면 extract_screens, 하나만 받으려면 extract_screen.

[베이스] 색 덩어리로 찾기
1) (글자 위치가 있으면) 글자가 제일 많이 모인 곳에 여유 있게 경계 → 그 안에서 찾기
2) 화면 찾기: 색 차이 키우기 → 색 6개 덩어리로 나누기 → '다른 단색(몸체)에 둘러싸인 네모난 덩어리'
   → 못 찾으면 색 키우기 없이 한 번 더 → 고른 네모 안에 더 작은 화면이 있으면 그걸로
3) 경계 안에서 실패하면 사진 전체로 다시
4) 다듬기: (글자 내용이 있고 기기를 알아보면) 화면 안 글자가 다 들어오게 넓히기
          (아니면) 흰 화면이면 사방 20% 넓히기

[이진] 흑백으로 바꿔 검은 테두리(액자) 안 흰 네모 찾기
1) 사진 전체를 흑백 두 가지로 나누기 → 끊긴 테두리 잇기
2) 검은 틀 안의 흰 구멍 중 '확실한 네모'만 (네 변이 테두리 위, 모서리 거의 직각)
3) 글자 무리의 글자가 하나라도 들어 있는 네모 중 제일 많이 든 것 (로고 몇 개는 밖이어도 됨)

[대조] (하나만 고를 때) 이진이 베이스 안에 있으면 같은 화면 → 크기가 비슷하면 이진(더 딱 맞음),
       베이스가 훨씬 넓으면 베이스. 반쯤 겹치면 같은 화면을 나눠 잡은 것 → 둘을 합친다.
       서로 다른 곳이면 화면 안 글자가 더 많이 든 쪽, 같으면 베이스 + 사람 확인 표시.
쓰는 법: extract_screens(사진) — 사진만 넣으면 된다. 원본 글자 읽기(rapidocr)는 안에서 한다 (없으면 베이스만).
"""

import re
from collections.abc import Callable
from difflib import SequenceMatcher

import cv2
import numpy as np

from ktl_contract import ReadError

from .devices import PROFILES
from .preprocess import order_corners, warp

WORK = 800                 # 찾기는 긴 변 800px로 줄여서 (속도)
TEXT_MARGIN = 0.8          # 글자 무리에 두는 여유 (무리 크기의 80%)
WHITE_SATURATION = 25      # 화면 안 평균 채도가 이보다 낮으면 흰 화면 (실제 견본: MEZUS 12~17, 나머지 40+)
WHITE_WIDEN = 0.2          # 흰 화면이면 사방으로 넓히는 비율
FRAME_EDGE_TOL = 8         # 이진 네모의 변이 실제 테두리에서 이만큼(px, 800 기준) 안이면 테두리 위로 본다 (렌즈 휨 대비)
FRAME_EDGE_COVER = 0.7     # 네 변의 70% 이상이 테두리 위여야 네모 (중간이 조금 끊겨도 됨)
FRAME_ANGLE_SLACK = 15     # 모서리가 90°±15° 안이어야 네모 (사다리꼴 탈락)
SAME_INSIDE = 0.9          # 이진이 베이스 네모 안에 90% 이상 → 같은 화면 (실제 견본 17장: 0.98~1.00)
SAME_AREA = 0.85           # 같은 화면이고 넓이비(이진/베이스)가 이 이상이면 이진, 미만이면 베이스 (MEZUS: 0.60~0.83)
PART_INSIDE = 0.5          # 50~90%만 겹치면 같은 화면을 나눠 잡은 것 → 둘을 합친다 (MEZUS 07: 베이스=위쪽, 이진=아래쪽)
SIDEWAYS_TALL = 1.5        # 글자 박스 세로가 가로의 1.5배 이상이면 누운 글자
SIDEWAYS_SHARE = 0.6       # 화면 안 글자의 60% 이상이 누웠으면 화면이 누운 것 (세로로 단 Alicat)

Texts = list[tuple[str, np.ndarray]]   # (글자, 꼭짓점 4개) 목록. 위치만 있으면 글자는 ""
ReadText = Callable[[np.ndarray], list[tuple[str, float]]]   # 사진 → [(글자, 점수 0~1), ...] (Reader의 OCR)


def _shrink(image):
    scale = min(1.0, WORK / max(image.shape[:2]))
    if scale == 1.0:
        return image, scale
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), scale


def _boost(image):
    """색 차이 키우기: 밝기 대비(CLAHE) + 채도 1.6배."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
    hsv = cv2.cvtColor(cv2.cvtColor(lab, cv2.COLOR_LAB2BGR), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.6, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def _touches_border(box, w, h, margin=3):
    return box[:, 0].min() < margin or box[:, 1].min() < margin or box[:, 0].max() > w - margin or box[:, 1].max() > h - margin


def _ring_contrast(lab, mask):
    """mask 안쪽 평균색과 바로 바깥 띠 평균색의 거리."""
    pad = max(5, int(0.04 * np.sqrt(mask.sum() / 255)))
    ring = cv2.subtract(cv2.dilate(mask, np.ones((2 * pad + 1, 2 * pad + 1), np.uint8)), mask)
    if not ring.any() or not mask.any():
        return 0.0
    return float(np.linalg.norm(np.array(cv2.mean(lab, mask)[:3]) - np.array(cv2.mean(lab, ring)[:3])))


def _find_block(image, k=6):
    """색을 k개로 나눠 '다른 단색에 둘러싸인 네모난 덩어리' 중 점수가 가장 높은 것."""
    h, w = image.shape[:2]
    lab = cv2.cvtColor(cv2.GaussianBlur(image, (7, 7), 0), cv2.COLOR_BGR2LAB)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    cv2.setRNGSeed(0)                                   # 같은 사진은 늘 같은 결과 (k-means 시작점 고정)
    _, labels, _ = cv2.kmeans(lab.reshape(-1, 3).astype(np.float32), k, None, criteria, 2, cv2.KMEANS_PP_CENTERS)
    labels = labels.reshape(h, w)
    best, best_score = None, 0.0
    for cluster in range(k):
        # 글자 때문에 생긴 구멍을 메운다
        mask = cv2.morphologyEx(np.uint8(labels == cluster) * 255, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
            area = cv2.contourArea(contour)
            rect = cv2.minAreaRect(contour)
            rect_area = rect[1][0] * rect[1][1]
            box = cv2.boxPoints(rect)
            # 조건: 사진의 1% 이상, 네모답고(80%), 사진 끝에 안 닿고, 너무 크지 않음
            if area < 0.01 * w * h or rect_area == 0 or area / rect_area < 0.8 \
                    or _touches_border(box, w, h) or rect_area > 0.8 * w * h:
                continue
            filled = np.zeros((h, w), np.uint8)
            cv2.drawContours(filled, [contour], -1, 255, -1)
            pad = max(5, int(0.04 * np.sqrt(area)))
            ring = cv2.subtract(cv2.dilate(filled, np.ones((2 * pad + 1, 2 * pad + 1), np.uint8)), filled)
            around = labels[ring > 0]
            around = around[around != cluster]
            if around.size == 0:
                continue
            surround = np.bincount(around).max() / around.size   # 둘러싼 띠가 한 가지 색일수록 1
            score = (area / rect_area) * surround * np.sqrt(area / (w * h))
            if score > best_score:
                best, best_score = box.astype(np.float32), score
    return best


def _edge_quad(image, max_area):
    """경계선에서 네모 후보를 찾아 안팎 색 차이가 큰 것 (몸체 안 화면 재확인용). max_area보다 큰 후보는 뺀다."""
    h, w = image.shape[:2]
    lab = cv2.cvtColor(cv2.GaussianBlur(image, (5, 5), 0), cv2.COLOR_BGR2LAB)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    med = np.median(gray)
    edges = cv2.dilate(cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 0.5 * med, 1.2 * med), np.ones((3, 3), np.uint8))
    best, best_score = None, 0.0
    for contour in cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]:
        if cv2.contourArea(contour) < 0.01 * w * h:
            continue
        hull = cv2.convexHull(contour)
        quad = cv2.approxPolyDP(hull, 0.03 * cv2.arcLength(hull, True), True)
        if len(quad) != 4:
            rect = cv2.minAreaRect(hull)
            if cv2.contourArea(hull) < 0.85 * rect[1][0] * rect[1][1]:
                continue
            quad = cv2.boxPoints(rect)
        quad = quad.reshape(4, 2).astype(np.int32)
        if _touches_border(quad, w, h) or cv2.contourArea(quad) > max_area:
            continue
        mask = np.zeros((h, w), np.uint8)
        cv2.fillConvexPoly(mask, quad, 255)
        score = _ring_contrast(lab, mask) * np.sqrt(cv2.contourArea(quad) / (w * h))
        if score > best_score:
            best, best_score = quad.astype(np.float32), score
    return best


def _refine_inside(image, quad):
    """고른 네모가 몸체 전체면 그 안의 화면으로 바꾼다."""
    x, y, bw, bh = cv2.boundingRect(quad.astype(np.int32))
    x0, y0 = max(0, x - 4), max(0, y - 4)
    sub = image[y0:y + bh + 4, x0:x + bw + 4]
    if min(sub.shape[:2]) < 40:
        return quad
    inner = _edge_quad(sub, max_area=0.85 * cv2.contourArea(quad))    # 바깥 네모 자신은 후보에서 뺀다
    if inner is None or cv2.contourArea(inner) / max(1.0, cv2.contourArea(quad)) < 0.2:
        return quad
    mask = np.zeros(sub.shape[:2], np.uint8)
    cv2.fillConvexPoly(mask, inner.astype(np.int32), 255)
    if _ring_contrast(cv2.cvtColor(cv2.GaussianBlur(sub, (5, 5), 0), cv2.COLOR_BGR2LAB), mask) < 25:
        return quad
    return inner + np.array([x0, y0], np.float32)


def _find_in(image):
    """사진(조각) 안에서 화면 네모 4점 (그 사진 좌표). 없으면 None."""
    small, scale = _shrink(image)
    for search in (_boost(small), small):        # 색 키운 것 먼저, 안 되면 원래 색으로
        quad = _find_block(search)
        if quad is not None:
            return _refine_inside(small, quad) / scale
    return None


def _text_groups(boxes, shape):
    """글자 박스를 가까운 것끼리 묶는다. (무리 번호 그림, 박스마다 무리 번호, 박스가 가장 많은 무리 번호 or None)."""
    h, w = shape[:2]
    mask = np.zeros((h, w), np.uint8)
    for box in boxes:
        cv2.fillPoly(mask, [box.astype(np.int32)], 255)
    gap = max(5, int(0.03 * max(h, w)))          # 사진 긴 변의 3% 안이면 같은 무리
    count, labels = cv2.connectedComponents(cv2.dilate(mask, np.ones((gap, gap), np.uint8)))
    if count < 2:
        return labels, [], None
    groups = []
    for box in boxes:
        cx, cy = box.mean(0).astype(int)
        groups.append(int(labels[min(max(cy, 0), h - 1), min(max(cx, 0), w - 1)]))
    votes = np.bincount(groups, minlength=count)
    votes[0] = 0
    return labels, groups, int(votes.argmax())


def _densest_text(boxes, shape):
    """박스가 가장 많은 글자 무리의 (x0, y0, x1, y1)."""
    labels, _, top = _text_groups(boxes, shape)
    if top is None:
        return None
    ys, xs = np.where(labels == top)
    return xs.min(), ys.min(), xs.max(), ys.max()


def find_screen(image: np.ndarray, texts: Texts | None = None) -> np.ndarray:
    """화면 네모 꼭짓점 4개 (받은 사진 좌표). 못 찾으면 ReadError."""
    h, w = image.shape[:2]
    if texts:
        found = _densest_text([box for _, box in texts], image.shape)
        if found is not None:
            x0, y0, x1, y1 = found
            px, py = int((x1 - x0) * TEXT_MARGIN), int((y1 - y0) * TEXT_MARGIN)
            rx0, ry0, rx1, ry1 = max(0, x0 - px), max(0, y0 - py), min(w, x1 + px), min(h, y1 + py)
            quad = _find_in(image[ry0:ry1, rx0:rx1])
            if quad is not None:
                quad = quad + np.array([rx0, ry0], np.float32)
                center = (float(x0 + x1) / 2, float(y0 + y1) / 2)
                if cv2.pointPolygonTest(quad.reshape(-1, 1, 2), center, False) >= 0:   # 글자 무리 한가운데를 품어야 함
                    return quad
    quad = _find_in(image)                           # 경계 안에서 실패 → 사진 전체로
    if quad is None:
        raise ReadError("화면을 찾지 못함")
    return quad


def _norm(text):
    return re.sub(r"\s+", "", text).lower()


def _hit(key, text):
    if key.startswith("re:"):
        return re.search(key[3:], text) is not None
    # 로고 글자가 살짝 틀려도(ZALICAT) 맞다고 본다
    return key in text or (len(key) >= 6 and SequenceMatcher(None, key, text).ratio() >= 0.8)


def _readable(texts, shape):
    """내용이 있는 글자만, 사진 왼쪽 아래 카메라 도장 자리는 뺀다."""
    h, w = shape[:2]
    out = []
    for text, box in texts:
        cx, cy = box.mean(0)
        if text and not (cx < 0.5 * w and cy > 0.85 * h):
            out.append((_norm(text), box))
    return out


def identify_device(texts: Texts, shape) -> str | None:
    """프로필의 id 글자가 가장 많이 맞는 기기 이름. 없으면 None (기본 크롭 사용)."""
    items = _readable(texts, shape)
    best, best_score = None, 0
    for name, profile in PROFILES.items():
        score = sum(any(_hit(key, t) for t, _ in items) for key in profile["id"])
        if score > best_score:
            best, best_score = name, score
    return best


def _expand_to_texts(image, quad, texts, profile):
    """화면 안에 있어야 할 글자가 크롭 밖이면 넣을 만큼 넓힌다. 화면 밖 글자가 들어오면 취소."""
    h, w = image.shape[:2]
    items = _readable(texts, image.shape)
    inner = [box for t, box in items if any(_hit(key, t) for key in profile["screen"])]
    if not inner:
        return quad
    (qx0, qy0), (qx1, qy1) = quad.min(0), quad.max(0)
    points = np.vstack(inner)
    (tx0, ty0), (tx1, ty1) = points.min(0), points.max(0)
    if tx0 >= qx0 and ty0 >= qy0 and tx1 <= qx1 and ty1 <= qy1:
        return quad                                  # 이미 다 들어 있음
    m = 0.6 * float(np.median([box[:, 1].max() - box[:, 1].min() for box in inner]))   # 글자 높이의 60% 여유
    x0, y0 = max(0, min(qx0, tx0 - m)), max(0, min(qy0, ty0 - m))
    x1, y1 = min(w - 1, max(qx1, tx1 + m)), min(h - 1, max(qy1, ty1 + m))
    for t, box in items:
        if any(_hit(key, t) for key in profile["outside"]):
            cx, cy = box.mean(0)
            if x0 < cx < x1 and y0 < cy < y1 and not (qx0 < cx < qx1 and qy0 < cy < qy1):
                return quad
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float32)


def _quad_from_texts(texts, profile, shape):
    """화면 찾기가 실패했을 때: 기기의 '화면 안 글자'가 퍼진 범위 + 글자 높이만큼 여유를 화면으로 본다."""
    h, w = shape[:2]
    inner = [box for t, box in _readable(texts, shape) if any(_hit(key, t) for key in profile["screen"])]
    if len(inner) < 2:
        return None
    points = np.vstack(inner)
    m = float(np.median([box[:, 1].max() - box[:, 1].min() for box in inner]))
    x0, y0 = max(0, points[:, 0].min() - m), max(0, points[:, 1].min() - m)
    x1, y1 = min(w - 1, points[:, 0].max() + m), min(h - 1, points[:, 1].max() + m)
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float32)


def _widen_if_white(image, quad):
    """화면 안 평균 채도가 낮으면(흰 화면) 사방으로 넓힌다. 흰 UI가 몸체랑 색이 비슷해 안쪽 표만 잡히는 경우 대비."""
    h, w = image.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(mask, quad.astype(np.int32), 255)
    if cv2.mean(cv2.cvtColor(image, cv2.COLOR_BGR2HSV), mask)[1] >= WHITE_SATURATION:
        return quad
    center = quad.mean(0)
    wide = center + (quad - center) * (1 + 2 * WHITE_WIDEN)
    wide[:, 0] = wide[:, 0].clip(0, w - 1)
    wide[:, 1] = wide[:, 1].clip(0, h - 1)
    return wide.astype(np.float32)


def _color_quad(image, texts, device):
    """[베이스] 방식 최종 네모 (찾기 + 다듬기). 못 찾으면 None."""
    try:
        quad = find_screen(image, texts)
    except ReadError:
        # 색으로 못 찾았어도 기기를 알아봤으면 화면 안 글자 범위로 추정한다
        return _quad_from_texts(texts, PROFILES[device], image.shape) if device else None
    if device is not None:
        return _expand_to_texts(image, quad, texts, PROFILES[device])
    return _widen_if_white(image, quad)


def _bridge_gaps(dark):
    """흑백 그림에서 같은 직선 위에 있는 두 선 조각 사이 틈을 이어 그린다 (중간이 끊긴 테두리 잇기)."""
    h, w = dark.shape[:2]
    segments = cv2.createLineSegmentDetector().detect(dark)[0]
    if segments is None:
        return
    segments = segments.reshape(-1, 4)
    lengths = np.hypot(segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1])
    segments = segments[lengths > 0.03 * max(h, w)]
    for i in range(len(segments)):
        start, end = segments[i, :2], segments[i, 2:]
        along = (end - start) / np.linalg.norm(end - start)
        normal = np.array([-along[1], along[0]])
        for other in segments[i + 1:]:
            p, q = other[:2], other[2:]
            if abs(np.dot(along, (q - p) / np.linalg.norm(q - p))) < np.cos(np.radians(3)):
                continue                                                # 방향이 3° 넘게 다름
            if max(abs(np.dot(p - start, normal)), abs(np.dot(q - start, normal))) > 4:
                continue                                                # 같은 줄 위가 아님
            a0, a1 = 0.0, float(np.dot(end - start, along))
            b0, b1 = sorted([float(np.dot(p - start, along)), float(np.dot(q - start, along))])
            if b0 > a1:
                gap, t0, t1 = b0 - a1, a1, b0
            elif a0 > b1:
                gap, t0, t1 = a0 - b1, b1, a0
            else:
                continue                                                # 이미 겹침
            if 3 < gap < 0.3 * max(h, w):
                cv2.line(dark, tuple(int(v) for v in start + along * t0), tuple(int(v) for v in start + along * t1), 255, 5)


def _edge_cover(quad, contour):
    """네모 네 변 위 점 중 실제 테두리에서 FRAME_EDGE_TOL 안인 비율. 안쪽을 글자가 파먹은 건 상관없다."""
    points = []
    for i in range(4):
        a, b = quad[i].astype(float), quad[(i + 1) % 4].astype(float)
        n = max(2, int(np.linalg.norm(b - a) / 3))
        points += [a + (b - a) * k / n for k in range(n)]
    contour = contour.reshape(-1, 1, 2).astype(np.float32)
    return float(np.mean([abs(cv2.pointPolygonTest(contour, (float(x), float(y)), True)) <= FRAME_EDGE_TOL
                          for x, y in points]))


def _right_angles(quad):
    for i in range(4):
        u, v = quad[i - 1] - quad[i], quad[(i + 1) % 4] - quad[i]
        cos = np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9)
        if abs(np.degrees(np.arccos(np.clip(cos, -1, 1))) - 90) > FRAME_ANGLE_SLACK:
            return False
    return True


def _frame_quads(image):
    """[이진] 사진 전체를 흑백으로 → 검은 틀 안의 흰 구멍 중 확실한 네모들 (받은 사진 좌표)."""
    small, scale = _shrink(image)
    h, w = small.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    _, dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)    # 어두운 곳 = 흰색
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))         # 작은 틈 메우기
    _bridge_gaps(dark)
    contours, hierarchy = cv2.findContours(dark, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    quads = []
    for contour, (_, _, _, parent) in zip(contours, hierarchy[0] if hierarchy is not None else []):
        if parent < 0 or cv2.contourArea(contour) < 0.01 * w * h:      # 부모가 있어야 구멍
            continue
        hull = cv2.convexHull(contour)
        for eps in (0.02, 0.03, 0.04, 0.05, 0.06):                     # 둥근 모서리 → 꼭짓점 4개가 될 때까지
            quad = cv2.approxPolyDP(hull, eps * cv2.arcLength(hull, True), True).reshape(-1, 2).astype(np.float32)
            if len(quad) <= 4:
                break
        if (len(quad) == 4 and cv2.isContourConvex(quad.reshape(-1, 1, 2)) and _right_angles(quad)
                and _edge_cover(quad, contour) >= FRAME_EDGE_COVER
                and not _touches_border(quad, w, h) and cv2.contourArea(quad) <= 0.8 * w * h):
            quads.append(quad / scale)
    return quads


def find_frame(image: np.ndarray, texts: Texts) -> np.ndarray | None:
    """[이진] 글자 무리의 글자가 가장 많이 든 이진 네모. 하나도 안 들면 None."""
    boxes = [box for _, box in texts]
    _, groups, top = _text_groups(boxes, image.shape)
    if top is None:
        return None
    centers = [box.mean(0) for box, g in zip(boxes, groups) if g == top]
    best, best_count = None, 0
    for quad in _frame_quads(image):
        polygon = quad.reshape(-1, 1, 2)
        count = sum(cv2.pointPolygonTest(polygon, (float(x), float(y)), False) >= 0 for x, y in centers)
        if count > best_count or (count == best_count and count and cv2.contourArea(quad) < cv2.contourArea(best)):
            best, best_count = quad, count
    return best


def _inside(inner, outer, shape):
    """inner 네모 넓이 중 outer 네모 안에 든 비율, inner/outer 넓이비."""
    a, b = np.zeros(shape[:2], np.uint8), np.zeros(shape[:2], np.uint8)
    cv2.fillConvexPoly(a, inner.astype(np.int32), 1)
    cv2.fillConvexPoly(b, outer.astype(np.int32), 1)
    return (a & b).sum() / max(1, a.sum()), a.sum() / max(1, b.sum())


def _screen_text_count(quad, texts, device, shape):
    """네모 안에 든 '화면 안 글자' 수. 기기를 모르면 내용 있는 글자 전부."""
    keys = PROFILES[device]["screen"] if device else None
    polygon = quad.reshape(-1, 1, 2).astype(np.float32)
    return sum(cv2.pointPolygonTest(polygon, tuple(float(v) for v in box.mean(0)), False) >= 0
               for t, box in _readable(texts, shape) if keys is None or any(_hit(k, t) for k in keys))


def _both(image, texts):
    """(기기, 베이스 네모 or None, 이진 네모 or None)."""
    device = identify_device(texts, image.shape) if texts else None
    return device, _color_quad(image, texts, device), (find_frame(image, texts) if texts else None)


def _choose(image, texts, device, color, frame):
    """두 네모 중 하나와 고른 근거.

    근거: "같음-이진" / "같음-베이스" (두 방식이 같은 화면) · "합침" (같은 화면을 나눠 잡음)
          · "베이스만" / "이진만" (한쪽만 찾음)
          · "다름-이진" / "다름-베이스" (서로 다른 곳, 화면 글자 많은 쪽) · "확인 필요" (다른데 글자 수도 같음 → 베이스)
    둘 다 못 찾으면 ReadError.
    """
    if color is None and frame is None:
        raise ReadError("화면을 찾지 못함")
    if frame is None:
        return color, "베이스만"
    if color is None:
        return frame, "이진만"
    inside, area = _inside(frame, color, image.shape)
    if inside >= SAME_INSIDE:
        return (frame, "같음-이진") if area >= SAME_AREA else (color, "같음-베이스")
    if inside >= PART_INSIDE:
        joined = cv2.boxPoints(cv2.minAreaRect(np.vstack([frame, color]).astype(np.float32)))
        joined[:, 0] = joined[:, 0].clip(0, image.shape[1] - 1)
        joined[:, 1] = joined[:, 1].clip(0, image.shape[0] - 1)
        return joined.astype(np.float32), "합침"
    in_frame = _screen_text_count(frame, texts, device, image.shape)
    in_color = _screen_text_count(color, texts, device, image.shape)
    if in_frame == in_color:
        return color, "확인 필요"
    return (frame, "다름-이진") if in_frame > in_color else (color, "다름-베이스")


def _is_sideways(quad, texts, shape):
    """화면 안 글자 박스 대부분이 세로로 길면 화면이 옆으로 누운 것."""
    polygon = quad.reshape(-1, 1, 2).astype(np.float32)
    inside = [box for t, box in _readable(texts or [], shape) if len(t) >= 2
              and cv2.pointPolygonTest(polygon, tuple(float(v) for v in box.mean(0)), False) >= 0]
    if len(inside) < 2:
        return False
    tall = sum(np.ptp(box[:, 1]) >= SIDEWAYS_TALL * np.ptp(box[:, 0]) for box in inside)
    return tall >= SIDEWAYS_SHARE * len(inside)


def _cut(image, quad, turn, width):
    """꼭짓점 순서를 돌려서 자른다. turn 1 = 글자가 위→아래로 읽히게 누운 화면을 세움, -1 = 반대, 0 = 그대로.
    회전이 변환 행렬에 같이 들어가므로 역행렬로 되돌리기는 그대로 된다."""
    return warp(image, np.roll(order_corners(quad), -turn, axis=0), width)


def _turn(image, quad, texts, read_text, width):
    """누운 화면을 세울 방향. read_text가 있으면 양쪽을 읽어 점수(점수 × 글자 수)가 높은 쪽."""
    if not texts or not _is_sideways(quad, texts, image.shape):
        return 0
    if read_text is None:
        return 1        # TODO(확인 필요): 실제 견본(세로로 단 Alicat 2장)은 모두 이 방향. 반대로 단 기기는 read_text를 넘겨야 맞음
    scores = {turn: sum(score * len(t) for t, score in read_text(_cut(image, quad, turn, width)[0])) for turn in (1, -1)}
    return max(scores, key=scores.get)


def _one(image, texts, read_text, width):
    """고른 네모 하나를 (세워서) 자른다."""
    quad, _ = _choose(image, texts, *_both(image, texts))
    return _cut(image, quad, _turn(image, quad, texts, read_text, width), width)


def _crops(image, texts, read_text, width):
    """베이스·이진 네모를 각각 (같은 방향으로 세워서) 자른다. 고른 쪽이 먼저."""
    device, color, frame = _both(image, texts)
    chosen, how = _choose(image, texts, device, color, frame)         # 둘 다 없으면 여기서 ReadError
    found = [(quad, name) for quad, name in ((color, "베이스"), (frame, "이진")) if quad is not None]
    if "이진" in how:
        found.reverse()
    turn = _turn(image, chosen, texts, read_text, width)
    return [(*_cut(image, quad, turn, width), name) for quad, name in found]


_engine = None


def _ocr(image):
    """rapidocr로 읽기 (처음 한 번만 불러온다). rapidocr가 없으면 None → 베이스만 쓴다."""
    global _engine
    if _engine is None:
        try:
            from rapidocr import RapidOCR
        except ImportError:
            return None
        _engine = RapidOCR()
    return _engine(image)


def _read_texts(image) -> Texts | None:
    """원본 사진의 글자 위치·내용 (화면 찾기·기기 알아보기·누움 판단에 씀)."""
    result = _ocr(image)
    if result is None:
        return None
    texts = result.txts or []                                    # 글자들 (아무것도 못 읽으면 None → 빈 목록)
    boxes = result.boxes if result.boxes is not None else []     # 꼭짓점들 (numpy 배열이라 `or`를 못 씀)
    return [(text, np.array(box, np.float32)) for text, box in zip(texts, boxes)]


def _read_text(image) -> list[tuple[str, float]]:
    """잘린 화면의 글자와 점수 (누운 화면 세울 방향 고르기에 씀)."""
    result = _ocr(image)
    return list(zip(result.txts or [], result.scores or [])) if result is not None else []


def extract_screens(image: np.ndarray, width: int = 800) -> list[tuple[np.ndarray, np.ndarray, str]]:
    """기기 사진 → 베이스·이진 두 방식으로 각각 자른 화면 (Reader가 둘 다 읽고 값을 대조하는 용도).

    [(잘린 화면, 변환 행렬, "베이스" 또는 "이진"), ...]. 못 찾은 방식은 빠진다 (BAM처럼 검은 테두리가 없으면 베이스만).
    고른 쪽이 먼저. 옆으로 누운 화면은 세워서 자른다. 둘 다 못 찾으면 ReadError.
    잘린 화면은 가로 800px, 행렬은 받은 사진 → 잘린 화면 (역행렬로 bbox를 받은 사진 좌표로 되돌린다).
    """
    texts = _read_texts(image)
    return _crops(image, texts, _read_text if texts is not None else None, width)


def extract_screen(image: np.ndarray, width: int = 800) -> tuple[np.ndarray, np.ndarray]:
    """기기 사진 → 화면 하나만 (두 방식 중 고른 쪽, 같은 화면을 나눠 잡았으면 합친 것). (잘린 화면, 변환 행렬)."""
    texts = _read_texts(image)
    return _one(image, texts, _read_text if texts is not None else None, width)


def locate_screen(image: np.ndarray) -> tuple[np.ndarray, str]:
    """화면 네모 꼭짓점 4개 (받은 사진 좌표)와 고른 근거 (_choose 설명 참고)."""
    texts = _read_texts(image)
    return _choose(image, texts, *_both(image, texts))
