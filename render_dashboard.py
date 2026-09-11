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


@light_client.event
async def on_ready() -> None:
    print(f"[Spectre-Dashboard] اتصال الداشبورد الخفيف جاهز: {light_client.user}", flush=True)
    port = int(os.getenv("PORT") or os.getenv("SERVER_PORT") or "5000")
    from dashboard.app import run_embedded

    threading.Thread(target=run_embedded, args=(light_client, port), daemon=True, name="spectre-dashboard").start()
    print(f"[Spectre-Dashboard] لوحة التحكم تعمل على المنفذ {port}", flush=True)


if __name__ == "__main__":
    light_client.run(TOKEN)
