"""공통 변환: 입력 오류를 숨기거나 측정값을 보정하지 않는다."""
import math
import re
from datetime import datetime

from .radon_models import ParseWarning, RadonParseError


def normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def parse_timestamp(value: str, filename: str, line: int, field: str) -> datetime:
    text = " ".join(value.split())
    if re.fullmatch(r"\d{4}([-\.])\d{2}\1\d{2} \d{2}:\d{2}:\d{2}", text):
        try:
            return datetime.strptime(text, "%Y.%m.%d %H:%M:%S" if "." in text else "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    raise RadonParseError(filename, "INVALID_TIMESTAMP", f"{field}: 날짜·시간을 해석할 수 없습니다 ({value!r}).", line)


def parse_number(value: str, filename: str, line: int, field: str,
                 warnings: list[ParseWarning]) -> float | None:
    text = value.strip()
    if not text:
        warnings.append(ParseWarning("MISSING_VALUE", f"{field}: 빈 측정값을 None으로 반환합니다.", filename, line))
        return None
    # float()가 허용하는 NaN/Infinity와 숫자 내부 밑줄은 측정값으로 받지 않는다.
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        result = float(text)
        if math.isfinite(result):
            return result
    raise RadonParseError(filename, "INVALID_NUMBER", f"{field}: 올바른 유한 숫자가 아닙니다 ({value!r}).", line)
