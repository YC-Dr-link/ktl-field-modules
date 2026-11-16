"""통합 API 및 읽기 전용 예제 검증. 외부 파일은 환경변수로만 지정한다."""
import csv
import hashlib
import json
import os
from pathlib import Path

import pytest

from ktl_contract import ReadError
from ktl_selectors.radon import (
    RadonParseError, detect_radon_file, parse_radon_file, parse_radon_path, parse_radon_upload,
)

SYNTHETIC = Path(__file__).resolve().parents[1] / "synthetic" / "radon_merge"


@pytest.mark.parametrize("filename,content,code", [
    ("unknown.xlsx", b"data", "UNSUPPORTED_EXTENSION"),
    ("empty.txt", b"\xef\xbb\xbf \r\n", "NO_DATA"),
    ("broken.csv", b"\xff\xfe\x00", "INVALID_ENCODING"),
    ("broken.txt", b"first\n\xff", "INVALID_ENCODING"),
    ("binary.csv", b"Date\x00", "INVALID_ENCODING"),
    ("input.txt", "not bytes", "INVALID_INPUT"),
])
def test_api_errors(filename, content, code):
    with pytest.raises(RadonParseError) as caught:
        parse_radon_file(filename, content)
    assert isinstance(caught.value, ReadError)
    assert caught.value.source_file == filename
    assert caught.value.code == code
    assert filename in str(caught.value)
    assert detect_radon_file(filename, content) is None


def test_encoding_error_line_and_unknown_codec():
    with pytest.raises(RadonParseError) as caught:
        parse_radon_file("bad.txt", b"first\n\xff")
    assert caught.value.line == 2
    with pytest.raises(RadonParseError, match="INVALID_ENCODING"):
        parse_radon_file("bad.txt", b"data", encoding="nonexistent-codec")


def test_path_read_error():
    with pytest.raises(RadonParseError, match="FILE_READ_ERROR"):
        parse_radon_path(str(SYNTHETIC / "does-not-exist.txt"))


def test_path_adapter_and_explicit_encoding():
    fixture = SYNTHETIC.parent / "radon_parser" / "chamber.csv"
    expected = parse_radon_path(str(fixture))
    text = fixture.read_text(encoding="utf-8").replace("SYNTHETIC PARSER TEST", "합성 시험")
    result = parse_radon_file("upload.csv", text.encode("cp949"), encoding="cp949")
    assert result.measurements == expected.measurements
    assert "합성 시험" in result.metadata_lines[0]
    with pytest.raises(RadonParseError, match="INVALID_ENCODING"):
        parse_radon_file("upload.csv", text.encode("cp949"))


def test_unknown_file_is_not_detected():
    assert detect_radon_file("random.txt", b"unrelated report\n1,2,3") is None
    with pytest.raises(RadonParseError, match="UNKNOWN_FORMAT"):
        parse_radon_file("random.txt", b"unrelated report\n1,2,3")


@pytest.mark.parametrize("filename", ["chamber.csv", "device400.txt", "device500.txt", "device2400.txt"])
def test_path_bytes_and_json_upload_agree(filename, monkeypatch):
    path = SYNTHETIC.parent / "radon_parser" / filename
    content = path.read_bytes()
    by_path = parse_radon_path(str(path))

    def no_filesystem(*args, **kwargs):
        raise AssertionError("bytes 파서는 파일을 열거나 저장하면 안 됩니다.")

    monkeypatch.setattr("builtins.open", no_filesystem)
    monkeypatch.setattr("io.open", no_filesystem)
    by_bytes = parse_radon_file(path.name, content)
    assert by_path == by_bytes
    payload = parse_radon_upload(path.name, content)
    assert payload == by_bytes.to_dict()
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def check_example(path):
    before = path.read_bytes()
    result = parse_radon_file(path.name, before)
    assert parse_radon_path(str(path)) == result
    raw_lines = before.decode("utf-8-sig").splitlines()
    if result.format == "chamber":
        rows = list(csv.reader(raw_lines))
        header = next(i for i, row in enumerate(rows) if "Sequence Status" in row)
        rows = rows[header + 1:]
        assert len(rows) == result.measurement_count
        assert [r[1] for r in rows] == [m.sequence_status for m in result.measurements]
        assert result.measurements[0].sequence_status == "Start"
        assert result.measurements[-1].sequence_status == "Zero Air Purge"
    else:
        assert result.data_no == result.measurement_count
        assert result.measurement_start == result.measurements[0].timestamp
        assert result.measurement_end == result.measurements[-1].timestamp
        assert result.serial_number and result.serial_number in "\n".join(raw_lines[:10])
        assert result.model_name in {"FRD400", "FRD500", "FRD2400V1"}
        assert result.measurements[0].index == 1
        assert result.measurements[-1].index == result.data_no
    assert result.warnings == []
    payload = result.to_dict()
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
    assert payload["measurement_count"] == result.measurement_count
    assert detect_radon_file(path.name, before)["format"] == result.format
    # 파일명에 식별번호가 없어도 내용에서 읽으며 대문자 확장자도 허용한다.
    renamed = parse_radon_file("upload" + path.suffix.upper(), before)
    assert renamed.serial_number == result.serial_number
    assert renamed.measurements == result.measurements
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(before).digest()
    return result


@pytest.mark.parametrize("path", sorted(p for p in SYNTHETIC.glob("*") if p.suffix in {".csv", ".txt"}), ids=lambda p: p.name)
def test_repository_examples(path):
    result = check_example(path)
    expected = 24 if result.format == "chamber" else 23 if result.model_name == "FRD2400V1" else 22
    assert result.measurement_count == expected


def test_external_examples():
    folder = os.environ.get("RADON_EXAMPLE_DIR")
    if not folder:
        pytest.skip("RADON_EXAMPLE_DIR 미지정: 외부 예제 통합 테스트 생략")
    root = Path(folder)
    assert root.is_dir(), f"외부 예제 폴더에 접근할 수 없습니다: {root}"
    paths = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".txt"})
    assert paths, "외부 예제 CSV/TXT가 없습니다."
    for path in paths:
        check_example(path)
