import copy
import json
from pathlib import Path

import pytest

from ktl_selectors.radon import parse_radon_file, parse_radon_path
from ktl_selectors.radon_models import RadonParseError
from ktl_selectors.radon_temperature import average_tail_temperature, average_temperatures

SYN = Path(__file__).resolve().parents[1] / "synthetic"
FIXTURE = SYN / "radon_average" / "temperature.txt"


def test_temperature_not_radon_and_only_last_twelve():
    before = FIXTURE.read_bytes()
    parsed = parse_radon_path(str(FIXTURE))
    original = copy.deepcopy(parsed)
    result = average_tail_temperature(parsed)
    assert result["column"] == "temp" and result["count"] == 12
    assert result["values"] == list(range(20, 32))
    assert result["average"] == 25.5
    assert result["measurement_rows"] == list(range(3, 15))
    assert result["source_lines"] == list(range(11, 23))
    assert result["start_time"] == "2026-01-03T02:00:00"
    assert result["end_time"] == "2026-01-03T13:00:00"
    assert result["serial_number"] == "SYNTHETIC-TEMPERATURE"
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert parsed == original and FIXTURE.read_bytes() == before


@pytest.mark.parametrize("model,extension", [
    ("FRD400", "txt"), ("FRD500", "txt"), ("FRD500", "csv"), ("FRD2400V1", "txt"),
])
def test_models_and_csv_txt(model, extension):
    text = FIXTURE.read_text(encoding="utf-8").replace("FRD500", model)
    if model == "FRD400":
        text = text.replace("SN:", "S/N:")
    elif model == "FRD2400V1":
        text = text.replace("Date&Time", "DT").replace("Radon\t", "Rn-222\t")
    if extension == "csv":
        text = text.replace("\t", ",")
    parsed = parse_radon_file("synthetic." + extension, text.encode("utf-8-sig"))
    assert average_tail_temperature(parsed)["average"] == 25.5


@pytest.mark.parametrize("length", [0, 11, 12])
def test_twelve_rows_required(length):
    parsed = parse_radon_path(str(FIXTURE))
    parsed.measurements = parsed.measurements[-length:] if length else []
    if length < 12:
        with pytest.raises(RadonParseError, match="INSUFFICIENT_AVERAGE_ROWS"):
            average_tail_temperature(parsed)
    else:
        assert average_tail_temperature(parsed)["average"] == 25.5


def test_missing_temperature_is_not_backfilled_and_order_not_sorted():
    parsed = parse_radon_path(str(FIXTURE))
    parsed.measurements[-1].temp = None
    with pytest.raises(RadonParseError, match="INVALID_AVERAGE_VALUE"):
        average_tail_temperature(parsed)
    parsed = parse_radon_path(str(FIXTURE))
    parsed.measurements[0].temp = None  # 구간 밖 누락은 선택 구간을 바꾸지 않는다.
    assert average_tail_temperature(parsed)["average"] == 25.5
    parsed = parse_radon_path(str(FIXTURE))
    parsed.measurements.reverse()
    result = average_tail_temperature(parsed)
    assert result["values"] == list(range(29, 19, -1)) + [999, 999]
    assert result["average"] == pytest.approx(2243 / 12)


def test_chamber_temperature_column_must_be_explicit():
    parsed = parse_radon_path(str(SYN / "radon_average" / "chamber.csv"))
    with pytest.raises(RadonParseError, match="TEMPERATURE_COLUMN_REQUIRED"):
        average_tail_temperature(parsed)
    with pytest.raises(RadonParseError, match="MISSING_TEMPERATURE_COLUMN"):
        average_tail_temperature(parsed, chamber_column="Inner Temperature")


def test_explicit_chamber_temperature_keeps_purge_rows():
    parsed = parse_radon_path(str(SYN / "radon_average" / "chamber.csv"))
    for i, row in enumerate(parsed.measurements):
        row.extra_values["Inner Temperature"] = str(i)
    result = average_tail_temperature(parsed, chamber_column="Inner Temperature")
    # 현재 요청은 파일 마지막 12행이므로 Purge 앞에서 자르지 않는다.
    assert result["values"] == list(range(5, 17))
    assert result["average"] == 10.5


def test_all_files_parsed_then_averaged_individually():
    content = FIXTURE.read_bytes()
    uploads = [("same.txt", content), ("same.txt", content.replace(b"\t20\t", b"\t32\t"))]
    parsed = [parse_radon_file(filename, data) for filename, data in uploads]
    chamber = parse_radon_path(str(SYN / "radon_average" / "chamber.csv"))
    result = average_temperatures([*parsed, chamber], chamber_column=None)
    assert [r["average"] for r in result["averages"]] == [25.5, 26.5]
    assert [r["source_index"] for r in result["averages"]] == [1, 2]
    assert [r["source_file"] for r in result["averages"]] == ["same.txt", "same.txt"]
    assert result["excluded_files"] == [{"source_index": 3, "source_file": "chamber.csv",
                                          "reason": "CHAMBER_EXCLUDED"}]
    assert result["warnings"] == []


def test_batch_explicit_chamber_choice_and_parsing_warnings():
    device = parse_radon_file("device.txt", FIXTURE.read_bytes().replace(b"Data No: 14", b"Data No: 15"))
    chamber = parse_radon_path(str(SYN / "radon_average" / "chamber.csv"))
    for row in chamber.measurements:
        row.extra_values["Inner Temperature"] = "22"
    result = average_temperatures([device, chamber], chamber_column="Inner Temperature")
    assert [r["average"] for r in result["averages"]] == [25.5, 22]
    assert result["excluded_files"] == []
    assert [w["code"] for w in result["warnings"]] == ["COUNT_MISMATCH"]
    assert result["warnings"][0]["source_file"] == "device.txt"
    assert json.loads(json.dumps(result, allow_nan=False)) == result


@pytest.mark.parametrize("chamber_column", [None, "Inner Temperature"])
def test_supplied_fifteen_examples_if_available(chamber_column):
    folder = SYN / "radon_merge"
    paths = sorted(p for p in folder.glob("*") if p.suffix.lower() in {".csv", ".txt"})
    if not paths:
        pytest.skip("로컬 합성 예제는 커밋 대상에서 제외됨")
    before = {path: path.read_bytes() for path in paths}
    parsed = [parse_radon_file(path.name, before[path]) for path in paths]
    result = average_temperatures(parsed, chamber_column=chamber_column)
    assert len(result["averages"]) + len(result["excluded_files"]) == len(paths)
    for item in result["averages"]:
        original = parsed[item["source_index"] - 1]
        expected = ([row.temp for row in original.measurements[-12:]] if original.format == "device"
                    else [float(row.extra_values[chamber_column]) for row in original.measurements[-12:]])
        assert item["values"] == expected
        assert item["average"] == pytest.approx(sum(expected) / 12)
        assert item["count"] == 12
    assert {path: path.read_bytes() for path in paths} == before
