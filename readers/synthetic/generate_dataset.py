"""Generate deterministic, fictional cert and flowmeter OCR samples.

Run from the repository root with:
    python readers/synthetic/generate_dataset.py

Requires Pillow in the environment used for dataset generation; it is not a
runtime dependency of ktl_readers.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
COUNT_PER_READER = 30
SIZE = (800, 600)
FONT = ImageFont.load_default(size=19)
SMALL_FONT = ImageFont.load_default(size=14)


def _draw_certificate(index: int, rng: random.Random) -> tuple[Image.Image, dict[str, str]]:
    image = Image.new("RGB", SIZE, (246, 246, 242))
    draw = ImageDraw.Draw(image)
    draw.rectangle((34, 30, 766, 570), fill=(255, 255, 252), outline=(45, 58, 62), width=3)
    draw.text((62, 54), "CALIBRATION CERTIFICATE", font=FONT, fill=(25, 42, 50))
    draw.text((62, 84), "SYNTHETIC SAMPLE - NOT AN OFFICIAL DOCUMENT", font=SMALL_FONT, fill=(140, 45, 45))
    draw.line((62, 116, 738, 116), fill=(80, 92, 96), width=2)

    answers = {
        "prev_receipt": f"SYN-PREV-{index:04d}",
        "approval_no": f"SYN-APP-{(index * 7) % 997:04d}",
        "maker": f"SYN MAKER {index % 9 + 1:02d}",
        "serial": f"SYN-SN-{index:04d}",
    }
    rows = [
        ("PREV. RECEIPT", answers["prev_receipt"]),
        ("APPROVAL NO.", answers["approval_no"]),
        ("MAKER", answers["maker"]),
        ("SERIAL", answers["serial"]),
    ]
    for row_index, (label, value) in enumerate(rows):
        top = 145 + row_index * 84
        draw.rounded_rectangle((62, top, 738, top + 62), radius=5, outline=(168, 178, 178), width=2)
        draw.text((80, top + 8), label, font=SMALL_FONT, fill=(76, 91, 96))
        draw.text((80 + rng.randrange(0, 3), top + 30), value, font=FONT, fill=(18, 27, 32))
    draw.text((62, 500), "All identifiers and values on this page are generated test data.", font=SMALL_FONT, fill=(88, 95, 98))
    return image, answers


def _draw_flowmeter(index: int, rng: random.Random) -> tuple[Image.Image, dict[str, str]]:
    image = Image.new("RGB", SIZE, (224, 228, 224))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((158, 42, 642, 558), radius=34, fill=(70, 78, 76), outline=(36, 42, 41), width=5)
    draw.rounded_rectangle((196, 98, 604, 420), radius=12, fill=(208, 224, 194), outline=(23, 34, 30), width=4)
    draw.text((222, 124), "REFERENCE FLOWMETER", font=SMALL_FONT, fill=(39, 58, 46))
    draw.text((222, 166), "FLOW", font=SMALL_FONT, fill=(39, 58, 46))
    value = f"{(index * 137 + 83) % 9999 / 1000:0.3f}"
    if index % 10 == 0:
        value = "0.000"
    elif index % 10 == 1:
        value = "9.999"
    draw.text((222 + rng.randrange(0, 4), 204), value, font=ImageFont.load_default(size=58), fill=(18, 38, 23))
    draw.text((470, 266), "L/min", font=FONT, fill=(39, 58, 46))
    draw.text((214, 368), "SYNTHETIC DISPLAY", font=SMALL_FONT, fill=(67, 83, 69))
    for button_x, label in ((220, "MODE"), (362, "ZERO"), (504, "ENTER")):
        draw.ellipse((button_x, 458, button_x + 72, 518), fill=(180, 185, 179), outline=(38, 44, 42), width=3)
        draw.text((button_x + 11, 478), label, font=SMALL_FONT, fill=(35, 40, 38))
    return image, {"flow": value}


def _apply_difficulty(
    image: Image.Image,
    index: int,
    rng: random.Random,
) -> tuple[Image.Image, list[str]]:
    applied: list[str] = []
    if index % 5 in (0, 1):
        angle = rng.choice((-7, -5, -3, 3, 5, 7))
        image = image.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=(238, 238, 234))
        applied.append("rotation")
    if index % 4 in (0, 1):
        image = image.filter(ImageFilter.GaussianBlur(radius=0.7 + (index % 3) * 0.25))
        applied.append("blur")
    if index % 3 == 0:
        overlay = Image.new("RGBA", SIZE, (255, 255, 255, 0))
        reflection = ImageDraw.Draw(overlay)
        reflection.ellipse((rng.randrange(350, 500), -100, 860, 340), fill=(255, 255, 255, 105))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        applied.append("reflection")
    if index % 2 == 0:
        noise = Image.frombytes("L", SIZE, rng.randbytes(SIZE[0] * SIZE[1])).convert("RGB")
        image = Image.blend(image, noise, 0.09)
        applied.append("noise")
    if index % 7 == 4:
        image = ImageEnhance.Contrast(image).enhance(0.72)
        applied.append("low_contrast")
    return image, applied


def _write_sample(directory: Path, stem: str, image: Image.Image, truth: dict[str, Any]) -> None:
    image_path = directory / f"{stem}.jpg"
    answer_path = directory / f"{stem}.json"
    image.save(image_path, format="JPEG", quality=84, optimize=True)
    answer_path.write_text(
        json.dumps(truth, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def generate() -> None:
    cert_dir = ROOT / "cert"
    flowmeter_dir = ROOT / "flowmeter"
    cert_dir.mkdir(exist_ok=True)
    flowmeter_dir.mkdir(exist_ok=True)

    for index in range(1, COUNT_PER_READER + 1):
        rng = random.Random(20261027 + index)
        image, answers = _draw_certificate(index, rng)
        image, difficulties = _apply_difficulty(image, index, rng)
        _write_sample(
            cert_dir,
            f"cert_{index:03d}",
            image,
            {
                "reader": "cert",
                "item": "cert",
                "values": answers,
                "distortions": difficulties,
            },
        )

        rng = random.Random(20301027 + index)
        item = ("prec_1", "prec_2", "prec_3", "flow_1", "flow_2", "flow_3")[(index - 1) % 6]
        image, answers = _draw_flowmeter(index, rng)
        image, difficulties = _apply_difficulty(image, index, rng)
        _write_sample(
            flowmeter_dir,
            f"flowmeter_{index:03d}",
            image,
            {
                "reader": "flowmeter",
                "item": item,
                "values": answers,
                "units": {"flow": "L/min"},
                "distortions": difficulties,
            },
        )


if __name__ == "__main__":
    generate()