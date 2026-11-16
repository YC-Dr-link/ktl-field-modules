import csv
import io
from datetime import datetime
from pathlib import Path

import pytest

from ktl_selectors.radon import parse_radon_file
from ktl_selectors.radon_models import RadonParseError


FIXTURE = Path(__file__).resolve().parents[1] / "synthetic" / "radon_parser" / "chamber.csv"
REQUIRED = ["Date", "Sequence Status", "Target Radon", "Calculate Radon", "CRM-1 Radon"]


def parse(text):
    return parse_radon_file(filename="synthetic.csv", content=text.encode("utf-8-sig"))


def rows_text(rows):
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    return stream.getvalue()


def fixture_rows():
    return list(csv.reader(io.StringIO(FIXTURE.read_text(encoding="utf-8"))))


def test_required_columns_status_order_metadata_and_raw_values():
    result = parse(FIXTURE.read_text(encoding="utf-8"))
    assert result.format == "chamber" and result.file_type == "csv"
    assert result.columns == REQUIRED
    assert result.measurement_count == 4
    assert [item.sequence_status for item in result.measurements] == [
        "Start", "Source Purge", "1st Target Radon", "Zero Air Purge"
    ]
    assert [item.line for item in result.measurements] == [3, 4, 5, 6]
    first, _, third, _ = result.measurements
    assert first.date == datetime(2026, 10, 22, 10, 55)
    assert first.date_raw == "2026-10-22 10:55:00"
    assert first.extra_values == {"Extra": "synthetic-a"}
    assert third.target_radon == 200 and third.calculate_radon == 200.1 and third.crm1_radon == 50
    assert third.raw_values["Calculate Radon"] == "200.100"
    assert result.metadata_lines == ["Project Name : ,SYNTHETIC PARSER TEST,,,,"]
    assert result.to_dict()["measurements"][0]["date"] == "2026-10-22T10:55:00"


def test_reordered_columns_whitespace_quoted_cells_and_physical_lines():
    rows = fixture_rows()
    order = [4, 2, 1, 0, 3, 5]
    rows[1:] = [[row[index] for index in order] for row in rows[1:]]
    rows[1][2] = " Sequence   Status "
    rows[2][2] = " Start,\ncontinued "
    rows[2][4] = " 0.000 "
    # Input order is authoritative even when timestamps are not monotonic.
    rows[3][3] = "2026-10-22 09:00:00"
    result = parse(rows_text(rows))
    assert result.columns == [REQUIRED[index] for index in order if index < 5]
    assert result.measurements[0].sequence_status == " Start,\ncontinued "
    assert result.measurements[0].raw_values["Calculate Radon"] == " 0.000 "
    assert result.measurements[0].line == 3 and result.measurements[1].line == 5
    assert result.measurements[1].date.hour == 9


def test_blank_numeric_cells_remain_missing_with_warning():
    rows = fixture_rows()
    rows[2][2:5] = ["", " ", ""]
    result = parse(rows_text(rows))
    first = result.measurements[0]
    assert first.target_radon is first.calculate_radon is first.crm1_radon is None
    assert [(warning.code, warning.line) for warning in result.warnings] == [("MISSING_VALUE", 3)] * 3


@pytest.mark.parametrize(("column", "value", "code"), [
    (0, "2026-02-30 10:00:00", "INVALID_TIMESTAMP"),
    (2, "invalid", "INVALID_NUMBER"), (3, "NaN", "INVALID_NUMBER"),
    (4, "Infinity", "INVALID_NUMBER"),
])
def test_invalid_measurement_reports_filename_and_line(column, value, code):
    rows = fixture_rows()
    rows[2][column] = value
    with pytest.raises(RadonParseError) as error:
        parse(rows_text(rows))
    assert error.value.code == code and error.value.line == 3
    assert error.value.source_file == "synthetic.csv"


@pytest.mark.parametrize("change", ["short", "long", "duplicate", "missing", "empty"])
def test_invalid_structure(change):
    rows = fixture_rows()
    if change == "short":
        rows[2].pop()
    elif change == "long":
        rows[2].append("unexpected")
    elif change == "duplicate":
        rows[1][-1] = " Date "
    elif change == "missing":
        rows[1][3] = "unrecognized"
    else:
        rows = rows[:2]
    expected = {"short": "INVALID_ROW", "long": "INVALID_ROW", "duplicate": "INVALID_HEADER",
                "missing": "MISSING_COLUMNS", "empty": "NO_DATA"}[change]
    with pytest.raises(RadonParseError) as error:
        parse(rows_text(rows))
    assert error.value.code == expected


def test_malformed_csv_rejected():
    text = FIXTURE.read_text(encoding="utf-8").replace("synthetic-a", '"unterminated')
    with pytest.raises(RadonParseError) as error:
        parse(text)
    assert error.value.code == "INVALID_CSV" and error.value.line == 3
