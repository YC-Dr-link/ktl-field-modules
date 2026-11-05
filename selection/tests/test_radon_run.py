import csv
import hashlib
import io
import json
from pathlib import Path

import pytest
from ktl_contract import ReadError, SelectResult, Warning
from ktl_contract.testing import check_selector
from ktl_selectors import get_selector

SYN = Path(__file__).resolve().parents[1] / "synthetic"
SAMPLES = [str(SYN / "radon_average" / name) for name in ("chamber.csv", "temperature.txt")]


def test_real_run_contract_metadata_csv_and_input_preservation():
    before = {path: hashlib.sha256(Path(path).read_bytes()).digest() for path in SAMPLES}
    selector = get_selector("radon_merge", fake_fallback=False)
    result = check_selector(selector, SAMPLES, {"reference": SAMPLES[1], "align": "sequence"})
    assert isinstance(result, SelectResult) and result.table.shape == (13, 5)
    assert result.meta["layout"] == "radon_wide_v1"
    assert result.meta["reference_file_index"] == 2
    assert result.meta["row_order"] == "selected_row_position_per_file"
    assert [a["average"] for a in result.meta["averages"]] == [6.5, 25.5]
    assert [a["source_column"] for a in result.meta["averages"]] == ["CRM-1 Radon", "Temp"]
    assert all(isinstance(warning, Warning) for warning in result.warnings)
    assert [warning.code for warning in result.warnings] == ["DETAIL_LAYOUT"]
    assert {"raw1_4_layout", "repeatability", "indication_error"}.issubset(result.meta["pending"])
    json.dumps(result.meta, allow_nan=False)
    content = result.table.to_csv(index=False, lineterminator="\r\n").encode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert len(rows) == 13
    first, second = result.meta["sources"]
    assert first["value_column"].endswith("CRM-1 Radon") and second["value_column"].endswith("Temp")
    assert rows[12]["구분"] == "평균"
    assert float(rows[12][first["value_column"]]) == 6.5
    assert float(rows[12][second["value_column"]]) == 25.5
    assert before == {path: hashlib.sha256(Path(path).read_bytes()).digest() for path in SAMPLES}


@pytest.mark.parametrize("options,message", [
    (None, "dict"), ({"align": "hour"}, "순번"), ({"align": None}, "순번"),
    ({"unexpected": True}, "옵션"), ({"reference": 1}, "문자열"),
    ({"reference": "not-uploaded.txt"}, "선택한 파일"),
])
def test_unsupported_options_are_not_silently_ignored(options, message):
    with pytest.raises(ReadError, match=message):
        get_selector("radon_merge").run(SAMPLES, options)


def test_empty_input_unknown_file_and_short_file(tmp_path):
    selector = get_selector("radon_merge")
    with pytest.raises(ReadError, match="파일"):
        selector.run([], {})
    unknown = tmp_path / "unknown.txt"
    unknown.write_text("SYNTHETIC UNKNOWN", encoding="utf-8")
    with pytest.raises(ReadError):
        selector.run([str(unknown)], {})
    with pytest.raises(ReadError, match="INSUFFICIENT_AVERAGE_ROWS"):
        selector.run([str(SYN / "radon_parser" / "device500.txt")], {})


def test_default_options_and_parsing_warnings_survive(tmp_path):
    folder = tmp_path / "synthetic"
    folder.mkdir()
    path = folder / "device.txt"
    data = Path(SAMPLES[1]).read_bytes().replace(b"Data No: 14", b"Data No: 15")
    path.write_bytes(data)
    result = get_selector("radon_merge").run([str(path)], {})
    assert result.meta["reference_file_index"] is None
    assert result.meta["averages"][0]["average"] == 25.5
    assert [warning.code for warning in result.warnings] == ["COUNT_MISMATCH", "DETAIL_LAYOUT"]


def test_fifteen_files_return_side_by_side_columns_when_examples_available():
    paths = sorted(str(p) for p in (SYN / "radon_merge").glob("*") if p.suffix.lower() in {".csv", ".txt"})
    if not paths:
        pytest.skip("로컬 합성 예제는 커밋 대상에서 제외됨")
    result = get_selector("radon_merge").run(paths, {})
    assert result.table.shape == (13, 1 + 2 * len(paths))
    assert len(result.meta["averages"]) == len(paths)
    assert (result.table["구분"] == "평균").sum() == 1
