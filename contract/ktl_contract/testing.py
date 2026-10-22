"""계약 테스트 도우미. 각 Reader/Selector 테스트에서 불러 쓴다.

    from ktl_contract.testing import check_reader
    def test_cert_contract(tmp_path):
        check_reader(get_reader("cert"), "readers/synthetic/cert/0001.jpg", "cert")
"""
from __future__ import annotations

import time
from typing import Any

from . import Reader, ReadError, ReadResult, Selector, SelectResult, Value, Warning

READ_LIMIT_S = 10.0


def check_value(v: Value) -> None:
    assert isinstance(v, Value), f"Value가 아님: {type(v)}"
    assert v.key and isinstance(v.key, str)
    assert isinstance(v.label, str)
    assert isinstance(v.value, str), f"{v.key}: value는 문자열이어야 함 (받은 값 {type(v.value).__name__})"
    assert v.unit is None or isinstance(v.unit, str)
    assert 0.0 <= v.confidence <= 1.0, f"{v.key}: confidence 범위 0~1 (받은 값 {v.confidence})"
    if v.bbox is not None:
        assert len(v.bbox) == 4 and all(isinstance(n, int) for n in v.bbox), f"{v.key}: bbox는 정수 4개"
        x1, y1, x2, y2 = v.bbox
        assert x1 <= x2 and y1 <= y2, f"{v.key}: bbox 좌표 순서 [x1, y1, x2, y2]"


def check_reader(reader: Any, image_path: str, item: str) -> ReadResult | None:
    """정상 사진 한 장으로 계약을 확인한다. ReadError는 허용(못 읽는 사진일 수 있음)."""
    assert isinstance(reader, Reader), "name 속성과 read(image_path, item) 메서드가 필요"
    start = time.monotonic()
    try:
        result = reader.read(image_path, item)
    except ReadError:
        return None
    elapsed = time.monotonic() - start
    assert elapsed <= READ_LIMIT_S, f"1장 {READ_LIMIT_S:.0f}초 제한 초과 ({elapsed:.1f}초)"
    assert isinstance(result, ReadResult), "read()는 ReadResult를 돌려줘야 함"
    keys = [v.key for v in result.values]
    assert len(keys) == len(set(keys)), f"같은 key가 두 번 나옴: {keys}"
    for v in result.values:
        check_value(v)
    for w in result.warnings:
        assert isinstance(w, Warning) and w.code and w.message
    return result


def check_reader_rejects(reader: Any, bad_path: str, item: str) -> None:
    """읽을 수 없는 파일(빈 파일, 이미지 아님)에는 ReadError를 내야 한다. 다른 예외는 안 됨."""
    try:
        reader.read(bad_path, item)
    except ReadError:
        return
    except Exception as e:  # noqa: BLE001
        raise AssertionError(f"ReadError 대신 {type(e).__name__} 발생: {e}") from e
    raise AssertionError("읽을 수 없는 파일인데 ReadError가 나지 않음")


def check_selector(selector: Any, paths: list[str], options: dict[str, Any]) -> SelectResult:
    import pandas as pd

    assert isinstance(selector, Selector), "name, detect, series, run이 필요"
    for p in paths:
        d = selector.detect(p)
        assert d is None or isinstance(d, dict)
    s = selector.series(paths)
    assert isinstance(s, pd.DataFrame) and "t" in s.columns, "series()는 t 칼럼이 있는 DataFrame"
    result = selector.run(paths, options)
    assert isinstance(result, SelectResult), "run()은 SelectResult를 돌려줘야 함"
    assert isinstance(result.table, pd.DataFrame) and len(result.table.columns) > 0
    assert isinstance(result.meta, dict)
    return result
