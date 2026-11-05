"""#13: 장비를 가로로 나란히 놓는 측정값·시간·평균 표."""
import pandas as pd

from ktl_contract import ReadError
from .radon_average import average_radon_files
from .radon_models import ParsedRadonFile


def build_average_detail_table(parsed_files: list[ParsedRadonFile]) -> pd.DataFrame:
    """파일별 시간/값 열을 나란히 놓고 마지막 행에 평균을 붙인다.

    같은 행은 각 파일에서 선택한 값의 순번이며 동일 시각을 뜻하지 않는다.
    장비 이름은 헤더에만 표시하고 원본 측정시간은 파일별로 보존한다.
    RAW1~4의 상세 배치는 별도 확인이 필요하다. 파일 저장은 하지 않는다.
    """
    if not parsed_files:
        raise ReadError("상세표를 만들 라돈 파일이 없습니다.")
    result = average_radon_files(parsed_files)
    records = [{"구분": f"측정값 {i}"} for i in range(1, 13)] + [{"구분": "평균"}]
    sources = []
    for parsed, average in zip(parsed_files, result["averages"]):
        prefix = f'[{average["source_index"]}]'
        identity = " · ".join(part for part in (parsed.model_name, parsed.serial_number) if part)
        identity = identity or parsed.source_file
        time_column = f"{prefix} 측정시간"
        value_column = f'{prefix} {identity} · {average["source_column"]}'
        for position, (index, value) in enumerate(zip(average["measurement_rows"], average["values"])):
            row = parsed.measurements[index - 1]
            timestamp = row.date if parsed.format == "chamber" else row.timestamp
            records[position].update({time_column: timestamp.isoformat(sep=" "), value_column: value})
        records[-1].update({time_column: "", value_column: average["average"]})
        sources.append({"source_index": average["source_index"], "source_file": parsed.source_file,
                        "model_name": parsed.model_name, "serial_number": parsed.serial_number,
                        "time_column": time_column, "value_column": value_column})
    table = pd.DataFrame(records)
    table.attrs.update(averages=result["averages"], warnings=result["warnings"], sources=sources)
    return table
