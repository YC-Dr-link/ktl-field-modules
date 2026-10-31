from pathlib import Path

import pytest
from ktl_contract import ReadError
from ktl_contract.fakes import FakeReader
from ktl_contract.testing import check_reader, check_reader_rejects
from ktl_readers import REGISTRY, get_reader

SYN = Path(__file__).resolve().parents[1] / "synthetic"


def test_fake_reader_follows_contract(tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"not really a jpeg")
    for name in ("cert", "flowmeter", "dust"):
        assert check_reader(FakeReader(name), str(img), name) is not None


def test_flowmeter_reader_contract_while_ocr_is_unavailable(tmp_path):
    img = tmp_path / "synthetic.jpg"
    img.write_bytes(b"synthetic image")
    reader = get_reader("flowmeter", fake_fallback=False)

    assert check_reader(reader, str(img), "prec_1") is None
    with pytest.raises(ReadError, match="OCR 연동"):
        reader.read(str(img), "prec_1")


def test_flowmeter_reader_rejects_empty_file(tmp_path):
    img = tmp_path / "empty.jpg"
    img.write_bytes(b"")

    check_reader_rejects(get_reader("flowmeter", fake_fallback=False), str(img), "prec_1")


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_registered_reader_contract(name, tmp_path):
    samples = sorted((SYN / name).glob("*.jpg"))
    if not samples:
        pytest.skip(f"synthetic/{name}/ 에 합성 이미지가 아직 없음")
    reader = get_reader(name, fake_fallback=False)
    for p in samples[:5]:
        check_reader(reader, str(p), name)
    bad = tmp_path / "empty.jpg"
    bad.write_bytes(b"")
    check_reader_rejects(reader, str(bad), name)
