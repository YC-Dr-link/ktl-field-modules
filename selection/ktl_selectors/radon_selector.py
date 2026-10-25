"""서버용 경로 인터페이스. 판별/시계열은 #11, RAW 병합은 #13."""
from dataclasses import asdict

import pandas as pd

from ktl_contract import ReadError, SelectResult
from .radon import parse_radon_path
from .radon_models import ParsedRadonFile, RadonParseError


class RadonMergePendingError(ReadError):
    """실제 병합이 구현되기 전 성공한 RAW 표를 반환하지 않도록 한다."""


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
        # TODO(확인 필요): #13의 합성 정답과 RAW1~4 배치에 맞춰 병합을 구현한다.
        raise RadonMergePendingError("라돈 병합·RAW 출력은 아직 지원하지 않습니다. 후속 이슈 #13 구현이 필요합니다.")
