import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from ktl_contract import ReadError
from ktl_contract.testing import check_reader, check_reader_rejects

from ktl_readers import get_reader
from ktl_readers import dust as dust_module

SYNTHETIC = Path(__file__).resolve().parents[1] / "synthetic" / "dust"


def _ocr_result(text, score=0.98, box=((100, 100), (350, 100), (350, 170), (100, 170))):
    return SimpleNamespace(
        txts=[text],
        scores=[score],
        boxes=np.asarray([box], dtype=np.float32),
    )


def _patch_two_crops(monkeypatch, results, source_to_crop=None):
    reader = get_reader("dust", fake_fallback=False)
    from ktl_readers import screen
    from ktl_readers import preprocess

    image = np.zeros((600, 800, 3), dtype=np.uint8)
    matrix = np.eye(3) if source_to_crop is None else source_to_crop
    monkeypatch.setattr(preprocess, "load_image", lambda _path: image)
    monkeypatch.setattr(
        screen,
        "extract_screens",
        lambda _image, width=800: [(image, matrix, "베이스"), (image, matrix, "이진")],
    )
    iterator = iter(results)
    monkeypatch.setattr(screen, "_ocr", lambda _crop: next(iterator))
    return reader


def test_dust_reader_uses_both_crops_and_maps_bbox(monkeypatch):
    reader = _patch_two_crops(monkeypatch, [_ocr_result("0.123"), _ocr_result("0.123", 0.96)])

    result = reader.read("unused.jpg", "span_1")

    assert len(result.values) == 1
    value = result.values[0]
    assert value.key == "value"
    assert value.value == "0.123"
    assert value.label == "스팬 1"
    assert value.confidence == 0.96
    assert value.bbox == [100, 100, 350, 170]
    assert not result.warnings


def test_bbox_is_transformed_back_to_original_image(monkeypatch):
    matrix = np.eye(3)
    matrix[0, 2] = -10
    matrix[1, 2] = -20
    _patch_two_crops(monkeypatch, [_ocr_result("0.123"), _ocr_result("0.123")], matrix)

    result = get_reader("dust", fake_fallback=False).read("unused.jpg", "span_1")

    assert result.values[0].bbox == [110, 120, 360, 190]


def test_disagreeing_crops_lower_confidence_and_warn(monkeypatch):
    reader = _patch_two_crops(monkeypatch, [_ocr_result("+12.34", 0.99), _ocr_result("+1234", 0.94)])

    result = reader.read("unused.jpg", "span_1")

    assert result.values[0].value == "+12.34"
    assert result.values[0].confidence <= 0.5
    assert result.warnings[0].code == "OCR_VARIANTS_DISAGREE"


def test_pre_measure_reading_has_warning(monkeypatch):
    _patch_two_crops(monkeypatch, [_ocr_result("0.000"), _ocr_result("0.000")])

    result = get_reader("dust", fake_fallback=False).read("unused.jpg", "span_1")

    assert any(warning.code == "PRE_MEASURE_SCREEN" for warning in result.warnings)


def test_missing_numeric_reading_raises_read_error(monkeypatch):
    _patch_two_crops(monkeypatch, [_ocr_result("Running"), _ocr_result("mg/cm2")])

    with pytest.raises(ReadError):
        get_reader("dust", fake_fallback=False).read("unused.jpg", "span_1")


def test_reader_contract_and_invalid_image(monkeypatch, tmp_path):
    reader = _patch_two_crops(monkeypatch, [_ocr_result("0.625"), _ocr_result("0.625")])
    assert check_reader(reader, "unused.jpg", "span_2") is not None

    from ktl_readers import preprocess

    def fail_to_load(_path):
        raise ReadError("사진을 열 수 없음")

    monkeypatch.setattr(preprocess, "load_image", fail_to_load)
    check_reader_rejects(reader, str(tmp_path / "missing.jpg"), "span_2")


def test_dust_synthetic_dataset_has_two_models_and_answers():
    images = sorted(SYNTHETIC.glob("*.jpg"))
    assert len(images) >= 30
    models = set()
    for image_path in images:
        truth = json.loads(image_path.with_suffix(".json").read_text(encoding="utf-8"))
        assert truth["reader"] == "dust"
        assert truth["values"].keys() == {"value"}
        assert isinstance(truth["values"]["value"], str)
        models.add(truth["model"])
        assert image_path.read_bytes().startswith(b"\xff\xd8")
    assert models == {"bam1020", "mezus610"}
