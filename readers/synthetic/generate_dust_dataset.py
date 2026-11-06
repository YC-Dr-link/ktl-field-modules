"""Generate fictional BAM/MEZUS dust-monitor screens for OCR evaluation.

Run from the repository root with ``python readers/synthetic/generate_dust_dataset.py``.
Pillow is only needed when regenerating the committed synthetic samples.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

OUTPUT = Path(__file__).resolve().parent / "dust"
COUNT_PER_DEVICE = 15
SIZE = (800, 600)
ITEMS = (
    "span_film",
    "span_1",
    "span_2",
    "mid_film",
    "linearity",
    "meas_flow",
    "rep_1",
    "rep_2",
    "rep_3",
    "blank_1",
    "blank_2",
    "blank_3",
    "env",
)


def _fonts() -> tuple[ImageFont.ImageFont, ImageFont.ImageFont, ImageFont.ImageFont]:
    return (
        ImageFont.load_default(size=22),
        ImageFont.load_default(size=17),
        ImageFont.load_default(size=62),
    )


def _draw_bam(value: str) -> Image.Image:
    image = Image.new("RGB", SIZE, (218, 222, 216))
    draw = ImageDraw.Draw(image)
    title_font, label_font, value_font = _fonts()
    draw.rounded_rectangle((142, 70, 658, 530), radius=24, fill=(56, 64, 59), outline=(25, 30, 27), width=5)
    draw.rectangle((196, 132, 604, 426), fill=(178, 205, 166), outline=(21, 33, 25), width=4)
    draw.text((220, 148), "CALIBRATION MODE", font=title_font, fill=(23, 38, 27))
    draw.text((220, 196), "CONC", font=label_font, fill=(30, 45, 31))
    draw.text((220, 246), value, font=value_font, fill=(16, 34, 20))
    draw.text((220, 344), "QTot 24.01", font=label_font, fill=(30, 45, 31))
    for x, label in ((212, "START"), (348, "NEXT"), (484, "EXIT")):
        draw.rounded_rectangle((x, 452, x + 96, 495), radius=8, fill=(166, 171, 164), outline=(35, 40, 37), width=2)
        draw.text((x + 15, 466), label, font=label_font, fill=(35, 40, 37))
    return image


def _draw_mezus(value: str) -> Image.Image:
    image = Image.new("RGB", SIZE, (206, 210, 206))
    draw = ImageDraw.Draw(image)
    title_font, label_font, value_font = _fonts()
    draw.rounded_rectangle((168, 74, 632, 526), radius=28, fill=(105, 110, 108), outline=(35, 39, 38), width=5)
    draw.rectangle((198, 126, 602, 442), fill=(24, 25, 24))
    draw.rectangle((218, 146, 582, 422), fill=(246, 246, 242))
    draw.text((232, 160), "Running", font=title_font, fill=(32, 38, 32))
    draw.text((232, 207), "mg/cm2", font=label_font, fill=(50, 55, 50))
    draw.text((232, 252), value, font=value_font, fill=(17, 22, 18))
    draw.text((232, 360), "MEZUS 610", font=label_font, fill=(44, 49, 44))
    draw.text((390, 360), "COUNT 12345", font=label_font, fill=(44, 49, 44))
    return image


def _distort(image: Image.Image, index: int, rng: random.Random) -> tuple[Image.Image, list[str]]:
    applied: list[str] = []
    if index % 7 in (1, 2):
        image = image.rotate(rng.choice((-2, -1, 1, 2)), resample=Image.Resampling.BICUBIC, fillcolor=(216, 219, 214))
        applied.append("rotation")
    if index % 5 == 0:
        image = image.filter(ImageFilter.GaussianBlur(radius=0.35))
        applied.append("blur")
    if index % 4 == 0:
        image = ImageEnhance.Contrast(image).enhance(0.9)
        applied.append("low_contrast")
    if index % 6 == 0:
        overlay = Image.new("RGBA", SIZE, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        draw.polygon(((470, 120), (590, 120), (430, 420), (335, 420)), fill=(255, 255, 255, 36))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        applied.append("reflection")
    if index % 3 == 0:
        import numpy as np

        pixels = np.asarray(image).astype(np.int16)
        noise = np.random.default_rng(20261106 + index).normal(0, 3, pixels.shape)
        image = Image.fromarray((pixels + noise).clip(0, 255).astype("uint8"))
        applied.append("noise")
    return image, applied


def generate() -> None:
    OUTPUT.mkdir(exist_ok=True)
    for model_index, model in enumerate(("bam1020", "mezus610")):
        for index in range(1, COUNT_PER_DEVICE + 1):
            seed = 2026110600 + model_index * 100 + index
            rng = random.Random(seed)
            raw_value = "0.000" if index == 1 else f"{(index * 137 + model_index * 53) % 9999 / 1000:.3f}"
            image = _draw_bam(raw_value) if model == "bam1020" else _draw_mezus(raw_value)
            image, distortions = _distort(image, index, rng)
            stem = f"dust_{model}_{index:03d}"
            image.save(OUTPUT / f"{stem}.jpg", format="JPEG", quality=94, optimize=True)
            answer = {
                "reader": "dust",
                "item": ITEMS[(index + model_index - 1) % len(ITEMS)],
                "model": model,
                "values": {"value": raw_value},
                "distortions": distortions,
            }
            (OUTPUT / f"{stem}.json").write_text(
                json.dumps(answer, ensure_ascii=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    generate()
