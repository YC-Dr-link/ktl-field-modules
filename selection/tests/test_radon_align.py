"""#15 (REQ-B4-08): 정렬 방식 sequence | hour + 기기 시계 차이."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ktl_selectors.radon_align import (RadonOptionError, align_files, format_offset,
                                       resolve_align, resolve_reference)
from ktl_selectors.radon_models import ChamberMeasurement, DeviceMeasurement, ParsedRadonFile
from ktl_selectors.radon_selector import RadonSelector

SYN = Path(__file__).resolve().parents[1] / "synthetic" / "radon_merge"
T0 = datetime(2026, 10, 22, 12, 0, 0)
H = timedelta(hours=1)
M = timedelta(minutes=1)


def device(name, times):
    rows = [DeviceMeasurement(i + 1, t, t.isoformat(), 100.0, 20.0, 40.0, 1013.0, i + 10)
            for i, t in enumerate(times)]
    return ParsedRadonFile(name, "txt", "device", [], rows, model_name="FRD500", serial_number=name)


def chamber(name, times):
    rows = [ChamberMeasurement(t, t.isoformat(), "1st Target Radon", 200.0, 200.0, 50.0, i + 12)
            for i, t in enumerate(times)]
    return ParsedRadonFile(name, "csv", "chamber", [], rows)


def hourly(start, n):
    return [start + k * H for k in range(n)]


def codes(alignment):
    return [w.code for w in alignment.warnings]


# --- sequence (기본) ---------------------------------------------------------

def test_sequence_pairs_same_position_and_trims_to_shortest():
    files = [device("ref", hourly(T0, 23)), device("a", hourly(T0 + 7 * M, 22))]
    result = align_files(files, reference=0, mode="sequence")
    assert len(result.slot_times) == 22
    assert result.rows == [list(range(22)), list(range(22))]
    assert result.clock == [None, None]          # 시계 차이는 hour에서만
    assert codes(result) == ["ALIGN_COUNT_MISMATCH"]


def test_default_mode_is_sequence():
    assert resolve_align({}) == "sequence"
    assert resolve_align(None) == "sequence"
    assert resolve_align({"align": "hour"}) == "hour"
    with pytest.raises(RadonOptionError):
        resolve_align({"align": "minute"})


# --- hour ----------------------------------------------------------------------

def test_hour_matches_nearest_and_reports_clock_offset():
    files = [device("ref", hourly(T0, 22)), device("slow", hourly(T0 - 3 * M, 22))]
    result = align_files(files, reference=0, mode="hour")
    assert result.tolerance_s == 1800
    assert result.rows[1] == list(range(22))
    clock = result.clock[1]
    assert (clock.offset_s, clock.drift_s) == (-180, 0)
    assert result.clock[0].offset_s == 0
    assert result.warnings == []


def test_hour_late_start_leaves_missing_slots_without_shifting_rows():
    # 순번 정렬이면 1:1로 붙지만, 시각 정렬이면 2시간 늦게 켠 기기는 기준기 3번째 행부터 대응한다.
    files = [device("ref", hourly(T0, 22)), device("late", hourly(T0 + 2 * H + 5 * M, 22))]
    result = align_files(files, reference=0, mode="hour")
    assert result.rows[1][:3] == [None, None, 0]
    assert result.rows[1][-1] == 19
    meta = result.to_meta(files)["files"][1]
    assert meta["missing_slots"] == [1, 2]
    assert meta["unmatched_rows"] == [21, 22]
    assert meta["clock"]["offset_text"] == "+5분"
    assert codes(result) == ["ALIGN_MISSING_SLOTS", "ALIGN_UNMATCHED_ROWS"]


def test_hour_reports_drift_of_running_fast_clock():
    times = [T0 + k * H + k * 20 * timedelta(seconds=1) for k in range(10)]   # 1시간에 20초씩 빨라짐
    result = align_files([device("ref", hourly(T0, 10)), device("fast", times)], mode="hour")
    clock = result.clock[1]
    assert (clock.min_offset_s, clock.max_offset_s, clock.drift_s) == (0, 180, 180)
    assert clock.offset_s == 90


def test_exactly_half_interval_is_ambiguous_and_not_matched():
    files = [device("ref", hourly(T0, 5)), device("half", hourly(T0 + 30 * M, 5))]
    result = align_files(files, mode="hour")
    assert result.rows[1] == [None] * 5
    assert result.clock[1] is None
    assert codes(result) == ["ALIGN_NO_MATCH"]


def test_one_row_is_used_for_only_one_slot():
    # 같은 기준 시각 근처에 두 행 → 가까운 행만 쓰고 다른 행은 빠진다.
    files = [device("ref", [T0, T0 + H]), device("dup", [T0 + 2 * M, T0 + 5 * M])]
    result = align_files(files, mode="hour")
    assert result.rows[1] == [0, None]
    assert result.to_meta(files)["files"][1]["unmatched_rows"] == [2]


def test_chamber_reference_uses_median_interval():
    # 챔버는 Start 다음 행만 5분 간격 → 허용 범위는 중앙 간격(1시간)의 절반.
    ref = chamber("1023.csv", [T0 - 65 * M, T0 - 60 * M] + hourly(T0, 5))
    result = align_files([ref, device("a", hourly(T0 + 4 * M, 5))], mode="hour")
    assert result.tolerance_s == 1800
    assert result.rows[1] == [None, None, 0, 1, 2, 3, 4]
    assert result.clock[1].offset_s == 240


def test_hour_needs_two_reference_rows():
    with pytest.raises(RadonOptionError):
        align_files([device("ref", [T0]), device("a", [T0])], mode="hour")


# --- 옵션 · 표시 ---------------------------------------------------------------

def test_resolve_reference_accepts_index_path_and_name():
    paths = ["/up/1023.csv", "/up/a.txt", "/other/b.txt"]
    assert resolve_reference(paths, {}) == 0
    assert resolve_reference(paths, {"reference": 2}) == 2
    assert resolve_reference(paths, {"reference": "/up/a.txt"}) == 1
    assert resolve_reference(paths, {"reference": "b.txt"}) == 2
    for bad in (3, -1, True, "file_11", 1.0):
        with pytest.raises(RadonOptionError):
            resolve_reference(paths, {"reference": bad})
    with pytest.raises(RadonOptionError, match="여러 개"):
        resolve_reference(["/x/a.txt", "/y/a.txt"], {"reference": "a.txt"})


@pytest.mark.parametrize("seconds, text", [
    (0, "0초"), (0.4, "0초"), (480, "+8분"), (-150, "-2분 30초"), (3725, "+1시간 2분 5초"), (-3600, "-1시간"),
])
def test_format_offset(seconds, text):
    assert format_offset(seconds) == text


# --- 합성 파일 15개로 Selector 진입점 -------------------------------------------

def synthetic_paths():
    return sorted(str(p) for p in SYN.glob("*") if p.suffix in {".csv", ".txt"})


def test_selector_align_hour_on_synthetic_files():
    paths = synthetic_paths()
    meta = RadonSelector().align(paths, {"align": "hour", "reference": "1023.csv"})
    json.dumps(meta)                                        # 서버가 그대로 응답에 실을 수 있어야 함
    by_name = {f["source_file"].split("_2026")[0].split("_20261022")[0]: f for f in meta["files"]}
    assert meta["align"] == "hour" and meta["slots"] == 24
    assert by_name["1023.csv"]["reference"] is True
    assert by_name["FA25_SYNTHETIC_004"]["clock"]["offset_text"] == "+8분"
    assert by_name["FA25_SYNTHETIC_004"]["missing_slots"] == [1, 2]    # Start · Source Purge 시각엔 아직 측정 전
    assert by_name["KTL_SYNTHETIC"]["matched"] == 21
    assert by_name["KTL_SYNTHETIC"]["unmatched_rows"] == [22, 23]
    assert all(f["clock"]["drift_s"] == 0 for f in meta["files"])
    assert {w["code"] for w in meta["warnings"]} == {"ALIGN_MISSING_SLOTS", "ALIGN_UNMATCHED_ROWS"}


def test_selector_align_defaults_to_sequence():
    meta = RadonSelector().align(synthetic_paths(), {})
    assert meta["align"] == "sequence" and meta["slots"] == 22
    assert all(f["clock"] is None for f in meta["files"])
    assert [w["code"] for w in meta["warnings"]] == ["ALIGN_COUNT_MISMATCH"]
