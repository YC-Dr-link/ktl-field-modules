import pytest
from ktl_contract import ReadError
from ktl_contract.fakes import FakeReader
from ktl_contract.testing import check_reader


def test_fake_reader(tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(b"abc")
    assert check_reader(FakeReader("cert"), str(p), "cert").values


def test_fake_reader_fail(tmp_path):
    p = tmp_path / "fail.jpg"
    p.write_bytes(b"abc")
    with pytest.raises(ReadError):
        FakeReader("cert").read(str(p), "cert")
