from pathlib import Path
import zipfile
import runpy

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "dashboard_bundle.zip"
TARGET = ROOT / "dashboard"

if not TARGET.is_dir():
    if not BUNDLE.is_file():
        raise FileNotFoundError("dashboard_bundle.zip غير موجود")
    with zipfile.ZipFile(BUNDLE) as z:
        z.extractall(ROOT)
    print("[Spectre] Dashboard files prepared.", flush=True)

runpy.run_path(str(ROOT / "start_latest.py"), run_name="__main__")
