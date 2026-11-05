import copy
import csv
from datetime import timedelta
from math import sqrt
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
    table = build_average_detail_table(parsed, align="sequence")
    assert table.shape == (14, 5)
    first, second = table.attrs["sources"]
    assert first["value_column"] == "[1]"
    assert second["value_column"] == "[2] CRM-1 Radon"
    assert table["구분"].tolist() == [f"측정값 {i}" for i in range(1, 13)] + ["평균", "표준편차"]
    assert table[first["value_column"]].tolist() == pytest.approx(list(range(20, 32)) + [25.5, sqrt(13)])
    assert table[second["value_column"]].tolist() == pytest.approx(list(range(1, 13)) + [6.5, sqrt(13)])
    for source in (first, second):
        assert table[source["time_column"]].tolist() == [f"2026-01-03 {hour:02d}:00:00" for hour in range(2, 14)] + ["", ""]
    assert parsed == original and [path.read_bytes() for path in paths] == before


def test_time_value_pairs_stay_together_without_sorting_or_alignment():
    parsed = parse_radon_path(str(DEVICE))
    parsed.measurements[-2].timestamp -= timedelta(days=2)
    table = build_average_detail_table([parsed], align="sequence")
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
    table = build_average_detail_table([first, second], align="sequence")
    one, two = table.attrs["sources"]
    assert table.columns.is_unique and table.shape == (14, 5)
    assert table.iloc[12][one["value_column"]] == 25.5
    assert table.iloc[12][two["value_column"]] == 26.5
    assert two["serial_number"] == "SYNTHETIC-SECOND"
    assert [w["code"] for w in table.attrs["warnings"]] == ["COUNT_MISMATCH"]
    assert [a["count"] for a in table.attrs["averages"]] == [12, 12]


def test_csv_roundtrip_has_time_values_and_mean_below_each_file():
    parsed = parse_radon_file('synthetic,"quoted".txt', DEVICE.read_bytes())
    table = build_average_detail_table([parsed], align="sequence")
    content = table.to_csv(index=False, lineterminator="\r\n").encode("utf-8-sig")
    assert content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    source = table.attrs["sources"][0]
    assert len(rows) == 14
    assert source["source_file"] == 'synthetic,"quoted".txt'
    assert rows[0][source["time_column"]] == "2026-01-03 02:00:00"
    assert float(rows[0][source["value_column"]]) == 20
    assert rows[-2]["구분"] == "평균" and rows[-2][source["time_column"]] == ""
    assert float(rows[-2][source["value_column"]]) == 25.5
    assert rows[-1]["구분"] == "표준편차" and rows[-1][source["time_column"]] == ""
    assert float(rows[-1][source["value_column"]]) == pytest.approx(sqrt(13))


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
    table = build_average_detail_table(parsed, align="sequence")
    assert table.shape == (14, 1 + 2 * len(paths))
    for info in table.attrs["sources"]:
        source = parsed[info["source_index"] - 1]
        assert info["source_file"] == source.source_file
        column = table[info["value_column"]]
        assert column.iloc[-2] == pytest.approx(sum(column.iloc[:12]) / 12)


def test_identical_devices_keep_unique_headers_and_independent_timestamps():
    first = parse_radon_path(str(DEVICE))
    second = copy.deepcopy(first)
    for row in second.measurements:
        row.timestamp += timedelta(minutes=2)
    table = build_average_detail_table([first, second], align="sequence")
    one, two = table.attrs["sources"]
    assert table.columns.is_unique
    assert table.iloc[0][one["time_column"]] == "2026-01-03 02:00:00"
    assert table.iloc[0][two["time_column"]] == "2026-01-03 02:02:00"
    assert table.iloc[0][one["value_column"]] == table.iloc[0][two["value_column"]] == 20


def test_reference_group_precedes_other_files_and_headers_do_not_use_filenames():
    parsed = [parse_radon_path(str(DEVICE)) for _ in range(4)]
    for index, source in enumerate(parsed, 1):
        source.source_file = f"SYNTHETIC-FILE-{index}.txt"
        source.serial_number = f"SYNTHETIC-SN-{index}"
        source.measurements[-1].temp += index
    original = copy.deepcopy(parsed)
    table = build_average_detail_table(parsed, reference_indices=[3, 1])
    assert table.columns.tolist() == ["측정시간", "[1]", "[2]", "[3]", "[4]"]
    assert table.attrs["csv_header_rows"] == [
        ["파일명", "SYNTHETIC-FILE-3.txt", "SYNTHETIC-FILE-1.txt", "SYNTHETIC-FILE-2.txt", "SYNTHETIC-FILE-4.txt"],
        ["S/N", "SYNTHETIC-SN-3", "SYNTHETIC-SN-1", "SYNTHETIC-SN-2", "SYNTHETIC-SN-4"],
    ]
    assert [source["source_index"] for source in table.attrs["sources"]] == [3, 1, 2, 4]
    assert [source["is_reference"] for source in table.attrs["sources"]] == [True, True, False, False]
    for info, average in zip(table.attrs["sources"], table.attrs["averages"]):
        assert info["source_file"] == parsed[info["source_index"] - 1].source_file
        assert table.iloc[-3][info["value_column"]] == 31 + info["source_index"]
        assert table.iloc[-2][info["value_column"]] == average["average"]
    assert parsed == original


@pytest.mark.parametrize("indices", [[0], [2], [1, 1], [True]])
def test_invalid_reference_indices_are_rejected(indices):
    with pytest.raises(ReadError, match="기준장비"):
        build_average_detail_table([parse_radon_path(str(DEVICE))], reference_indices=indices)


@pytest.mark.parametrize("align", ["hour", "sequence"])
def test_ktl_hj_and_1023_crm1_are_first_without_using_filenames_as_serials(align):
    chamber = parse_radon_file("1023.csv", CHAMBER.read_bytes())
    hj = parse_radon_file("Hj-SYNTHETIC.txt", DEVICE.read_bytes().replace(b"SYNTHETIC-TEMPERATURE", b"SYNTHETIC-HJ-SERIAL"))
    ktl = parse_radon_file("ktl-SYNTHETIC.txt", DEVICE.read_bytes().replace(b"SYNTHETIC-TEMPERATURE", b"SYNTHETIC-KTL-SERIAL"))
    other = parse_radon_file("other.txt", DEVICE.read_bytes().replace(b"SYNTHETIC-TEMPERATURE", b"KTL-SYNTHETIC-DEVICE"))
    table = build_average_detail_table([other, chamber, hj, ktl], align=align)
    sources = table.attrs["sources"]
    assert [source["source_index"] for source in sources] == [4, 3, 2, 1]
    assert [source["is_reference"] for source in sources] == [True, True, True, False]
    assert [source["value_column"] for source in sources] == [
        "[1]", "[2]", "[3] CRM-1 Radon", "[4]"]
    filename_row, serial_row = table.attrs["csv_header_rows"]
    for source in sources:
        column = table.columns.get_loc(source["value_column"])
        assert filename_row[column] == source["source_file"]
        assert serial_row[column] == (source["serial_number"] or "")
    assert sources[0]["source_file"] == "ktl-SYNTHETIC.txt"
    assert sources[0]["serial_number"] == "SYNTHETIC-KTL-SERIAL"
    assert sources[2]["source_file"] == "1023.csv" and sources[2]["serial_number"] is None
    assert [average["average"] for average in table.attrs["averages"]] == [25.5, 25.5, 6.5, 25.5]
