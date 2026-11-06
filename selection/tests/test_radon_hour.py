import copy
from datetime import datetime, timedelta
from math import sqrt
import json
from pathlib import Path

import pytest
from ktl_contract import ReadError
from ktl_selectors.radon import parse_radon_path
from ktl_selectors.radon_models import RadonParseError
from ktl_selectors.radon_table import build_average_detail_table

DEVICE = Path(__file__).resolve().parents[1] / "synthetic" / "radon_average" / "temperature.txt"


def device_at(minute=0, *, offset_hours=0):
    parsed = parse_radon_path(str(DEVICE))
    for index, row in enumerate(parsed.measurements[-12:]):
        row.timestamp = datetime(2026, 1, 3, 23, minute, 47) + timedelta(hours=index + offset_hours)
    return parsed


def test_2300_2304_2321_share_one_hour_and_date_is_preserved():
    parsed = [device_at(minute) for minute in (0, 4, 21)]
    original = copy.deepcopy(parsed)
    table = build_average_detail_table(parsed)
    assert table.shape == (14, 4) and table.columns.is_unique
    assert table["측정시간"].tolist() == [
        (datetime(2026, 1, 3, 23) + timedelta(hours=i)).isoformat(sep=" ") for i in range(12)
    ] + ["평균", "표준편차"]
    for source in table.attrs["sources"]:
        assert table[source["value_column"]].tolist() == pytest.approx(list(range(20, 32)) + [25.5, sqrt(13)])
        assert source["time_column"] == "측정시간"
    assert table.attrs["sources"][2]["selected_timestamps"][0] == "2026-01-03 23:21:47"
    assert parsed == original


def test_missing_hours_are_blank_not_zero_and_averages_use_original_twelve():
    first, second = device_at(), device_at(4, offset_hours=2)
    first.measurements[-12].temp = 0
    table = build_average_detail_table([first, second])
    one, two = table.attrs["sources"]
    assert table.shape == (16, 3)
    assert table.iloc[0][one["value_column"]] == 0
    assert table.iloc[0][two["value_column"]] is None
    assert table.iloc[-3][one["value_column"]] is None
    assert table.iloc[-2][one["value_column"]] == pytest.approx(25.5 - 20 / 12)
    assert table.iloc[-2][two["value_column"]] == 25.5
    assert table.to_csv(index=False).splitlines()[1].endswith(",")
    json.dumps(table.values.tolist(), allow_nan=False)


def test_same_clock_hour_on_different_dates_stays_separate():
    table = build_average_detail_table([device_at(), device_at(21, offset_hours=24)])
    assert len(table) == 26
    assert table.iloc[0]["측정시간"] == "2026-01-03 23:00:00"
    assert table.iloc[12]["측정시간"] == "2026-01-04 23:00:00"


def test_duplicate_hour_in_one_device_is_an_error_instead_of_overwrite():
    parsed = device_at()
    parsed.measurements[-11].timestamp = parsed.measurements[-12].timestamp + timedelta(minutes=4)
    with pytest.raises(RadonParseError) as caught:
        build_average_detail_table([parsed])
    assert caught.value.code == "DUPLICATE_HOUR"
    assert caught.value.source_file == DEVICE.name
    assert caught.value.line == parsed.measurements[-11].line


def test_unsorted_times_keep_values_attached_to_original_rows():
    parsed = device_at(59)
    parsed.measurements[-12].timestamp, parsed.measurements[-1].timestamp = (
        parsed.measurements[-1].timestamp, parsed.measurements[-12].timestamp)
    table = build_average_detail_table([parsed])
    column = table.attrs["sources"][0]["value_column"]
    assert table.iloc[0]["측정시간"] == "2026-01-03 23:00:00" and table.iloc[0][column] == 31
    assert table.iloc[-3]["측정시간"] == "2026-01-04 10:00:00" and table.iloc[-3][column] == 20
    assert table.iloc[-2][column] == 25.5


def test_unknown_alignment_is_rejected():
    with pytest.raises(ReadError, match="hour"):
        build_average_detail_table([device_at()], align="nearest")
