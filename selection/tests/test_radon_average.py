import copy
import csv
import io
import json
from pathlib import Path

import pytest

from ktl_selectors.radon import parse_radon_file, parse_radon_path
from ktl_selectors.radon_average import average_before_zero_air_purge
from ktl_selectors.radon_models import RadonParseError

SYN = Path(__file__).resolve().parents[1] / "synthetic"
FIXTURE = SYN / "radon_average" / "chamber.csv"


def parse_rows(change):
    rows = list(csv.reader(io.StringIO(FIXTURE.read_text(encoding="utf-8"))))
    change(rows)
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    return parse_radon_file("synthetic.csv", stream.getvalue().encode("utf-8-sig"))


@pytest.mark.parametrize("column,expected", [
    ("crm1_radon", 6.5), ("target_radon", 200), ("calculate_radon", 206.5),
])
def test_exact_twelve_rows_and_independent_channels(column, expected):
    before = FIXTURE.read_bytes()
    parsed = parse_radon_path(str(FIXTURE))
    original = copy.deepcopy(parsed)
    result = average_before_zero_air_purge(parsed, column=column)
    assert result["average"] == pytest.approx(expected)
    assert result["count"] == 12
    assert result["column"] == column
    assert result["measurement_rows"] == list(range(3, 15))
    assert result["source_lines"] == list(range(5, 17))
    assert result["start_time"] == "2026-01-03T02:00:00"
    assert result["end_time"] == "2026-01-03T13:00:00"
    assert result["zero_air_purge_row"] == 15
    assert result["zero_air_purge_line"] == 17
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert parsed == original and FIXTURE.read_bytes() == before


def test_status_spacing_and_input_order_preserved():
    def change(rows):
        rows[16][1] = "  Zero   Air Purge "
        rows[4][0] = "2026-01-02 00:00:00"  # 시각순으로 재정렬하지 않는다.
    result = average_before_zero_air_purge(parse_rows(change), column="crm1_radon")
    assert result["measurement_rows"] == list(range(3, 15))
    assert result["average"] == 6.5


def test_missing_values_are_not_skipped_or_replaced():
    parsed = parse_rows(lambda rows: rows[8].__setitem__(4, ""))
    with pytest.raises(RadonParseError) as caught:
        average_before_zero_air_purge(parsed, column="crm1_radon")
    assert caught.value.code == "INVALID_AVERAGE_VALUE" and caught.value.line == 9
    # 다른 채널이나 구간 밖의 빈 값이 선택 열의 평균을 바꾸지 않는다.
    assert average_before_zero_air_purge(parsed, column="calculate_radon")["average"] == 206.5
    outside = parse_rows(lambda rows: rows[2].__setitem__(4, ""))
    assert average_before_zero_air_purge(outside, column="crm1_radon")["average"] == 6.5


@pytest.mark.parametrize("length", [0, 11, 12, 13])
def test_window_boundary(length):
    parsed = parse_radon_path(str(FIXTURE))
    parsed.measurements = parsed.measurements[:length] + parsed.measurements[14:16]
    if length < 12:
        with pytest.raises(RadonParseError, match="INSUFFICIENT_AVERAGE_ROWS"):
            average_before_zero_air_purge(parsed, column="crm1_radon")
    else:
        result = average_before_zero_air_purge(parsed, column="crm1_radon")
        assert result["count"] == 12
        assert result["measurement_rows"] == list(range(length - 11, length + 1))


def test_missing_or_ambiguous_purge():
    parsed = parse_rows(lambda rows: rows.__delitem__(slice(16, 18)))
    with pytest.raises(RadonParseError, match="PURGE_NOT_FOUND"):
        average_before_zero_air_purge(parsed, column="crm1_radon")
    parsed = parse_rows(lambda rows: rows[8].__setitem__(1, "Zero Air Purge"))
    with pytest.raises(RadonParseError, match="AMBIGUOUS_PURGE"):
        average_before_zero_air_purge(parsed, column="crm1_radon")


def test_device_or_unknown_column_rejected():
    device = parse_radon_path(str(SYN / "radon_parser" / "device500.txt"))
    with pytest.raises(RadonParseError, match="CHAMBER_REQUIRED"):
        average_before_zero_air_purge(device, column="radon")
    parsed = parse_radon_path(str(FIXTURE))
    with pytest.raises(RadonParseError, match="INVALID_AVERAGE_COLUMN"):
        average_before_zero_air_purge(parsed, column="temp")


def test_supplied_chamber_when_available():
    path = SYN / "radon_merge" / "1023.csv"
    if not path.exists():
        pytest.skip("로컬 합성 예제는 커밋 대상에서 제외됨")
    before = path.read_bytes()
    result = average_before_zero_air_purge(parse_radon_path(str(path)), column="crm1_radon")
    assert result["measurement_rows"] == list(range(11, 23))
    assert result["average"] == pytest.approx(2407 / 12)
    assert result["start_time"] == "2026-10-22T20:00:00"
    assert result["end_time"] == "2026-10-23T07:00:00"
    assert path.read_bytes() == before
