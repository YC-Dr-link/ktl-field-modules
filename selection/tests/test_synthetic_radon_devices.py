"""실제 견본 없이 실행하는 합성 시험품 생성 검증 (pytest에서도 실행 가능)."""

import codecs
import csv
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
import unittest


SYN = Path(__file__).resolve().parents[1] / "synthetic" / "radon_merge"
generate = runpy.run_path(str(SYN / "generate_test_devices.py"))["generate"]


class SyntheticDeviceTests(unittest.TestCase):
    def test_counts_and_formats(self):
        with TemporaryDirectory() as folder:
            paths = generate(Path(folder))
            self.assertEqual(len(paths), 12)
            self.assertEqual(len(set(paths)), 12)
            self.assertEqual(Counter(p.name.split('_')[0] for p in paths),
                             {"F4N": 3, "FA25": 3, "GA21": 6})
            self.assertEqual(Counter(p.suffix for p in paths), {".txt": 9, ".csv": 3})
            self.assertEqual({p.name.split('_')[0] for p in paths if p.suffix == ".csv"},
                             {"F4N", "FA25", "GA21"})
            for path in paths:
                with self.subTest(file=path.name):
                    raw = path.read_bytes()
                    self.assertTrue(raw.startswith(codecs.BOM_UTF8))
                    self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
                    lines = raw.decode("utf-8-sig").splitlines()
                    if path.suffix == ".csv":
                        self.assertNotIn(b"\t", raw)
                        lines = ["\t".join(row) for row in csv.reader(lines)]
                    frd400 = path.name.startswith("F4N")
                    offset = 8 if frd400 else 9
                    self.assertEqual(len(lines), offset + 22)
                    rows = [line.split("\t") for line in lines[offset:]]
                    self.assertTrue(all(len(row) == 6 for row in rows))
                    self.assertEqual([int(row[0]) for row in rows], list(range(1, 23)))
                    self.assertEqual(rows[0][0], "1 ")
                    self.assertEqual(lines[2].split("\t")[1], path.name.split("_2026")[0])
                    fmt = "%Y.%m.%d %H:%M:%S" if frd400 else "%Y-%m-%d %H:%M:%S"
                    times = [datetime.strptime(row[1], fmt) for row in rows]
                    self.assertTrue(all(b - a == timedelta(hours=1)
                                        for a, b in zip(times, times[1:])))
                    for prefix, value in [("Date and Time(Start)", times[0]),
                                          ("Date and Time(Last)", times[-1])]:
                        line = next(line for line in lines if line.startswith(prefix))
                        self.assertEqual(datetime.strptime(line.split("\t")[1], fmt), value)
                    for row in rows:
                        for value in row[2:]:
                            float(value)
                    if frd400:
                        self.assertEqual(lines[1], "MODEL NAME:\tFRD400\tV2.0")
                        self.assertEqual(lines[7], "Data No :\t22")
                        self.assertTrue(rows[0][2].startswith(" "))
                        stats = lines[6].split("\t")
                        values = [int(row[2]) for row in rows]
                        self.assertEqual(stats[3], f"{sum(values) / 22:.0f}")
                        self.assertEqual(int(stats[5]), min(values))
                        self.assertEqual(int(stats[7]), max(values))
                    else:
                        self.assertEqual(lines[1], "MODEL NAME:\tFRD500")
                        self.assertEqual(lines[7], "Data No: 22")
                        self.assertEqual(lines[8], "No\tDate&Time\tRadon\tTemp\tHumi\tBaroMeter")

    def test_reproducible_and_preserves_existing_files(self):
        with TemporaryDirectory() as folder:
            output = Path(folder)
            reference = output / "1023.csv"
            reference.write_bytes(b"reference sentinel")
            first = {p.name: p.read_bytes() for p in generate(output)}
            second = {p.name: p.read_bytes() for p in generate(output)}
            self.assertEqual(first, second)
            self.assertEqual(reference.read_bytes(), b"reference sentinel")
            for name, expected in first.items():
                self.assertEqual((SYN / name).read_bytes(), expected)
                if name.endswith(".csv"):
                    self.assertFalse((SYN / name).with_suffix(".txt").exists())

    def test_devices_have_different_measurement_patterns(self):
        with TemporaryDirectory() as folder:
            patterns = []
            averages = []
            for path in generate(Path(folder)):
                offset = 8 if path.name.startswith("F4N") else 9
                delimiter = "," if path.suffix == ".csv" else "\t"
                with path.open(encoding="utf-8-sig", newline="") as source:
                    rows = list(csv.reader(source, delimiter=delimiter))[offset:]
                values = [float(row[2]) for row in rows]
                # 단순히 같은 곡선에 상수만 더한 파일들이 아닌지 확인한다.
                patterns.append(tuple(b - a for a, b in zip(values, values[1:])))
                averages.append([sum(float(row[c]) for row in rows) / 22
                                 for c in (3, 4, 5)])
            self.assertEqual(len(set(patterns)), 12)
            for column, minimum_spread in enumerate((1, 5, 5)):
                means = [row[column] for row in averages]
                self.assertGreater(max(means) - min(means), minimum_spread)


if __name__ == "__main__":
    unittest.main()
