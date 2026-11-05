from math import sqrt
from pathlib import Path

import pytest
from ktl_contract import ReadError
from ktl_selectors import get_selector
from ktl_selectors.radon import parse_radon_path
from ktl_selectors.radon_table import build_average_detail_table

SYN = Path(__file__).resolve().parents[1] / "synthetic" / "radon_average"


@pytest.mark.parametrize("ddof,expected", [(1, sqrt(13)), (0, sqrt(143 / 12))])
def test_sample_and_population_use_the_same_twelve_values_as_average(ddof, expected):
    paths = [str(SYN / name) for name in ("temperature.txt", "chamber.csv")]
    result = get_selector("radon_merge").run(paths, {"stddev_ddof": ddof})
    assert result.table["측정시간"].tolist()[-2:] == ["평균", "표준편차"]
    assert result.meta["standard_deviation"]["ddof"] == ddof
    for source, average in zip(result.meta["sources"], result.meta["averages"]):
        assert average["count"] == 12
        assert result.table.iloc[-2][source["value_column"]] == average["average"]
        assert result.table.iloc[-1][source["value_column"]] == pytest.approx(expected)


def test_constant_temperature_has_zero_standard_deviation_and_radon_is_not_used():
    parsed = parse_radon_path(str(SYN / "temperature.txt"))
    for row in parsed.measurements[-12:]:
        row.temp = 20.0
        row.radon = float(row.index * 100)
    table = build_average_detail_table([parsed])
    column = table.attrs["sources"][0]["value_column"]
    assert table.iloc[-2][column] == 20 and table.iloc[-1][column] == 0


@pytest.mark.parametrize("value", [None, True, -1, 2, "1"])
def test_invalid_ddof_is_rejected(value):
    with pytest.raises(ReadError, match="표준편차"):
        get_selector("radon_merge").run([str(SYN / "temperature.txt")], {"stddev_ddof": value})
