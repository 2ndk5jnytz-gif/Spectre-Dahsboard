"""نقطة تشغيل خفيفة للداشبورد على استضافة منفصلة (مثل Render) — بينما البوت
الكامل (بكل أوامره) يستمر بالعمل من استضافته الأصلية (مثل Wispbyte) بدون أي
تغيير عليه.

ليش نحتاج هذا الملف بدل تشغيل bot.py مباشرة على Render؟ لأن bot.py يشغّل
نسخة كاملة من البوت (كل الأوامر، كل الأحداث، مزامنة Slash Commands...)، ولو
شغّلناها مرتين بنفس الوقت (Wispbyte + Render) بنفس التوكن، راح تصير تعارضات
حقيقية (مزامنة أوامر متكررة، ردود مزدوجة على بعض الأحداث). هذا الملف يفتح
اتصالاً "خفيفاً" بديسكورد (بدون تسجيل أي أوامر) فقط لخدمة الداشبورد — ديسكورد
يسمح رسمياً بأكثر من اتصال (Session) لنفس البوت بنفس الوقت (تماماً متل ما تقدر
تفتح ديسكورد بجوالك وجهازك بنفس اللحظة)، فهذا آمن تماماً.
"""

from __future__ import annotations

import os
import threading
import zipfile
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("لم أجد DISCORD_TOKEN. أضفه بملف .env")

intents = discord.Intents.default()
intents.members = True  # مطلوب لبحث الأعضاء بالداشبورد (استثناء أدمن، إلخ)
intents.guilds = True

# نستخدم commands.Bot (وليس discord.Client) فقط لأن bot_actions.py وبعض
# دوال spectre_bot_latest.py (مثل build_apply_view) تتوقع كائناً من نوعه —
# لكن لا نسجّل عليه أي أمر إطلاقاً، فلا يوجد تعارض مع النسخة الكاملة بـWispbyte.
light_client = commands.Bot(command_prefix="!", intents=intents, help_command=None)
views_registered = False
ROOT = Path(__file__).resolve().parent


def ensure_dashboard_package() -> None:
    """Restore dashboard/ from the compact bundle when a deployment omits the directory."""
    dashboard_dir = ROOT / "dashboard"
    if (dashboard_dir / "app.py").is_file():
        return
    bundle = ROOT / "dashboard_bundle.zip"
    if not bundle.is_file():
        raise FileNotFoundError("لم أجد dashboard/app.py ولا dashboard_bundle.zip")
    with zipfile.ZipFile(bundle, "r") as archive:
        archive.extractall(ROOT)
    if not (dashboard_dir / "app.py").is_file():
        raise RuntimeError("فشل تجهيز الداشبورد: dashboard/app.py غير موجود.")
    print("[Spectre-Dashboard] Dashboard package restored from bundle.", flush=True)


@light_client.event
async def on_ready() -> None:
    global views_registered
    print(f"[Spectre-Dashboard] اتصال الداشبورد الخفيف جاهز: {light_client.user}", flush=True)

    if not views_registered:
        try:
            import json
            import db
            from spectre_bot_latest import (
                TicketCloseView, TicketCreateView, build_apply_view,
                build_faq_view, build_custom_workflow_view, build_panel_view,
            )
            db.init_db()
            light_client.add_view(TicketCloseView())
            for guild in light_client.guilds:
                settings = db.get_guild_settings(guild.id)
                light_client.add_view(
                    TicketCreateView(settings["ticket_emoji"], settings["ticket_label"], settings["ticket_style"])
                )
                light_client.add_view(build_apply_view(guild.id, settings["apply_emoji"], settings["apply_style"]))
                faqs = db.get_faqs(guild.id)
                if faqs:
                    light_client.add_view(build_faq_view(guild.id, faqs))
                for workflow_type in ("ticket", "application"):
                    workflow = db.get_workflow(guild.id, workflow_type)
                    if not workflow or not workflow.get("enabled", 1):
                        continue
                    try:
                        config = json.loads(workflow["config_json"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if isinstance(config, dict):
                        light_client.add_view(build_custom_workflow_view(guild.id, workflow_type, config))
                for panel in db.get_panels(guild.id):
                    try:
                        config = json.loads(panel["config_json"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if isinstance(config, dict):
                        light_client.add_view(build_panel_view(guild.id, config))
            views_registered = True
            print("[Spectre-Dashboard] Persistent dashboard buttons registered.", flush=True)
        except Exception as error:
            print(f"[Spectre-Dashboard] Persistent view registration warning: {error}", flush=True)

    ensure_dashboard_package()
    port = int(os.getenv("PORT") or os.getenv("SERVER_PORT") or "5000")
    from dashboard.app import run_embedded

    threading.Thread(target=run_embedded, args=(light_client, port), daemon=True, name="spectre-dashboard").start()
    print(f"[Spectre-Dashboard] لوحة التحكم تعمل على المنفذ {port}", flush=True)


if __name__ == "__main__":
    light_client.run(TOKEN)
