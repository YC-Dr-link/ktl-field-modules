"""서버용 경로 인터페이스. 판별/시계열은 #11, RAW 병합은 #13."""
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from ktl_contract import ReadError, SelectResult, Warning
from .radon import parse_radon_path
from .radon_models import ParsedRadonFile, RadonParseError
from .radon_table import build_average_detail_table


def _timestamps(parsed: ParsedRadonFile) -> list:
    if parsed.format == "chamber":
        return [row.date for row in parsed.measurements]
    return [row.timestamp for row in parsed.measurements]


class RadonSelector:
    name = "radon_merge"

    def detect(self, path: str) -> dict | None:
        """OpenAPI DataFile.detected의 kind/serial/interval_s/unit/rows 형식."""
        try:
            parsed = parse_radon_path(path)
        except RadonParseError as exc:
            if exc.code == "FILE_READ_ERROR":
                raise  # 읽기 실패는 미지원 형식과 구분한다.
            return None
        kinds = {"FRD400": "radon_frd400", "FRD500": "radon_frd500",
                 "FRD2400V1": "radon_frd2400"}
        result = {"kind": "radon_chamber" if parsed.format == "chamber" else kinds[parsed.model_name],
                  "rows": parsed.measurement_count}
        if parsed.serial_number is not None:
            result["serial"] = parsed.serial_number
        if parsed.unit is not None:
            result["unit"] = parsed.unit
        times = _timestamps(parsed)
        intervals = {(b - a).total_seconds() for a, b in zip(times, times[1:])}
        if len(intervals) == 1:
            interval = next(iter(intervals))
            if interval > 0 and interval.is_integer():
                result["interval_s"] = int(interval)
        # 선택 필드가 불명확하면 생략한다. 챔버 단위·불규칙 간격은 추측하지 않는다.
        return result

    def series(self, paths: list[str]) -> pd.DataFrame:
        """t + 숫자 채널. 입력 파일/행 순서 유지, 시각 정렬·병합 없음."""
        if not paths:
            raise ReadError("시계열을 조회할 라돈 파일이 없습니다.")
        records, columns, sources, warnings = [], ["t"], [], []
        for index, path in enumerate(paths, 1):
            parsed = parse_radon_path(path)
            channels = (["target_radon", "calculate_radon", "crm1_radon"]
                        if parsed.format == "chamber" else ["radon", "temp", "humi", "barometer"])
            # 여러 파일의 같은 이름/SN도 덮어쓰지 않는다. source_N은 서버 file ID가 아니다.
            names = [f"source_{index}.{key}" if len(paths) > 1 else key for key in channels]
            columns.extend(names)
            for time, row in zip(_timestamps(parsed), parsed.measurements):
                records.append({"t": time, **{name: getattr(row, key) for name, key in zip(names, channels)}})
            sources.append({"source_file": parsed.source_file, "serial_number": parsed.serial_number,
                            "model_name": parsed.model_name, "unit": parsed.unit, "columns": names})
            warnings.extend(asdict(warning) for warning in parsed.warnings)
        # 다른 파일의 채널과 빈 측정값은 None으로 유지해 JSON에 NaN이 나가지 않게 한다.
        frame = pd.DataFrame([{column: record.get(column) for column in columns} for record in records],
                             columns=columns, dtype=object)
        frame.attrs.update(sources=sources, warnings=warnings)
        return frame

    def run(self, paths: list[str], options: dict) -> SelectResult:
        """장비별 열과 마지막 평균 행을 반환한다. CSV 저장은 서버에서 수행한다."""
        if not paths:
            raise ReadError("병합할 라돈 파일이 없습니다.")
        if not isinstance(options, dict):
            raise ReadError("병합 options는 dict여야 합니다.")
        if set(options) - {"reference", "align"}:
            raise ReadError("지원하지 않는 병합 옵션이 있습니다.")
        align = options.get("align", "hour")
        if align not in ("hour", "sequence"):
            raise ReadError("정렬 방식은 hour 또는 sequence여야 합니다.")
        reference_index = None
        reference = options.get("reference")
        if reference is not None:
            if not isinstance(reference, str):
                raise ReadError("기준기 reference는 선택한 파일의 경로 문자열이어야 합니다.")
            normalized = [Path(path).resolve() for path in paths]
            if Path(reference).resolve() not in normalized:
                raise ReadError("기준기는 선택한 파일 경로 중 하나여야 합니다.")
            reference_index = normalized.index(Path(reference).resolve()) + 1
        parsed = [parse_radon_path(path) for path in paths]
        table = build_average_detail_table(parsed, align=align)
        warnings = [warning for source in parsed for warning in source.warnings]
        description = ("같은 날짜의 측정시각을 한 시간 단위 정시로 묶습니다. 빈 시간대는 빈칸입니다."
                       if align == "hour" else "같은 행은 파일별 선택 순번이며 시각 정렬은 수행하지 않습니다.")
        warnings.append(Warning("DETAIL_LAYOUT", f"{description} 장비별 기존 12개 값의 평균을 마지막 행에 표시합니다. RAW1~4 배치는 포함되지 않습니다."))
        # TODO(확인 필요): 장비 간 순번 대응, 지시오차·반복성 식, RAW1~4 배치.
        return SelectResult(table=table, warnings=warnings, meta={
            "layout": "radon_hour_v1" if align == "hour" else "radon_wide_v1", "requested_align": align,
            "row_order": "hour_ascending" if align == "hour" else "selected_row_position_per_file",
            "sources": table.attrs["sources"],
            "alignment": {"mode": align, "rounding": "floor_to_hour" if align == "hour" else None,
                          "missing": "blank", "duplicate_hour": "error"},
            "reference_file_index": reference_index, "averages": table.attrs["averages"],
            "pending": (["cross_device_alignment"] if align == "sequence" else [])
                       + ["indication_error", "repeatability", "raw1_4_layout"],
        })
