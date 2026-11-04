"""#15 (REQ-B4-08): 라돈 파일 정렬 방식(sequence | hour)과 기기 시계 차이.

입력 측정값을 바꾸거나 시각을 보정하지 않는다. 기준기 행(slot)마다 각 파일의
몇 번째 측정행이 대응하는지와, hour 정렬일 때 기준기와의 시각 차이만 계산한다.
병합·평균·지시오차·RAW 배치는 run() 쪽(REQ-B4-05)이 이 결과를 받아 쓴다.

- sequence: 순번 k ↔ 순번 k. 건수가 다르면 짧은 쪽에 맞추고 경고 (03 UI 시나리오 D).
- hour: 기준기 각 행에 가장 가까운 시각의 행을 1:1로 짝짓는다. 허용 범위는
  기준기 측정 간격의 절반 미만(1시간 간격이면 30분 미만). 정확히 절반이면 앞·뒤
  어느 쪽인지 모호하므로 짝짓지 않고 경고한다.
  TODO(확인 필요): KTL의 "라돈 정렬 기준" (01 §9). 정시 내림(같은 '시')인지,
  기준기 최근접 시각인지 연구원님 답을 받으면 이 규칙을 맞춘다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from ktl_contract import ReadError
from .radon_models import ParsedRadonFile, ParseWarning

ALIGN_MODES = ("sequence", "hour")
DEFAULT_ALIGN = "sequence"


class RadonOptionError(ReadError):
    """정렬 옵션(align · reference)이 잘못됨. 메시지는 화면에 그대로 보여 준다."""


def timestamps(parsed: ParsedRadonFile) -> list[datetime]:
    if parsed.format == "chamber":
        return [row.date for row in parsed.measurements]
    return [row.timestamp for row in parsed.measurements]


def resolve_align(options: dict | None) -> str:
    mode = (options or {}).get("align", DEFAULT_ALIGN)
    if mode not in ALIGN_MODES:
        raise RadonOptionError(f"정렬 방식은 sequence 또는 hour 이어야 합니다 (받은 값: {mode!r}).")
    return mode


def resolve_reference(paths: list[str], options: dict | None) -> int:
    """options["reference"] → paths 안의 위치(0부터). 없으면 첫 파일.

    정수(위치), 전체 경로, 파일 이름을 받는다.
    TODO(확인 필요): 02 §2.5 예시는 서버 파일 ID("file_11")다. 서버(B-1)가 모듈을
    부르기 전에 경로로 바꿔 넘기는지 확인 필요. 지금은 ID를 받으면 오류를 낸다.
    """
    ref = (options or {}).get("reference")
    if ref is None:
        return 0
    if isinstance(ref, bool):
        raise RadonOptionError(f"기준기 지정이 올바르지 않습니다: {ref!r}")
    if isinstance(ref, int):
        if 0 <= ref < len(paths):
            return ref
        raise RadonOptionError(f"기준기 번호 {ref}가 파일 개수({len(paths)})를 벗어났습니다.")
    if isinstance(ref, str):
        for index, path in enumerate(paths):
            if ref == path:
                return index
        names = [index for index, path in enumerate(paths) if Path(path).name == ref]
        if len(names) == 1:
            return names[0]
        if len(names) > 1:
            raise RadonOptionError(f"같은 이름의 파일이 여러 개라 기준기를 정할 수 없습니다: {ref}")
    raise RadonOptionError(f"기준기 파일을 찾을 수 없습니다: {ref!r}")


@dataclass
class ClockDifference:
    """기기 시각 − 기준기 시각(초). 짝지은 행들 기준."""
    offset_s: float          # 중앙값. 화면에 보여 줄 대표값
    min_offset_s: float
    max_offset_s: float
    drift_s: float           # 마지막 짝 − 첫 짝. 기기 시계가 점점 벌어지는지

    def to_dict(self) -> dict[str, Any]:
        return {"offset_s": self.offset_s, "min_offset_s": self.min_offset_s,
                "max_offset_s": self.max_offset_s, "drift_s": self.drift_s,
                "offset_text": format_offset(self.offset_s)}


@dataclass
class Alignment:
    mode: str
    reference: int
    slot_times: list[datetime]                 # 기준기 시각 (sequence면 기준기 행 시각)
    rows: list[list[int | None]]               # rows[파일][slot] = 측정행 위치(0부터) 또는 None
    clock: list[ClockDifference | None]        # hour만. 기준기 자신은 0, 짝이 없으면 None
    tolerance_s: float | None = None
    warnings: list[ParseWarning] = field(default_factory=list)

    def to_meta(self, files: list[ParsedRadonFile]) -> dict[str, Any]:
        """SelectResult.meta["alignment"]에 넣을 JSON 가능한 dict. 행 번호는 1부터."""
        out = []
        for index, (parsed, rows) in enumerate(zip(files, self.rows)):
            used = {r for r in rows if r is not None}
            out.append({
                "index": index, "source_file": parsed.source_file,
                "serial_number": parsed.serial_number, "model_name": parsed.model_name,
                "reference": index == self.reference,
                "rows": [None if r is None else r + 1 for r in rows],
                "matched": len(used), "total": parsed.measurement_count,
                "unmatched_rows": [r + 1 for r in range(parsed.measurement_count) if r not in used],
                "missing_slots": [s + 1 for s, r in enumerate(rows) if r is None],
                "clock": None if self.clock[index] is None else self.clock[index].to_dict(),
            })
        return {"align": self.mode, "reference": self.reference, "tolerance_s": self.tolerance_s,
                "slots": len(self.slot_times),
                "slot_times": [t.isoformat() for t in self.slot_times], "files": out}


def format_offset(seconds: float) -> str:
    """1080 → "+18분", -150 → "-2분 30초", 0 → "0초". 초 단위 반올림."""
    total = round(seconds)
    if total == 0:
        return "0초"
    sign = "+" if total > 0 else "-"
    hours, rest = divmod(abs(total), 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{hours}시간"] * bool(hours) + [f"{minutes}분"] * bool(minutes) + [f"{secs}초"] * bool(secs)
    return sign + " ".join(parts)


def align_files(files: list[ParsedRadonFile], *, reference: int = 0,
                mode: str = DEFAULT_ALIGN) -> Alignment:
    if not files:
        raise RadonOptionError("정렬할 라돈 파일이 없습니다.")
    if mode not in ALIGN_MODES:
        raise RadonOptionError(f"정렬 방식은 sequence 또는 hour 이어야 합니다 (받은 값: {mode!r}).")
    if not 0 <= reference < len(files):
        raise RadonOptionError(f"기준기 번호 {reference}가 파일 개수({len(files)})를 벗어났습니다.")
    return (_align_sequence if mode == "sequence" else _align_hour)(files, reference)


def _align_sequence(files: list[ParsedRadonFile], reference: int) -> Alignment:
    counts = [parsed.measurement_count for parsed in files]
    slots = min(counts)
    warnings = []
    if len(set(counts)) > 1:
        detail = ", ".join(f"{p.source_file} {n}건" for p, n in zip(files, counts))
        warnings.append(ParseWarning("ALIGN_COUNT_MISMATCH",
                                     f"파일마다 건수가 달라 짧은 쪽({slots}건)에 맞췄습니다: {detail}",
                                     files[reference].source_file))
    return Alignment("sequence", reference, timestamps(files[reference])[:slots],
                     [list(range(slots)) for _ in files], [None] * len(files), None, warnings)


def _align_hour(files: list[ParsedRadonFile], reference: int) -> Alignment:
    ref = files[reference]
    ref_times = timestamps(ref)
    steps = [(b - a).total_seconds() for a, b in zip(ref_times, ref_times[1:])]
    steps = [s for s in steps if s > 0]
    if not steps:
        raise RadonOptionError(f"{ref.source_file}: 기준기 측정이 2건 이상이어야 시각 정렬을 할 수 있습니다.")
    tolerance = median(steps) / 2
    rows, clock, warnings = [], [], []
    for index, parsed in enumerate(files):
        if index == reference:
            rows.append(list(range(len(ref_times))))
            clock.append(ClockDifference(0.0, 0.0, 0.0, 0.0))
            continue
        matched = _match(ref_times, timestamps(parsed), tolerance)
        rows.append(matched)
        clock.append(_clock(ref_times, timestamps(parsed), matched))
        used = {r for r in matched if r is not None}
        missing = [s + 1 for s, r in enumerate(matched) if r is None]
        unused = [r + 1 for r in range(parsed.measurement_count) if r not in used]
        if not used:
            warnings.append(ParseWarning("ALIGN_NO_MATCH",
                                         f"기준기 시각 ±{format_offset(tolerance)[1:]} 안에 맞는 측정이 하나도 없습니다.",
                                         parsed.source_file))
            continue
        if missing:
            warnings.append(ParseWarning("ALIGN_MISSING_SLOTS",
                                         f"기준기 {len(missing)}개 시각에 맞는 측정이 없습니다 (기준기 행 {_ranges(missing)}).",
                                         parsed.source_file))
        if unused:
            warnings.append(ParseWarning("ALIGN_UNMATCHED_ROWS",
                                         f"기준기 시각과 짝이 없어 측정 {len(unused)}건을 뺐습니다 (행 {_ranges(unused)}).",
                                         parsed.source_file))
    return Alignment("hour", reference, ref_times, rows, clock, tolerance, warnings)


def _match(ref_times: list[datetime], times: list[datetime], tolerance: float) -> list[int | None]:
    """가까운 쌍부터 1:1로 짝짓는다 (같은 거리면 앞 행 우선 → 결과가 항상 같음)."""
    pairs = sorted(
        (abs((t - r).total_seconds()), s, i)
        for s, r in enumerate(ref_times) for i, t in enumerate(times)
        if abs((t - r).total_seconds()) < tolerance
    )
    result: list[int | None] = [None] * len(ref_times)
    taken = set()
    for _, s, i in pairs:
        if result[s] is None and i not in taken:
            result[s] = i
            taken.add(i)
    return result


def _clock(ref_times, times, matched) -> ClockDifference | None:
    offsets = [(times[i] - ref_times[s]).total_seconds() for s, i in enumerate(matched) if i is not None]
    if not offsets:
        return None
    return ClockDifference(float(median(offsets)), min(offsets), max(offsets), offsets[-1] - offsets[0])


def _ranges(numbers: list[int]) -> str:
    """[1, 2, 3, 7] → "1~3, 7"."""
    parts, start = [], numbers[0]
    for a, b in zip(numbers, numbers[1:] + [None]):
        if b != a + 1:
            parts.append(str(start) if start == a else f"{start}~{a}")
            start = b
    return ", ".join(parts)
