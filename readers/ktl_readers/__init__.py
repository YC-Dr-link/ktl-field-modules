"""B-3 사진 판독 모듈. 서버는 get_reader(name)으로 불러 쓴다.

새 Reader를 만들면 REGISTRY에 등록하고 tests/에 계약 테스트를 추가한다.
"""
from ktl_contract import Reader
from ktl_contract.fakes import FakeReader

REGISTRY: dict[str, type | object] = {
    # "cert": CertReader,          # 지호
    # "flowmeter": FlowmeterReader,  # 정윤
    # "dust": DustReader,
}


def get_reader(name: str, fake_fallback: bool = True) -> Reader:
    """name에 맞는 Reader. 아직 없으면 가짜 모듈(fake_fallback=True일 때)."""
    if name in REGISTRY:
        r = REGISTRY[name]
        return r() if isinstance(r, type) else r
    if fake_fallback:
        return FakeReader(name)
    raise KeyError(f"등록되지 않은 Reader: {name}")
