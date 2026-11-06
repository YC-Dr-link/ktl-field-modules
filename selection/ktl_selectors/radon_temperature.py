"""#13: 파일별 온도 열의 마지막 12개 측정행 평균. 원본 순서를 유지한다."""
from dataclasses import asdict
from math import fsum, isfinite

from ._radon_common import parse_number
from .radon_models import ParsedRadonFile, RadonParseError


def average_tail_temperature(parsed: ParsedRadonFile, *, chamber_column: str | None = None) -> dict:
    """장비는 Temp, 챔버는 호출자가 명시한 추가 열을 사용한다.

    챔버 열을 지정하지 않으면 오류로 알리며 임의로 열을 선택하지 않는다.
    파일 끝의 측정행 12개를 사용하므로 Zero Air Purge 위치와 독립적이다.
    """
    if parsed.format == "device":
        column = "temp"
    elif parsed.format == "chamber" and chamber_column:
        column = chamber_column
    else:
        raise RadonParseError(parsed.source_file, "TEMPERATURE_COLUMN_REQUIRED",
                              "챔버 온도 평균에 사용할 컬럼을 명시해야 합니다.")
    end = len(parsed.measurements)
    if end < 12:
        raise RadonParseError(parsed.source_file, "INSUFFICIENT_AVERAGE_ROWS",
                              f"온도 평균에 마지막 12행이 필요하지만 {end}행뿐입니다.")
    window = parsed.measurements[-12:]
    values = []
    for row in window:
        if parsed.format == "device":
            value = row.temp
        else:
            if column not in row.extra_values:
                raise RadonParseError(parsed.source_file, "MISSING_TEMPERATURE_COLUMN",
                                      f"챔버 온도 컬럼이 없습니다: {column}", row.line)
            value = parse_number(row.extra_values[column], parsed.source_file, row.line, column, [])
        if value is None or not isfinite(value):
            raise RadonParseError(parsed.source_file, "INVALID_AVERAGE_VALUE",
                                  f"{column}: 마지막 12행에 빈 값 또는 유효하지 않은 값이 있습니다.", row.line)
        values.append(value)
    times = [row.timestamp if parsed.format == "device" else row.date for row in window]
    return {
        "source_file": parsed.source_file, "serial_number": parsed.serial_number,
        "model_name": parsed.model_name, "column": column, "count": 12,
        "values": values, "average": fsum(value / 12 for value in values),
        "measurement_rows": list(range(end - 11, end + 1)),
        "source_lines": [row.line for row in window],
        "start_time": times[0].isoformat(), "end_time": times[-1].isoformat(),
    }


def average_temperatures(parsed_files: list[ParsedRadonFile], *, chamber_column: str | None) -> dict:
    """구조화된 파일들을 입력 순서대로 처리한다. 챔버 정책은 호출자가 지정한다.

    chamber_column=None은 챔버를 평균 대상에서 명시적으로 제외한다.
    열 이름을 전달하면 그 챔버 열의 마지막 12행도 평균 낸다.
    """
    averages, excluded = [], []
    for index, parsed in enumerate(parsed_files, 1):
        if parsed.format == "chamber" and chamber_column is None:
            excluded.append({"source_index": index, "source_file": parsed.source_file,
                             "reason": "CHAMBER_EXCLUDED"})
            continue
        result = average_tail_temperature(parsed, chamber_column=chamber_column)
        averages.append({"source_index": index, **result})
    return {"averages": averages, "excluded_files": excluded,
            "warnings": [asdict(warning) for parsed in parsed_files for warning in parsed.warnings]}
