"""#13: 챔버의 첫 Zero Air Purge 직전 12행 평균. 입력을 정렬·보정하지 않는다."""
from math import fsum, isfinite

from ._radon_common import normalize
from .radon_models import ParsedRadonFile, RadonParseError


def average_before_zero_air_purge(parsed: ParsedRadonFile, *, column: str) -> dict:
    """선택 열의 산술평균과 계산 근거를 JSON 가능한 dict로 반환한다.

    column은 target_radon/calculate_radon/crm1_radon 중 호출자가 지정한다.
    연속된 Purge 행은 하나의 구간으로 본다. 여러 Purge 구간은 모호하므로 거부한다.
    """
    if parsed.format != "chamber":
        raise RadonParseError(parsed.source_file, "CHAMBER_REQUIRED", "평균 구간을 찾을 챔버 CSV가 필요합니다.")
    if column not in {"target_radon", "calculate_radon", "crm1_radon"}:
        raise RadonParseError(parsed.source_file, "INVALID_AVERAGE_COLUMN", f"지원하지 않는 평균 컬럼입니다: {column}")
    markers = [i for i, row in enumerate(parsed.measurements)
               if normalize(row.sequence_status) == "zero air purge"]
    if not markers:
        raise RadonParseError(parsed.source_file, "PURGE_NOT_FOUND", "Zero Air Purge 행을 찾을 수 없습니다.")
    if any(b != a + 1 for a, b in zip(markers, markers[1:])):
        raise RadonParseError(parsed.source_file, "AMBIGUOUS_PURGE", "Zero Air Purge 구간이 여러 개입니다. 대상 구간을 확인하세요.")
    end = markers[0]
    marker = parsed.measurements[end]
    if end < 12:
        raise RadonParseError(parsed.source_file, "INSUFFICIENT_AVERAGE_ROWS",
                              f"Zero Air Purge 직전 12행이 필요하지만 {end}행뿐입니다.", marker.line)
    window = parsed.measurements[end - 12:end]
    values = []
    for row in window:
        value = getattr(row, column)
        if value is None or not isfinite(value):
            raise RadonParseError(parsed.source_file, "INVALID_AVERAGE_VALUE",
                                  f"{column}: 평균 구간 12행에 빈 값 또는 유효하지 않은 값이 있습니다.", row.line)
        values.append(value)
    return {
        "source_file": parsed.source_file, "column": column, "count": 12,
        "average": fsum(value / 12 for value in values),
        "measurement_rows": list(range(end - 12 + 1, end + 1)),
        "source_lines": [row.line for row in window],
        "start_time": window[0].date.isoformat(), "end_time": window[-1].date.isoformat(),
        "zero_air_purge_row": end + 1, "zero_air_purge_line": marker.line,
    }


# TODO(확인 필요): 시험품에 적용할 챔버 행과의 대응, 지시오차·반복성 식, RAW1~4 전체 배치.
