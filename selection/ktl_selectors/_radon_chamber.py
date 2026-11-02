"""챔버 CSV의 원본 행 순서와 필드 표기를 보존하는 파서."""
import csv
import io

from ._radon_common import normalize, parse_number, parse_timestamp
from .radon_models import ChamberMeasurement, ParsedRadonFile, RadonParseError


COLUMNS = ("Date", "Sequence Status", "Target Radon", "Calculate Radon", "CRM-1 Radon")
_CANONICAL = {normalize(name): name for name in COLUMNS}


def parse_chamber(filename: str, text: str, file_type: str) -> ParsedRadonFile:
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    source_lines = text.splitlines(keepends=True)
    result = ParsedRadonFile(filename, file_type, "chamber", [], [])
    header = None
    partial_header = None
    try:
        while True:
            line = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                break
            if header is None:
                normalized = [normalize(cell) for cell in row]
                found = set(normalized) & _CANONICAL.keys()
                if found != _CANONICAL.keys():
                    if found:
                        partial_header = (line, found)
                    result.metadata_lines.extend(
                        item.rstrip("\r\n") for item in source_lines[line - 1:reader.line_num]
                    )
                    continue
                if len(normalized) != len(set(normalized)) or "" in normalized:
                    raise RadonParseError(filename, "INVALID_HEADER", "빈 이름 또는 중복된 컬럼명이 있습니다.", line)
                header = [_CANONICAL.get(name, raw.strip()) for name, raw in zip(normalized, row)]
                result.columns = [name for name in header if name in COLUMNS]
                continue
            if not row:  # 빈 물리 행만 건너뛰고 빈 셀로 구성된 데이터 행은 검증한다.
                continue
            if len(row) != len(header):
                raise RadonParseError(filename, "INVALID_ROW", f"컬럼 {len(header)}개가 필요하지만 {len(row)}개입니다.", line)
            fields = dict(zip(header, row))
            numbers = [parse_number(fields[name], filename, line, name, result.warnings) for name in COLUMNS[2:]]
            result.measurements.append(ChamberMeasurement(
                date=parse_timestamp(fields["Date"], filename, line, "Date"),
                date_raw=fields["Date"], sequence_status=fields["Sequence Status"],
                target_radon=numbers[0], calculate_radon=numbers[1], crm1_radon=numbers[2],
                line=line, raw_values={name: fields[name] for name in COLUMNS},
                extra_values={name: value for name, value in fields.items() if name not in COLUMNS},
            ))
    except csv.Error as exc:
        raise RadonParseError(filename, "INVALID_CSV", f"CSV 구문 오류: {exc}", line) from exc
    if header is None:
        if partial_header:
            line, found = partial_header
            missing = [name for name in COLUMNS if normalize(name) not in found]
            raise RadonParseError(filename, "MISSING_COLUMNS", f"필수 컬럼 누락: {', '.join(missing)}", line)
        raise RadonParseError(filename, "UNKNOWN_FORMAT", "지원하는 챔버 CSV 헤더를 찾지 못했습니다.")
    if not result.measurements:
        raise RadonParseError(filename, "NO_DATA", "측정 데이터가 없습니다.")
    return result
