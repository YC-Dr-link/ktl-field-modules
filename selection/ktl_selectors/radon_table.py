"""#13: 파일별 선택 값·측정시간과 마지막 평균 행을 보여 주는 상세표."""
import pandas as pd

from ktl_contract import ReadError
from .radon_average import average_radon_files
from .radon_models import ParsedRadonFile


def build_average_detail_table(parsed_files: list[ParsedRadonFile]) -> pd.DataFrame:
    """입력 파일마다 선택된 12행 뒤에 평균 1행을 붙인다. 파일 저장은 하지 않는다.

    챔버 모델명/SN처럼 입력에 없는 정보는 빈칸으로 둔다.
    RAW1~4의 상세 배치는 확인 중이므로 이 표는 별도의 상세 미리보기다.
    """
    if not parsed_files:
        raise ReadError("상세표를 만들 라돈 파일이 없습니다.")
    result = average_radon_files(parsed_files)
    records = []
    for parsed, average in zip(parsed_files, result["averages"]):
        info = {"파일순번": average["source_index"], "파일명": parsed.source_file,
                "모델명": parsed.model_name or "", "S/N": parsed.serial_number or "",
                "항목": average["source_column"]}
        for index, value in zip(average["measurement_rows"], average["values"]):
            row = parsed.measurements[index - 1]
            timestamp = row.date if parsed.format == "chamber" else row.timestamp
            records.append({**info, "구분": "측정값", "측정시간": timestamp.isoformat(sep=" "), "값": value})
        records.append({**info, "구분": "평균", "측정시간": "", "값": average["average"]})
    table = pd.DataFrame(records, columns=["파일순번", "파일명", "모델명", "S/N", "구분", "측정시간", "항목", "값"])
    table.attrs.update(averages=result["averages"], warnings=result["warnings"])
    return table
