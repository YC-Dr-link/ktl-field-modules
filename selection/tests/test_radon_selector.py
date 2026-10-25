"""서버가 쓰는 패키지 로더 → 실제 Selector → 파서 경로 검증."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from ktl_contract import ReadError, Selector
from ktl_contract.fakes import FakeSelector
from ktl_selectors import detect_any, get_selector
from ktl_selectors.radon import parse_radon_path
from ktl_selectors.radon_models import RadonParseError
from ktl_selectors.radon_selector import RadonMergePendingError, RadonSelector

SYN = Path(__file__).resolve().parents[1] / "synthetic" / "radon_parser"


@pytest.fixture
def selector():
    result = get_selector("radon_merge", fake_fallback=False)
    assert isinstance(result, Selector)
    assert isinstance(result, RadonSelector)
    assert not isinstance(result, FakeSelector)
    return result


@pytest.fixture
def write_input(tmp_path):
    folder = tmp_path / "synthetic"
    folder.mkdir()

    def write(content, name="uploaded.txt"):
        path = folder / name
        path.write_bytes(content)
        return str(path)
    return write


@pytest.mark.parametrize("filename,kind,serial,interval", [
    ("chamber.csv", "radon_chamber", None, None),
    ("device400.txt", "radon_frd400", "SYNTHETIC-400", None),
    ("device500.txt", "radon_frd500", "SYNTHETIC-500", 3600),
    ("device2400.txt", "radon_frd2400", "SYNTHETIC-2400", 3600),
])
def test_server_detection_schema(selector, filename, kind, serial, interval):
    path = str(SYN / filename)
    expected = {"kind": kind, "rows": 4 if filename == "chamber.csv" else 2}
    if serial:
        expected.update(serial=serial, unit="Bq/m3")
    if interval:
        expected["interval_s"] = interval
    assert selector.detect(path) == expected
    assert detect_any(path) == ("radon_merge", expected)
    assert get_selector("radon_merge").detect(path) == expected
    assert json.loads(json.dumps(expected)) == expected


def test_frd400_regular_interval_and_csv_content(selector, write_input):
    text = (SYN / "device500.txt").read_text(encoding="utf-8")
    path = write_input(text.replace("\t", ",").encode("utf-8-sig"), "anonymous.CSV")
    assert selector.detect(path) == {"kind": "radon_frd500", "rows": 2,
                                     "serial": "SYNTHETIC-500", "unit": "Bq/m3", "interval_s": 3600}
    lines = (SYN / "device400.txt").read_text(encoding="utf-8").splitlines()
    lines[-2:] = reversed(lines[-2:])
    assert selector.detect(write_input("\n".join(lines).encode("utf-8")))["interval_s"] == 3600


@pytest.mark.parametrize("content,name", [
    (b"unrelated file", "unknown.txt"), (b"", "empty.csv"),
    (b"\xff", "broken.txt"), (b"unrelated file", "photo.jpg"),
])
def test_unknown_or_invalid_detection_is_none(selector, write_input, content, name):
    path = write_input(content, name)
    assert selector.detect(path) is None
    assert detect_any(path) is None
    with pytest.raises(RadonParseError):
        selector.series([path])


def test_unreadable_file_is_not_unknown_format(selector, tmp_path):
    with pytest.raises(ReadError, match="FILE_READ_ERROR"):
        selector.detect(str(tmp_path / "missing.csv"))


@pytest.mark.parametrize("filename,first_time", [
    ("device400.txt", datetime(2026, 1, 2, 13)),
    ("device500.txt", datetime(2026, 1, 2, 12)),
    ("device2400.txt", datetime(2026, 1, 2, 12)),
])
def test_device_series_values_and_order(selector, filename, first_time):
    frame = selector.series([str(SYN / filename)])
    assert isinstance(frame, pd.DataFrame)
    assert list(frame.columns) == ["t", "radon", "temp", "humi", "barometer"]
    assert frame.iloc[0].tolist() == [first_time, 46, 27, 31, 1023]
    assert frame.iloc[1]["radon"] == (-99 if filename == "device400.txt" else 163)
    assert frame.attrs["sources"][0]["source_file"] == filename
    assert frame.attrs["warnings"] == []


def test_chamber_series_all_rows_without_filtering(selector):
    frame = selector.series([str(SYN / "chamber.csv")])
    assert list(frame.columns) == ["t", "target_radon", "calculate_radon", "crm1_radon"]
    assert frame["target_radon"].tolist() == [0, 0, 200, 0]
    assert frame["calculate_radon"].tolist() == [0, 0, 200.1, 0]
    assert frame["crm1_radon"].tolist() == [0, 0, 50, 90]
    assert frame.iloc[-1]["t"] == datetime(2026, 10, 23, 8)
    assert frame.attrs["sources"][0]["unit"] is None


def test_multiple_files_do_not_align_or_overwrite(selector):
    frame = selector.series([str(SYN / "device400.txt"), str(SYN / "device500.txt")])
    assert len(frame) == 4 and frame.columns.is_unique
    assert [time.hour for time in frame["t"]] == [13, 12, 12, 13]
    assert frame["source_1.radon"].tolist() == [46, -99, None, None]
    assert frame["source_2.radon"].tolist() == [None, None, 46, 163]
    assert [source["serial_number"] for source in frame.attrs["sources"]] == ["SYNTHETIC-400", "SYNTHETIC-500"]
    json.dumps(frame.to_dict("records"), default=lambda time: time.isoformat(), allow_nan=False)
    repeated = selector.series([str(SYN / "device500.txt")] * 2)
    assert len(repeated) == 4 and len(repeated.columns) == 9


def test_missing_values_and_warnings_preserved(selector, write_input):
    text = (SYN / "device500.txt").read_text(encoding="utf-8")
    path = write_input(text.replace("\t046\t", "\t\t").replace("Data No: 2", "Data No: 3").encode("utf-8"))
    assert selector.detect(path)["rows"] == 2  # 실제로 읽은 측정행 수를 반환한다.
    frame = selector.series([path])
    assert frame.iloc[0]["radon"] is None
    assert frame.iloc[0]["temp"] == 27
    assert {warning["code"] for warning in frame.attrs["warnings"]} == {"MISSING_VALUE", "COUNT_MISMATCH"}


def test_empty_series_and_pending_merge(selector):
    with pytest.raises(ReadError, match="파일"):
        selector.series([])
    with pytest.raises(RadonMergePendingError, match="#13"):
        selector.run([str(SYN / "chamber.csv")], {"align": "sequence"})


def test_inputs_unchanged_after_server_calls(selector):
    paths = sorted(path for path in SYN.iterdir() if path.suffix in {".csv", ".txt"})
    before = {p: hashlib.sha256(p.read_bytes()).digest() for p in paths}
    for path in paths:
        selector.detect(str(path))
    selector.series([str(path) for path in paths])
    assert before == {p: hashlib.sha256(p.read_bytes()).digest() for p in paths}


def test_unregistered_selectors_keep_existing_fallback():
    assert isinstance(get_selector("gas_select"), FakeSelector)
    with pytest.raises(KeyError):
        get_selector("gas_select", fake_fallback=False)


def test_external_examples_through_selector(selector):
    folder = os.environ.get("RADON_EXAMPLE_DIR")
    if not folder:
        pytest.skip("RADON_EXAMPLE_DIR 미지정: 외부 예제 Selector 검증 생략")
    root = Path(folder)
    assert root.is_dir(), f"외부 예제 폴더에 접근할 수 없습니다: {root}"
    paths = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".txt"})
    assert paths, "외부 예제 CSV/TXT가 없습니다."
    for path in paths:
        before = path.read_bytes()
        parsed = parse_radon_path(str(path))
        name, detected = detect_any(str(path))
        frame = selector.series([str(path)])
        assert name == "radon_merge"
        assert detected["rows"] == len(frame) == parsed.measurement_count
        assert detected.get("serial") == parsed.serial_number
        channel = "crm1_radon" if parsed.format == "chamber" else "radon"
        assert frame[channel].tolist() == [getattr(row, channel) for row in parsed.measurements]
        assert path.read_bytes() == before
