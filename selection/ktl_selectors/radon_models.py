"""라돈 파서 전용 모델. ktl_contract의 Selector 계약과 독립적인 내부 API."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from ktl_contract import ReadError, Warning


class RadonParseError(ReadError):
    def __init__(self, filename: str, code: str, reason: str, line: int | None = None):
        self.source_file, self.code, self.line, self.reason = filename, code, line, reason
        location = f"{filename}:{line}" if line is not None else filename
        super().__init__(f"{location} [{code}] {reason}")


@dataclass
class ParseWarning(Warning):
    source_file: str
    line: int | None = None


@dataclass
class ChamberMeasurement:
    date: datetime
    date_raw: str
    sequence_status: str
    target_radon: float | None
    calculate_radon: float | None
    crm1_radon: float | None
    line: int
    raw_values: dict[str, str] = field(default_factory=dict)
    extra_values: dict[str, str] = field(default_factory=dict)


@dataclass
class DeviceMeasurement:
    index: int
    timestamp: datetime
    timestamp_raw: str
    radon: float | None
    temp: float | None
    humi: float | None
    barometer: float | None
    line: int
    raw_values: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedRadonFile:
    source_file: str
    file_type: str
    format: str
    columns: list[str]
    measurements: list[ChamberMeasurement] | list[DeviceMeasurement]
    model_name: str | None = None
    serial_number: str | None = None
    measurement_start: datetime | None = None
    measurement_end: datetime | None = None
    unit: str | None = None
    data_no: int | None = None
    metadata_lines: list[str] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)

    @property
    def measurement_count(self) -> int:
        return len(self.measurements)

    def to_dict(self) -> dict[str, Any]:
        """datetime을 ISO 8601 문자열로 바꾼 JSON 직렬화 가능한 사본."""
        def convert(value: Any) -> Any:
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, dict):
                return {key: convert(item) for key, item in value.items()}
            if isinstance(value, list):
                return [convert(item) for item in value]
            return value

        return {**convert(asdict(self)), "measurement_count": self.measurement_count}
