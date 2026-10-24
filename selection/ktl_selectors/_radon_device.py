"""Parse the three observed FRD layouts without assigning reference/test roles."""
import csv
import re

from ._radon_common import normalize, parse_number, parse_timestamp
from .radon_models import DeviceMeasurement, ParsedRadonFile, ParseWarning, RadonParseError

COLUMNS = ["index", "timestamp", "radon", "temp", "humi", "barometer"]
ALIASES = {"no": "index", "date&time": "timestamp", "dt": "timestamp",
           "radon": "radon", "rn-222": "radon", "temp": "temp", "temp.": "temp",
           "humi": "humi", "humi.": "humi", "barometer": "barometer"}
META = {
    "model_name": r"model\s+name",
    "serial_number": r"s\s*/?\s*n",
    "measurement_start": r"(?:date\s+and\s+time\s*\(start\)|measurement\s+start\s+time)",
    "measurement_end": r"(?:date\s+and\s+time\s*\(last\)|measurement\s+end\s+time)",
    "unit": r"unit", "data_no": r"data\s+no",
}


def _metadata(line):
    if "," in line:
        line = "\t".join(next(csv.reader([line], strict=True)))
    for key, label in META.items():
        match = re.match(rf"^\s*(?:{label})(?:\s*:\s*|[\t, ]+)(.*)$", line, re.I)
        if match:
            return key, match[1].lstrip("\t, ").strip()
    return None


def _cells(line, comma, filename, number):
    if comma:
        try:
            return next(csv.reader([line], strict=True))
        except csv.Error as exc:
            raise RadonParseError(filename, "INVALID_ROW", f"CSV 행 구조 오류: {exc}", number) from exc
    # Preserve empty tab-separated cells; ordinary spaces may separate other cells.
    chunks = line.split("\t")
    if len(chunks) in (6, 7) and all(
        not re.search(r"\s", chunk.strip())
        or re.fullmatch(r"\S+[ ]+\d{2}:\d{2}:\d{2}", chunk.strip())
        for chunk in chunks
    ):
        return chunks
    result = []
    for chunk in chunks:
        if not chunk.strip():
            result.append("")
        else:
            result.extend(re.findall(r"\S+[ ]+\d{2}:\d{2}:\d{2}|\S+", chunk))
    return result


def parse_device(filename: str, text: str, file_type: str) -> ParsedRadonFile:
    lines = text.splitlines()
    meta, meta_lines, metadata_lines = {}, {}, []
    header = None
    measurements, warnings = [], []
    model = None
    comma = False
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            match = _metadata(line) if not measurements else None
        except csv.Error as exc:
            raise RadonParseError(filename, "INVALID_ROW", f"CSV 메타데이터 구조 오류: {exc}", number) from exc
        if match:
            key, value = match
            if key in meta:
                raise RadonParseError(filename, "DUPLICATE_METADATA", f"메타데이터 중복: {key}", number)
            meta[key], meta_lines[key] = value, number
            metadata_lines.append(line)
            if key == "model_name":
                comma = "," in line
                model_match = re.fullmatch(r"(FRD400)(?:[\s,]+V2\.0)?|(FRD500|FRD2400V1)", value, re.I)
                if not model_match:
                    raise RadonParseError(filename, "UNSUPPORTED_MODEL", f"지원하지 않는 모델: {value}", number)
                model = (model_match[1] or model_match[2]).upper()
            continue
        cells = _cells(line, comma, filename, number)
        if model == "FRD2400V1" and len(cells) == 7 and not cells[-1].strip():
            cells.pop()  # Observed device's final tab/comma is a delimiter, not a seventh channel.
        canonical = [ALIASES.get(normalize(cell)) for cell in cells]
        is_header = "index" in canonical or "timestamp" in canonical
        if not measurements and is_header:
            if header is not None or len(canonical) != 6 or set(canonical) != set(COLUMNS):
                raise RadonParseError(filename, "INVALID_HEADER", "측정 헤더가 누락되거나 중복되었습니다.", number)
            header = canonical
            continue
        if not measurements and header is None and not re.match(r"^\s*\d", line):
            # Only observed descriptive metadata may precede headerless data.
            # A corrupt measurement such as 'bad: 2026.01.02 ...' is an error.
            if re.match(r"^\s*(?:MeasMode|Average\s+Time|Duration\s*\(min\))\s*:", line, re.I) or normalize(line) in {"ftlab radon data file", "frd2400 radon data file v1"}:
                metadata_lines.append(line)
                continue
        missing = [key for key in META if not meta.get(key)]
        if missing:
            raise RadonParseError(filename, "MISSING_METADATA", f"필수 메타데이터 누락: {', '.join(missing)}", number)
        if header is None and model != "FRD400":
            raise RadonParseError(filename, "MISSING_HEADER", "이 모델에는 측정 컬럼 헤더가 필요합니다.", number)
        if len(cells) != 6:
            raise RadonParseError(filename, "INVALID_ROW", f"측정행은 6개 필드가 필요합니다 (실제 {len(cells)}개).", number)
        raw = dict(zip(header or COLUMNS, cells))
        if not re.fullmatch(r"\d+", raw["index"].strip()):
            raise RadonParseError(filename, "INVALID_INDEX", "측정 순번은 정수여야 합니다.", number)
        measurements.append(DeviceMeasurement(
            index=int(raw["index"]),
            timestamp=parse_timestamp(raw["timestamp"], filename, number, "timestamp"),
            timestamp_raw=raw["timestamp"], line=number, raw_values=raw,
            **{key: parse_number(raw[key], filename, number, key, warnings) for key in COLUMNS[2:]},
        ))
    missing = [key for key in META if not meta.get(key)]
    if missing:
        raise RadonParseError(filename, "MISSING_METADATA", f"필수 메타데이터 누락: {', '.join(missing)}")
    if not measurements:
        raise RadonParseError(filename, "NO_MEASUREMENTS", "측정 데이터가 없습니다.")
    if not re.fullmatch(r"\d+", meta["data_no"]):
        raise RadonParseError(filename, "INVALID_COUNT", "Data No는 음수가 아닌 정수여야 합니다.", meta_lines["data_no"])
    data_no = int(meta["data_no"])
    start, end = (parse_timestamp(meta[key], filename, meta_lines[key], key)
                  for key in ("measurement_start", "measurement_end"))
    if data_no != len(measurements):
        warnings.append(ParseWarning("COUNT_MISMATCH", f"Data No {data_no}와 실제 측정 건수 {len(measurements)}가 다릅니다.", filename, meta_lines["data_no"]))
    if start > end or any(not start <= row.timestamp <= end for row in measurements):
        warnings.append(ParseWarning("TIME_RANGE_MISMATCH", "측정시간이 선언된 시작/종료 범위와 맞지 않습니다.", filename, meta_lines["measurement_start"]))
    return ParsedRadonFile(
        source_file=filename, file_type=file_type, format="device", columns=COLUMNS.copy(),
        measurements=measurements, model_name=model, serial_number=meta["serial_number"],
        measurement_start=start, measurement_end=end, unit=meta["unit"], data_no=data_no,
        metadata_lines=metadata_lines, warnings=warnings,
    )
