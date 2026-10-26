import json
from pathlib import Path

import pytest
from ktl_contract.testing import check_reader, check_reader_rejects
from ktl_readers import REGISTRY, get_reader

SYN = Path(__file__).resolve().parents[1] / "synthetic"
REQUIRED_DISTORTIONS = {"rotation", "blur", "reflection", "noise"}


def test_fake_reader_follows_contract(tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"not really a jpeg")
    for name in ("cert", "flowmeter", "dust"):
        assert check_reader(get_reader(name), str(img), name) is not None


@pytest.mark.parametrize(
    ("name", "minimum_fields"),
    [
        ("cert", {"prev_receipt", "approval_no", "maker", "serial"}),
        ("flowmeter", {"flow"}),
    ],
)
def test_synthetic_dataset_has_answers_and_hard_cases(name, minimum_fields):
    image_paths = sorted((SYN / name).glob("*.jpg"))
    assert len(image_paths) >= 30
    distortions = set()

    for image_path in image_paths:
        answer_path = image_path.with_suffix(".json")
        truth = json.loads(answer_path.read_text(encoding="utf-8"))
        assert truth["reader"] == name
        assert minimum_fields <= set(truth["values"])
        assert all(isinstance(value, str) for value in truth["values"].values())
        if name == "flowmeter":
            assert truth["units"]["flow"] == "L/min"
        assert image_path.read_bytes().startswith(b"\xff\xd8")
        distortions.update(truth["distortions"])

    assert REQUIRED_DISTORTIONS <= distortions


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
