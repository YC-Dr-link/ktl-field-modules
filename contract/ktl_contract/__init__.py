"""B-3 · B-4 모듈과 B-1 서버 사이의 계약 (ktl-hub/docs/02-API명세.md §3).

이 파일은 계약이다. 바꾸려면 ktl-hub에 "계약변경" 이슈를 먼저 연다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import pandas

__all__ = ["Value", "Warning", "ReadResult", "SelectResult", "ReadError", "Reader", "Selector", "CONTRACT_VERSION"]

CONTRACT_VERSION = "1.0"


@dataclass
class Value:
    key: str                         # categories.yaml의 칸 key
    label: str                       # 화면 표시 이름
    value: str                       # 항상 문자열, 원본 표기 유지
    unit: str | None = None
    confidence: float = 1.0          # 0~1. 형식·범위 검사 실패면 0.5 이하
    bbox: list[int] | None = None    # 받은 이미지 기준 [x1, y1, x2, y2]


@dataclass
class Warning:
    code: str                        # "PRE_MEASURE_SCREEN", "MULTIPLE_DOCS", "SATURATED" …
    message: str                     # 화면에 그대로 보여 줄 한국어 문장


@dataclass
class ReadResult:
    values: list[Value]
    warnings: list[Warning] = field(default_factory=list)


@dataclass
class SelectResult:
    table: "pandas.DataFrame"        # RAW 시트에 붙일 배치 그대로 (칼럼 순서 = 출력 순서)
    warnings: list[Warning] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)   # 계산 근거


class ReadError(Exception):
    """아예 읽지 못했을 때. 메시지는 한국어로."""


@runtime_checkable
class Reader(Protocol):
    name: str                        # "cert" | "flowmeter" | "dust"

    def read(self, image_path: str, item: str) -> ReadResult: ...


@runtime_checkable
class Selector(Protocol):
    name: str                        # "gas_select" | "radon_merge"

    def detect(self, path: str) -> dict[str, Any] | None: ...

    def series(self, paths: list[str]) -> "pandas.DataFrame": ...

    def run(self, paths: list[str], options: dict[str, Any]) -> SelectResult: ...
