"""가짜 모듈. 서버(B-1)·화면(B-2)이 실제 모듈 없이 끝까지 개발할 수 있게 정해진 값을 돌려준다."""
from __future__ import annotations

import hashlib
import time
from typing import Any

from . import ReadError, ReadResult, SelectResult, Value, Warning

_FAKE_VALUES: dict[str, list[tuple[str, str, str, str | None]]] = {
    "cert": [
        ("prev_receipt", "직전접수번호", "25-123456-01-1", None),
        ("approval_no", "형식승인번호", "ABCD-2020-3", None),
        ("maker", "제조사", "가나다테크(주)", None),
        ("serial", "제조번호", "A100-0007", None),
    ],
    "flowmeter": [
        ("flow", "유량", "1.002", "L/min"),
        ("reading_no", "측정 번호", "01 of 003", None),
    ],
    "dust": [
        ("conc", "Conc", "0.034", "mg/m³"),
        ("qtot", "Qtot", "24.01", "m³"),
    ],
}


class FakeReader:
    """파일 해시로 신뢰도를 정해서, 같은 사진은 항상 같은 결과가 나온다.

    파일 이름에 'fail'이 있으면 ReadError, 'slow'가 있으면 12초 대기(서버 시간 제한 시험용).
    """

    def __init__(self, name: str):
        self.name = name

    def read(self, image_path: str, item: str) -> ReadResult:
        if "fail" in image_path:
            raise ReadError("화면을 찾지 못했습니다 (가짜 모듈)")
        if "slow" in image_path:
            time.sleep(12)
        with open(image_path, "rb") as f:
            seed = hashlib.sha256(f.read()).digest()[0]
        rows = _FAKE_VALUES.get(self.name, [("value", "값", "0", None)])
        values = [
            Value(key=k, label=lab, value=v, unit=u,
                  confidence=0.6 if i == 1 and seed % 3 == 0 else 0.95,
                  bbox=[40 + 10 * i, 40 + 60 * i, 300, 90 + 60 * i])
            for i, (k, lab, v, u) in enumerate(rows)
        ]
        warnings = [Warning("PRE_MEASURE_SCREEN", "측정 전 화면(0.000)일 수 있습니다.")] if seed % 7 == 0 else []
        return ReadResult(values=values, warnings=warnings)


class FakeSelector:
    def __init__(self, name: str):
        self.name = name

    def detect(self, path: str) -> dict[str, Any] | None:
        kind = "gas_gl240" if self.name == "gas_select" else "radon_frd500"
        return {"kind": kind, "interval_s": 60 if kind == "gas_gl240" else 3600, "rows": 30}

    def series(self, paths: list[str]):
        import pandas as pd
        t = pd.date_range("2026-10-29 10:00", periods=30, freq="min")
        return pd.DataFrame({"t": t, "CH1": [1.0 + (i // 10) * 200 for i in range(30)]})

    def run(self, paths: list[str], options: dict[str, Any]) -> SelectResult:
        import pandas as pd
        if self.name == "gas_select":
            codes = ["ZDS", "ZDE", "SDS", "SDE", "LT", "RZ1", "RZ2", "RZ3", "RS1", "RS2", "RS3", "RT90", "RT10"]
            table = pd.DataFrame([[c] + [f"{i + 0.1 * j:.1f}" for j in range(10)] for i, c in enumerate(codes)],
                                 columns=["code"] + [f"v{j}" for j in range(1, 11)])
        else:
            table = pd.DataFrame({"no": range(1, 13), "test": [300 + i for i in range(12)], "ref": [298 + i for i in range(12)]})
        return SelectResult(table=table, meta={"fake": True, "options": options})
