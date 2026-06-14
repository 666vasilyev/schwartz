"""
Recompute lemma_baseline.json from the actual CSV files.
Run once after updating lemma CSVs:

    python scripts/compute_lemma_baseline.py
"""
from __future__ import annotations
import csv
import json
from pathlib import Path

CSV_COLUMNS = (
    "Безопасность",
    "Социальная интегрированность",
    "Амбиозность",
    "Индивидуальность",
    "Рациональность",
    "Красота",
    "Социальная справедливость",
    "Гражданственность / Общественный договор",
    "Процветание",
    "Свобода совести",
)

FILES: dict[str, tuple[str, list[str]]] = {
    "ru":     ("ru.csv",     ["cp1251", "utf-8"]),
    "ru_un":  ("ru_un.csv",  ["utf-8", "cp1251"]),
    "usa":    ("usa.csv",    ["utf-8", "cp1251"]),
    "usa_un": ("usa_un.csv", ["utf-8", "cp1251"]),
    "frg":    ("frg.csv",    ["utf-8", "cp1251"]),
}

LEMMA_DIR = Path(__file__).parents[1] / "server" / "lemma"
OUTPUT = LEMMA_DIR / "lemma_baseline.json"


def detect_encoding(path: Path, options: list[str]) -> str:
    for enc in options:
        try:
            path.read_text(encoding=enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "cp1251"


def compute_baseline(path: Path, encoding: str) -> dict[str, float]:
    totals = {k: 0.0 for k in CSV_COLUMNS}
    count = 0
    with open(path, encoding=encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        next(reader, None)  # skip header
        for row in reader:
            if len(row) < len(CSV_COLUMNS) + 1:
                continue
            ok = True
            for i, col in enumerate(CSV_COLUMNS, start=1):
                try:
                    totals[col] += float(row[i].replace(",", ".").strip())
                except (ValueError, IndexError):
                    ok = False
                    break
            if ok:
                count += 1
    if count == 0:
        return {k: 0.0 for k in CSV_COLUMNS}
    return {k: round(v / count, 6) for k, v in totals.items()}


def main() -> None:
    baseline: dict = {}
    for lang, (filename, enc_options) in FILES.items():
        path = LEMMA_DIR / filename
        if not path.exists():
            print(f"[SKIP] {filename} not found")
            continue
        enc = detect_encoding(path, enc_options)
        print(f"[{lang}] encoding={enc}", end=" ... ", flush=True)
        vals = compute_baseline(path, enc)
        baseline[lang] = {"label": lang, "schwartz_values": vals}
        print("OK")

    OUTPUT.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nBaseline written to {OUTPUT}")


if __name__ == "__main__":
    main()
