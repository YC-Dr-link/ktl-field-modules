"""#13: 장비를 가로로 나란히 놓는 측정값·시간·평균 표."""
import pandas as pd
from pathlib import PureWindowsPath

from ktl_contract import ReadError
from .radon_average import average_radon_files
from .radon_models import ParsedRadonFile, RadonParseError


def build_average_detail_table(parsed_files: list[ParsedRadonFile], *, align: str = "hour",
                              reference_indices: list[int] | None = None, stddev_ddof: int = 1) -> pd.DataFrame:
    """장비별 값 열과 평균·표준편차 행을 만든다. 기본은 날짜별 정시 맞춤이다.

    hour는 분·초를 버린 정시를 공유하고, sequence는 파일별 시각을 보존한다.
    같은 장비의 한 시간에 값이 여러 개면 덮어쓰거나 평균 내지 않고 오류로 알린다.
    RAW1~4의 상세 배치는 별도 확인이 필요하다. 파일 저장은 하지 않는다.
    """
    if not parsed_files:
        raise ReadError("상세표를 만들 라돈 파일이 없습니다.")
    if align not in ("hour", "sequence"):
        raise ReadError("정렬 방식은 hour 또는 sequence여야 합니다.")
    if type(stddev_ddof) is not int or stddev_ddof not in (0, 1):
        raise ReadError("표준편차 stddev_ddof는 표본 1 또는 모집단 0이어야 합니다.")
    references = list(reference_indices or [])
    if (any(type(index) is not int or not 1 <= index <= len(parsed_files) for index in references)
            or len(set(references)) != len(references)):
        raise ReadError("기준장비 순번은 중복 없이 입력 파일의 1부터 시작하는 순번이어야 합니다.")
    # 사용자 지정 업무 규칙: 파일명은 역할만 구분하며 S/N 값으로 쓰지 않는다.
    groups = [[], [], []]
    for index, parsed in enumerate(parsed_files, 1):
        filename = PureWindowsPath(parsed.source_file)
        name = filename.name.casefold()
        if name.startswith("ktl"):
            groups[0].append(index)
        elif name.startswith("hj"):
            groups[1].append(index)
        elif filename.stem == "1023" and parsed.format == "chamber":
            groups[2].append(index)
    automatic = [index for group in groups for index in group]
    references = automatic + [index for index in references if index not in automatic]
    result = average_radon_files(parsed_files)
    order = references + [index for index in range(1, len(parsed_files) + 1) if index not in references]
    averages = [result["averages"][index - 1] for index in order]
    records = {}
    columns = ["측정시간"] if align == "hour" else ["구분"]
    mean_row = {columns[0]: "평균"}
    deviation_row = {columns[0]: "표준편차"}
    sources = []
    for display_index, average in enumerate(averages, 1):
        parsed = parsed_files[average["source_index"] - 1]
        prefix = f"[{display_index}]"
        time_column = "측정시간" if align == "hour" else f"{prefix} 측정시간"
        identity = "CRM-1 Radon" if parsed.format == "chamber" else ""
        value_column = f"{prefix} {identity}" if identity else prefix
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
            deviation_row[time_column] = ""
        mean_row[value_column] = average["average"]
        deviation_row[value_column] = average["standard_deviations"]["sample" if stddev_ddof else "population"]
        sources.append({"source_index": average["source_index"], "source_file": parsed.source_file,
                        "display_index": display_index, "is_reference": average["source_index"] in references,
                        "model_name": parsed.model_name, "serial_number": parsed.serial_number,
                        "time_column": time_column, "value_column": value_column,
                        "selected_timestamps": original_times})
    # 빈 장비 셀은 None으로 유지해 서버 JSON에 NaN이 나가지 않게 한다.
    rows = [records[key] for key in sorted(records)] + [mean_row, deviation_row]
    table = pd.DataFrame([{column: row.get(column) for column in columns} for row in rows],
                         columns=columns, dtype=object)
    file_row = ["파일명"] + [""] * (len(columns) - 1)
    serial_row = ["S/N"] + [""] * (len(columns) - 1)
    for source in sources:
        position = columns.index(source["value_column"])
        file_row[position] = source["source_file"]
        serial_row[position] = source["serial_number"] or ""
    table.attrs.update(averages=averages, warnings=result["warnings"], sources=sources,
                       csv_header_rows=[file_row, serial_row], stddev_ddof=stddev_ddof)
    return table
