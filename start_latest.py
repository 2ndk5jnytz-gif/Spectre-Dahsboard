from __future__ import annotations

import importlib.util
import os
import runpy
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "spectre_bot_latest.py"
REQUIREMENTS = ROOT / "requirements.txt"


def prepare_ffmpeg() -> None:
    """Use bundled FFmpeg when present, or unpack the compact archive once."""
    existing = ROOT / "bin" / "ffmpeg"
    archive = ROOT / "ffmpeg-static.tar.xz"
    runtime = ROOT / ".runtime" / "ffmpeg"
    configured = os.getenv("FFMPEG_PATH", "").strip()
    if configured:
        return
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        os.environ["FFMPEG_PATH"] = system_ffmpeg
        print(f"[Spectre] Using system FFmpeg at {system_ffmpeg}", flush=True)
        return
    if existing.is_file():
        os.environ.setdefault("FFMPEG_PATH", str(existing))
        return
    if not archive.is_file() or runtime.is_file():
        if runtime.is_file():
            os.environ.setdefault("FFMPEG_PATH", str(runtime))
        return
    runtime.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode="r:xz") as bundle:
        member = next((item for item in bundle.getmembers() if item.name.endswith("/ffmpeg")), None)
        if member is None:
            raise FileNotFoundError("لم أجد ملف ffmpeg داخل الأرشيف المضغوط")
        source = bundle.extractfile(member)
        if source is None:
            raise FileNotFoundError("تعذر قراءة ffmpeg من الأرشيف المضغوط")
        with runtime.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
    runtime.chmod(runtime.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.environ.setdefault("FFMPEG_PATH", str(runtime))
    print(f"[Spectre] Prepared bundled FFmpeg at {runtime}", flush=True)

# JustRunMyApp/Wispbyte قد يرفعان الملفات بدون تثبيت الاعتماديات تلقائياً.
# نثبّت فقط ما هو ناقص فعلياً من الوحدات المطلوبة وقت التشغيل.
_REQUIRED_MODULES = {
    "discord": "discord.py",
    "dotenv": "python-dotenv",
    "aiohttp": "aiohttp",
    "yt_dlp": "yt-dlp",
    "nacl": "PyNaCl",
    "davey": "davey",
    "flask": "Flask",
    "requests": "requests",
}
# الوحدات الحرجة: بدونها البوت لا يعمل إطلاقاً (حتى بدون صوت). الباقي
# (nacl/davey/yt_dlp) يخص ميزات الصوت فقط — لو تعذّر تثبيتها لسبب عابر (مثل
# عدم توفر عجلة مبنية مسبقاً لمعمارية نادرة)، الأفضل أن يستمر تشغيل البوت
# بكل ميزاته النصية بدل التوقف الكامل بسبب اعتمادية صوت اختيارية.
_CRITICAL_MODULES = {"discord", "dotenv", "aiohttp"}
_missing = [package for module, package in _REQUIRED_MODULES.items() if importlib.util.find_spec(module) is None]
prepare_ffmpeg()

if _missing:
    if not REQUIREMENTS.is_file():
        raise FileNotFoundError(f"لم أجد ملف المتطلبات: {REQUIREMENTS}")
    print(f"[Spectre] Installing missing dependencies: {', '.join(_missing)}", flush=True)
    bulk_install = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    if bulk_install.returncode != 0:
        # التثبيت الجماعي فشل — عادة بسبب حزمة واحدة عالقة (مثل عدم توفر عجلة
        # مبنية مسبقاً لهذه المعمارية بالذات). نجرّب كل حزمة على حدة بدل
        # إسقاط كل شيء، حتى تنجح الحزم القابلة للتثبيت ونعرف بالضبط أيها فشلت.
        print("[Spectre] Bulk install failed; retrying package-by-package...", flush=True)
        failed_packages = []
        for module, package in _REQUIRED_MODULES.items():
            if importlib.util.find_spec(module) is not None:
                continue
            result = subprocess.run([sys.executable, "-m", "pip", "install", package])
            if result.returncode != 0:
                failed_packages.append(package)
        if failed_packages:
            still_missing_critical = [
                package for module, package in _REQUIRED_MODULES.items()
                if module in _CRITICAL_MODULES and importlib.util.find_spec(module) is None
            ]
            print(f"[Spectre] تعذّر تثبيت: {', '.join(failed_packages)}", flush=True)
            if still_missing_critical:
                raise RuntimeError(f"تعذّر تثبيت اعتماديات أساسية لا يعمل البوت بدونها: {', '.join(still_missing_critical)}")
            print("[Spectre] الاعتماديات الحرجة سليمة؛ متابعة التشغيل بدون ميزات الصوت الناقصة.", flush=True)
    print("[Spectre] Dependencies check complete", flush=True)

if not TARGET.is_file():
    raise FileNotFoundError(f"لم أجد ملف تشغيل البوت: {TARGET}")

print("[Spectre] Starting spectre_bot_latest.py", flush=True)
runpy.run_path(str(TARGET), run_name="__main__")
