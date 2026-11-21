"""OCR evidence step for the wage tables (Step 7B, optional utility).

The Labour Bureau VDA order is a SCANNED PDF with no text layer, so
the numbers in ``data/kv_wage_tables_2026-10.json`` were read by
OCR. This script reproduces the raw OCR evidence (per-page text
with confidences) from the official PDF:

    python -m scripts.ingest.ocr_vda_order --out /tmp/lb-ocr.json

Needs ``rapidocr-onnxruntime`` (pip) and ``pdftoppm`` (poppler) —
neither is a dependency of the app or the main ingestion pipeline,
which is why this lives apart from ``wages.py``. The structured
data file is built from this script's output by hand, then
verified: every ``basic + VDA = total`` sum re-added
(``validate_wage_data`` in ``wages.py`` fails the ingest on any
mismatch) and all totals cross-checked against independent
readings of the same order. Never edit the data file's numbers
without re-running both checks.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PDF_URL = (
    "https://labourbureau.gov.in/uploads/public/notice/"
    "VDA-orders-October-2026-1pdf-f1c4d10c67a017bf34cd65319b294b99.pdf"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-url", default=PDF_URL)
    parser.add_argument("--pdf", default="", help="local PDF path (skips download)")
    parser.add_argument("--out", default="lb-ocr.json")
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args(argv)

    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        print(
            "ERROR: rapidocr-onnxruntime is not installed "
            "(pip install rapidocr-onnxruntime) — OCR is an optional "
            "evidence step, not part of the app.",
            file=sys.stderr,
        )
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = args.pdf or os.path.join(tmp, "vda-order.pdf")
        if not args.pdf:
            print(f"downloading {args.pdf_url}")
            urllib.request.urlretrieve(args.pdf_url, pdf_path)
        print(f"rendering {pdf_path} at {args.dpi} DPI")
        subprocess.run(
            ["pdftoppm", "-gray", "-r", str(args.dpi), "-png", pdf_path, os.path.join(tmp, "page")],
            check=True,
        )
        engine = RapidOCR()
        out: dict[str, list[dict]] = {}
        for page in sorted(glob.glob(os.path.join(tmp, "page-*.png"))):
            result, _ = engine(page)
            lines = [{"text": text, "conf": round(conf, 3)} for _box, text, conf in (result or [])]
            out[os.path.basename(page)] = lines
            print(f"{os.path.basename(page)}: {len(lines)} lines", flush=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {args.out} ({sum(len(v) for v in out.values())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
