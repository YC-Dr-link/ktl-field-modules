import copy
import csv
from datetime import timedelta
import io
from pathlib import Path

import pytest
from ktl_contract import ReadError

from ktl_selectors.radon import parse_radon_file, parse_radon_path
from ktl_selectors.radon_table import build_average_detail_table

SYN = Path(__file__).resolve().parents[1] / "synthetic"
DEVICE = SYN / "radon_average" / "temperature.txt"
CHAMBER = SYN / "radon_average" / "chamber.csv"


def test_twelve_rows_and_average_with_one_time_value_pair_per_file():
    paths = [DEVICE, CHAMBER]
    before = [path.read_bytes() for path in paths]
    parsed = [parse_radon_file(path.name, data) for path, data in zip(paths, before)]
    original = copy.deepcopy(parsed)
    table = build_average_detail_table(parsed)
    assert table.shape == (13, 5)
    first, second = table.attrs["sources"]
    assert first["value_column"] == "[1] FRD500 · SYNTHETIC-TEMPERATURE · Temp"
    assert second["value_column"] == "[2] chamber.csv · CRM-1 Radon"
    assert table["구분"].tolist() == [f"측정값 {i}" for i in range(1, 13)] + ["평균"]
    assert table[first["value_column"]].tolist() == list(range(20, 32)) + [25.5]
    assert table[second["value_column"]].tolist() == list(range(1, 13)) + [6.5]
    for source in (first, second):
        assert table[source["time_column"]].tolist() == [f"2026-01-03 {hour:02d}:00:00" for hour in range(2, 14)] + [""]
    assert parsed == original and [path.read_bytes() for path in paths] == before


def test_time_value_pairs_stay_together_without_sorting_or_alignment():
    parsed = parse_radon_path(str(DEVICE))
    parsed.measurements[-2].timestamp -= timedelta(days=2)
    table = build_average_detail_table([parsed])
    source = table.attrs["sources"][0]
    assert table.iloc[10][source["time_column"]] == "2026-01-01 12:00:00"
    assert table.iloc[10][source["value_column"]] == 30
    assert table.iloc[11][source["time_column"]] == "2026-01-03 13:00:00"
    assert table.iloc[11][source["value_column"]] == 31
    assert table.iloc[12][source["value_column"]] == 25.5


def test_duplicate_model_and_file_name_keep_separate_blocks_and_warnings():
    data = DEVICE.read_bytes()
    first = parse_radon_file("same.txt", data)
    second = parse_radon_file("same.txt", data.replace(b"SYNTHETIC-TEMPERATURE", b"SYNTHETIC-SECOND")
                              .replace(b"\t20\t", b"\t32\t").replace(b"Data No: 14", b"Data No: 15"))
    table = build_average_detail_table([first, second])
    one, two = table.attrs["sources"]
    assert table.columns.is_unique and table.shape == (13, 5)
    assert table.iloc[12][one["value_column"]] == 25.5
    assert table.iloc[12][two["value_column"]] == 26.5
    assert two["serial_number"] == "SYNTHETIC-SECOND"
    assert [w["code"] for w in table.attrs["warnings"]] == ["COUNT_MISMATCH"]
    assert [a["count"] for a in table.attrs["averages"]] == [12, 12]


def test_csv_roundtrip_has_time_values_and_mean_below_each_file():
    parsed = parse_radon_file('synthetic,"quoted".txt', DEVICE.read_bytes())
    table = build_average_detail_table([parsed])
    content = table.to_csv(index=False, lineterminator="\r\n").encode("utf-8-sig")
    assert content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    source = table.attrs["sources"][0]
    assert len(rows) == 13
    assert source["source_file"] == 'synthetic,"quoted".txt'
    assert rows[0][source["time_column"]] == "2026-01-03 02:00:00"
    assert float(rows[0][source["value_column"]]) == 20
    assert rows[-1]["구분"] == "평균" and rows[-1][source["time_column"]] == ""
    assert float(rows[-1][source["value_column"]]) == 25.5


def test_empty_input_and_insufficient_measurements_are_errors():
    with pytest.raises(ReadError, match="파일"):
        build_average_detail_table([])
    parsed = parse_radon_path(str(SYN / "radon_parser" / "device500.txt"))
    with pytest.raises(ReadError, match="INSUFFICIENT_AVERAGE_ROWS"):
        build_average_detail_table([parsed])


def test_supplied_files_have_one_average_below_twelve_rows_each():
    paths = sorted(p for p in (SYN / "radon_merge").glob("*") if p.suffix.lower() in {".csv", ".txt"})
    if not paths:
        pytest.skip("로컬 합성 예제는 커밋 대상에서 제외됨")
    parsed = [parse_radon_path(str(path)) for path in paths]
    table = build_average_detail_table(parsed)
    assert table.shape == (13, 1 + 2 * len(paths))
    for source, info in zip(parsed, table.attrs["sources"]):
        assert info["source_file"] == source.source_file
        column = table[info["value_column"]]
        assert column.iloc[-1] == pytest.approx(sum(column.iloc[:12]) / 12)


def test_identical_devices_keep_unique_headers_and_independent_timestamps():
    first = parse_radon_path(str(DEVICE))
    second = copy.deepcopy(first)
    for row in second.measurements:
        row.timestamp += timedelta(minutes=2)
    table = build_average_detail_table([first, second])
    one, two = table.attrs["sources"]
    assert table.columns.is_unique
    assert table.iloc[0][one["time_column"]] == "2026-01-03 02:00:00"
    assert table.iloc[0][two["time_column"]] == "2026-01-03 02:02:00"
    assert table.iloc[0][one["value_column"]] == table.iloc[0][two["value_column"]] == 20
