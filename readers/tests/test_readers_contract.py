from pathlib import Path

import pytest
from ktl_contract.testing import check_reader, check_reader_rejects
from ktl_readers import REGISTRY, get_reader

SYN = Path(__file__).resolve().parents[1] / "synthetic"


def test_fake_reader_follows_contract(tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"not really a jpeg")
    for name in ("cert", "flowmeter", "dust"):
        assert check_reader(get_reader(name), str(img), name) is not None


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
