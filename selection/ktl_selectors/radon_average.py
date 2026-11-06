"""#13: 파일별 지정 열과 구간의 12개 값 평균. 입력을 정렬·보정하지 않는다."""
from dataclasses import asdict
from math import fsum, isfinite
from statistics import pstdev, stdev

from ._radon_common import normalize
from .radon_models import ParsedRadonFile, RadonParseError
from .radon_temperature import average_tail_temperature


def average_before_zero_air_purge(parsed: ParsedRadonFile, *, column: str) -> dict:
    """선택 열의 산술평균과 계산 근거를 JSON 가능한 dict로 반환한다.

    column은 target_radon/calculate_radon/crm1_radon 중 호출자가 지정한다.
    첫 Zero Air Purge 이전에서 Start/Source Purge를 제외한 마지막 12행을 쓴다.
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
    eligible = [i for i in range(end)
                if normalize(parsed.measurements[i].sequence_status) not in {"start", "source purge"}]
    if len(eligible) < 12:
        raise RadonParseError(parsed.source_file, "INSUFFICIENT_AVERAGE_ROWS",
                              f"Start/Source Purge를 제외한 평균 대상 12행이 필요하지만 {len(eligible)}행뿐입니다.", marker.line)
    selected = eligible[-12:]
    window = [parsed.measurements[i] for i in selected]
    values = []
    for row in window:
        value = getattr(row, column)
        if value is None or not isfinite(value):
            raise RadonParseError(parsed.source_file, "INVALID_AVERAGE_VALUE",
                                  f"{column}: 평균 구간 12행에 빈 값 또는 유효하지 않은 값이 있습니다.", row.line)
        values.append(value)
    return {
        "source_file": parsed.source_file, "column": column, "count": 12,
        "values": values, "average": fsum(value / 12 for value in values),
        "measurement_rows": [i + 1 for i in selected],
        "source_lines": [row.line for row in window],
        "start_time": window[0].date.isoformat(), "end_time": window[-1].date.isoformat(),
        "zero_air_purge_row": end + 1, "zero_air_purge_line": marker.line,
    }


def average_radon_files(parsed_files: list[ParsedRadonFile]) -> dict:
    """챔버 CRM-1 Radon, 장비 Temp의 같은 12개 값으로 통계를 계산한다."""
    averages = []
    for index, parsed in enumerate(parsed_files, 1):
        if parsed.format == "chamber":
            result = average_before_zero_air_purge(parsed, column="crm1_radon")
            source_column, selection = "CRM-1 Radon", "before_zero_air_purge"
        elif parsed.format == "device":
            result = average_tail_temperature(parsed)
            source_column, selection = "Temp", "tail"
        else:
            raise RadonParseError(parsed.source_file, "UNSUPPORTED_FORMAT", "지원하지 않는 라돈 파일 형식입니다.")
        deviations = {"sample": stdev(result["values"]), "population": pstdev(result["values"])}
        if not all(isfinite(value) for value in deviations.values()):
            raise RadonParseError(parsed.source_file, "INVALID_STANDARD_DEVIATION", "표준편차를 유한한 숫자로 계산할 수 없습니다.")
        averages.append({"source_index": index, "model_name": parsed.model_name,
                         "serial_number": parsed.serial_number, "source_column": source_column,
                         "selection": selection, "standard_deviations": deviations, **result})
    return {"averages": averages,
            "warnings": [asdict(warning) for parsed in parsed_files for warning in parsed.warnings]}


# TODO(확인 필요): 시험품에 적용할 챔버 행과의 대응, 지시오차·반복성 식, RAW1~4 전체 배치.
