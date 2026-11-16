"""Small invented fixtures; mutations are in memory and never rewrite examples."""
from datetime import datetime
from pathlib import Path

import pytest

from ktl_selectors.radon import parse_radon_file
from ktl_selectors.radon_models import RadonParseError

FIXTURES = Path(__file__).parents[1] / "synthetic" / "radon_parser"


def content(model="500"):
    return (FIXTURES / f"device{model}.txt").read_text(encoding="utf-8")


def parse(text, filename="upload.txt"):
    return parse_radon_file(filename=filename, content=text.encode("utf-8"))


@pytest.mark.parametrize("model,name", [("400", "FRD400"), ("500", "FRD500"), ("2400", "FRD2400V1")])
def test_models_and_measurements(model, name):
    result = parse(content(model))
    assert result.model_name == name
    assert result.serial_number == f"SYNTHETIC-{model}"
    assert result.unit == "Bq/m3"
    assert result.data_no == result.measurement_count == 2
    row = result.measurements[0]
    assert (row.radon, row.temp, row.humi, row.barometer) == (46, 27, 31, 1023)
    assert isinstance(row.timestamp, datetime)
    assert result.measurement_start == datetime(2026, 1, 2, 12)
    assert result.measurement_end == datetime(2026, 1, 2, 13)
    assert not result.warnings


def test_raw_values_order_and_json():
    result = parse(content("400"))
    assert [row.index for row in result.measurements] == [2, 1]
    assert result.measurements[1].radon == -99  # Meaning unknown; no replacement.
    assert result.measurements[0].timestamp_raw == "2026.01.02 13:00:00"
    result = parse(content())
    assert result.measurements[0].raw_values["radon"] == "046"
    assert result.to_dict()["measurements"][0]["timestamp"] == "2026-01-02T12:00:00"


@pytest.mark.parametrize("serial_label", ["SN:", "SN :", "S/N:", " S / N :"])
def test_serial_variants(serial_label):
    assert parse(content().replace("SN:", serial_label)).serial_number == "SYNTHETIC-500"


@pytest.mark.parametrize("model", ["400", "500", "2400"])
def test_csv_device_variant_and_extension_independence(model):
    text = content(model)
    if model == "400":
        # Use explicit CSV fields for this headerless space-delimited fixture.
        text = text.replace("MODEL NAME: FRD400 V2.0", "MODEL NAME:,FRD400,V2.0")
        text = text.replace("2 2026.01.02 13:00:00 46 27.0 31 1023", "2,2026.01.02 13:00:00,46,27.0,31,1023")
        text = text.replace("1    2026.01.02 12:00:00    -99    26.0    39    1022", "1,2026.01.02 12:00:00,-99,26.0,39,1022")
    else:
        text = text.replace("\t", ",")
    assert parse(text, "uploaded.csv").measurement_count == 2
    assert parse(text, "uploaded.txt").measurement_count == 2
    assert parse(content(model), "uploaded.csv").measurement_count == 2


def test_mixed_whitespace_and_header_aliases():
    text = content().replace("Date&Time", "DT").replace("Radon", "Rn-222")
    text = text.replace("Temp\tHumi", "Temp.\tHumi.")
    text = text.replace("\t046\t27.0\t31", "  046\t27.0    31")
    assert parse(text).measurements[0].temp == 27


def test_reordered_header():
    text = content().splitlines()
    for index in (8, 9, 10):
        cells = text[index].split("\t")
        cells[2], cells[3] = cells[3], cells[2]
        text[index] = "\t".join(cells)
    row = parse("\n".join(text)).measurements[0]
    assert (row.radon, row.temp) == (46, 27)


@pytest.mark.parametrize("old,new,code", [
    ("SN:\tSYNTHETIC-500", "", "MISSING_METADATA"),
    ("Unit:\tBq/m3", "", "MISSING_METADATA"),
    ("2026-01-02 12:00:00\t046", "2026-13-02 12:00:00\t046", "INVALID_TIMESTAMP"),
    ("\t046\t", "\tbad\t", "INVALID_NUMBER"),
    ("\t27.0\t", "\tNaN\t", "INVALID_NUMBER"),
    ("\t27.0\t31\t1023", "\t27.0\t31", "INVALID_ROW"),
    ("\t27.0\t31\t1023", "\t27.0\t31\t1023\textra", "INVALID_ROW"),
    ("Data No: 2", "Data No: nope", "INVALID_COUNT"),
    ("Humi\tBaroMeter", "Temp\tBaroMeter", "INVALID_HEADER"),
])
def test_invalid_input(old, new, code):
    with pytest.raises(RadonParseError) as exc:
        parse(content().replace(old, new))
    assert exc.value.code == code
    assert exc.value.source_file == "upload.txt"
    assert exc.value.line is not None


def test_missing_value_and_count_are_warnings():
    result = parse(content().replace("\t046\t", "\t\t").replace("Data No: 2", "Data No: 3"))
    assert result.measurements[0].radon is None
    assert result.measurements[0].temp == 27
    assert {warning.code for warning in result.warnings} == {"MISSING_VALUE", "COUNT_MISMATCH"}
    assert all(warning.line for warning in result.warnings)


def test_no_measurements():
    with pytest.raises(RadonParseError, match="NO_MEASUREMENTS"):
        parse("\n".join(content().splitlines()[:9]))


def test_malformed_row_after_data_is_not_ignored():
    with pytest.raises(RadonParseError):
        parse(content() + "broken row\n")


def test_unknown_model_is_not_guessed_from_filename():
    with pytest.raises(RadonParseError):
        parse(content().replace("FRD500", "FRD999"), "FRD500_SYNTHETIC.txt")


def test_headerless_only_for_observed_frd400():
    text = "\n".join(line for line in content().splitlines() if not line.startswith("No\t"))
    with pytest.raises(RadonParseError, match="MISSING_HEADER"):
        parse(text)


@pytest.mark.parametrize("bad_index", ["bad", "bad:"])
def test_malformed_first_headerless_row_is_not_metadata(bad_index):
    text = content("400").replace("2 2026.01.02", f"{bad_index} 2026.01.02")
    with pytest.raises(RadonParseError) as exc:
        parse(text)
    assert exc.value.line == 9


def test_raw_tab_cells_and_quoted_csv_metadata():
    text = content().replace("\t046\t", "\t 046 \t")
    assert parse(text).measurements[0].raw_values["radon"] == " 046 "
    text = content().replace("\t", ",").replace("SN:,SYNTHETIC-500", 'SN:,"SYNTHETIC-500"')
    text = text.replace("MODEL NAME:,FRD500", 'MODEL NAME:,"FRD500"')
    assert parse(text).serial_number == "SYNTHETIC-500"


def test_time_span_mismatch_warning():
    text = content().replace("Date and Time(Last)\t2026-01-02 13:00:00", "Date and Time(Last)\t2026-01-02 12:00:00")
    assert "TIME_RANGE_MISMATCH" in {warning.code for warning in parse(text).warnings}


def test_frd2400_mixed_whitespace_with_trailing_tab():
    text = content("2400").replace("\t27.0\t31", "\t27.0 31")
    row = parse(text).measurements[0]
    assert (row.radon, row.temp, row.humi, row.barometer) == (46, 27, 31, 1023)
