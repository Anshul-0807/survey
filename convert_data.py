import csv
import json
from collections import defaultdict

# 👇 Apni file ke actual column names yahan set karo
CSV_PATH = "mp_master_data.csv"
JSON_PATH = "mp_locations.json"
DISTRICT_COL = "District_Name_E"
TEHSIL_COL = "Tehsil_Name_E"
VILLAGE_COL = "Village_Name_E"


def csv_to_locations(csv_path, json_path):
    data = defaultdict(lambda: defaultdict(list))

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(f, dialect=dialect)
        actual_fields = [(fn or "").strip() for fn in reader.fieldnames]
        reader.fieldnames = actual_fields

        print(f"ℹ Detected delimiter: {repr(dialect.delimiter)}")
        print(f"ℹ Columns found ({len(actual_fields)}): {actual_fields}")

        missing = [c for c in (DISTRICT_COL, TEHSIL_COL, VILLAGE_COL) if c not in actual_fields]
        if missing:
            print(f"✗ Missing columns in CSV: {missing}")
            return

        row_count = 0
        skipped = 0
        debug_printed = 0
        for row in reader:
            row_count += 1
            d = (row.get(DISTRICT_COL) or "").strip()
            t = (row.get(TEHSIL_COL) or "").strip()
            v = (row.get(VILLAGE_COL) or "").strip()

            if debug_printed < 3:
                print(f"  [debug row {row_count}] District={d!r} Tehsil={t!r} Village={v!r}")
                debug_printed += 1

            if not d or not t or not v:
                skipped += 1
                continue
            if v not in data[d][t]:
                data[d][t].append(v)

    plain = {
        d: {t: sorted(villages) for t, villages in sorted(tehsils.items())}
        for d, tehsils in sorted(data.items())
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(plain, f, ensure_ascii=False, indent=2)

    n_districts = len(plain)
    n_tehsils = sum(len(t) for t in plain.values())
    n_villages = sum(len(v) for t in plain.values() for v in t.values())
    print(f"\n✓ Processed {row_count} rows ({skipped} skipped due to blank fields)")
    print(f"✓ Districts: {n_districts}, Tehsils: {n_tehsils}, Villages: {n_villages}")
    print(f"✓ Saved to {json_path}")


if __name__ == "__main__":
    csv_to_locations(CSV_PATH, JSON_PATH)