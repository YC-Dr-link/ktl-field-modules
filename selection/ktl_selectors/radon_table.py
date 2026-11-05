"""#13: 장비를 가로로 나란히 놓는 측정값·시간·평균 표."""
import pandas as pd

from ktl_contract import ReadError
from .radon_average import average_radon_files
from .radon_models import ParsedRadonFile, RadonParseError


def build_average_detail_table(parsed_files: list[ParsedRadonFile], *, align: str = "hour") -> pd.DataFrame:
    """장비별 값 열과 마지막 평균 행을 만든다. 기본은 날짜별 정시 맞춤이다.

    hour는 분·초를 버린 정시를 공유하고, sequence는 파일별 시각을 보존한다.
    같은 장비의 한 시간에 값이 여러 개면 덮어쓰거나 평균 내지 않고 오류로 알린다.
    RAW1~4의 상세 배치는 별도 확인이 필요하다. 파일 저장은 하지 않는다.
    """
    if not parsed_files:
        raise ReadError("상세표를 만들 라돈 파일이 없습니다.")
    if align not in ("hour", "sequence"):
        raise ReadError("정렬 방식은 hour 또는 sequence여야 합니다.")
    result = average_radon_files(parsed_files)
    records = {}
    columns = ["측정시간"] if align == "hour" else ["구분"]
    mean_row = {columns[0]: "평균"}
    sources = []
    for parsed, average in zip(parsed_files, result["averages"]):
        prefix = f'[{average["source_index"]}]'
        identity = " · ".join(part for part in (parsed.model_name, parsed.serial_number) if part)
        identity = identity or parsed.source_file
        time_column = "측정시간" if align == "hour" else f"{prefix} 측정시간"
        value_column = f'{prefix} {identity} · {average["source_column"]}'
        columns.extend([value_column] if align == "hour" else [time_column, value_column])
        seen_hours, original_times = set(), []
        for position, (index, value) in enumerate(zip(average["measurement_rows"], average["values"])):
            row = parsed.measurements[index - 1]
            timestamp = row.date if parsed.format == "chamber" else row.timestamp
            original_times.append(timestamp.isoformat(sep=" "))
            if align == "hour":
                hour = timestamp.replace(minute=0, second=0, microsecond=0)
                if hour in seen_hours:
                    raise RadonParseError(parsed.source_file, "DUPLICATE_HOUR",
                                          f"{hour.isoformat(sep=' ')} 시간대에 선택값이 여러 개입니다. 같은 장비의 중복 처리 규칙이 필요합니다.", row.line)
                seen_hours.add(hour)
                record = records.setdefault(hour, {time_column: hour.isoformat(sep=" ")})
            else:
                record = records.setdefault(position, {"구분": f"측정값 {position + 1}"})
                record[time_column] = timestamp.isoformat(sep=" ")
            record[value_column] = value
        if align == "sequence":
            mean_row[time_column] = ""
        mean_row[value_column] = average["average"]
        sources.append({"source_index": average["source_index"], "source_file": parsed.source_file,
                        "model_name": parsed.model_name, "serial_number": parsed.serial_number,
                        "time_column": time_column, "value_column": value_column,
                        "selected_timestamps": original_times})
    # 빈 장비 셀은 None으로 유지해 서버 JSON에 NaN이 나가지 않게 한다.
    rows = [records[key] for key in sorted(records)] + [mean_row]
    table = pd.DataFrame([{column: row.get(column) for column in columns} for row in rows],
                         columns=columns, dtype=object)
    table.attrs.update(averages=result["averages"], warnings=result["warnings"], sources=sources)
    return table
