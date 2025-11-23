# import_from_excel.py
import os
import json
import openpyxl

from app import create_app
from extensions import db
from models import Question

XLSX_PATH = os.path.join("data", "questions.xlsx")

def import_from_xlsx(path):
    if not os.path.exists(path):
        print(f"❌ File not found: {path}")
        return []

    wb = openpyxl.load_workbook(path)
    sheet = wb.active

    rows = []
    headers = None

    for i, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        if i == 1:
            headers = [str(x).strip() if x else "" for x in row]
            print("📄 XLSX headers:", headers)
            continue

        rowdict = {}
        for h, val in zip(headers, row):
            rowdict[h] = "" if val is None else str(val)
        rows.append((i, rowdict))

    return rows

def normalize_difficulty(raw):
    if raw is None:
        return 1
    try:
        diff = int(raw)
    except:
        return 1

    # FIX RULES
    if diff <= 0:
        return 1
    if diff > 10:
        return 10
    return diff

def normalize_options(row):
    opts = []
    for i in range(1, 5):
        key = f"Op{i}"
        val = row.get(key, "").strip()
        if val:
            opts.append({"id": str(i), "text": val})
    return opts

def run_import():
    print(f"🔍 Looking for: {XLSX_PATH}")
    rows = import_from_xlsx(XLSX_PATH)
    print(f"📦 Found {len(rows)} question rows")

    added = 0
    skipped = []

    app = create_app()

    with app.app_context():
        for lineno, row in rows:

            prompt = row.get("Question", "").strip()
            if not prompt:
                skipped.append((lineno, "❌ Missing Question"))
                continue

            options = normalize_options(row)
            if len(options) < 2:
                skipped.append((lineno, "❌ Need at least 2 options"))
                continue

            correct = row.get("CorrectOp", "").strip()
            if not correct:
                skipped.append((lineno, "❌ Missing CorrectOp"))
                continue

            difficulty_raw = row.get("Difficulty", "1")
            difficulty = normalize_difficulty(difficulty_raw)

            q = Question(
                prompt=prompt,
                options_json=json.dumps(options, ensure_ascii=False),
                correct_answers=correct,
                qtype="single",
                difficulty=difficulty
            )
            db.session.add(q)
            added += 1

        db.session.commit()

    print(f"✅ Added: {added}")
    print(f"⚠️ Skipped: {len(skipped)}")
    for s in skipped:
        print(" ", s)

if __name__ == "__main__":
    run_import()
