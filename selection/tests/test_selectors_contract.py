from pathlib import Path

import pytest
from ktl_contract.testing import check_selector
from ktl_selectors import REGISTRY, get_selector

SYN = Path(__file__).resolve().parents[1] / "synthetic"


def test_fake_selector_follows_contract(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("x")
    for name in ("gas_select", "radon_merge"):
        check_selector(get_selector(name), [str(f)], {})


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_registered_selector_contract(name):
    files = sorted(str(p) for p in (SYN / name).glob("*") if p.is_file())
    if not files:
        pytest.skip(f"synthetic/{name}/ 에 합성 파일이 아직 없음")
    check_selector(get_selector(name, fake_fallback=False), files, {})
