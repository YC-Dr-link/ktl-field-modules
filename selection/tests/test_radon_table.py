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


def test_twelve_timestamp_value_rows_followed_by_average_per_file():
    paths = [DEVICE, CHAMBER]
    before = [path.read_bytes() for path in paths]
    parsed = [parse_radon_file(path.name, data) for path, data in zip(paths, before)]
    original = copy.deepcopy(parsed)
    table = build_average_detail_table(parsed)
    assert list(table.columns) == ["파일순번", "파일명", "모델명", "S/N", "구분", "측정시간", "항목", "값"]
    assert len(table) == 26
    first, second = table.iloc[:13], table.iloc[13:]
    assert first["모델명"].tolist() == ["FRD500"] * 13
    assert first["S/N"].tolist() == ["SYNTHETIC-TEMPERATURE"] * 13
    assert first["항목"].tolist() == ["Temp"] * 13
    assert first["구분"].tolist() == ["측정값"] * 12 + ["평균"]
    assert first["값"].tolist() == list(range(20, 32)) + [25.5]
    assert first["측정시간"].tolist() == [f"2026-01-03 {hour:02d}:00:00" for hour in range(2, 14)] + [""]
    assert second["파일순번"].tolist() == [2] * 13
    assert second["모델명"].tolist() == [""] * 13
    assert second["S/N"].tolist() == [""] * 13
    assert second["항목"].tolist() == ["CRM-1 Radon"] * 13
    assert second["값"].tolist() == list(range(1, 13)) + [6.5]
    assert second["측정시간"].tolist() == [f"2026-01-03 {hour:02d}:00:00" for hour in range(2, 14)] + [""]
    assert parsed == original and [path.read_bytes() for path in paths] == before


def test_time_value_pairs_stay_together_without_sorting_or_alignment():
    parsed = parse_radon_path(str(DEVICE))
    parsed.measurements[-2].timestamp -= timedelta(days=2)
    table = build_average_detail_table([parsed])
    assert table.iloc[10]["측정시간"] == "2026-01-01 12:00:00"
    assert table.iloc[10]["값"] == 30
    assert table.iloc[11]["측정시간"] == "2026-01-03 13:00:00"
    assert table.iloc[11]["값"] == 31
    assert table.iloc[12]["값"] == 25.5


def test_duplicate_model_and_file_name_keep_separate_blocks_and_warnings():
    data = DEVICE.read_bytes()
    first = parse_radon_file("same.txt", data)
    second = parse_radon_file("same.txt", data.replace(b"SYNTHETIC-TEMPERATURE", b"SYNTHETIC-SECOND")
                              .replace(b"\t20\t", b"\t32\t").replace(b"Data No: 14", b"Data No: 15"))
    table = build_average_detail_table([first, second])
    assert table["파일순번"].tolist() == [1] * 13 + [2] * 13
    assert table.iloc[12]["값"] == 25.5 and table.iloc[25]["값"] == 26.5
    assert table.iloc[13]["S/N"] == "SYNTHETIC-SECOND"
    assert [w["code"] for w in table.attrs["warnings"]] == ["COUNT_MISMATCH"]
    assert [a["count"] for a in table.attrs["averages"]] == [12, 12]


def test_csv_roundtrip_has_time_values_and_mean_below_each_file():
    parsed = parse_radon_file('synthetic,"quoted".txt', DEVICE.read_bytes())
    table = build_average_detail_table([parsed])
    content = table.to_csv(index=False, lineterminator="\r\n").encode("utf-8-sig")
    assert content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert len(rows) == 13
    assert rows[0]["파일명"] == 'synthetic,"quoted".txt'
    assert rows[0]["측정시간"] == "2026-01-03 02:00:00" and float(rows[0]["값"]) == 20
    assert rows[-1]["구분"] == "평균" and rows[-1]["측정시간"] == ""
    assert float(rows[-1]["값"]) == 25.5


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
    assert len(table) == len(paths) * 13
    for i, source in enumerate(parsed):
        block = table.iloc[i * 13:(i + 1) * 13]
        assert block["구분"].tolist() == ["측정값"] * 12 + ["평균"]
        assert block["파일명"].tolist() == [source.source_file] * 13
        assert block.iloc[-1]["값"] == pytest.approx(sum(block.iloc[:12]["값"]) / 12)
