from __future__ import annotations

import importlib.util
import os
import runpy
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "spectre_bot_latest.py"
REQUIREMENTS = ROOT / "requirements.txt"


def prepare_ffmpeg() -> None:
    """Resolve FFmpeg without bundling a huge binary inside the project ZIP."""
    configured = os.getenv("FFMPEG_PATH", "").strip()
    if configured:
        return

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        os.environ["FFMPEG_PATH"] = system_ffmpeg
        print(f"[Spectre] Using system FFmpeg at {system_ffmpeg}", flush=True)
        return

    existing = ROOT / "bin" / "ffmpeg"
    if existing.is_file():
        os.environ.setdefault("FFMPEG_PATH", str(existing))
        return

    # Keep the repository small: static-ffmpeg is a tiny Python package and
    # downloads/caches the correct platform binary only when needed.
    try:
        import static_ffmpeg
        from static_ffmpeg import run as static_run
        ffmpeg_path, _ffprobe_path = static_run.get_or_fetch_platform_executables_else_raise()
        os.environ["FFMPEG_PATH"] = str(ffmpeg_path)
        print(f"[Spectre] Using lazy static FFmpeg at {ffmpeg_path}", flush=True)
        return
    except Exception as error:
        print(f"[Spectre] static-ffmpeg unavailable: {error}", flush=True)

    raise FileNotFoundError(
        "FFmpeg not found. Install static-ffmpeg or provide FFMPEG_PATH."
    )

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
