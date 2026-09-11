"""نقطة تشغيل Wispbyte لبوت Spectre.

يجب ضبط Startup Command على: python3 main.py
"""
from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "spectre_bot_latest.py"

if not TARGET.is_file():
    raise FileNotFoundError(f"لم أجد ملف البوت الحديث: {TARGET}")

print("[Spectre] Wispbyte launcher: starting spectre_bot_latest.py", flush=True)
runpy.run_path(str(TARGET), run_name="__main__")
