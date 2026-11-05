"""시험품 합성 TXT 9개·CSV 3개 생성. 실제 견본 없이 데이터는 22행 고정."""

import csv
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from random import Random


# 확인한 FRD400 1개와 FRD500 3개 견본 모두 측정 데이터가 22행이다.
DATA_ROWS = 22
CSV_DEVICES = {1, 4, 7}  # F4N·FA25·GA21 각 1개를 쉼표 구분 합성 변형으로 만든다.


def generate(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for device in range(1, 13):
        frd400 = device <= 3
        prefix = "F4N" if frd400 else "FA25" if device <= 6 else "GA21"
        serial = f"{prefix}_SYNTHETIC_{device:03d}"
        start = datetime(2026, 10, 22, 13 if frd400 else 12) + timedelta(
            minutes=device * 2
        )
        end = start + timedelta(hours=DATA_ROWS - 1)
        fmt = "%Y.%m.%d %H:%M:%S" if frd400 else "%Y-%m-%d %H:%M:%S"
        filename_fmt = "%Y%m%d %H%M%S" if frd400 else "%Y-%m-%d %H_%M_%S"
        # 고정 시드로 파일별 변화 폭과 모양을 다르게 하되 재생성 결과는 유지한다.
        rng = Random(102300 + device)
        if frd400:
            middle = [180 + device + (i % 5 - 2) * 5
                      for i in range(DATA_ROWS - 2)]
            rng.shuffle(middle)
            # 기존 헤더를 유지하기 위해 총합·최소·최대는 바꾸지 않는다.
            ceiling = max(middle)
            for i in range(0, len(middle), 2):
                if ceiling in middle[i:i + 2]:
                    continue
                change = rng.randint(-25, 25)
                left, right = middle[i] + change, middle[i + 1] - change
                if 100 <= left <= ceiling and 100 <= right <= ceiling:
                    middle[i:i + 2] = [left, right]
            values = [40 + device] + middle + [60 + device]
        else:
            level = 155 + (device * 17) % 85
            spread = 8 + device % 5 * 3
            values = [rng.randint(25, 75), rng.randint(85, 130)] + [
                level + rng.randint(-spread, spread)
                for _ in range(DATA_ROWS - 4)
            ] + [rng.randint(90, 140), rng.randint(30, 80)]
        if frd400:
            # TODO(확인 필요): 장비의 3day 집계 정의. 합성 22행의 요약을 임시 사용.
            lines = [
                "FTLAB RADON DATA FILE",
                "MODEL NAME:\tFRD400\tV2.0",
                f"S/N:\t{serial}",
                f"Date and Time(Start):\t{start.strftime(fmt)}",
                f"Date and Time(Last):\t{end.strftime(fmt)}",
                "Unit:\tBq/m3 ",
                "Duration(min):\t60"
                f"\t3day Avg:Bq/m3:\t{sum(values) / DATA_ROWS:.0f}"
                f"\t3day Min:Bq/m3:\t{min(values)}"
                f"\t3day Max:Bq/m3:\t{max(values)}",
                f"Data No :\t{DATA_ROWS}",
            ]
        else:
            lines = [
                "FTLAB RADON DATA FILE",
                "MODEL NAME:\tFRD500",
                f"SN:\t{serial}",
                "MeasMode:\tMeasurement Rn222",
                f"Date and Time(Start)\t{start.strftime(fmt)}",
                f"Date and Time(Last)\t{end.strftime(fmt)}",
                "Unit:\tBq/m3",
                f"Data No: {DATA_ROWS}",
                "No\tDate&Time\tRadon\tTemp\tHumi\tBaroMeter",
            ]
        for i, value in enumerate(values):
            timestamp = (start + timedelta(hours=i)).strftime(fmt)
            radon = f"{value:3d}" if frd400 else str(value)
            lines.append(
                f"{i + 1:<2d}\t{timestamp}\t{radon}\t"
                f"{20 + (device * 7) % 35 / 10 + rng.uniform(-0.8, 0.8):.1f}\t"
                f"{36 + (device * 3) % 22 + rng.randint(-3, 3)}\t"
                f"{995 + (device * 7) % 24 + rng.randint(-2, 2)}"
            )
        extension = ".csv" if device in CSV_DEVICES else ".txt"
        path = output_dir / f"{serial}_{start.strftime(filename_fmt)}{extension}"
        if device in CSV_DEVICES:
            buffer = StringIO(newline="")
            csv.writer(buffer, lineterminator="\r\n").writerows(
                line.split("\t") for line in lines
            )
            content = buffer.getvalue()
        else:
            content = "\r\n".join(lines) + "\r\n"
        path.write_bytes(content.encode("utf-8-sig"))
        paths.append(path)
    return paths


if __name__ == "__main__":
    for path in generate(Path(__file__).resolve().parent):
        print(path.name)
