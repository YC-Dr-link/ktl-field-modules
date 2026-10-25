"""B-4 선별·병합 모듈. 서버는 get_selector(name)으로 불러 쓴다.

새 Selector를 만들면 REGISTRY에 등록하고 tests/에 계약 테스트를 추가한다.
"""
from ktl_contract import Selector
from ktl_contract.fakes import FakeSelector
from .radon_selector import RadonSelector

REGISTRY: dict[str, type | object] = {
    # "gas_select": GasSelector,     # 다운
    "radon_merge": RadonSelector,   # 탁 (#11 판별·시계열, #13 병합)
}


def get_selector(name: str, fake_fallback: bool = True) -> Selector:
    if name in REGISTRY:
        s = REGISTRY[name]
        return s() if isinstance(s, type) else s
    if fake_fallback:
        return FakeSelector(name)
    raise KeyError(f"등록되지 않은 Selector: {name}")


def detect_any(path: str) -> tuple[str, dict] | None:
    """등록된 모든 Selector로 파일 형식을 판별. 처음 맞는 것을 돌려준다."""
    for name in REGISTRY:
        d = get_selector(name, fake_fallback=False).detect(path)
        if d:
            return name, d
    return None
