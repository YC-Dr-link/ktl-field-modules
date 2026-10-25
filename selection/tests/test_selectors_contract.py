from pathlib import Path

import pytest
from ktl_contract.testing import check_selector
from ktl_contract.fakes import FakeSelector
from ktl_selectors import REGISTRY, get_selector
from ktl_selectors.radon_selector import RadonMergePendingError

SYN = Path(__file__).resolve().parents[1] / "synthetic"


def test_fake_selector_follows_contract(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("x")
    for name in ("gas_select", "radon_merge"):
        check_selector(FakeSelector(name), [str(f)], {})


@pytest.mark.parametrize("name", [
    pytest.param(name, marks=pytest.mark.xfail(
        raises=RadonMergePendingError, strict=True,
        reason="#13: run()의 RAW 병합 미구현. detect/series 검증은 test_radon_selector.py에서 수행.",
    )) if name == "radon_merge" else name
    for name in sorted(REGISTRY)
])
def test_registered_selector_contract(name):
    folder = "radon_parser" if name == "radon_merge" else name
    files = sorted(str(p) for p in (SYN / folder).glob("*") if p.is_file() and p.suffix in {".csv", ".txt"})
    if not files:
        pytest.skip(f"synthetic/{name}/ 에 합성 파일이 아직 없음")
    check_selector(get_selector(name, fake_fallback=False), files, {})
