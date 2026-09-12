"""بوت ديسكورد عربي متكامل.

الملفات المطلوبة في نفس المجلد:
- bot.py  (هذا الملف)
- db.py
- .env    وفيه DISCORD_TOKEN=توكن_البوت

لا تشارك التوكن مع أي أحد.
"""

from __future__ import annotations
SPECTRE_RUNTIME_MARKER = "SPECTRE-V3-GUARD-2026-09-05"
print(f"[Spectre] Runtime marker: {SPECTRE_RUNTIME_MARKER} | file={__file__}", flush=True)

import asyncio
import base64
import json
import os
import random
import re
import time
import traceback
import zlib
from io import BytesIO
from collections import defaultdict
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ext.commands.view import StringView
from dotenv import load_dotenv
import aiohttp
from aiohttp import web
from PIL import Image, ImageDraw, ImageFont, ImageOps

import db
import presence_config
import counting
import radio
import antinuke
import adhkar
import social_notifications
import games

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# ============================================================
# الإعداد العام والنوايا
# ============================================================

intents = discord.Intents.default()
intents.message_content = True  # مطلوب لأوامر ! ولحساب XP من الرسائل.
intents.members = True          # مطلوب للترحيب والرتب والتقديم.
intents.guilds = True
intents.voice_states = True
intents.bans = True

ALLOWED_MENTIONS = discord.AllowedMentions(roles=True, users=True, everyone=False)
DASHBOARD_COMMAND_MARKER = "\u2063spectre-dashboard:"
BOT_BUILD_ID = "2026-09-11-radio-reliable-source-1"
DEFAULT_QURAN_RADIO_STREAM_URL = radio.DEFAULT_QURAN_RADIO_STREAM_URL
radio_manager = radio.RadioManager()


async def db_call(func, *args, **kwargs):
    """ينفّذ استدعاء SQLite المتزامن (db.py) في Thread منفصل حتى لا يوقف حلقة
    الأحداث الرئيسية. بدون هذا، أي تأخر بسيط في قاعدة البيانات (مثل تعارض قفل
    عابر) يمنع الرد على زر أو نموذج خلال 3 ثوانٍ فيظهر خطأ ديسكورد الأحمر
    "the application didn't respond in time" حتى مع استخدام interaction.response.defer().
    """
    return await asyncio.to_thread(func, *args, **kwargs)


_ticket_creation_locks: dict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)

_settings_cache: dict[int, tuple[float, dict]] = {}
_SETTINGS_CACHE_TTL = 5.0  # ثوانٍ. قصير عمداً حتى يبقى تعديل لوحة التحكم "شبه فوري"
# (أقصى تأخير 5 ثوانٍ) بدل قراءة قاعدة البيانات من القرص مع كل رسالة يرسلها أي
# عضو في أي سيرفر، وهي أكثر نقطة استدعاء تكراراً بالبوت بالكامل.


async def cached_guild_settings(guild_id: int) -> dict:
    now = time.monotonic()
    cached = _settings_cache.get(guild_id)
    if cached and now - cached[0] < _SETTINGS_CACHE_TTL:
        return cached[1]
    settings = await db_call(db.get_guild_settings, guild_id)
    _settings_cache[guild_id] = (now, settings)
    return settings


async def send_mod_log(guild: discord.Guild, embed: discord.Embed) -> None:
    """يرسل Embed سجل إلى قناة اللوق المضبوطة للسيرفر (إن وُجدت). يُستخدم مع
    الطرد/الباند/التايم أوت وفتح/إغلاق التذاكر ليعرف الأدمن من نفّذ الإجراء وأين."""
    settings = await db_call(db.get_guild_settings, guild.id)
    channel_id = settings.get("mod_log_channel_id")
    if not channel_id:
        return
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


def normalize_command_token(value: str) -> str:
    return (value or "").translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ـ": ""})).replace("\u200f", "").replace("\u200e", "").replace("\u2060", "").strip()


DASHBOARD_COMMAND_ALIASES = {
    "ضبط_خبرة_اللفلات": "ضبط_خبرة_اللفل",
    "ضبط_رسالة_اللفلات": "ضبط_رسالة_اللفل",
    "إضافة_لفل_رتبة": "اضافة_لفل_رتبة",
    "إعداد_روم_العد": "اعداد_روم_العد",
    "تشغيل_إذاعة_القرآن": "تشغيل_القرآن",
    "إيقاف_القرآن": "ايقاف_القرآن",
    "اذكار_الان": "أذكار_الآن",
    "اذكار_الآن": "أذكار_الآن",
    "أذكار_العام": "أذكار_الآن",
    "اذكار_العام": "أذكار_الآن",
}


def normalize_dashboard_command(content: str, active_prefix: str, known_names: Iterable[str]) -> str:
    """يوحّد الأمر والـ alias حتى مع اختلاف بادئة الداشبورد عن البادئة المحفوظة في البوت."""
    text = content.strip()
    prefix = active_prefix if isinstance(active_prefix, str) and active_prefix else "!"
    if text.startswith(prefix):
        command_text = text[len(prefix):].lstrip()
    elif text.startswith(("!", "/")):
        command_text = text[1:].lstrip()
    else:
        command_text = text
    parts = command_text.split(maxsplit=1)
    if not parts:
        return f"{prefix}{command_text}"
    token = parts[0]
    suffix = f" {parts[1]}" if len(parts) == 2 else ""
    normalized_token = normalize_command_token(token)
    for name in sorted(set(known_names), key=len, reverse=True):
        if token == name or token.endswith(name) or normalized_token == normalize_command_token(name):
            canonical = DASHBOARD_COMMAND_ALIASES.get(name, name)
            return f"{prefix}{canonical}{suffix}"
    if normalized_token in {"اذكار_الان", "اذكار_الآن", "اذكار_العام"}:
        return f"{prefix}أذكار_الآن{suffix}"
    return f"{prefix}{command_text}"

async def dynamic_prefix(_bot: commands.Bot, message: discord.Message) -> str:
    if not message.guild:
        return "!"
    # هذي الدالة تُستدعى مع كل رسالة يستقبلها البوت في كل السيرفرات (قبل حتى
    # معرفة إن كانت أمر أو لا)، فكانت أخطر نقطة حجب بالكود كله. تحويلها لغير
    # متزامنة (async + db_call) يفصل قراءة قاعدة البيانات عن حلقة الأحداث تماماً.
    settings = await cached_guild_settings(message.guild.id)
    prefix = settings.get("prefix", "!")
    return prefix if isinstance(prefix, str) and prefix else "!"


async def build_dashboard_context(message: discord.Message) -> commands.Context:
    """Build a command context without get_context's bot-author guard.

    ملاحظة مهمة: dynamic_prefix صارت async (لتفادي حجب حلقة الأحداث)، فلازم
    ننتظرها هنا بـ await. نسيان الـ await كان يمرر Coroutine بدل نص فعلي لدالة
    view.skip_string() فيرمي TypeError فوراً، وهذا كان يعطّل كل أوامر الداشبورد
    الخارجية بالكامل (كانت تفشل قبل حتى الوصول لتنفيذ أي أمر حقيقي)."""
    prefix = await dynamic_prefix(bot, message)
    view = StringView(message.content)
    context = commands.Context(prefix=None, view=view, bot=bot, message=message)
    if not view.skip_string(prefix):
        return context
    view.skip_ws()
    context.prefix = prefix
    context.invoked_with = view.get_word()
    context.command = bot.all_commands.get(context.invoked_with)
    if context.command is None:
        canonical = normalize_command_token(context.invoked_with)
        if canonical in {"اذكار_الان", "اذكار_الآن", "اذكار_العام"}:
            context.invoked_with = "أذكار_الآن"
            context.command = bot.all_commands.get(context.invoked_with)
    return context


class SpectreBot(commands.Bot):
    """Bot wrapper that keeps prefix commands when Discord's 100 global
    application-command limit is reached during hybrid registration.
    discord.py registers the prefix command before attaching its app command;
    therefore catching only CommandLimitReached preserves the full feature.
    """

    def add_command(self, command, *, override=False):
        try:
            # ملاحظة مهمة: discord.py's BotBase.add_command() الأصلية لا تقبل
            # معامل override إطلاقاً بهذه النسخة (>=2.4). المعامل override هنا
            # موجود فقط بتوقيع دالتنا نحن (للتوافق مع أي استدعاء خارجي يمرره)،
            # ولا يجب تمريره لدالة discord.py الأصلية أبداً — تمريره كان يسبب
            # TypeError فوري عند إضافة أول أمر بالبوت، ويمنع تشغيل البوت بالكامل!
            return super().add_command(command)
        except Exception as error:
            if type(error).__name__ != "CommandLimitReached":
                raise
            print(
                f"[Spectre] Slash limit reached; kept prefix command: "
                f"{getattr(command, 'name', '<unknown>')}",
                flush=True,
            )
            return None

bot = SpectreBot(command_prefix=dynamic_prefix, intents=intents, allowed_mentions=ALLOWED_MENTIONS, help_command=None)


@bot.before_invoke
async def _auto_defer_slash_commands(ctx: commands.Context) -> None:
    """يفعّل ديسكورد قاعدة الرد خلال 3 ثوانٍ فقط على أي Slash Command. الكثير من أوامر
    البوت (طرد/باند/... إلخ) قد تأخذ أكثر من 3 ثوانٍ (إرسال DM، استعلام قاعدة بيانات، ...)،
    فينتهي وقت التفاعل ويصير الأمر مُنفَّذاً فعلياً لكن الرد النهائي يفشل بخطأ
    "رفض Discord الطلب (HTTP 404)" رغم نجاح الأمر. هذا الحارس العام يعمل defer() تلقائياً
    قبل أي أمر يُستخدم كـ Slash، فيمنع هذه المشكلة نهائياً لكل الأوامر دفعة واحدة.
    """
    if ctx.interaction is not None and not ctx.interaction.response.is_done():
        try:
            await ctx.defer()
        except discord.HTTPException:
            pass

STYLE_MAP: dict[str, discord.ButtonStyle] = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
    "blurple": discord.ButtonStyle.primary,
    "ازرق": discord.ButtonStyle.primary,
    "أزرق": discord.ButtonStyle.primary,
    "blue": discord.ButtonStyle.primary,
    "green": discord.ButtonStyle.success,
    "اخضر": discord.ButtonStyle.success,
    "أخضر": discord.ButtonStyle.success,
    "red": discord.ButtonStyle.danger,
    "احمر": discord.ButtonStyle.danger,
    "أحمر": discord.ButtonStyle.danger,
    "grey": discord.ButtonStyle.secondary,
    "gray": discord.ButtonStyle.secondary,
    "رمادي": discord.ButtonStyle.secondary,
    "link": discord.ButtonStyle.link,
}

COLOR_MAP: dict[str, discord.Color] = {
    "blurple": discord.Color.blurple(),
    "ازرق": discord.Color.blue(),
    "أزرق": discord.Color.blue(),
    "blue": discord.Color.blue(),
    "اخضر": discord.Color.green(),
    "أخضر": discord.Color.green(),
    "green": discord.Color.green(),
    "احمر": discord.Color.red(),
    "أحمر": discord.Color.red(),
    "red": discord.Color.red(),
    "رمادي": discord.Color.light_grey(),
    "grey": discord.Color.light_grey(),
    "gray": discord.Color.light_grey(),
    "ذهبي": discord.Color.gold(),
    "gold": discord.Color.gold(),
    "بنفسجي": discord.Color.purple(),
    "purple": discord.Color.purple(),
    "برتقالي": discord.Color.orange(),
    "orange": discord.Color.orange(),
}

ADMIN_PERMISSIONS = (
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "kick_members",
    "ban_members",
    "moderate_members",
    "manage_messages",
)


def parse_style(name: str | None) -> discord.ButtonStyle:
    return STYLE_MAP.get((name or "").strip().lower(), discord.ButtonStyle.primary)


def parse_emoji(raw: str | None) -> str | discord.PartialEmoji | None:
    """يقبل إيموجي الهاتف أو إيموجي مخصص بصيغة <:name:id>."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        parsed = discord.PartialEmoji.from_str(raw)
        return parsed if parsed.id else raw
    except (TypeError, ValueError):
        return raw


def parse_color(raw: str | None) -> discord.Color:
    """يقبل لوناً عربياً/إنجليزياً أو كود HEX مثل #5865F2."""
    value = (raw or "").strip().lower()
    if value in COLOR_MAP:
        return COLOR_MAP[value]
    if value.startswith("#") and len(value) == 7:
        try:
            return discord.Color(int(value[1:], 16))
        except ValueError:
            pass
    return discord.Color.blurple()


def is_staff_role(role: discord.Role) -> bool:
    if role.is_default() or role.managed:
        return False
    return any(getattr(role.permissions, permission, False) for permission in ADMIN_PERMISSIONS)


def is_staff_member(member: discord.abc.User | discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    return any(is_staff_role(role) for role in member.roles)


def get_staff_roles(guild: discord.Guild) -> list[discord.Role]:
    return [role for role in guild.roles if is_staff_role(role)]


def get_staff_mentions(guild: discord.Guild) -> str:
    return " ".join(role.mention for role in get_staff_roles(guild))


def staff_only():
    async def predicate(ctx: commands.Context) -> bool:
        if isinstance(ctx.author, discord.Member) and is_staff_member(ctx.author):
            return True
        raise commands.MissingPermissions(["إدارة السيرفر"])

    return commands.check(predicate)


def can_moderate(actor: discord.Member, target: discord.Member) -> tuple[bool, str]:
    """يمنع معاقبة المالك أو رتبة أعلى أو عضو أعلى من رتبة البوت."""
    guild = actor.guild
    me = guild.me
    if target.id == actor.id:
        return False, "لا يمكنك تنفيذ إجراء إداري على نفسك."
    if target.id == guild.owner_id:
        return False, "لا يمكن تنفيذ هذا الإجراء على مالك السيرفر."
    if actor.id != guild.owner_id and target.top_role >= actor.top_role:
        return False, "رتبة العضو المستهدف مساوية أو أعلى من رتبتك."
    if me and target.top_role >= me.top_role:
        return False, "رتبة العضو المستهدف مساوية أو أعلى من رتبة البوت؛ ارفع رتبة البوت أولاً."
    return True, ""


def safe_channel(guild: discord.Guild, channel_id: int | None) -> discord.abc.GuildChannel | None:
    return guild.get_channel(channel_id) if channel_id else None


# ============================================================
# رسائل Embed: لون + صورة + صورة مصغرة + Footer
# ============================================================

class EmbedModal(discord.ui.Modal, title="إنشاء رسالة مضمّنة"):
    embed_title = discord.ui.TextInput(label="العنوان", required=False, max_length=256)
    embed_desc = discord.ui.TextInput(label="المحتوى", style=discord.TextStyle.paragraph, max_length=4000)
    embed_color = discord.ui.TextInput(
        label="اللون: أزرق/أخضر/أحمر أو #5865F2", required=False, max_length=20
    )
    image_url = discord.ui.TextInput(label="رابط الصورة الكبيرة (اختياري)", required=False, max_length=400)
    thumbnail_url = discord.ui.TextInput(label="رابط الصورة المصغرة (اختياري)", required=False, max_length=400)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.channel or not hasattr(interaction.channel, "send"):
            await interaction.response.send_message("❌ لا أستطيع النشر في هذه القناة.", ephemeral=True)
            return

        embed = discord.Embed(
            title=self.embed_title.value or None,
            description=self.embed_desc.value,
            color=parse_color(self.embed_color.value),
            timestamp=datetime.now(timezone.utc),
        )
        if self.image_url.value.strip():
            embed.set_image(url=self.image_url.value.strip())
        if self.thumbnail_url.value.strip():
            embed.set_thumbnail(url=self.thumbnail_url.value.strip())
        embed.set_footer(text=f"نُشرت بواسطة {interaction.user.display_name}")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ تم نشر الرسالة الملوّنة بنجاح.", ephemeral=True)


async def open_embed_modal(interaction: discord.Interaction) -> None:
    if not is_staff_member(interaction.user):
        await interaction.response.send_message("❌ هذا الأمر للإدارة فقط.", ephemeral=True)
        return
    await interaction.response.send_modal(EmbedModal())


@bot.tree.command(name="embed", description="أنشئ Embed ملوّناً مع صورة (للإدارة)")
async def embed_slash_command(interaction: discord.Interaction) -> None:
    await open_embed_modal(interaction)


@bot.tree.command(name="رسالة_مضمنة", description="أنشئ رسالة ملوّنة مع صورة (للإدارة)")
async def arabic_embed_slash_command(interaction: discord.Interaction) -> None:
    await open_embed_modal(interaction)


@bot.hybrid_command(name="تضمين", aliases=["embed_msg"])
@staff_only()
@commands.guild_only()
async def send_embed_prefix(ctx: commands.Context, attachment: Optional[discord.Attachment] = None, *, data: str) -> None:
    """!تضمين العنوان | المحتوى | اللون | رابط_الصورة | رابط_المصغرة

    يمكن إرسال صورة مرفقة من الهاتف مع الأمر بدلاً من رابط الصورة (كأمر نصي أو Slash).
    """
    parts = [part.strip() for part in data.split("|")]
    if len(parts) < 2:
        await ctx.send("❌ الصيغة: `!تضمين العنوان | المحتوى | اللون | رابط الصورة (اختياري) | رابط المصغرة (اختياري)`")
        return
    title, description = parts[0], parts[1]
    color = parts[2] if len(parts) > 2 else "blurple"
    image_url = parts[3] if len(parts) > 3 else ""
    thumbnail_url = parts[4] if len(parts) > 4 else ""
    if attachment and not image_url:
        image_url = attachment.url
    elif ctx.message.attachments and not image_url:
        image_url = ctx.message.attachments[0].url

    embed = discord.Embed(title=title or None, description=description, color=parse_color(color))
    if image_url:
        embed.set_image(url=image_url)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    embed.set_footer(text=f"بواسطة {ctx.author.display_name}")
    await ctx.send(embed=embed)


# ============================================================
# الأزرار والأسئلة الشائعة: Ephemeral Messages
# ============================================================

class FAQButton(discord.ui.Button):
    def __init__(self, faq_id: int, label: str, emoji: str, style: str):
        super().__init__(
            label=label[:80],
            style=parse_style(style),
            emoji=parse_emoji(emoji),
            custom_id=f"faq:{faq_id}",
        )
        self.faq_id = faq_id

    async def callback(self, interaction: discord.Interaction) -> None:
        entry = await db_call(db.get_faq, self.faq_id)
        if not entry:
            await interaction.response.send_message("❌ هذا الزر لم يعد موجوداً.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"❓ {entry['question']}",
            description=entry["answer"],
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def build_faq_view(guild_id: int, faqs: list[dict]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for entry in faqs[:25]:  # هذا حد ديسكورد للأزرار في رسالة واحدة.
        label = entry["question"][:80]
        view.add_item(FAQButton(entry["id"], label, entry["emoji"], entry["style"]))
    return view


@bot.command(name="اضافة_زر", aliases=["اضافة_سؤال"])
@staff_only()
@commands.guild_only()
async def add_faq_cmd(ctx: commands.Context, *, data: str) -> None:
    """!اضافة_زر النص على الزر | الرد الخاص | الإيموجي | اللون"""
    parts = [part.strip() for part in data.split("|")]
    if len(parts) < 2:
        await ctx.send("❌ الصيغة: `!اضافة_زر النص على الزر | الرد الخاص | إيموجي (اختياري) | لون (اختياري)`")
        return
    question, answer = parts[0], parts[1]
    if not question or not answer:
        await ctx.send("❌ اكتب نص الزر والرد الخاص معاً.")
        return
    emoji = parts[2] if len(parts) >= 3 and parts[2] else "❓"
    style = parts[3] if len(parts) >= 4 and parts[3] else "blurple"
    new_id = db.add_faq(ctx.guild.id, question, answer, emoji, style)
    await ctx.send(f"✅ تمت إضافة الزر رقم `#{new_id}`. استخدم `!نشر_الازرار` لإظهاره.")


@bot.command(name="حذف_زر", aliases=["حذف_سؤال"])
@staff_only()
@commands.guild_only()
async def delete_faq_cmd(ctx: commands.Context, faq_id: int) -> None:
    if db.delete_faq(ctx.guild.id, faq_id):
        await ctx.send(f"🗑️ تم حذف الزر رقم `#{faq_id}`. انشر لوحة جديدة لتحديث الرسالة.")
    else:
        await ctx.send("❌ لم أجد هذا الزر في السيرفر.")


@bot.command(name="عرض_الازرار", aliases=["عرض_الاسئلة"])
@staff_only()
@commands.guild_only()
async def list_faq_cmd(ctx: commands.Context) -> None:
    faqs = db.get_faqs(ctx.guild.id)
    if not faqs:
        await ctx.send("لا توجد أزرار محفوظة حتى الآن.")
        return
    lines = [f"`#{faq['id']}` {faq['emoji']} **{faq['question']}** — اللون: `{faq['style']}`" for faq in faqs]
    embed = discord.Embed(title="لوحة الأزرار المحفوظة", description="\n".join(lines), color=discord.Color.blurple())
    await ctx.send(embed=embed)


@bot.command(name="نشر_الازرار", aliases=["نشر_الاسئلة"])
@staff_only()
@commands.guild_only()
async def publish_faq(ctx: commands.Context) -> None:
    faqs = db.get_faqs(ctx.guild.id)
    if not faqs:
        await ctx.send("❌ أضف زرّاً واحداً على الأقل أولاً عبر `!اضافة_زر`.")
        return
    embed = discord.Embed(
        title="📚 المعلومات والأسئلة الشائعة",
        description="اضغط أي زر في الأسفل؛ سيظهر الرد لك أنت فقط.",
        color=discord.Color.blurple(),
    )
    view = build_faq_view(ctx.guild.id, faqs)
    bot.add_view(view)
    await ctx.send(embed=embed, view=view)


# ============================================================
# نظام التقديم للإدارة: Modal + قبول/رفض مع سبب Ephemeral
# ============================================================

class ReviewReasonModal(discord.ui.Modal, title="سبب رفض طلب الإدارة"):
    reason = discord.ui.TextInput(
        label="اكتب السبب الذي سيصل لمقدم الطلب",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, application_id: int):
        super().__init__()
        self.application_id = application_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        application = await db_call(db.get_application, self.application_id)
        if not application:
            await interaction.followup.send("❌ لم أجد الطلب.", ephemeral=True)
            return
        if not is_staff_member(interaction.user):
            await interaction.followup.send("❌ هذا الإجراء للإدارة فقط.", ephemeral=True)
            return
        if not await db_call(db.review_application, self.application_id, "rejected", interaction.user.id, self.reason.value):
            await interaction.followup.send("⚠️ تمت مراجعة هذا الطلب سابقاً.", ephemeral=True)
            return

        applicant = interaction.guild.get_member(application["applicant_id"]) if interaction.guild else None
        if applicant:
            try:
                await applicant.send(
                    f"❌ تم رفض طلبك للإدارة في **{interaction.guild.name}**.\n**السبب:** {self.reason.value}"
                )
            except discord.Forbidden:
                pass
        await interaction.followup.send("✅ تم رفض الطلب وإرسال السبب لصاحبه إن كانت الخاصية مفتوحة.", ephemeral=True)
        if interaction.message:
            view = ReviewActionView(self.application_id, disabled=True)
            await interaction.message.edit(view=view)


class ReviewActionView(discord.ui.View):
    def __init__(self, application_id: int, disabled: bool = False):
        super().__init__(timeout=None)
        self.application_id = application_id
        # المعرّفات فريدة لكل طلب حتى لا تختلط أزرار الطلبات بعد إعادة التشغيل.
        self.accept_button.custom_id = f"application_accept:{application_id}"
        self.reject_button.custom_id = f"application_reject:{application_id}"
        self.accept_button.disabled = disabled
        self.reject_button.disabled = disabled

    @discord.ui.button(label="قبول", style=discord.ButtonStyle.success, emoji="✅", custom_id="application_accept")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not is_staff_member(interaction.user):
            await interaction.response.send_message("❌ زر المراجعة مخصص للإدارة فقط.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        application = await db_call(db.get_application, self.application_id)
        if not application:
            await interaction.followup.send("❌ لم أجد بيانات هذا الطلب.", ephemeral=True)
            return
        if not await db_call(db.review_application, self.application_id, "accepted", interaction.user.id, "تم القبول"):
            await interaction.followup.send("⚠️ تمت مراجعة هذا الطلب سابقاً.", ephemeral=True)
            return

        applicant = interaction.guild.get_member(application["applicant_id"]) if interaction.guild else None
        if applicant:
            try:
                await applicant.send(f"🎉 تم قبول طلبك للانضمام إلى إدارة **{interaction.guild.name}**. بالتوفيق!")
            except discord.Forbidden:
                pass
        await interaction.followup.send("✅ تم قبول الطلب. وصلت رسالة خاصة لصاحبه إن كانت الخاصية مفتوحة.", ephemeral=True)
        self.accept_button.disabled = True
        self.reject_button.disabled = True
        if interaction.message:
            await interaction.message.edit(view=self)

    @discord.ui.button(label="رفض مع سبب", style=discord.ButtonStyle.danger, emoji="❌", custom_id="application_reject")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not is_staff_member(interaction.user):
            await interaction.response.send_message("❌ زر المراجعة مخصص للإدارة فقط.", ephemeral=True)
            return
        application = await db_call(db.get_application, self.application_id)
        if not application or application["status"] != "pending":
            await interaction.response.send_message("⚠️ تمت مراجعة هذا الطلب سابقاً أو لم يعد موجوداً.", ephemeral=True)
            return
        await interaction.response.send_modal(ReviewReasonModal(self.application_id))


class StaffApplyModal(discord.ui.Modal, title="التقديم للإدارة"):
    age = discord.ui.TextInput(label="كم عمرك؟", max_length=10)
    reason = discord.ui.TextInput(label="لماذا تريد الانضمام للإدارة؟", style=discord.TextStyle.paragraph, max_length=500)
    experience = discord.ui.TextInput(label="خبرتك السابقة ورتبتك؟", style=discord.TextStyle.paragraph, max_length=500)
    position = discord.ui.TextInput(label="ما الرتبة التي تتقدم إليها؟", max_length=80)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ التقديم متاح داخل السيرفر فقط.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        settings = await db_call(db.get_guild_settings, interaction.guild.id)
        review_channel = safe_channel(interaction.guild, settings["review_channel_id"])
        if not isinstance(review_channel, discord.TextChannel):
            await interaction.followup.send("⚠️ لم تضبط الإدارة قناة مراجعة الطلبات بعد.", ephemeral=True)
            return

        application_id = await db_call(
            db.create_application,
            interaction.guild.id,
            interaction.user.id,
            self.age.value,
            self.reason.value,
            self.experience.value,
            self.position.value,
        )
        embed = discord.Embed(
            title=f"📋 طلب إدارة جديد — #{application_id}",
            description=(
                f"**المتقدم:** {interaction.user.mention}\n"
                f"**العمر:** {self.age.value}\n"
                f"**الرتبة المطلوبة:** {self.position.value}\n\n"
                f"**سبب الانضمام:**\n{self.reason.value}\n\n"
                f"**الخبرة:**\n{self.experience.value}"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        mentions = get_staff_mentions(interaction.guild)
        try:
            message = await review_channel.send(content=mentions or None, embed=embed, view=ReviewActionView(application_id))
        except discord.Forbidden:
            await interaction.followup.send("❌ ما عندي صلاحية الإرسال بقناة المراجعة. أبلغ الإدارة لضبط صلاحيات البوت.", ephemeral=True)
            return
        except discord.HTTPException as error:
            await interaction.followup.send(f"❌ تعذّر إرسال طلبك لقناة المراجعة: {error}", ephemeral=True)
            return
        await db_call(db.set_application_message, application_id, message.id)
        try:
            await interaction.user.send(f"✅ تم استلام طلبك في **{interaction.guild.name}** برقم #{application_id}.")
        except discord.Forbidden:
            pass
        await interaction.followup.send("✅ تم إرسال طلبك للإدارة. سيصلك القرار في الخاص إن كانت رسائلك الخاصة مفتوحة.", ephemeral=True)


def build_apply_view(guild_id: int, emoji: str, style_name: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    button = discord.ui.Button(
        label="التقديم للإدارة",
        style=parse_style(style_name),
        emoji=parse_emoji(emoji),
        custom_id=f"apply:{guild_id}",
    )

    async def callback(interaction: discord.Interaction) -> None:
        if not interaction.guild or interaction.guild.id != guild_id:
            await interaction.response.send_message("❌ هذا الزر ليس تابعاً لهذا السيرفر.", ephemeral=True)
            return
        await interaction.response.send_modal(StaffApplyModal())

    button.callback = callback
    view.add_item(button)
    return view


@bot.command(name="اعداد_التقديم", aliases=["setup_apply"])
@staff_only()
@commands.guild_only()
async def setup_apply(ctx: commands.Context, emoji: str = "🛠️", color: str = "blurple", image_url: str = "", attachment: Optional[discord.Attachment] = None) -> None:
    """!اعداد_التقديم [إيموجي] [لون] [رابط صورة اختياري]
    يمكن أيضاً إرفاق صورة من الهاتف مباشرة (كأمر نصي أو كـ Slash) بدل كتابة رابط."""
    if attachment and not image_url:
        image_url = attachment.url
    elif ctx.message.attachments and not image_url:
        image_url = ctx.message.attachments[0].url
    db.set_guild_setting(ctx.guild.id, "apply_emoji", emoji)
    db.set_guild_setting(ctx.guild.id, "apply_style", color)
    db.set_guild_setting(ctx.guild.id, "apply_image_url", image_url)
    embed = discord.Embed(
        title="التقديم للإدارة 🛡️",
        description="هذه الغرفة مخصصة لطلبات الإدارة. اضغط الزر في الأسفل ثم املأ النموذج.",
        color=parse_color(color),
    )
    if image_url:
        embed.set_image(url=image_url)
    view = build_apply_view(ctx.guild.id, emoji, color)
    bot.add_view(view)
    await ctx.send(embed=embed, view=view)


@bot.command(name="ضبط_قناة_المراجعة")
@staff_only()
@commands.guild_only()
async def set_review_channel(ctx: commands.Context, channel: discord.TextChannel) -> None:
    db.set_guild_setting(ctx.guild.id, "review_channel_id", channel.id)
    await ctx.send(f"✅ تم تعيين قناة مراجعة التقديمات: {channel.mention}")


class ServerEmojiPickerView(discord.ui.View):
    """قائمة اختيار تعرض إيموجيات السيرفر نفسه (وليس فقط إيموجي لوحة مفاتيح الهاتف)،
    لاستخدامها في زر التذاكر أو زر التقديم للإدارة."""

    def __init__(self, target: str, emojis: list[discord.Emoji]):
        super().__init__(timeout=120)
        self.target = target
        options = [
            discord.SelectOption(label=f":{emoji.name}:"[:100], value=str(emoji.id), emoji=emoji)
            for emoji in emojis[:25]
        ]
        select = discord.ui.Select(placeholder="اختر إيموجي من إيموجيات السيرفر", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction) -> None:
        select: discord.ui.Select = self.children[0]
        emoji = discord.utils.get(interaction.guild.emojis, id=int(select.values[0]))
        emoji_str = f"<:{emoji.name}:{emoji.id}>" if not emoji.animated else f"<a:{emoji.name}:{emoji.id}>"
        if self.target == "تذاكر":
            settings = await db_call(db.get_guild_settings, interaction.guild.id)
            db.set_guild_setting(interaction.guild.id, "ticket_emoji", emoji_str)
            bot.add_view(TicketCreateView(emoji_str, settings["ticket_label"], settings["ticket_style"]))
            await interaction.response.edit_message(content=f"✅ تم ضبط إيموجي زر التذاكر: {emoji_str}\nنفّذ `!اعداد_التذاكر` لإعادة نشر الزر بالشكل الجديد.", view=None)
        else:
            settings = await db_call(db.get_guild_settings, interaction.guild.id)
            db.set_guild_setting(interaction.guild.id, "apply_emoji", emoji_str)
            bot.add_view(build_apply_view(interaction.guild.id, emoji_str, settings["apply_style"]))
            await interaction.response.edit_message(content=f"✅ تم ضبط إيموجي زر التقديم للإدارة: {emoji_str}\nنفّذ `!اعداد_التقديم` لإعادة نشر الزر بالشكل الجديد.", view=None)


@bot.command(name="اختيار_ايموجي", description="اختر إيموجي من إيموجيات السيرفر لزر التذاكر أو زر التقديم للإدارة")
@app_commands.choices(target=[app_commands.Choice(name="زر التذاكر", value="تذاكر"), app_commands.Choice(name="زر التقديم للإدارة", value="تقديم")])
@staff_only()
@commands.guild_only()
async def pick_server_emoji(ctx: commands.Context, target: str) -> None:
    if not ctx.guild.emojis:
        await ctx.send("❌ لا يوجد إيموجي مخصص مرفوع في هذا السيرفر. ارفع إيموجي من إعدادات السيرفر أولاً، أو استخدم إيموجي الهاتف مباشرة داخل أمر `!اعداد_التذاكر`/`!اعداد_التقديم`.")
        return
    view = ServerEmojiPickerView(target, list(ctx.guild.emojis))
    await ctx.send("اختر الإيموجي من القائمة:", view=view, ephemeral=True)


@bot.command(name="ضبط_قناة_اللوق", description="قناة تُسجَّل فيها كل إجراءات الإدارة (طرد/باند/تايم أوت/تذاكر)")
@staff_only()
@commands.guild_only()
async def set_mod_log_channel(ctx: commands.Context, channel: discord.TextChannel) -> None:
    db.set_guild_setting(ctx.guild.id, "mod_log_channel_id", channel.id)
    await ctx.send(f"✅ سيتم تسجيل كل إجراءات الإدارة (طرد، باند، تايم أوت، فتح/إغلاق تذاكر) في {channel.mention}.")


@bot.command(name="ايقاف_قناة_اللوق")
@staff_only()
@commands.guild_only()
async def disable_mod_log_channel(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "mod_log_channel_id", None)
    await ctx.send("✅ تم إيقاف تسجيل إجراءات الإدارة.")


# ============================================================
# نظام التذاكر
# ============================================================

class TicketCreateView(discord.ui.View):
    def __init__(self, emoji: str | None = None, label: str | None = None, style: str | None = None):
        super().__init__(timeout=None)
        # يسمح بإيموجي مخصص من السيرفر (وليس فقط إيموجي الهاتف)، لأن parse_emoji
        # تفهم صيغة <:name:id> وتحوّلها إلى PartialEmoji صالح لديسكورد.
        if emoji:
            self.create_ticket.emoji = parse_emoji(emoji)
        if label:
            self.create_ticket.label = label[:80]
        if style:
            self.create_ticket.style = parse_style(style)

    @discord.ui.button(label="فتح تذكرة دعم", style=discord.ButtonStyle.success, emoji="🎫", custom_id="ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ افتح التذكرة من داخل السيرفر.", ephemeral=True)
            return
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)
        lock = _ticket_creation_locks[(guild.id, interaction.user.id)]
        if lock.locked():
            await interaction.followup.send("⏳ طلب فتح تذكرتك قيد المعالجة بالفعل، ثانية وحدة.", ephemeral=True)
            return
        async with lock:
            old_ticket = discord.utils.get(guild.text_channels, topic=f"ticket-owner:{interaction.user.id}")
            if old_ticket:
                await interaction.followup.send(f"⚠️ لديك تذكرة مفتوحة بالفعل: {old_ticket.mention}", ephemeral=True)
                return

            overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            }
            for role in get_staff_roles(guild):
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

            settings = await db_call(db.get_guild_settings, guild.id)
            category = safe_channel(guild, settings["ticket_category_id"])
            if not isinstance(category, discord.CategoryChannel):
                category = None
            try:
                ticket_channel = await guild.create_text_channel(
                    name=f"ticket-{interaction.user.name}"[:90],
                    category=category,
                    topic=f"ticket-owner:{interaction.user.id}",
                    overwrites=overwrites,
                    reason=f"تذكرة دعم للعضو {interaction.user}",
                )
            except discord.Forbidden:
                await interaction.followup.send("❌ ما عندي صلاحية إنشاء رومات بهذا السيرفر. تأكد أن رتبة البوت فيها صلاحية إدارة القنوات.", ephemeral=True)
                return
            except discord.HTTPException as error:
                await interaction.followup.send(f"❌ تعذّر إنشاء روم التذكرة (قد يكون السيرفر وصل الحد الأقصى للقنوات). التفاصيل: {error}", ephemeral=True)
                return
            embed = discord.Embed(
                title="🎫 تذكرة الدعم الفني",
                description="اكتب مشكلتك بالتفصيل. لا تشارك كلمات المرور أو التوكنات أو أي بيانات خاصة.",
                color=discord.Color.blue(),
            )
            await ticket_channel.send(
                content=f"{interaction.user.mention} {get_staff_mentions(guild)}".strip(),
                embed=embed,
                view=TicketCloseView(),
            )
        await interaction.followup.send(f"✅ تم فتح تذكرتك: {ticket_channel.mention}", ephemeral=True)
        await send_mod_log(guild, discord.Embed(title="🎫 فتح تذكرة", description=f"**العضو:** {interaction.user.mention} (`{interaction.user.id}`)\n**الروم:** {ticket_channel.mention}", color=discord.Color.blue()))


class TicketCloseView(discord.ui.View):
    def __init__(self, close_message: str = "🔒 سيتم إغلاق وحذف التذكرة خلال 5 ثوانٍ.", close_mentions: str = "", image_url: Any = None, thumbnail_url: Any = None):
        super().__init__(timeout=None)
        self.close_message = close_message[:2500]
        self.close_mentions = close_mentions
        self.close_image_url = str(image_url or "")
        self.close_thumbnail_url = str(thumbnail_url or "")

    @discord.ui.button(label="إغلاق التذكرة", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("❌ لا أستطيع إغلاق هذه القناة.", ephemeral=True)
            return
        owner_id = None
        if interaction.channel.topic and interaction.channel.topic.startswith("ticket-owner:"):
            try:
                owner_id = int(interaction.channel.topic.split(":", 1)[1])
            except ValueError:
                pass
        can_close = is_staff_member(interaction.user) or interaction.user.id == owner_id
        if not can_close:
            await interaction.response.send_message("❌ فقط صاحب التذكرة أو الإدارة يستطيع الإغلاق.", ephemeral=True)
            return
        close_embed = discord.Embed(description=self.close_message, color=discord.Color.red())
        if self.close_image_url.startswith(("https://", "http://")): close_embed.set_image(url=self.close_image_url)
        if self.close_thumbnail_url.startswith(("https://", "http://")): close_embed.set_thumbnail(url=self.close_thumbnail_url)
        await interaction.response.send_message(content=self.close_mentions or None, embed=close_embed, ephemeral=True, allowed_mentions=ALLOWED_MENTIONS)
        channel_name = interaction.channel.name
        await send_mod_log(interaction.guild, discord.Embed(title="🔒 إغلاق تذكرة", description=f"**بواسطة:** {interaction.user.mention}\n**الروم:** #{channel_name}", color=discord.Color.red()))
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"أغلقها {interaction.user}")


def decode_workflow_payload(encoded: str) -> dict[str, Any]:
    packed = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    try:
        # The dashboard uses Node deflateRawSync, which produces a raw DEFLATE stream.
        raw = zlib.decompress(packed, -zlib.MAX_WBITS)
    except zlib.error:
        # Keep compatibility with older dashboard payloads using the zlib wrapper.
        raw = zlib.decompress(packed)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("إعدادات التدفق غير صالحة")
    return value


def discord_asset_url(raw_url: object) -> str:
    value = str(raw_url or "").strip()
    if value.startswith(("https://", "http://")):
        return value
    if value.startswith("/manus-storage/"):
        origin = os.getenv("PUBLIC_APP_URL", "https://spectredash-anmny4qn.manus.space").rstrip("/")
        return f"{origin}{value}"
    return ""


def workflow_embed(config: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title=str(config.get("title", "Spectre"))[:256] or None,
        description=str(config.get("description", ""))[:4096],
        color=parse_color(str(config.get("color", "#5865F2"))),
    )
    author = config.get("author") or {}
    if isinstance(author, dict) and (author.get("name") or author.get("iconUrl")):
        author_kwargs = {"name": str(author.get("name") or "Spectre")[:256]}
        icon = discord_asset_url(author.get("iconUrl"))
        link = discord_asset_url(author.get("url"))
        if icon:
            author_kwargs["icon_url"] = icon
        if link:
            author_kwargs["url"] = link
        embed.set_author(**author_kwargs)
    for field in (config.get("fields") or [])[:25]:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "حقل")[:256]
        value = str(field.get("value") or "—")[:1024]
        embed.add_field(name=name, value=value, inline=bool(field.get("inline", False)))
    footer = config.get("footer") or {}
    if isinstance(footer, dict) and (footer.get("text") or footer.get("iconUrl")):
        footer_kwargs = {"text": str(footer.get("text") or "")[:2048]}
        icon = discord_asset_url(footer.get("iconUrl"))
        if icon:
            footer_kwargs["icon_url"] = icon
        embed.set_footer(**footer_kwargs)
    image_url = discord_asset_url(config.get("imageUrl"))
    thumbnail_url = discord_asset_url(config.get("thumbnailUrl"))
    if image_url: embed.set_image(url=image_url)
    if thumbnail_url: embed.set_thumbnail(url=thumbnail_url)
    if config.get("timestamp"):
        embed.timestamp = datetime.now(timezone.utc)
    return embed


async def blocked_role_ids(guild: discord.Guild, key: str) -> set[int]:
    settings = await db_call(db.get_guild_settings, guild.id)
    raw = settings.get(key, "[]")
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        values = []
    return {int(value) for value in values if str(value).isdigit()}


async def member_is_blocked(member: discord.Member, key: str) -> bool:
    blocked = await blocked_role_ids(member.guild, key)
    return bool({role.id for role in member.roles} & blocked)


def configured_role_mentions(guild: discord.Guild, config: dict[str, Any], key: str = "mentionRoleIds") -> str:
    raw_ids = config.get(key) or ([] if key != "mentionRoleIds" else ([config.get("mentionRoleId")] if config.get("mentionRoleId") else []))
    mentions: list[str] = []
    for raw_id in raw_ids if isinstance(raw_ids, list) else []:
        try:
            role = guild.get_role(int(str(raw_id)))
        except (TypeError, ValueError):
            role = None
        if role and not role.managed:
            mentions.append(role.mention)
    return " ".join(dict.fromkeys(mentions))


async def create_custom_ticket(interaction: discord.Interaction, config: dict[str, Any]) -> None:
    guild = interaction.guild
    if not guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ افتح التكت من داخل السيرفر.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    if await member_is_blocked(interaction.user, "blocked_ticket_role_ids"):
        await interaction.followup.send("⛔ لا يمكنك فتح تذكرة بهذه الرتبة.", ephemeral=True); return
    existing = discord.utils.find(lambda channel: isinstance(channel, discord.TextChannel) and channel.topic == f"workflow-ticket-owner:{interaction.user.id}", guild.text_channels)
    if existing:
        await interaction.followup.send(f"⚠️ لديك تكت مفتوح بالفعل: {existing.mention}", ephemeral=True); return
    lock = _ticket_creation_locks[(guild.id, interaction.user.id)]
    if lock.locked():
        await interaction.followup.send("⏳ طلب فتح تذكرتك قيد المعالجة بالفعل.", ephemeral=True); return
    async with lock:
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)}
        for role in get_staff_roles(guild): overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        category = safe_channel(guild, int(config.get("ticketCategoryId") or 0))
        category = category if isinstance(category, discord.CategoryChannel) else None
        prefix = str(config.get("ticketNamePrefix") or "ticket")[:20]
        try:
            channel = await guild.create_text_channel(f"{prefix}-{interaction.user.name}"[:90], category=category, topic=f"workflow-ticket-owner:{interaction.user.id}", overwrites=overwrites, reason="تذكرة من تدفق Spectre المخصص")
        except discord.Forbidden:
            await interaction.followup.send("❌ ما عندي صلاحية إنشاء رومات بهذا السيرفر.", ephemeral=True); return
        except discord.HTTPException as error:
            await interaction.followup.send(f"❌ تعذّر إنشاء روم التذكرة: {error}", ephemeral=True); return
    mention = " ".join(part for part in [interaction.user.mention, configured_role_mentions(guild, config, "ticketSupportRoleIds")] if part)
    welcome_config = {
        "title": str(config.get("ticketWelcomeTitle") or "تذكرة الدعم")[:256],
        "description": str(config.get("ticketWelcomeMessage") or config.get("openingMessage") or config.get("description") or "اكتب تفاصيل مشكلتك هنا.")[:2500],
        "color": config.get("color", "#5865F2"),
        "imageUrl": config.get("ticketWelcomeImageUrl") or config.get("imageUrl", ""),
        "thumbnailUrl": config.get("ticketWelcomeThumbnailUrl") or config.get("thumbnailUrl", ""),
    }
    await channel.send(content=mention or None, embed=workflow_embed(welcome_config), view=TicketCloseView(str(config.get("ticketCloseMessage") or "🔒 سيتم إغلاق وحذف التذكرة خلال 5 ثوانٍ."), "", config.get("ticketCloseImageUrl"), config.get("ticketCloseThumbnailUrl")))
    await interaction.followup.send(f"✅ تم فتح التذكرة: {channel.mention}", ephemeral=True)


class CustomWorkflowModal(discord.ui.Modal):
    def __init__(self, workflow_type: str, config: dict[str, Any]):
        super().__init__(title=str(config.get("title", "نموذج Spectre"))[:45])
        self.workflow_type = workflow_type
        self.config = config
        for field in config.get("fields", [])[:5]:
            self.add_item(discord.ui.TextInput(label=str(field.get("label", "سؤال"))[:45], placeholder=str(field.get("placeholder", ""))[:100], style=discord.TextStyle.paragraph if field.get("style") == "paragraph" else discord.TextStyle.short, required=bool(field.get("required", True)), max_length=min(int(field.get("maxLength", 200)), 2500)))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ هذا النموذج يعمل داخل السيرفر فقط.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        if isinstance(interaction.user, discord.Member) and await member_is_blocked(interaction.user, "blocked_application_role_ids"):
            await interaction.followup.send("⛔ لا يمكنك إرسال تقديم بهذه الرتبة.", ephemeral=True); return
        channel_id = str(self.config.get("logChannelId") or self.config.get("targetChannelId") or "")
        target = safe_channel(interaction.guild, int(channel_id) if channel_id.isdigit() else 0)
        if not isinstance(target, discord.TextChannel):
            await interaction.followup.send("⚠️ لم يتم تحديد قناة استقبال الطلبات.", ephemeral=True); return
        answers = "\n\n".join(f"**{item.label}**\n{item.value}" for item in self.children if isinstance(item, discord.ui.TextInput))
        content = configured_role_mentions(interaction.guild, self.config, "applicationReviewRoleIds") or None
        embed = workflow_embed({**self.config, "description": f"**المتقدم:** {interaction.user.mention}\n\n{answers}"})
        await target.send(content=content or None, embed=embed, view=ReviewActionView(0))
        await interaction.followup.send("✅ تم إرسال التقديم للإدارة.", ephemeral=True)


def build_custom_workflow_view(guild_id: int, workflow_type: str, config: dict[str, Any]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for item in config.get("buttons", [])[:25]:
        button = discord.ui.Button(label=str(item.get("label", "زر"))[:80], style=parse_style(str(item.get("style", "primary"))), emoji=parse_emoji(str(item.get("emoji", ""))), custom_id=f"workflow:{workflow_type}:{guild_id}:{item.get('id') or 'button'}")
        action = str(item.get("action", "send_message"))
        async def callback(interaction: discord.Interaction, selected_action=action) -> None:
            if not interaction.guild or interaction.guild.id != guild_id: await interaction.response.send_message("❌ هذا الزر ليس تابعاً لهذا السيرفر.", ephemeral=True); return
            if selected_action == "open_modal":
                if isinstance(interaction.user, discord.Member) and await member_is_blocked(interaction.user, "blocked_application_role_ids"):
                    await interaction.response.send_message("⛔ لا يمكنك إرسال تقديم بهذه الرتبة.", ephemeral=True); return
                await interaction.response.send_modal(CustomWorkflowModal(workflow_type, config))
            elif selected_action == "create_ticket": await create_custom_ticket(interaction, config)
            else: await interaction.response.send_message(str(config.get("openingMessage") or "تم استلام طلبك."), ephemeral=True)
        button.callback = callback
        view.add_item(button)
    return view


class PanelMessageModal(discord.ui.Modal):
    def __init__(self, config: dict[str, Any]):
        super().__init__(title=str(config.get("title", "رسالة Spectre"))[:45])
        self.message_input = discord.ui.TextInput(label="رسالتك", style=discord.TextStyle.paragraph, required=True, max_length=2000)
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"✅ تم استلام رسالتك: {self.message_input.value[:1900]}", ephemeral=True)


def build_panel_view(guild_id: int, config: dict[str, Any]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for item in config.get("buttons", [])[:25]:
        action = str(item.get("action", "send_message"))
        style_name = str(item.get("style", "primary"))
        if action == "open_url":
            button = discord.ui.Button(
                label=str(item.get("label", "فتح الرابط"))[:80],
                style=discord.ButtonStyle.link,
                emoji=parse_emoji(str(item.get("emoji", ""))),
                url=str(item.get("url") or item.get("responseUrl") or "https://discord.com")[:512],
            )
        else:
            button = discord.ui.Button(
                label=str(item.get("label", "زر"))[:80],
                style=parse_style(style_name),
                emoji=parse_emoji(str(item.get("emoji", ""))),
                custom_id=f"panel:{guild_id}:{item.get('id') or 'button'}",
            )

        async def callback(interaction: discord.Interaction, selected_action=action, selected_item=item) -> None:
            if not interaction.guild or interaction.guild.id != guild_id:
                await interaction.response.send_message("❌ هذا الزر ليس تابعاً لهذا السيرفر.", ephemeral=True); return
            if selected_action == "open_modal":
                if isinstance(interaction.user, discord.Member) and await member_is_blocked(interaction.user, "blocked_application_role_ids"):
                    await interaction.response.send_message("⛔ لا يمكنك إرسال تقديم بهذه الرتبة.", ephemeral=True); return
                await interaction.response.send_modal(PanelMessageModal(config))
            elif selected_action == "create_ticket":
                await create_custom_ticket(interaction, config)
            else:
                response = {
                    "title": str(selected_item.get("responseTitle") or "")[:256],
                    "description": str(selected_item.get("responseMessage") or selected_item.get("message") or "تم استلام طلبك.")[:4096],
                    "color": selected_item.get("responseColor") or config.get("color", "#5865F2"),
                    "imageUrl": selected_item.get("responseImageUrl") or "",
                    "thumbnailUrl": selected_item.get("responseThumbnailUrl") or "",
                    "fields": selected_item.get("responseFields") or [],
                    "footer": selected_item.get("responseFooter") or {},
                    "timestamp": bool(selected_item.get("responseTimestamp")),
                }
                content = str(selected_item.get("responseContent") or "")[:2000] or None
                await interaction.response.send_message(
                    content=content,
                    embed=workflow_embed(response),
                    ephemeral=True,
                    allowed_mentions=ALLOWED_MENTIONS,
                )
        if action != "open_url":
            button.callback = callback
        view.add_item(button)
    return view


@bot.command(name="تحديث_لوحة")
@commands.guild_only()
async def update_panel(ctx: commands.Context, encoded: str) -> None:
    if not isinstance(ctx.author, discord.Member) or not is_staff_member(ctx.author):
        await ctx.send("❌ تحتاج صلاحية إدارة السيرفر."); return
    try:
        config = decode_workflow_payload(encoded)
        for key, setting in (("blockedApplicationRoleIds", "blocked_application_role_ids"), ("blockedTicketRoleIds", "blocked_ticket_role_ids")):
            values = config.get(key) if isinstance(config.get(key), list) else []
            db.set_guild_setting(ctx.guild.id, setting, json.dumps([str(value) for value in values[:10]]))
        message = await ctx.send(content=str(config.get("content") or "")[:2000] or None, embed=workflow_embed(config), view=build_panel_view(ctx.guild.id, config), allowed_mentions=ALLOWED_MENTIONS)
        # نحفظ إعداد اللوحة حتى يستطيع البوت إعادة تسجيل أزرارها تلقائياً بعد أي
        # إعادة تشغيل (راجع on_ready)، وإلا تتوقف اللوحة عن الرد بعد فترة.
        db.save_panel(ctx.guild.id, message.channel.id, message.id, json.dumps(config, ensure_ascii=False))
        print(f"[DashboardControl] Panel published guild={ctx.guild.id} message={message.id} buttons={len(config.get('buttons', []))}")
    except Exception as error:
        await ctx.send(f"❌ تعذر نشر اللوحة: {str(error)[:180]}")


@bot.command(name="تحديث_تدفق")
@commands.guild_only()
async def update_workflow(ctx: commands.Context, workflow_type: str, encoded: str) -> None:
    if not isinstance(ctx.author, discord.Member) or not is_staff_member(ctx.author):
        await ctx.send("❌ تحتاج صلاحية إدارة السيرفر."); return
    try:
        config = decode_workflow_payload(encoded)
        db.save_workflow(ctx.guild.id, workflow_type, json.dumps(config, ensure_ascii=False))
        view = build_custom_workflow_view(ctx.guild.id, workflow_type, config)
        bot.add_view(view)
        await ctx.send(embed=workflow_embed(config), view=view, allowed_mentions=ALLOWED_MENTIONS)
    except Exception as error:
        await ctx.send(f"❌ تعذر تطبيق التدفق: {str(error)[:180]}")


@bot.command(name="اعداد_التذاكر", aliases=["setup_ticket"])
@staff_only()
@commands.guild_only()
async def setup_ticket(ctx: commands.Context, emoji: str = "", label: str = "", style: str = "") -> None:
    """!اعداد_التذاكر [إيموجي] [نص الزر] [لون الزر]
    مثال: !اعداد_التذاكر 🎫 "فتح تذكرة" success
    يمكن اختيار إيموجي من إيموجيات السيرفر بأمر `اختيار_ايموجي_التذاكر` بدلاً من كتابته يدوياً."""
    if emoji:
        db.set_guild_setting(ctx.guild.id, "ticket_emoji", emoji)
    if label:
        db.set_guild_setting(ctx.guild.id, "ticket_label", label)
    if style:
        db.set_guild_setting(ctx.guild.id, "ticket_style", style)
    settings = db.get_guild_settings(ctx.guild.id)
    embed = discord.Embed(
        title="مركز المساعدة والدعم",
        description="اضغط الزر في الأسفل لفتح تذكرة خاصة بك.",
        color=discord.Color.blurple(),
    )
    view = TicketCreateView(settings["ticket_emoji"], settings["ticket_label"], settings["ticket_style"])
    bot.add_view(view)
    await ctx.send(embed=embed, view=view)


@bot.command(name="ضبط_قسم_التذاكر")
@staff_only()
@commands.guild_only()
async def set_ticket_category(ctx: commands.Context, category: discord.CategoryChannel) -> None:
    db.set_guild_setting(ctx.guild.id, "ticket_category_id", category.id)
    await ctx.send(f"✅ ستُنشأ التذاكر الجديدة داخل القسم {category.name}.")


# ============================================================
# الترحيب واللفلات والحماية من السبام
# ============================================================

WELCOME_SIZE = (1206, 700)


def _welcome_rgb(value: Any, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            pass
    return fallback


def _welcome_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


async def _welcome_download(url: str) -> Image.Image | None:
    if not url.startswith(("http://", "https://")):
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.read()
        if len(data) > 8 * 1024 * 1024:
            return None
        return Image.open(BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def welcome_text(template: object, member: discord.Member) -> str:
    replacements = {
        "{user}": member.mention,
        "{username}": member.name,
        "{display_name}": member.display_name,
        "{mention}": member.mention,
        "{server}": member.guild.name,
        "{member_count}": str(member.guild.member_count or 0),
        "{user_id}": str(member.id),
    }
    value = str(template or "")
    for token, replacement in replacements.items():
        value = value.replace(token, replacement)
    return value


async def render_welcome_image(member: discord.Member, config: dict[str, Any]) -> BytesIO:
    width, height = WELCOME_SIZE
    background = await _welcome_download(str(config.get("background_url", "")))
    if background is None:
        background = Image.new("RGBA", WELCOME_SIZE, _welcome_rgb(config.get("background_color", "#17233A"), (23, 35, 58)) + (255,))
    canvas = ImageOps.fit(background, WELCOME_SIZE, method=Image.Resampling.LANCZOS).convert("RGBA")
    overlay = Image.new("RGBA", WELCOME_SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle((0, 0, width, height), fill=(0, 0, 0, max(0, min(100, int(config.get("overlay_opacity", 18)))) * 255 // 100))
    canvas.alpha_composite(overlay)
    avatar_size = max(96, min(int(config.get("avatar_size", 220)), 520))
    center_x = max(0, min(int(config.get("avatar_x", width // 2)), width))
    center_y = max(0, min(int(config.get("avatar_y", 245)), height))
    avatar = ImageOps.fit(Image.open(BytesIO(await member.display_avatar.read())).convert("RGBA"), (avatar_size, avatar_size), method=Image.Resampling.LANCZOS)
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, avatar_size - 1, avatar_size - 1), fill=255)
    avatar.putalpha(mask)
    left, top = center_x - avatar_size // 2, center_y - avatar_size // 2
    draw = ImageDraw.Draw(canvas)
    border = max(0, min(int(config.get("avatar_border_width", 8)), 30))
    if border:
        draw.ellipse((left - border, top - border, left + avatar_size + border, top + avatar_size + border), fill=_welcome_rgb(config.get("avatar_border_color", "#20D6A7"), (32, 214, 167)) + (255,))
    canvas.alpha_composite(avatar, (left, top))
    title = welcome_text(config.get("title", "عضو جديد انضم إلينا!"), member)
    description = welcome_text(config.get("description", "مرحباً بك {display_name} في سيرفرنا!"), member)
    text_color = _welcome_rgb(config.get("text_color", "#FFFFFF"), (255, 255, 255)) + (255,)
    title_font, body_font = _welcome_font(int(config.get("title_size", 42)), True), _welcome_font(int(config.get("description_size", 26)))
    draw = ImageDraw.Draw(canvas)
    text_x, text_y = int(config.get("text_x", width // 2)), int(config.get("text_y", 500))
    title_width = draw.textbbox((0, 0), title, font=title_font)[2]
    body_width = draw.textbbox((0, 0), description, font=body_font)[2]
    draw.text((text_x - title_width / 2, text_y), title, font=title_font, fill=text_color, stroke_width=1, stroke_fill=(0, 0, 0, 190))
    draw.text((text_x - body_width / 2, text_y + 58), description, font=body_font, fill=text_color, stroke_width=1, stroke_fill=(0, 0, 0, 170))
    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


message_history: dict[tuple[int, int], list[datetime]] = defaultdict(list)
xp_cooldown: dict[tuple[int, int], datetime] = {}

# يمنع تفعيل قفل الغارة (lockdown) عدة مرات متزامنة لنفس السيرفر لو انضم عدة
# أعضاء بنفس اللحظة تقريباً بعد تجاوز الحد أصلاً.
_raid_lockdown_active: set[int] = set()


async def apply_raid_action(member: discord.Member, settings: dict[str, Any], reason: str) -> None:
    """ينفّذ إجراء الحماية من الغارات على عضو معيّن انضم أثناء الغارة المكتشفة،
    حسب antiraid_action: kick_new (طرد)، ban_new (حظر)، أو lockdown_only (لا
    شيء للعضو نفسه، فقط قفل السيرفر مؤقتاً)."""
    action = settings.get("antiraid_action", "kick_new")
    if action == "lockdown_only":
        return
    try:
        if action == "ban_new":
            await member.ban(reason=reason, delete_message_seconds=0)
        else:
            await member.kick(reason=reason)
    except discord.Forbidden:
        pass


async def trigger_raid_lockdown(guild: discord.Guild, settings: dict[str, Any], join_count: int, window: int) -> None:
    """يرفع مستوى التحقق (Verification Level) للسيرفر إلى الحد الأقصى مؤقتاً
    (يمنع الحسابات الجديدة جداً من الكتابة أو حتى الانضمام حسب قواعد ديسكورد
    نفسها)، ثم يعيده تلقائياً للوضع الطبيعي بعد المدة المضبوطة. هذا يشتري وقتاً
    للإدارة الحقيقية للتعامل مع الغارة يدوياً إن احتاج الأمر."""
    if guild.id in _raid_lockdown_active:
        return
    _raid_lockdown_active.add(guild.id)
    lockdown_minutes = int(settings.get("antiraid_lockdown_minutes", 10))
    original_level = guild.verification_level
    try:
        await guild.edit(verification_level=discord.VerificationLevel.highest, reason="نظام الحماية: غارة أعضاء مكتشفة")
    except discord.Forbidden:
        pass
    await send_mod_log(guild, discord.Embed(
        title="🚨 تم اكتشاف غارة أعضاء (Raid)",
        description=f"انضم **{join_count}** عضو خلال **{window}** ثانية.\nتم رفع مستوى التحقق للحد الأقصى لمدة {lockdown_minutes} دقيقة تلقائياً.\nراجع سجل الأعضاء المنضمين حديثاً يدوياً للاطمئنان.",
        color=discord.Color.red(),
    ))

    async def _restore_after_delay() -> None:
        await asyncio.sleep(lockdown_minutes * 60)
        try:
            await guild.edit(verification_level=original_level, reason="نظام الحماية: انتهاء فترة القفل بعد الغارة")
        except discord.Forbidden:
            pass
        _raid_lockdown_active.discard(guild.id)
        await send_mod_log(guild, discord.Embed(title="✅ انتهى قفل الغارة", description="تم إرجاع مستوى التحقق للوضع الطبيعي.", color=discord.Color.green()))

    asyncio.create_task(_restore_after_delay())


@bot.event
async def on_member_join(member: discord.Member) -> None:
    settings = await db_call(db.get_guild_settings, member.guild.id)

    # ---------------- الحماية من التخريب: طرد البوتات المشبوهة فوراً ----------------
    if member.bot and antinuke.is_enabled(settings):
        allowed_bots = antinuke.load_json_list(settings, "antinuke_bot_whitelist_json")
        allowed_ids = {int(value) for value in allowed_bots if str(value).isdigit()}
        if member.id not in allowed_ids:
            try:
                await member.kick(reason="بوت غير موثوق (غير موجود بقائمة السماح) — نظام الحماية")
            except discord.Forbidden:
                pass
            else:
                await send_mod_log(
                    member.guild,
                    discord.Embed(
                        title="🛡️ طرد بوت مشبوه",
                        description=f"**البوت:** {member.mention} (`{member.id}`)\nانضم للسيرفر وليس بقائمة البوتات الموثوقة، فتم طرده تلقائياً.\nلإضافته للقائمة الموثوقة استخدم أمر `!اضافة_بوت_موثوق`.",
                        color=discord.Color.red(),
                    ),
                )
            return

    # ---------------- الحماية من الغارات الجماعية (Anti-Raid) ----------------
    # نسجّل توقيت انضمام *كل* عضو (بشري أو بوت) بنافذة زمنية قصيرة عبر نفس آلية
    # antinuke.record_action، ونقارن العدد بحد "الغارة" المضبوط. لو تجاوزنا
    # الحد، نفعّل وضع الطوارئ: نرفع مستوى التحقق (Verification Level) للحد
    # الأقصى مؤقتاً (يمنع أي عضو جديد من الكتابة/المشاركة لفترة قصيرة تلقائياً
    # حسب قواعد ديسكورد نفسها)، ونطرد/نحظر كل من انضم ضمن نافذة الغارة نفسها
    # حسب الإجراء المختار.
    if bool(settings.get("antiraid_enabled")):
        raid_window = int(settings.get("antiraid_window_seconds", 20))
        join_count = antinuke.record_action(member.guild.id, 0, "guild_join_raid_probe", raid_window)
        if join_count > int(settings.get("antiraid_max_joins", 10)):
            antinuke.reset_action(member.guild.id, 0, "guild_join_raid_probe")
            await trigger_raid_lockdown(member.guild, settings, join_count, raid_window)
            # العضو الحالي جزء من الغارة المكتشفة توّاً، فنطبّق عليه الإجراء أيضاً.
            await apply_raid_action(member, settings, "جزء من نمط انضمام جماعي مشبوه (غارة)")
            return

    # ---------------- الحماية من الحسابات الحديثة (Anti-Alt) ----------------
    if not member.bot and bool(settings.get("antialt_enabled")):
        min_age_days = int(settings.get("antialt_min_age_days", 7))
        account_age_days = (datetime.now(timezone.utc) - member.created_at).days
        if account_age_days < min_age_days:
            action = settings.get("antialt_action", "kick")
            reason = f"حساب حديث الإنشاء ({account_age_days} يوم، الحد الأدنى {min_age_days} يوم) — نظام الحماية"
            try:
                if action == "ban":
                    await member.ban(reason=reason, delete_message_seconds=0)
                else:
                    await member.kick(reason=reason)
            except discord.Forbidden:
                pass
            else:
                await send_mod_log(member.guild, discord.Embed(
                    title="🛡️ حساب حديث مرفوض",
                    description=f"**العضو:** {member.mention} (`{member.id}`)\n**عمر الحساب:** {account_age_days} يوم\n**الإجراء:** {'حظر' if action == 'ban' else 'طرد'}",
                    color=discord.Color.orange(),
                ))
            return

    # ---------------- الرتب اللاصقة (Sticky Roles) ----------------
    # لو العضو غادر سابقاً وكان محتفظاً برتب، نعيدها له الآن قبل أي شيء آخر
    # (بما فيها رتب العقوبة مثل "مكتوم" إن كانت من ضمن رتبه وقت المغادرة —
    # وهذا هو بالضبط الهدف الأمني: منع الهروب من العقوبة بالخروج والعودة).
    if bool(settings.get("sticky_roles_enabled")):
        saved_role_ids = await db_call(db.get_sticky_roles, member.guild.id, member.id)
        if saved_role_ids:
            roles_to_restore = [member.guild.get_role(role_id) for role_id in saved_role_ids]
            roles_to_restore = [role for role in roles_to_restore if role is not None and role < member.guild.me.top_role]
            if roles_to_restore:
                try:
                    await member.add_roles(*roles_to_restore, reason="استعادة الرتب اللاصقة بعد العودة للسيرفر")
                except discord.Forbidden:
                    pass
            await db_call(db.clear_sticky_roles, member.guild.id, member.id)

    if not settings["welcome_enabled"]:
        return
    config = await db_call(db.get_welcome_config, member.guild.id)
    if config and not bool(config.get("enabled", True)):
        return
    channel_id = int(config.get("channel_id") or settings.get("welcome_channel_id") or 0)
    channel = safe_channel(member.guild, channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        image = await render_welcome_image(member, config)
        file = discord.File(image, filename="spectre-welcome.png")
        content = welcome_text(config.get("content", ""), member) or (member.mention if config.get("mention", True) else None)
        embed = discord.Embed(description=content, color=discord.Color.from_rgb(*_welcome_rgb(config.get("embed_color", "#20D6A7"), (32, 214, 167))))
        embed.set_image(url="attachment://spectre-welcome.png")
        await channel.send(content=content, embed=embed, file=file, allowed_mentions=ALLOWED_MENTIONS)
    except Exception:
        traceback.print_exc()
        try:
            embed = discord.Embed(title="✨ عضو جديد انضم إلينا!", description=f"مرحباً بك {member.mention} في سيرفرنا! نتمنى لك وقتاً ممتعاً.", color=discord.Color.green())
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"العضو رقم #{member.guild.member_count}")
            await channel.send(embed=embed, allowed_mentions=ALLOWED_MENTIONS)
        except discord.Forbidden:
            pass


# ==================== أحداث نظام الحماية من التخريب (Anti-Nuke) ====================

async def _antinuke_settings(guild_id: int) -> dict[str, Any]:
    return await db_call(db.get_guild_settings, guild_id)


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel) -> None:
    antinuke._last_known_channel_names[channel.id] = channel.name
    settings = await _antinuke_settings(channel.guild.id)
    if not antinuke.is_enabled(settings):
        return

    banned_word = antinuke.contains_banned_word(channel.name, settings)
    actor = await antinuke.find_actor(channel.guild, discord.AuditLogAction.channel_create, target_id=channel.id)

    if banned_word:
        try:
            await channel.delete(reason=f"اسم يحتوي كلمة ممنوعة: {banned_word} — نظام الحماية")
        except discord.Forbidden:
            pass
        if actor and isinstance(actor, discord.Member):
            await antinuke.punish(channel.guild, actor, settings, f"إنشاء روم باسم يحتوي كلمة ممنوعة ({banned_word})", send_mod_log)
        return

    if actor and isinstance(actor, discord.Member):
        window = int(settings.get("antinuke_window_seconds", 10))
        count = antinuke.record_action(channel.guild.id, actor.id, "channel_create", window)
        if count > int(settings.get("antinuke_max_channel_create", 5)):
            antinuke.reset_action(channel.guild.id, actor.id, "channel_create")
            await antinuke.punish(channel.guild, actor, settings, f"إنشاء {count} رومات خلال {window} ثوانٍ (نمط تخريب مشبوه)", send_mod_log)


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel) -> None:
    antinuke._last_known_channel_names.pop(channel.id, None)
    settings = await _antinuke_settings(channel.guild.id)
    if not antinuke.is_enabled(settings):
        return
    actor = await antinuke.find_actor(channel.guild, discord.AuditLogAction.channel_delete, target_id=channel.id)
    if actor and isinstance(actor, discord.Member):
        window = int(settings.get("antinuke_window_seconds", 10))
        count = antinuke.record_action(channel.guild.id, actor.id, "channel_delete", window)
        if count > int(settings.get("antinuke_max_channel_delete", 3)):
            antinuke.reset_action(channel.guild.id, actor.id, "channel_delete")
            await antinuke.punish(channel.guild, actor, settings, f"حذف {count} رومات خلال {window} ثوانٍ (نمط تخريب مشبوه)", send_mod_log)


@bot.event
async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
    old_name = antinuke._last_known_channel_names.get(after.id, before.name)
    if after.name == old_name:
        antinuke._last_known_channel_names[after.id] = after.name
        return
    settings = await _antinuke_settings(after.guild.id)
    if not antinuke.is_enabled(settings):
        antinuke._last_known_channel_names[after.id] = after.name
        return

    banned_word = antinuke.contains_banned_word(after.name, settings)
    if banned_word:
        actor = await antinuke.find_actor(after.guild, discord.AuditLogAction.channel_update, target_id=after.id)
        try:
            await after.edit(name=old_name, reason="إرجاع اسم القناة بعد تغيير مرفوض — نظام الحماية")
        except discord.Forbidden:
            pass
        else:
            antinuke._last_known_channel_names[after.id] = old_name
        if actor and isinstance(actor, discord.Member):
            await antinuke.punish(after.guild, actor, settings, f"تغيير اسم روم لاسم يحتوي كلمة ممنوعة ({banned_word})", send_mod_log)
        return
    antinuke._last_known_channel_names[after.id] = after.name


@bot.event
async def on_guild_role_create(role: discord.Role) -> None:
    antinuke._last_known_role_permissions[role.id] = role.permissions.value
    settings = await _antinuke_settings(role.guild.id)
    if not antinuke.is_enabled(settings):
        return
    dangerous = antinuke.dangerous_permissions_present(role.permissions, settings)
    if not dangerous:
        return
    actor = await antinuke.find_actor(role.guild, discord.AuditLogAction.role_create, target_id=role.id)
    try:
        await role.delete(reason=f"صلاحيات خطيرة عند الإنشاء: {', '.join(dangerous)} — نظام الحماية")
    except discord.Forbidden:
        pass
    antinuke._last_known_role_permissions.pop(role.id, None)
    if actor and isinstance(actor, discord.Member):
        await antinuke.punish(role.guild, actor, settings, f"إنشاء رتبة بصلاحيات خطيرة ({', '.join(dangerous)})", send_mod_log)


@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role) -> None:
    old_permissions_value = antinuke._last_known_role_permissions.get(after.id, before.permissions.value)
    if after.permissions.value == old_permissions_value:
        antinuke._last_known_role_permissions[after.id] = after.permissions.value
        return
    settings = await _antinuke_settings(after.guild.id)
    if not antinuke.is_enabled(settings):
        antinuke._last_known_role_permissions[after.id] = after.permissions.value
        return

    dangerous = antinuke.dangerous_permissions_present(after.permissions, settings)
    old_dangerous = antinuke.dangerous_permissions_present(discord.Permissions(old_permissions_value), settings)
    newly_added = [perm for perm in dangerous if perm not in old_dangerous]
    if newly_added:
        actor = await antinuke.find_actor(after.guild, discord.AuditLogAction.role_update, target_id=after.id)
        try:
            await after.edit(permissions=discord.Permissions(old_permissions_value), reason="إرجاع صلاحيات الرتبة بعد إضافة صلاحية خطيرة — نظام الحماية")
        except discord.Forbidden:
            pass
        else:
            antinuke._last_known_role_permissions[after.id] = old_permissions_value
        if actor and isinstance(actor, discord.Member):
            await antinuke.punish(after.guild, actor, settings, f"إضافة صلاحية خطيرة لرتبة موجودة ({', '.join(newly_added)})", send_mod_log)
        return
    antinuke._last_known_role_permissions[after.id] = after.permissions.value


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    settings = await _antinuke_settings(member.guild.id)

    # ---------------- حفظ الرتب اللاصقة قبل أي شيء آخر ----------------
    # منفصل تماماً عن نظام antinuke؛ يعمل بشرط sticky_roles_enabled فقط بغض
    # النظر عن حالة الحماية من التخريب.
    if bool(settings.get("sticky_roles_enabled")):
        role_ids = [role.id for role in member.roles if not role.is_default()]
        if role_ids:
            await db_call(db.save_sticky_roles, member.guild.id, member.id, role_ids)

    if not antinuke.is_enabled(settings):
        return
    actor = await antinuke.find_actor(member.guild, discord.AuditLogAction.kick, target_id=member.id, within_seconds=5)
    if actor and isinstance(actor, discord.Member):
        window = int(settings.get("antinuke_window_seconds", 10))
        count = antinuke.record_action(member.guild.id, actor.id, "kick", window)
        if count > int(settings.get("antinuke_max_kicks", 3)):
            antinuke.reset_action(member.guild.id, actor.id, "kick")
            await antinuke.punish(member.guild, actor, settings, f"طرد {count} أعضاء خلال {window} ثوانٍ (نمط تخريب مشبوه)", send_mod_log)


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User) -> None:
    settings = await _antinuke_settings(guild.id)
    if not antinuke.is_enabled(settings):
        return
    actor = await antinuke.find_actor(guild, discord.AuditLogAction.ban, target_id=user.id)
    if actor and isinstance(actor, discord.Member):
        window = int(settings.get("antinuke_window_seconds", 10))
        count = antinuke.record_action(guild.id, actor.id, "ban", window)
        if count > int(settings.get("antinuke_max_bans", 3)):
            antinuke.reset_action(guild.id, actor.id, "ban")
            await antinuke.punish(guild, actor, settings, f"حظر {count} أعضاء خلال {window} ثوانٍ (نمط تخريب مشبوه)", send_mod_log)


@bot.event
async def on_webhooks_update(channel: discord.abc.GuildChannel) -> None:
    """حماية إضافية: الويبهوكس من أشهر أدوات التخريب المستمر — مهاجم ينشئ
    ويبهوك بصلاحيات عالية، وحتى لو طُرد أو حُظر بعدها يقدر يستمر بإرسال رسائل
    عبر رابط الويبهوك القديم. أي ويبهوك جديد غير متوقع (مو من فاعل مستثنى)
    يُحذف فوراً ويُعاقَب من أنشأه."""
    guild = channel.guild
    settings = await _antinuke_settings(guild.id)
    if not antinuke.is_enabled(settings):
        return
    actor = await antinuke.find_actor(guild, discord.AuditLogAction.webhook_create, within_seconds=8)
    if actor is None or not isinstance(actor, discord.Member):
        return
    if antinuke.is_whitelisted(guild, actor, settings):
        return
    try:
        webhooks = await channel.webhooks()
    except discord.Forbidden:
        return
    # أحدث ويبهوك بالقناة هو غالباً الويبهوك اللي سبب الحدث نفسه.
    newest = max(webhooks, key=lambda hook: hook.created_at) if webhooks else None
    if newest is not None:
        try:
            await newest.delete(reason="ويبهوك غير موثوق — نظام الحماية")
        except discord.Forbidden:
            pass
    await antinuke.punish(guild, actor, settings, "إنشاء ويبهوك جديد بدون استثناء (خطر تخريب مستمر)", send_mod_log)


async def handle_counting_message(message: discord.Message) -> bool:
    if not message.guild or not isinstance(message.channel, discord.TextChannel):
        return False
    settings = await db_call(db.get_counting_channel, message.guild.id, message.channel.id)
    if not settings or not bool(settings.get("enabled", 1)):
        return False
    received = counting.parse_count(message.content)
    if received is None:
        return False
    current = int(settings.get("current_count", 0))
    if received == current + 1:
        updated = await db_call(db.advance_counting, message.guild.id, message.channel.id)
        try:
            await message.add_reaction(str((updated or settings).get("emoji") or "✅"))
        except (discord.HTTPException, discord.Forbidden):
            pass
        return True
    updated = await db_call(db.register_counting_violation, message.guild.id, message.channel.id) or settings
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden):
        pass
    attempts = int(updated.get("invalid_attempts", 1))
    if attempts >= 2 and isinstance(message.author, discord.Member):
        seconds = max(1, min(int(updated.get("timeout_seconds", 60)), 3600))
        try:
            await message.author.timeout(timedelta(seconds=seconds), reason="عد بشكل متواصل لا تخرب")
        except (discord.Forbidden, discord.HTTPException):
            pass
        await db_call(db.clear_counting_violations, message.guild.id, message.channel.id)
        try:
            await message.channel.send(
                f"{message.author.mention} تم إسكاتك لمدة {seconds} ثانية بسبب: عد بشكل متواصل لا تخرب",
                delete_after=6,
            )
        except (discord.Forbidden, discord.HTTPException):
            pass
    return True


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        has_dashboard_marker = message.content.startswith(DASHBOARD_COMMAND_MARKER)
        if has_dashboard_marker and (bot.user is None or message.author.id != bot.user.id):
            print(f"[DashboardControl] Ignored marker from sender_id={message.author.id}; running_bot_id={getattr(bot.user, 'id', None)}")
            return
        is_dashboard_command = bot.user is not None and message.author.id == bot.user.id and has_dashboard_marker
        if not is_dashboard_command:
            return

        # ---------------------------------------------------------------
        # كل هذا الجزء يُنفَّذ داخل try/finally واحد يغلّف كل شيء، لسببين:
        # 1) نضمن حذف رسالة الماركر (رسالة التحكم المخفية) في كل الحالات،
        #    حتى لو صار خطأ غير متوقع في منتصف المعالجة — قبل هذا الإصلاح كان
        #    أي استثناء يوقف الحذف فتبقى الرسالة ظاهرة بالقناة (وهذا بالضبط
        #    السبب في ظهور رسائل "قديمة الطراز" بروم القوانين).
        # 2) بالنسبة للأوامر العامة (غير نشر لوحة/تدفق)، لا نريد أي رد مرئي
        #    بديسكورد إطلاقاً — النجاح أو الفشل يظهر فقط داخل لوحة التحكم نفسها
        #    (Manus)، فنُسكِت ctx.send لهذا المسار تحديداً فقط.
        # ---------------------------------------------------------------
        message.content = message.content[len(DASHBOARD_COMMAND_MARKER):].lstrip()
        if not message.guild:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            return

        try:
            active_prefix = (await db_call(db.get_guild_settings, message.guild.id)).get("prefix", "!")
            known_dashboard_names = [command.name for command in bot.commands]
            known_dashboard_names.extend(alias for command in bot.commands for alias in getattr(command, "aliases", []))
            message.content = normalize_dashboard_command(message.content, active_prefix, known_dashboard_names)

            # مسار مباشر للتحكم الداخلي: يضمن تنفيذ Workflow حتى لو لم يتعرف
            # محلل commands.py على الاسم العربي بعد تعديل محتوى Message.
            # هذا المسار (نشر لوحة/تدفق) يبقى يرسل ناتجه الحقيقي (اللوحة نفسها
            # بأزرارها) لأن هذا هو المطلوب فعلياً نشره، وليس رسالة تأكيد عابرة.
            command_parts = message.content.split(maxsplit=2)
            if len(command_parts) >= 2 and command_parts[0] == f"{active_prefix}تحديث_لوحة":
                dashboard_context = await build_dashboard_context(message)
                print("[DashboardControl] Direct Panel dispatch")
                await update_panel.callback(dashboard_context, command_parts[1])
                return
            if len(command_parts) >= 3 and command_parts[0] == f"{active_prefix}تحديث_تدفق":
                dashboard_context = await build_dashboard_context(message)
                print("[DashboardControl] Direct Workflow dispatch")
                await update_workflow.callback(dashboard_context, command_parts[1], command_parts[2])
                return

            # بقية الأوامر (كل الإعدادات العامة، الطرد، الحظر، إلخ): تُنفَّذ
            # بصمت تام بديسكورد — بدون أي رسالة نجاح أو فشل مرئية بالروم.
            dashboard_context = await build_dashboard_context(message)
            if dashboard_context.command is None:
                command_token = message.content.split()[0] if message.content else "<فارغ>"
                print(f"[DashboardControl] Command was not recognized: {command_token}")
                return

            # نُسكِت أي رد يرسله الأمر نفسه (رسائل ✅/❌ العادية) عبر استبدال
            # دالة send الخاصة بهذا السياق فقط بنسخة لا تنشر شيئاً بديسكورد؛
            # النجاح/الفشل الحقيقي يظهر داخل لوحة التحكم عبر رمز الاستجابة.
            async def _silent_send(*_args: Any, **_kwargs: Any) -> None:
                return None

            dashboard_context.send = _silent_send  # type: ignore[assignment]
            print(f"[DashboardControl] Executing {dashboard_context.command.qualified_name}")
            await bot.invoke(dashboard_context)
        except Exception as error:  # لا نترك أي استثناء يسرّب رسالة أو يمنع الحذف
            print(f"[DashboardControl] Unexpected error: {type(error).__name__}: {error!r}")
        finally:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
        return
    if not message.guild:
        return

    # جلب إعدادات السيرفر مرة واحدة فقط (كانت تُقرأ من القرص مرتين لكل رسالة)،
    # وتنفيذها في Thread منفصل حتى لا تحجب حلقة الأحداث وتؤخر ردود الأزرار
    # الأخرى الواردة في نفس اللحظة.
    settings = await cached_guild_settings(message.guild.id)
    prefix = settings.get("prefix", "!")

    # ---------------- حماية من سبام المنشن الجماعي ----------------
    # مستوحاة من ميزة "Mention Spam" ببوتات الحماية الشهيرة: رسالة واحدة تمنشن
    # عدداً كبيراً جداً من الأعضاء/الرتب دفعة وحدة غالباً محاولة إزعاج متعمدة
    # (سبام منشن) وليست استخدام طبيعي. نحسب منشن الأعضاء + منشن الرتب معاً.
    if bool(settings.get("antispam_mention_enabled")) and isinstance(message.author, discord.Member):
        total_mentions = len(message.mentions) + len(message.role_mentions)
        max_mentions = int(settings.get("antispam_max_mentions", 6))
        if total_mentions > max_mentions and not antinuke.is_whitelisted(message.guild, message.author, settings):
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            action = settings.get("antispam_action", "timeout")
            reason = f"منشن {total_mentions} عضو/رتبة برسالة واحدة (الحد {max_mentions}) — نظام الحماية"
            if action == "kick":
                try:
                    await message.author.kick(reason=reason)
                except discord.Forbidden:
                    pass
            elif action == "timeout":
                try:
                    await message.author.timeout(timedelta(minutes=30), reason=reason)
                except discord.Forbidden:
                    pass
            await send_mod_log(message.guild, discord.Embed(
                title="🚫 سبام منشن جماعي",
                description=f"**العضو:** {message.author.mention} (`{message.author.id}`)\n**عدد المنشنات:** {total_mentions}\n**القناة:** {message.channel.mention}",
                color=discord.Color.red(),
            ))
            return

    # ---------------- فلتر روابط التصيّد (Anti-Phishing) ----------------
    # يُفحص قبل أي معالجة أخرى للرسالة (حتى قبل الأوامر) لأنه أولوية أمنية:
    # لو الرسالة فيها رابط تصيّد معروف (سكام نيترو مزيف، ستيم مزيف...)، تُحذف
    # فوراً بغض النظر عن أي شيء آخر بالرسالة.
    if antinuke.is_phishing_enabled(settings) and isinstance(message.author, discord.Member):
        matched_domain = antinuke.find_phishing_domain(message.content, settings)
        if matched_domain:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            action = settings.get("antiphishing_action", "delete")
            reason = f"إرسال رابط تصيّد معروف ({matched_domain})"
            if action != "delete" and not antinuke.is_whitelisted(message.guild, message.author, settings):
                # نستخدم نفس دالة العقاب بنظام antinuke (طرد/حظر/تايم أوت)
                # حتى تبقى منطقية العقوبة والاستثناءات موحّدة بمكان واحد.
                fake_settings = dict(settings)
                fake_settings["antinuke_punishment"] = action
                await antinuke.punish(message.guild, message.author, fake_settings, reason, send_mod_log)
            else:
                await send_mod_log(message.guild, discord.Embed(
                    title="🎣 حذف رابط تصيّد",
                    description=f"**العضو:** {message.author.mention} (`{message.author.id}`)\n**النطاق:** `{matched_domain}`\n**القناة:** {message.channel.mention}",
                    color=discord.Color.red(),
                ))
            return

    # الردود التلقائية: تُفحص فقط للرسائل التي ليست أوامر بوت، حتى لا تتعارض
    # مع أوامر Spectre نفسها.
    if not message.content.startswith(prefix):
        auto_responses = await db_call(db.get_auto_responses, message.guild.id)
        if auto_responses:
            matched = find_matching_auto_response(auto_responses, message.content)
            if matched:
                try:
                    reply_text = str(matched["response_text"]).format(
                        user=message.author.mention,
                        username=message.author.name,
                        display_name=message.author.display_name,
                    )
                except (KeyError, ValueError):
                    reply_text = str(matched["response_text"])
                try:
                    await message.channel.send(reply_text, allowed_mentions=ALLOWED_MENTIONS)
                except discord.HTTPException:
                    pass

    parts = message.content.split(maxsplit=1)
    if parts and parts[0].startswith(prefix):
        custom_name = parts[0][len(prefix):]
        canonical_name = games.resolve_custom_command(message.guild.id, custom_name)
        if canonical_name:
            message.content = f"{prefix}{canonical_name}" + (f" {parts[1]}" if len(parts) > 1 else "")

    if await games.handle_flag_guess(message):
        return

    if await handle_counting_message(message):
        return

    now = datetime.now(timezone.utc)
    key = (message.guild.id, message.author.id)
    history = [stamp for stamp in message_history[key] if now - stamp < timedelta(seconds=5)]
    history.append(now)
    message_history[key] = history
    if len(history) > 5:
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention}، الرجاء عدم السبام.", delete_after=4)
            message_history[key] = []
        except discord.Forbidden:
            pass
        return

    last_xp = xp_cooldown.get(key)
    if not settings["levels_enabled"]:
        await bot.process_commands(message)
        return
    if await member_is_blocked(message.author, "level_ignored_role_ids_json"):
        await bot.process_commands(message)
        return

    cooldown_seconds = max(5, int(settings.get("xp_cooldown_seconds", 60)))
    if last_xp is None or now - last_xp >= timedelta(seconds=cooldown_seconds):
        xp_cooldown[key] = now
        xp_min = max(1, int(settings.get("xp_min", 15)))
        xp_max = max(xp_min, int(settings.get("xp_max", 25)))
        base_xp = random.randint(xp_min, xp_max)
        xp_event = await db_call(db.get_xp_event, message.guild.id)
        multiplier = float(xp_event.get("multiplier", 1.0))
        awarded_xp = max(1, round(base_xp * multiplier))
        leveled_up, _old_level, new_level, _xp = await db_call(db.add_xp, message.guild.id, message.author.id, awarded_xp)
        if leveled_up and isinstance(message.author, discord.Member):
            await handle_level_up(message.guild, message.author, new_level, message.channel)

    await bot.process_commands(message)


def _level_json_list(settings: dict[str, Any], key: str) -> set[int]:
    raw = settings.get(key, "[]")
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        values = []
    return {int(v) for v in values if str(v).isdigit()} if isinstance(values, list) else set()


def _level_role_state(guild: discord.Guild, current_level: int) -> dict[str, Any]:
    rows = db.get_level_roles(guild.id)
    mapped = [(int(level), guild.get_role(int(role_id))) for level, role_id in rows]
    mapped = [(level, role) for level, role in mapped if role is not None]
    current = [role for level, role in mapped if level == current_level]
    next_items = [(level, role) for level, role in mapped if level > current_level]
    next_level, next_role = next_items[0] if next_items else (None, None)
    return {"current_role": current[-1] if current else None, "next_level": next_level, "next_role": next_role}


def render_level_message(template: str, *, guild: discord.Guild, member: discord.Member, level: int, xp: int, granted_roles: list[discord.Role]) -> str:
    state = _level_role_state(guild, level)
    current_role = state["current_role"]
    next_role = state["next_role"]
    variables = {
        "user": member.mention, "username": member.name, "display_name": member.display_name,
        "level": level, "xp": xp, "xp_total": db.total_xp(level, xp),
        "next_level": state["next_level"] if state["next_level"] is not None else "",
        "next_role": next_role.mention if next_role else "",
        "next_role_name": next_role.name if next_role else "",
        "role": current_role.mention if current_role else "",
        "role_name": current_role.name if current_role else "",
        "granted_roles": ", ".join(r.mention for r in granted_roles),
        "granted_role_names": ", ".join(r.name for r in granted_roles),
        "role_count": len(granted_roles),
        "remaining_xp": max(0, db.xp_for_level(level) - xp),
        "guild": guild.name, "member_count": guild.member_count,
    }
    try:
        return template.format(**variables)
    except (KeyError, ValueError, IndexError):
        return f"مبروك {member.mention}! وصلت للفل **{level}**." + (f"\n**الرتبة:** {current_role.mention}" if current_role else "")


async def handle_level_up(
    guild: discord.Guild, member: discord.Member, new_level: int, fallback_channel: discord.abc.Messageable,
) -> None:
    settings = await db_call(db.get_guild_settings, guild.id)
    excluded_roles = _level_json_list(settings, "level_excluded_role_ids_json")
    granted_roles: list[discord.Role] = []
    # ربط الرتب باللفلات مستقل عن إزالة الرتب. لا يزيل نظام اللفلات أي رتبة
    # موجودة لدى العضو عند الترقية؛ حذف/تعديل الربط يتم فقط من لوحة التحكم.
    for level, role_id in await db_call(db.get_level_roles, guild.id):
        if level <= new_level and role_id not in excluded_roles:
            role = guild.get_role(role_id)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"وصل إلى اللفل {new_level}")
                    granted_roles.append(role)
                except discord.Forbidden:
                    pass

    xp, _stored_level = await db_call(db.get_user_level, guild.id, member.id)
    template = str(settings.get("level_up_message") or "مبروك {user}! وصلت للفل **{level}**.{role}")
    description = render_level_message(template, guild=guild, member=member, level=new_level, xp=xp, granted_roles=granted_roles)
    embed = discord.Embed(title="🎉 ترقية لفل جديد", description=description, color=discord.Color.gold())
    custom_image = discord_asset_url(settings.get("level_up_image_url"))
    custom_thumb = discord_asset_url(settings.get("level_up_thumbnail_url"))
    if custom_image: embed.set_image(url=custom_image)
    if custom_thumb: embed.set_thumbnail(url=custom_thumb)
    else: embed.set_thumbnail(url=member.display_avatar.url)

    if settings.get("level_up_mode") == "dm":
        try: await member.send(embed=embed)
        except discord.Forbidden: pass
        return
    channel = safe_channel(guild, settings.get("level_up_channel_id"))
    target = channel if isinstance(channel, discord.TextChannel) else fallback_channel
    try: await target.send(embed=embed)
    except discord.Forbidden: pass

def parse_duration(text: str) -> int | None:
    """يحوّل نصاً مثل '10m' أو '2h' أو '1d' لعدد ثوانٍ. يدعم s/m/h/d
    (ثانية/دقيقة/ساعة/يوم) والأرقام العربية المكتوبة أيضاً بنفس الحروف
    اللاتينية (مثال شائع بأوامر بوتات الغيف أواي: 30m، 1h، 3d)."""
    match = re.fullmatch(r"(\d+)\s*([smhd])", text.strip().lower())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return amount * multiplier


async def draw_giveaway_winners(giveaway: dict[str, Any]) -> list[discord.Member]:
    """يجلب كل من تفاعل بـ🎉 على رسالة المسابقة (باستثناء البوت نفسه)، ويسحب
    عدداً عشوائياً منهم بحجم winners_count. يعيد قائمة فارغة لو محد شارك.
    نتجاهل من غادر السيرفر فعلاً (guild.get_member يعيد None له) لأنه لا
    معنى لفوز شخص لم يعد عضواً — لسنا بحاجة استدعاء API إضافي (fetch_member)
    لكل مشارك، فهذا يستهلك وقتاً طويلاً ويصطدم بحدود المعدل لو كان عدد
    المشاركين كبيراً، والكاش (get_member) يكفي عملياً بوجود members intent."""
    guild = bot.get_guild(int(giveaway["guild_id"]))
    if guild is None:
        return []
    channel = guild.get_channel(int(giveaway["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        return []
    try:
        message = await channel.fetch_message(int(giveaway["message_id"]))
    except (discord.NotFound, discord.Forbidden):
        return []
    participants: list[discord.Member] = []
    for reaction in message.reactions:
        if str(reaction.emoji) != "🎉":
            continue
        async for user in reaction.users():
            if not user.bot:
                member = guild.get_member(user.id)
                if member is not None:
                    participants.append(member)
        break
    if not participants:
        return []
    winners_count = min(int(giveaway["winners_count"]), len(participants))
    return random.sample(participants, winners_count)


def build_giveaway_embed(giveaway: dict[str, Any], *, ended: bool, winners: list[discord.Member] | None = None) -> discord.Embed:
    """يبني Embed موحّد لرسالة المسابقة، يُستخدم عند الإنشاء وأيضاً لتعديل
    نفس الرسالة الأصلية عند الانتهاء (بدل تركها كأنها لسا نشطة إلى الأبد)."""
    if ended:
        if winners:
            mentions = "، ".join(winner.mention for winner in winners)
            description = f"**الجائزة:** {giveaway['prize']}\n**الفائز/الفائزون:** {mentions}\n\n🔴 انتهت المسابقة."
        else:
            description = f"**الجائزة:** {giveaway['prize']}\nما شارك أحد 😕\n\n🔴 انتهت المسابقة."
        return discord.Embed(title="🎉 انتهت المسابقة", description=description, color=discord.Color.greyple())
    ends_at = giveaway.get("ends_at")
    timestamp_line = f"<t:{int(datetime.fromisoformat(ends_at).timestamp())}:R>" if ends_at else "قريباً"
    embed = discord.Embed(
        title="🎉 مسابقة جديدة!",
        description=f"**الجائزة:** {giveaway['prize']}\n**عدد الفائزين:** {giveaway['winners_count']}\n**تنتهي:** {timestamp_line}\n\nاضغط 🎉 للمشاركة!",
        color=discord.Color.gold(),
    )
    return embed


async def finish_giveaway(giveaway: dict[str, Any]) -> None:
    """تسحب الفائزين، تعدّل رسالة المسابقة الأصلية لتُظهر أنها انتهت (بدل
    تركها بشكلها النشط للأبد وكأن أحداً لم يتفقدها)، وتعلن الفائزين برسالة
    منفصلة يُذكرون فيها فعلياً (الـ mention لا يظهر بشكل موثوق داخل embed)."""
    winners = await draw_giveaway_winners(giveaway)
    await db_call(db.mark_giveaway_ended, giveaway["id"])
    guild = bot.get_guild(int(giveaway["guild_id"]))
    if guild is None:
        return
    channel = guild.get_channel(int(giveaway["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        return
    ended_embed = build_giveaway_embed(giveaway, ended=True, winners=winners)
    try:
        original_message = await channel.fetch_message(int(giveaway["message_id"]))
        await original_message.edit(embed=ended_embed)
    except (discord.NotFound, discord.Forbidden):
        pass
    try:
        if winners:
            mentions = "، ".join(winner.mention for winner in winners)
            await channel.send(f"🎉 مبروك {mentions}! فزت بـ **{giveaway['prize']}**", allowed_mentions=ALLOWED_MENTIONS)
        else:
            await channel.send(f"😕 انتهت مسابقة **{giveaway['prize']}** بدون أي مشارك.")
    except discord.Forbidden:
        pass


@tasks.loop(minutes=1)
async def check_pending_giveaways() -> None:
    """تعمل كل دقيقة: تجلب أي مسابقة حان وقت انتهائها ولم تُسحَب بعد وتسحب
    فائزيها. الاعتماد على قاعدة البيانات (بدل asyncio.sleep لكل مسابقة على
    حدة) يضمن أن المسابقة تُسحَب بشكل صحيح حتى لو أُعيد تشغيل البوت أثناء
    انتظارها."""
    now_iso = datetime.now(timezone.utc).isoformat()
    pending = await db_call(db.get_pending_giveaways, now_iso)
    for giveaway in pending:
        await finish_giveaway(giveaway)


@tasks.loop(minutes=30)
async def cleanup_memory_caches() -> None:
    """ينظّف قواميس السبام وكولداون الخبرة من المفاتيح القديمة بالذاكرة، لأنها
    تتراكم بلا حد أقصى (مفتاح لكل عضو تحدّث ولو مرة) وتسبب تسريب ذاكرة بطيء
    على المدى الطويل في السيرفرات النشطة."""
    now = datetime.now(timezone.utc)
    stale_history_keys = [key for key, stamps in message_history.items() if not stamps or now - stamps[-1] > timedelta(minutes=5)]
    for key in stale_history_keys:
        message_history.pop(key, None)
    stale_cooldown_keys = [key for key, stamp in xp_cooldown.items() if now - stamp > timedelta(hours=2)]
    for key in stale_cooldown_keys:
        xp_cooldown.pop(key, None)
    antinuke.cleanup_stale_actions()


@tasks.loop(minutes=10)
async def update_member_count() -> None:
    for guild in bot.guilds:
        channel = discord.utils.find(lambda item: item.name.startswith("👥 Members:"), guild.voice_channels)
        if channel:
            try:
                await channel.edit(name=f"👥 Members: {guild.member_count}")
            except discord.Forbidden:
                pass


@update_member_count.before_loop
async def before_member_count_loop() -> None:
    await bot.wait_until_ready()


@bot.command(name="تفعيل_الترحيب")
@staff_only()
@commands.guild_only()
async def enable_welcome(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "welcome_enabled", True)
    await ctx.send("✅ تم تفعيل رسائل الترحيب.")


@bot.command(name="تعطيل_الترحيب")
@staff_only()
@commands.guild_only()
async def disable_welcome(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "welcome_enabled", False)
    await ctx.send("⏸️ تم تعطيل رسائل الترحيب.")


@bot.command(name="ضبط_الويلكوم")
@staff_only()
@commands.guild_only()
async def set_welcome(ctx: commands.Context, channel: discord.TextChannel) -> None:
    db.set_guild_setting(ctx.guild.id, "welcome_channel_id", channel.id)
    db.set_guild_setting(ctx.guild.id, "welcome_enabled", True)
    await ctx.send(f"✅ تم تعيين قناة الترحيب وتفعيلها: {channel.mention}")


@bot.command(name="ضبط_ترحيب")
@commands.guild_only()
async def configure_welcome_design(ctx: commands.Context, encoded: str) -> None:
    if not isinstance(ctx.author, discord.Member) or not is_staff_member(ctx.author):
        await ctx.send("❌ تحتاج صلاحية إدارة السيرفر.")
        return
    try:
        config = decode_workflow_payload(encoded)
        config["channel_id"] = int(config.get("channel_id") or 0)
        db.save_welcome_config(ctx.guild.id, config)
        if config["channel_id"]:
            db.set_guild_setting(ctx.guild.id, "welcome_channel_id", config["channel_id"])
        db.set_guild_setting(ctx.guild.id, "welcome_enabled", bool(config.get("enabled", True)))
        await ctx.send("✅ تم حفظ تصميم الترحيب والصورة والخطوط بنجاح.")
    except Exception as error:
        print(f"[Welcome] Failed to save design: {error}")
        await ctx.send("❌ تعذر حفظ تصميم الترحيب. تحقق من البيانات ثم أعد المحاولة.")


@bot.hybrid_command(name="تفعيل_اللفلات")
@staff_only()
@commands.guild_only()
async def enable_levels(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "levels_enabled", True)
    await ctx.send("✅ تم تفعيل نظام المستويات.")


@bot.hybrid_command(name="تعطيل_اللفلات")
@staff_only()
@commands.guild_only()
async def disable_levels(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "levels_enabled", False)
    await ctx.send("⏸️ تم تعطيل نظام المستويات.")


@bot.command(name="ضبط_الحضور", description="تخصيص عبارات Presence وفترة تغييرها")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def configure_presence(ctx: commands.Context, interval_seconds: int = 60, *, messages: str = "") -> None:
    phrases = [item.strip() for item in messages.split("|") if item.strip()]
    if not phrases:
        await ctx.send("❌ اكتب عبارة واحدة على الأقل بعد مدة التغيير، وافصل العبارات بعلامة |.")
        return
    if len(phrases) > 10 or any(len(item) > 128 for item in phrases):
        await ctx.send("❌ الحد الأقصى 10 عبارات، وكل عبارة لا تتجاوز 128 حرفاً.")
        return
    try:
        db.set_presence_config(phrases, interval_seconds)
    except (TypeError, ValueError):
        await ctx.send("❌ مدة التغيير يجب أن تكون بين 15 ثانية و24 ساعة.")
        return
    rotate_presence.change_interval(seconds=presence_config.get_presence_interval(db))
    await apply_next_presence()
    await ctx.send(f"✅ تم حفظ {len(phrases)} عبارات Presence وتغييرها كل {presence_config.get_presence_interval(db)} ثانية.")


@bot.hybrid_command(name="تشغيل_القرآن", description="تشغيل إذاعة القرآن في القناة الصوتية")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def start_quran_radio(ctx: commands.Context, channel: Optional[discord.VoiceChannel] = None) -> None:
    if channel is None:
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ ادخل قناة صوتية أولاً أو حدد القناة في الأمر.")
            return
        channel = ctx.author.voice.channel
    me = ctx.guild.me
    if me is not None:
        voice_permissions = channel.permissions_for(me)
        missing = []
        if not voice_permissions.connect:
            missing.append("Connect")
        if not voice_permissions.speak:
            missing.append("Speak")
        if missing:
            missing_text = " و".join(missing)
            await ctx.send(f"❌ لا أملك صلاحية {missing_text} في {channel.mention}. فعّلها للبوت أو لرتبته.")
            return
    try:
        ffmpeg_path = radio_manager.ffmpeg_executable()
        print(f"[QuranRadio] Using FFmpeg: {ffmpeg_path}")
        await radio_manager.start(ctx.guild, channel, os.getenv("QURAN_RADIO_STREAM_URL"))
    except FileNotFoundError:
        print(f"[QuranRadio] FFmpeg executable not found: {radio_manager.ffmpeg_executable()}")
        await ctx.send("❌ لم أجد FFmpeg القابل للتشغيل. تأكد من وجود `bin/ffmpeg` داخل مجلد البوت أو اضبط FFMPEG_PATH.")
        return
    except PermissionError:
        print(f"[QuranRadio] FFmpeg is not executable: {radio_manager.ffmpeg_executable()}")
        await ctx.send("❌ ملف FFmpeg موجود لكنه غير قابل للتشغيل. أعد رفع الحزمة كاملة أو فعّل صلاحية التنفيذ للملف.")
        return
    except discord.Forbidden:
        await ctx.send(f"❌ رفض Discord دخول {channel.mention}. تأكد من صلاحيات Connect وSpeak ومن أن البوت يستطيع دخول الروم.")
        return
    except Exception as error:
        print(f"[QuranRadio] Start failed ({type(error).__name__}): {error!r}")
        await ctx.send("❌ فشل تشغيل الإذاعة. راجع سجل الاستضافة وابحث عن السطر `[QuranRadio] Start failed` لمعرفة السبب التفصيلي.")
        return
    await ctx.send(f"✅ تم تشغيل إذاعة القرآن في {channel.mention}. الرابط الافتراضي مفعّل ولا يلزم QURAN_RADIO_STREAM_URL.")


@bot.hybrid_command(name="ايقاف_القرآن", description="إيقاف إذاعة القرآن")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def stop_quran_radio(ctx: commands.Context) -> None:
    if ctx.guild.voice_client is None and ctx.guild.id not in radio_manager.jobs:
        await ctx.send("ℹ️ البوت غير موجود في قناة صوتية.")
        return
    await radio_manager.stop(ctx.guild)
    await ctx.send("✅ تم إيقاف إذاعة القرآن.")


@bot.hybrid_command(name="حالة_القرآن", description="عرض حالة إذاعة القرآن")
@commands.guild_only()
async def quran_radio_status(ctx: commands.Context) -> None:
    voice = ctx.guild.voice_client
    if voice and voice.is_connected() and voice.is_playing():
        await ctx.send(f"✅ الإذاعة تعمل في {voice.channel.mention}.")
    else:
        await ctx.send("ℹ️ الإذاعة متوقفة.")


@bot.command(name="اضافة_تنبيه_منصة", description="ربط قناة YouTube أو Twitch أو Kick بإشعار Embed")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def add_social_notification(ctx: commands.Context, platform: str, url: str, channel: discord.TextChannel, mention: str = "", color: str = "2ca77a", *, message: str = social_notifications.DEFAULT_MESSAGE) -> None:
    try:
        cleaned_mention = "" if mention.strip().lower() in {"-", "none", "بدون"} else mention
        color_value = int(color.strip().lstrip("#"), 16)
        source = social_notifications.normalize_source(platform, url, channel.id, cleaned_mention, message, color_value)
        sources = db.get_social_sources(ctx.guild.id)
        sources = [item for item in sources if not (item.get("platform") == source["platform"] and item.get("url") == source["url"])]
        sources.append(source)
        db.save_social_sources(ctx.guild.id, sources)
    except (TypeError, ValueError) as error:
        await ctx.send(f"❌ تعذر حفظ المصدر: {error}")
        return
    await ctx.send(f"✅ تمت إضافة تنبيه {source['platform']} في {channel.mention}. سيبدأ الفحص خلال دقائق، ولن تُرسل رسالة قديمة عند أول ربط.")


@bot.command(name="حذف_تنبيه_منصة", description="حذف مصدر إشعارات YouTube أو Twitch أو Kick")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def remove_social_notification(ctx: commands.Context, url: str) -> None:
    sources = db.get_social_sources(ctx.guild.id)
    remaining = [item for item in sources if item.get("url") != url.strip()]
    db.save_social_sources(ctx.guild.id, remaining)
    await ctx.send("✅ تم حذف مصدر الإشعار." if len(remaining) != len(sources) else "ℹ️ لم أجد هذا الرابط ضمن مصادر الإشعارات.")


@bot.command(name="تنبيهات_المنصات", description="عرض مصادر إشعارات YouTube وTwitch وKick")
@commands.guild_only()
async def list_social_notifications(ctx: commands.Context) -> None:
    sources = db.get_social_sources(ctx.guild.id)
    if not sources:
        await ctx.send("ℹ️ لا توجد مصادر إشعارات مضافة بعد.")
        return
    lines = [f"• {item['platform']} — <#{item['channel_id']}> — {item['url']}" for item in sources]
    await ctx.send("**مصادر إشعارات Spectre:**\n" + "\n".join(lines)[:1900])


@bot.command(name="اعداد_روم_العد", description="إضافة أو تحديث روم Counting")
@commands.has_permissions(manage_guild=True)
async def configure_counting(ctx: commands.Context, channel: discord.TextChannel, emoji: str = "✅", timeout_seconds: int = 60) -> None:
    db.set_counting_channel(ctx.guild.id, channel.id, emoji=emoji, timeout_seconds=timeout_seconds, enabled=True)
    await ctx.send(f"✅ تم تفعيل العد في {channel.mention} بالرمز {emoji} والعقوبة بعد المخالفة الثانية {timeout_seconds} ثانية.")


@bot.command(name="حذف_روم_العد", description="إيقاف Counting في روم")
@commands.has_permissions(manage_guild=True)
async def disable_counting(ctx: commands.Context, channel: discord.TextChannel) -> None:
    removed = db.remove_counting_channel(ctx.guild.id, channel.id)
    await ctx.send("✅ تم إيقاف Counting في الروم." if removed else "ℹ️ الروم غير مفعّل.")


@bot.command(name="تصفير_العد", description="تصفير رقم Counting")
@commands.has_permissions(manage_guild=True)
async def reset_counting(ctx: commands.Context, channel: discord.TextChannel, value: int = 0) -> None:
    db.reset_counting_channel(ctx.guild.id, channel.id, value)
    await ctx.send(f"✅ تم ضبط عداد {channel.mention} على {max(0, int(value))}.")


@bot.command(name="رومات_العد", description="عرض رومات Counting")
async def list_counting(ctx: commands.Context) -> None:
    rows = db.get_counting_channels(ctx.guild.id)
    if not rows:
        await ctx.send("لا توجد رومات Counting مفعلة.")
        return
    lines = []
    for row in rows:
        channel = ctx.guild.get_channel(int(row["channel_id"]))
        label = channel.mention if channel else str(row["channel_id"])
        lines.append(f"{label}: {row['current_count']} {row['emoji']}")
    await ctx.send("\\n".join(lines))


@bot.command(name="تغيير_البادئة")
@staff_only()
@commands.guild_only()
async def change_prefix(ctx: commands.Context, prefix: str) -> None:
    prefix = prefix.strip()
    if not 1 <= len(prefix) <= 3 or any(char.isspace() for char in prefix):
        await ctx.send("❌ البادئة يجب أن تكون من 1 إلى 3 رموز بلا مسافات.")
        return
    db.set_guild_setting(ctx.guild.id, "prefix", prefix)
    await ctx.send(f"✅ تم تغيير بادئة هذا السيرفر إلى `{prefix}`.")


@bot.command(name="انشاء_عداد_الاعضاء")
@staff_only()
@commands.guild_only()
async def create_member_count(ctx: commands.Context) -> None:
    channel = await ctx.guild.create_voice_channel(f"👥 Members: {ctx.guild.member_count}", reason="عداد أعضاء تلقائي")
    await ctx.send(f"✅ تم إنشاء عداد الأعضاء: {channel.mention}")


@bot.command(name="ضبط_قناة_اللفلات")
@staff_only()
@commands.guild_only()
async def set_level_channel(ctx: commands.Context, target: str) -> None:
    """!ضبط_قناة_اللفلات #القناة أو !ضبط_قناة_اللفلات خاص"""
    if target.lower() in {"خاص", "خاصة", "dm"}:
        db.set_guild_setting(ctx.guild.id, "level_up_mode", "dm")
        await ctx.send("✅ ستصل رسائل ترقية اللفلات في الخاص.")
        return
    if target.lower() in {"حالية", "الحالية", "current"}:
        db.set_guild_setting(ctx.guild.id, "level_up_mode", "current")
        db.set_guild_setting(ctx.guild.id, "level_up_channel_id", None)
        await ctx.send("✅ ستصل رسائل اللفلات في القناة الحالية عند حدوث الارتقاء.")
        return
    channel = ctx.message.channel_mentions[0] if ctx.message.channel_mentions else None
    if not isinstance(channel, discord.TextChannel):
        await ctx.send("❌ استخدم منشن قناة، مثال: `!ضبط_قناة_اللفلات #اللفلات`، أو اكتب `خاص`.")
        return
    db.set_guild_setting(ctx.guild.id, "level_up_mode", "channel")
    db.set_guild_setting(ctx.guild.id, "level_up_channel_id", channel.id)
    await ctx.send(f"✅ ستصل رسائل اللفلات في {channel.mention}.")


@bot.command(name="ضبط_خبرة_اللفل", aliases=["ضبط_خبرة_اللفلات"])
@staff_only()
@commands.guild_only()
async def set_level_xp(ctx: commands.Context, minimum: int, maximum: int, cooldown: int = 60) -> None:
    minimum = max(1, min(int(minimum), 1000))
    maximum = max(minimum, min(int(maximum), 2000))
    cooldown = max(5, min(int(cooldown), 3600))
    db.set_guild_setting(ctx.guild.id, "xp_min", minimum)
    db.set_guild_setting(ctx.guild.id, "xp_max", maximum)
    db.set_guild_setting(ctx.guild.id, "xp_cooldown_seconds", cooldown)
    await ctx.send(f"✅ إعداد XP: من **{minimum}** إلى **{maximum}** كل **{cooldown}** ثانية.")


@bot.command(name="فعالية_xp", aliases=["ايفنت_xp"])
@staff_only()
@commands.guild_only()
async def start_xp_event(ctx: commands.Context, multiplier: float = 2.0, duration_minutes: int = 60) -> None:
    multiplier = max(1.5, min(float(multiplier), 4.0))
    duration_minutes = max(1, min(int(duration_minutes), 10080))
    event = db.save_xp_event(ctx.guild.id, multiplier, duration_minutes)
    await ctx.send(f"⚡ بدأت فعالية XP بمضاعف **{multiplier:g}x** لمدة **{duration_minutes} دقيقة**. تنتهي في `{event['expires_at']}`.")


@bot.command(name="ايقاف_فعالية_xp", aliases=["توقف_xp"])
@staff_only()
@commands.guild_only()
async def stop_xp_event(ctx: commands.Context) -> None:
    db.clear_xp_event(ctx.guild.id)
    await ctx.send("⏹️ تم إيقاف فعالية XP والعودة إلى المعدل الطبيعي.")


@bot.command(name="حالة_فعالية_xp")
@commands.guild_only()
async def xp_event_status(ctx: commands.Context) -> None:
    event = db.get_xp_event(ctx.guild.id)
    multiplier = float(event.get("multiplier", 1.0))
    if multiplier <= 1.0:
        await ctx.send("ℹ️ لا توجد فعالية XP نشطة حاليًا.")
        return
    await ctx.send(f"⚡ فعالية XP نشطة بمضاعف **{multiplier:g}x** حتى `{event['expires_at']}`.")


@bot.command(name="ضبط_رسالة_اللفل", aliases=["ضبط_رسالة_اللفلات"])
@staff_only()
@commands.guild_only()
async def set_level_message(ctx: commands.Context, *, message: str) -> None:
    message = message.strip()[:2500]
    if not message:
        await ctx.send("❌ اكتب رسالة الارتقاء بعد الأمر.")
        return
    db.set_guild_setting(ctx.guild.id, "level_up_message", message)
    await ctx.send("✅ تم حفظ رسالة الارتقاء. المتغيرات المدعومة: `{user}` و`{username}` و`{display_name}` و`{level}` و`{role}` و`{role_name}`. إذا لم توجد رتبة للمستوى فسيُستبدل `{role}` و`{role_name}` بنص فارغ.")


@bot.command(name="اضافة_لفل_رتبة")
@staff_only()
@commands.guild_only()
async def add_level_role_cmd(ctx: commands.Context, level: int, role: discord.Role) -> None:
    if role >= ctx.guild.me.top_role:
        await ctx.send("❌ ضع رتبة البوت أعلى من الرتبة التي تريد منحها أولاً.")
        return
    db.add_level_role(ctx.guild.id, level, role.id)
    await ctx.send(f"✅ العضو الذي يصل للفل **{level}** سيحصل على رتبة {role.mention}.")


@bot.command(name="حذف_لفل_رتبة")
@staff_only()
@commands.guild_only()
async def remove_level_role_cmd(ctx: commands.Context, level: int) -> None:
    db.remove_level_role(ctx.guild.id, level)
    await ctx.send(f"🗑️ تم حذف ربط اللفل **{level}** بالرتبة.")


@bot.command(name="رتب_اللفلات")
@staff_only()
@commands.guild_only()
async def list_level_roles(ctx: commands.Context) -> None:
    level_roles = db.get_level_roles(ctx.guild.id)
    if not level_roles:
        await ctx.send("لا توجد رتب مربوطة باللفلات حالياً.")
        return
    lines = []
    for level, role_id in level_roles:
        role = ctx.guild.get_role(role_id)
        lines.append(f"اللفل **{level}** ← {role.mention if role else 'رتبة محذوفة'}")
    await ctx.send(embed=discord.Embed(title="📊 رتب اللفلات", description="\n".join(lines), color=discord.Color.blurple()))


@bot.hybrid_command(name="رتبتي")
@commands.guild_only()
async def my_level(ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
    member = member or ctx.author
    xp, level = db.get_user_level(ctx.guild.id, member.id)
    embed = discord.Embed(title=f"📈 مستوى {member.display_name}", color=discord.Color.blurple())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="اللفل", value=str(level), inline=True)
    embed.add_field(name="الخبرة", value=f"{xp} / {db.xp_for_level(level)} XP", inline=True)
    await ctx.send(embed=embed)


@bot.hybrid_command(name="المتصدرين")
@commands.guild_only()
async def leaderboard(ctx: commands.Context) -> None:
    top = db.get_leaderboard(ctx.guild.id, limit=10)
    if not top:
        await ctx.send("لا توجد بيانات لفلات حتى الآن.")
        return
    medals = ("🥇", "🥈", "🥉")
    lines = []
    for index, (user_id, xp, level) in enumerate(top):
        prefix = medals[index] if index < 3 else f"#{index + 1}"
        lines.append(f"{prefix} <@{user_id}> — اللفل **{level}** ({xp} XP)")
    await ctx.send(embed=discord.Embed(title="🏆 المتصدرون", description="\n".join(lines), color=discord.Color.gold()))


@bot.hybrid_command(name="تعديل_خبرة", aliases=["ضبط_خبرة_عضو"], description="زيادة أو إنقاص خبرة عضو يدوياً (استخدم رقم سالب للنقصان)")
@staff_only()
@commands.guild_only()
async def adjust_member_xp(ctx: commands.Context, member: discord.Member, amount: int) -> None:
    """!تعديل_خبرة @العضو 100   (أو -100 للنقصان)"""
    if amount == 0:
        await ctx.send("❌ حدد كمية خبرة غير صفرية (موجبة للزيادة أو سالبة للنقصان).")
        return
    new_level, new_xp = await db_call(db.add_xp_delta, ctx.guild.id, member.id, amount)
    settings = await db_call(db.get_guild_settings, ctx.guild.id)
    excluded_roles = _level_json_list(settings, "level_excluded_role_ids_json")
    for level, role_id in await db_call(db.get_level_roles, ctx.guild.id):
        if level <= new_level and role_id not in excluded_roles:
            role = ctx.guild.get_role(role_id)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="تعديل خبرة يدوي")
                except discord.Forbidden:
                    pass
    sign = "➕" if amount > 0 else "➖"
    await ctx.send(embed=discord.Embed(description=f"{sign} تم تعديل خبرة {member.mention} بمقدار **{amount:+d}**.\nالآن: اللفل **{new_level}** ({new_xp} XP).", color=discord.Color.blurple()))


@bot.hybrid_command(name="نقل_خبرة", description="ينقل كل خبرة/لفل من حساب قديم (مثلاً محظور) إلى حساب جديد")
@staff_only()
@commands.guild_only()
async def transfer_member_xp(ctx: commands.Context, old_account: discord.User, new_member: discord.Member) -> None:
    """!نقل_خبرة الايدي_او_المنشن_القديم @الحساب_الجديد
    يفيد عندما يُحظر حساب عضو ويصنع حساباً جديداً، فينقل تعبه السابق بدل ضياعه."""
    if old_account.id == new_member.id:
        await ctx.send("❌ لا يمكن النقل لنفس الحساب.")
        return
    old_xp, old_level = await db_call(db.get_user_level, ctx.guild.id, old_account.id)
    if old_xp == 0 and old_level == 0:
        await ctx.send(f"❌ لا توجد خبرة مسجّلة للحساب {old_account.mention} في هذا السيرفر.")
        return
    new_level, new_xp = await db_call(db.transfer_xp, ctx.guild.id, old_account.id, new_member.id)
    for level, role_id in await db_call(db.get_level_roles, ctx.guild.id):
        if level <= new_level:
            role = ctx.guild.get_role(role_id)
            if role and role not in new_member.roles:
                try:
                    await new_member.add_roles(role, reason="نقل خبرة من حساب قديم")
                except discord.Forbidden:
                    pass
    await ctx.send(embed=discord.Embed(description=f"✅ تم نقل كامل خبرة {old_account.mention} إلى {new_member.mention}.\nرصيد {new_member.mention} الآن: اللفل **{new_level}** ({new_xp} XP).\nتم تصفير رصيد الحساب القديم.", color=discord.Color.green()))


# ============================================================
# نظام الحماية من التخريب (Anti-Nuke)
# ============================================================
# هذا القسم كله أوامر تحكم بنظام antinuke.py (الملف المنفصل الذي يراقب الأحداث
# الفعلية). كل أمر هنا لا يفعل شيء بنفسه غير قراءة/كتابة إعداد بقاعدة البيانات؛
# المنطق الحقيقي (الكشف والعقاب والاسترجاع) موجود بأحداث discord.py المسجّلة
# فوق (on_guild_channel_create/update/delete, on_guild_role_create/update,
# on_member_join/remove/ban) والتي تستدعي دوال antinuke.py مع كل حدث جديد.
#
# نفس هذي الإعدادات بالضبط قابلة للتعديل من تبويب "الحماية من التخريب" بلوحة
# التحكم (dashboard/templates/tabs/antinuke.html) لأنها تكتب على نفس قاعدة
# البيانات مباشرة — فالأوامر هنا واللوحة وجهان لنفس البيانات، أيهما تستخدم
# ينعكس على البوت فوراً بدون فرق.

@bot.hybrid_command(name="تفعيل_الحماية", description="تفعيل نظام الحماية من التخريب (فلتر أسماء الرومات، حماية الرتب، طرد البوتات المشبوهة...)")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def enable_antinuke(ctx: commands.Context) -> None:
    # يشغّل antinuke_enabled=True فقط؛ لا يضبط أي حدود أو كلمات ممنوعة تلقائياً،
    # فلازم يضيفها الأدمن بنفسه (بالأوامر تحت أو من اللوحة) بعد التفعيل.
    db.set_guild_setting(ctx.guild.id, "antinuke_enabled", True)
    await ctx.send("🛡️ تم تفعيل نظام الحماية من التخريب.")


@bot.hybrid_command(name="تعطيل_الحماية")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def disable_antinuke(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "antinuke_enabled", False)
    await ctx.send("✅ تم تعطيل نظام الحماية من التخريب.")


@bot.hybrid_command(name="عقوبة_الحماية", description="اختر ماذا يحدث للفاعل عند اكتشاف تخريب")
@app_commands.choices(punishment=[
    app_commands.Choice(name="طرد", value="kick"),
    app_commands.Choice(name="حظر", value="ban"),
    app_commands.Choice(name="سحب كل الرتب", value="remove_roles"),
    app_commands.Choice(name="تايم أوت ساعة", value="timeout"),
])
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def set_antinuke_punishment(ctx: commands.Context, punishment: str) -> None:
    """يضبط ماذا يحدث لأي فاعل يثبت اكتشافه (كلمة ممنوعة، صلاحية خطيرة، أو
    تجاوز حدود المعدّل). القيمة تُقرأ لاحقاً بدالة antinuke.punish() مع كل عقوبة."""
    db.set_guild_setting(ctx.guild.id, "antinuke_punishment", punishment)
    labels = {"kick": "طرد", "ban": "حظر", "remove_roles": "سحب كل الرتب", "timeout": "تايم أوت ساعة"}
    await ctx.send(f"✅ عقوبة الحماية الآن: **{labels.get(punishment, punishment)}**.")


@bot.command(name="اضافة_كلمة_ممنوعة", description="كلمة إذا وُجدت باسم روم (عند إنشائه أو تغييره)، يُرجَّع الاسم تلقائياً ويُعاقَب الفاعل")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def add_banned_word(ctx: commands.Context, *, word: str) -> None:
    """يضيف كلمة لقائمة antinuke_banned_words_json (قائمة JSON محفوظة بإعدادات
    السيرفر). المطابقة عند الفحص "تحتوي" وليست "تساوي بالضبط" (مثلاً كلمة
    ممنوعة "نيوك" تطابق اسم روم "نيوك-هنا-الآن" أيضاً) — انظر antinuke.contains_banned_word.
    """
    settings = db.get_guild_settings(ctx.guild.id)
    words = antinuke.load_json_list(settings, "antinuke_banned_words_json")
    word = word.strip().lower()
    if word in words:
        await ctx.send("⚠️ الكلمة موجودة بالفعل بالقائمة.")
        return
    words.append(word)
    db.set_guild_setting(ctx.guild.id, "antinuke_banned_words_json", json.dumps(words, ensure_ascii=False))
    await ctx.send(f"✅ أُضيفت `{word}` لقائمة الكلمات الممنوعة بأسماء الرومات.")


@bot.command(name="حذف_كلمة_ممنوعة")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def remove_banned_word(ctx: commands.Context, *, word: str) -> None:
    settings = db.get_guild_settings(ctx.guild.id)
    words = antinuke.load_json_list(settings, "antinuke_banned_words_json")
    word = word.strip().lower()
    if word not in words:
        await ctx.send("❌ الكلمة غير موجودة بالقائمة.")
        return
    words.remove(word)
    db.set_guild_setting(ctx.guild.id, "antinuke_banned_words_json", json.dumps(words, ensure_ascii=False))
    await ctx.send(f"✅ حُذفت `{word}` من قائمة الكلمات الممنوعة.")


@bot.command(name="الكلمات_الممنوعة")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def list_banned_words(ctx: commands.Context) -> None:
    settings = db.get_guild_settings(ctx.guild.id)
    words = antinuke.load_json_list(settings, "antinuke_banned_words_json")
    await ctx.send("الكلمات الممنوعة: " + (", ".join(f"`{w}`" for w in words) if words else "لا توجد كلمات مضافة."))


@bot.hybrid_command(name="اضافة_صلاحية_خطيرة", description="صلاحية إذا وُجدت برتبة جديدة أو أُضيفت لرتبة موجودة، تُحذف الرتبة/تُرجَّع صلاحياتها تلقائياً ويُعاقَب الفاعل")
@app_commands.choices(permission=[
    app_commands.Choice(name=name, value=name) for name in [
        "administrator", "ban_members", "kick_members", "manage_guild", "manage_roles",
        "manage_channels", "manage_webhooks", "mention_everyone", "manage_messages", "moderate_members",
    ]
])
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def add_dangerous_permission(ctx: commands.Context, permission: str) -> None:
    """يضيف اسم صلاحية ديسكورد لقائمة antinuke_dangerous_perms_json. القيمة
    يجب أن تطابق اسم خاصية discord.Permissions بالضبط (بحروف صغيرة) لأن
    antinuke.dangerous_permissions_present() تستخدم getattr(permissions, name)
    مباشرة على الاسم المحفوظ — نفس القائمة الثابتة تظهر كخيارات Checkbox
    بتبويب الحماية باللوحة (dashboard/app.py: ANTINUKE_PERMISSION_CHOICES)."""
    settings = db.get_guild_settings(ctx.guild.id)
    perms = antinuke.load_json_list(settings, "antinuke_dangerous_perms_json")
    permission = permission.strip().lower()
    if permission in perms:
        await ctx.send("⚠️ هذي الصلاحية موجودة بالقائمة بالفعل.")
        return
    perms.append(permission)
    db.set_guild_setting(ctx.guild.id, "antinuke_dangerous_perms_json", json.dumps(perms))
    await ctx.send(f"✅ أُضيفت `{permission}` لقائمة الصلاحيات الخطيرة المراقَبة.")


@bot.command(name="حذف_صلاحية_خطيرة")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def remove_dangerous_permission(ctx: commands.Context, permission: str) -> None:
    settings = db.get_guild_settings(ctx.guild.id)
    perms = antinuke.load_json_list(settings, "antinuke_dangerous_perms_json")
    permission = permission.strip().lower()
    if permission not in perms:
        await ctx.send("❌ هذي الصلاحية غير موجودة بالقائمة.")
        return
    perms.remove(permission)
    db.set_guild_setting(ctx.guild.id, "antinuke_dangerous_perms_json", json.dumps(perms))
    await ctx.send(f"✅ حُذفت `{permission}` من قائمة الصلاحيات الخطيرة.")


@bot.command(name="الصلاحيات_الخطيرة")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def list_dangerous_permissions(ctx: commands.Context) -> None:
    settings = db.get_guild_settings(ctx.guild.id)
    perms = antinuke.load_json_list(settings, "antinuke_dangerous_perms_json")
    await ctx.send("الصلاحيات المراقَبة: " + (", ".join(f"`{p}`" for p in perms) if perms else "لا توجد."))


@bot.command(name="استثناء_عضو", description="استثناء عضو من عقوبات نظام الحماية (مثل الأدمن الموثوقين)")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def whitelist_member(ctx: commands.Context, member: discord.Member) -> None:
    # مهم جداً: بدون استثناء الأدمن الموثوقين هنا، أي أدمن يطرد/يحظر عدة أعضاء
    # مشاغبين خلال وقت قصير (استخدام طبيعي تماماً لعمله) ممكن يُعاقَب هو نفسه
    # بالخطأ من نظام الحماية. مالك السيرفر مستثنى تلقائياً دائماً (لا يحتاج إضافة).
    settings = db.get_guild_settings(ctx.guild.id)
    whitelist = antinuke.load_json_list(settings, "antinuke_whitelist_json")
    if member.id in whitelist:
        await ctx.send("⚠️ هذا العضو مستثنى بالفعل.")
        return
    whitelist.append(member.id)
    db.set_guild_setting(ctx.guild.id, "antinuke_whitelist_json", json.dumps(whitelist))
    await ctx.send(f"✅ {member.mention} صار مستثنى من عقوبات نظام الحماية.")


@bot.command(name="الغاء_استثناء_عضو")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def unwhitelist_member(ctx: commands.Context, member: discord.Member) -> None:
    settings = db.get_guild_settings(ctx.guild.id)
    whitelist = antinuke.load_json_list(settings, "antinuke_whitelist_json")
    if member.id not in whitelist:
        await ctx.send("❌ هذا العضو غير مستثنى أصلاً.")
        return
    whitelist.remove(member.id)
    db.set_guild_setting(ctx.guild.id, "antinuke_whitelist_json", json.dumps(whitelist))
    await ctx.send(f"✅ أُزيل {member.mention} من قائمة الاستثناءات.")


@bot.command(name="اضافة_بوت_موثوق", description="السماح لبوت معين بالدخول بدون طرد تلقائي")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def whitelist_bot(ctx: commands.Context, bot_id: str) -> None:
    if not bot_id.isdigit():
        await ctx.send("❌ آيدي غير صحيح.")
        return
    settings = db.get_guild_settings(ctx.guild.id)
    allowed = antinuke.load_json_list(settings, "antinuke_bot_whitelist_json")
    bot_id_int = int(bot_id)
    if bot_id_int in allowed:
        await ctx.send("⚠️ هذا البوت موثوق بالفعل.")
        return
    allowed.append(bot_id_int)
    db.set_guild_setting(ctx.guild.id, "antinuke_bot_whitelist_json", json.dumps(allowed))
    await ctx.send(f"✅ صار البوت `{bot_id}` موثوقاً ولن يُطرَد تلقائياً.")


@bot.command(name="حدود_الحماية", description="اضبط كم فعل خلال كم ثانية يُعتبر نمط تخريب مشبوه")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def set_antinuke_thresholds(ctx: commands.Context, max_channel_create: int = 5, max_channel_delete: int = 3, max_kicks: int = 3, max_bans: int = 3, window_seconds: int = 10) -> None:
    """يضبط "كم فعل خلال كم ثانية" يُعتبر نمط تخريب. مثال: max_kicks=5 و
    window_seconds=300 (٥ دقائق) يعني: أي عضو يطرد ٥ أشخاص أو أكثر خلال ٥
    دقائق تُطبَّق عليه العقوبة. نفس القيم بالضبط قابلة للتعديل من تبويب الحماية
    باللوحة (تُدخِل هناك "دقائق" وتتحول لثوانٍ تلقائياً قبل الحفظ)."""
    db.set_guild_setting(ctx.guild.id, "antinuke_max_channel_create", max(1, max_channel_create))
    db.set_guild_setting(ctx.guild.id, "antinuke_max_channel_delete", max(1, max_channel_delete))
    db.set_guild_setting(ctx.guild.id, "antinuke_max_kicks", max(1, max_kicks))
    db.set_guild_setting(ctx.guild.id, "antinuke_max_bans", max(1, max_bans))
    db.set_guild_setting(ctx.guild.id, "antinuke_window_seconds", max(3, window_seconds))
    await ctx.send("✅ تم تحديث حدود الحماية.")


@bot.hybrid_command(name="تفعيل_فلتر_التصيد", description="حذف رسائل تحتوي روابط تصيّد معروفة (نيترو مزيف، ستيم مزيف...) تلقائياً")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def enable_antiphishing(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "antiphishing_enabled", True)
    await ctx.send("🎣 تم تفعيل فلتر روابط التصيّد.")


@bot.hybrid_command(name="تعطيل_فلتر_التصيد")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def disable_antiphishing(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "antiphishing_enabled", False)
    await ctx.send("✅ تم تعطيل فلتر روابط التصيّد.")


@bot.hybrid_command(name="اجراء_فلتر_التصيد", description="ماذا يحدث لمن يرسل رابط تصيّد؟")
@app_commands.choices(action=[
    app_commands.Choice(name="حذف الرسالة فقط", value="delete"),
    app_commands.Choice(name="حذف + تايم أوت ساعة", value="timeout"),
    app_commands.Choice(name="حذف + طرد", value="kick"),
    app_commands.Choice(name="حذف + حظر", value="ban"),
])
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def set_antiphishing_action(ctx: commands.Context, action: str) -> None:
    db.set_guild_setting(ctx.guild.id, "antiphishing_action", action)
    labels = {"delete": "حذف الرسالة فقط", "timeout": "حذف + تايم أوت", "kick": "حذف + طرد", "ban": "حذف + حظر"}
    await ctx.send(f"✅ إجراء فلتر التصيّد الآن: **{labels.get(action, action)}**.")


@bot.command(name="اضافة_نطاق_تصيد", description="أضف نطاقاً مشبوهاً إضافياً فوق القائمة المدمجة بالبوت")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def add_phishing_domain(ctx: commands.Context, domain: str) -> None:
    settings = db.get_guild_settings(ctx.guild.id)
    domains = antinuke.load_json_list(settings, "antiphishing_domains_json")
    domain = domain.strip().lower().removeprefix("http://").removeprefix("https://").split("/")[0]
    if domain in domains:
        await ctx.send("⚠️ هذا النطاق مضاف بالفعل.")
        return
    domains.append(domain)
    db.set_guild_setting(ctx.guild.id, "antiphishing_domains_json", json.dumps(domains))
    await ctx.send(f"✅ أُضيف `{domain}` لقائمة نطاقات التصيّد المراقَبة.")


@bot.command(name="حذف_نطاق_تصيد")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def remove_phishing_domain(ctx: commands.Context, domain: str) -> None:
    settings = db.get_guild_settings(ctx.guild.id)
    domains = antinuke.load_json_list(settings, "antiphishing_domains_json")
    domain = domain.strip().lower()
    if domain not in domains:
        await ctx.send("❌ هذا النطاق غير موجود بالقائمة المخصصة (لاحظ: القائمة المدمجة بالكود لا يمكن حذفها بأمر).")
        return
    domains.remove(domain)
    db.set_guild_setting(ctx.guild.id, "antiphishing_domains_json", json.dumps(domains))
    await ctx.send(f"✅ حُذف `{domain}`.")


@bot.command(name="حالة_الحماية")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def antinuke_status(ctx: commands.Context) -> None:
    settings = db.get_guild_settings(ctx.guild.id)
    enabled = antinuke.is_enabled(settings)
    punishment_labels = {"kick": "طرد", "ban": "حظر", "remove_roles": "سحب كل الرتب", "timeout": "تايم أوت ساعة"}
    embed = discord.Embed(title="🛡️ حالة نظام الحماية من التخريب", color=discord.Color.blurple() if enabled else discord.Color.greyple())
    embed.add_field(name="الحالة", value="🟢 مفعّل" if enabled else "🔴 معطّل", inline=True)
    embed.add_field(name="العقوبة", value=punishment_labels.get(settings.get("antinuke_punishment", "kick"), "-"), inline=True)
    embed.add_field(name="الحدود", value=f"إنشاء رومات: {settings.get('antinuke_max_channel_create')}/{settings.get('antinuke_window_seconds')}ث\nحذف رومات: {settings.get('antinuke_max_channel_delete')}/{settings.get('antinuke_window_seconds')}ث\nطرد: {settings.get('antinuke_max_kicks')}/{settings.get('antinuke_window_seconds')}ث\nحظر: {settings.get('antinuke_max_bans')}/{settings.get('antinuke_window_seconds')}ث", inline=False)
    words = antinuke.load_json_list(settings, "antinuke_banned_words_json")
    perms = antinuke.load_json_list(settings, "antinuke_dangerous_perms_json")
    whitelist = antinuke.load_json_list(settings, "antinuke_whitelist_json")
    embed.add_field(name="الكلمات الممنوعة", value=str(len(words)), inline=True)
    embed.add_field(name="الصلاحيات المراقَبة", value=str(len(perms)), inline=True)
    embed.add_field(name="الأعضاء المستثنون", value=str(len(whitelist)), inline=True)
    phishing_enabled = antinuke.is_phishing_enabled(settings)
    phishing_domains = antinuke.load_json_list(settings, "antiphishing_domains_json")
    action_labels = {"delete": "حذف فقط", "timeout": "حذف + تايم أوت", "kick": "حذف + طرد", "ban": "حذف + حظر"}
    embed.add_field(
        name="🎣 فلتر التصيّد",
        value=f"{'🟢 مفعّل' if phishing_enabled else '🔴 معطّل'} — الإجراء: {action_labels.get(settings.get('antiphishing_action', 'delete'), '-')}\nنطاقات مخصصة إضافية: {len(phishing_domains)}",
        inline=False,
    )
    await ctx.send(embed=embed)


# ============================================================
# الحماية من الغارات الجماعية (Anti-Raid) — ميزة من بوتات Wick/Dyno/Vexera
# ============================================================
# تكشف انضمام عدد كبير من الأعضاء خلال وقت قصير (غارة منظّمة)، وتتدخل تلقائياً
# برفع مستوى التحقق للحد الأقصى مؤقتاً + طرد/حظر من انضم أثناء الغارة. المنطق
# الفعلي بدالة on_member_join و trigger_raid_lockdown/apply_raid_action أعلى
# بالملف؛ الأوامر هنا فقط لضبط الإعدادات (وقابلة للتعديل من نفس تبويب الحماية
# باللوحة لاحقاً، بما أنها كلها مفاتيح عادية بجدول guild_settings).

@bot.hybrid_command(name="تفعيل_الحماية_من_الغارات", description="يكشف انضمام عدد كبير من الأعضاء خلال وقت قصير ويتدخل تلقائياً")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def enable_antiraid(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "antiraid_enabled", True)
    await ctx.send("🚨 تم تفعيل الحماية من الغارات الجماعية.")


@bot.hybrid_command(name="تعطيل_الحماية_من_الغارات")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def disable_antiraid(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "antiraid_enabled", False)
    await ctx.send("✅ تم تعطيل الحماية من الغارات الجماعية.")


@bot.hybrid_command(name="ضبط_الحماية_من_الغارات", description="كم عضو خلال كم ثانية يُعتبر غارة، وماذا يحدث لهم")
@app_commands.choices(action=[
    app_commands.Choice(name="طرد المنضمين أثناء الغارة", value="kick_new"),
    app_commands.Choice(name="حظر المنضمين أثناء الغارة", value="ban_new"),
    app_commands.Choice(name="قفل السيرفر فقط بدون طرد أحد", value="lockdown_only"),
])
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def set_antiraid_settings(ctx: commands.Context, max_joins: int = 10, window_seconds: int = 20, action: str = "kick_new", lockdown_minutes: int = 10) -> None:
    db.set_guild_setting(ctx.guild.id, "antiraid_max_joins", max(3, max_joins))
    db.set_guild_setting(ctx.guild.id, "antiraid_window_seconds", max(5, window_seconds))
    db.set_guild_setting(ctx.guild.id, "antiraid_action", action)
    db.set_guild_setting(ctx.guild.id, "antiraid_lockdown_minutes", max(1, lockdown_minutes))
    await ctx.send("✅ تم تحديث إعدادات الحماية من الغارات.")


# ============================================================
# الحماية من الحسابات الحديثة (Anti-Alt)
# ============================================================

@bot.hybrid_command(name="تفعيل_حظر_الحسابات_الحديثة", description="يمنع/يطرد الحسابات المُنشأة حديثاً جداً بديسكورد (وقاية من الحسابات المزيفة)")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def enable_antialt(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "antialt_enabled", True)
    await ctx.send("🛡️ تم تفعيل حظر الحسابات الحديثة جداً.")


@bot.hybrid_command(name="تعطيل_حظر_الحسابات_الحديثة")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def disable_antialt(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "antialt_enabled", False)
    await ctx.send("✅ تم تعطيل حظر الحسابات الحديثة.")


@bot.hybrid_command(name="ضبط_عمر_الحساب", description="أقل عمر حساب مسموح بالانضمام (بالأيام)، وماذا يحدث لمن هو أصغر")
@app_commands.choices(action=[
    app_commands.Choice(name="طرد", value="kick"),
    app_commands.Choice(name="حظر", value="ban"),
])
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def set_antialt_settings(ctx: commands.Context, min_age_days: int = 7, action: str = "kick") -> None:
    db.set_guild_setting(ctx.guild.id, "antialt_min_age_days", max(0, min_age_days))
    db.set_guild_setting(ctx.guild.id, "antialt_action", action)
    await ctx.send(f"✅ الحد الأدنى لعمر الحساب الآن: {min_age_days} يوم.")


# ============================================================
# الرتب اللاصقة (Sticky Roles)
# ============================================================

@bot.hybrid_command(name="تفعيل_الرتب_اللاصقة", description="تُعاد رتب العضو تلقائياً لو غادر السيرفر ثم رجع (يمنع الهروب من عقوبة الكتم بالمغادرة والعودة)")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def enable_sticky_roles(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "sticky_roles_enabled", True)
    await ctx.send("✅ تم تفعيل الرتب اللاصقة.")


@bot.hybrid_command(name="تعطيل_الرتب_اللاصقة")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def disable_sticky_roles(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "sticky_roles_enabled", False)
    await ctx.send("✅ تم تعطيل الرتب اللاصقة.")


# ============================================================
# الحماية من سبام المنشن الجماعي
# ============================================================

@bot.hybrid_command(name="تفعيل_حماية_المنشن", description="حذف/عقاب من يمنشن عدداً كبيراً من الأعضاء برسالة واحدة")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def enable_antispam_mention(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "antispam_mention_enabled", True)
    await ctx.send("✅ تم تفعيل الحماية من سبام المنشن.")


@bot.hybrid_command(name="تعطيل_حماية_المنشن")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def disable_antispam_mention(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "antispam_mention_enabled", False)
    await ctx.send("✅ تم تعطيل الحماية من سبام المنشن.")


@bot.hybrid_command(name="ضبط_حماية_المنشن", description="كم منشن برسالة واحدة يُعتبر سبام، وماذا يحدث للمرسل")
@app_commands.choices(action=[
    app_commands.Choice(name="حذف الرسالة فقط", value="delete_only"),
    app_commands.Choice(name="حذف + تايم أوت", value="timeout"),
    app_commands.Choice(name="حذف + طرد", value="kick"),
])
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def set_antispam_mention_settings(ctx: commands.Context, max_mentions: int = 6, action: str = "timeout") -> None:
    db.set_guild_setting(ctx.guild.id, "antispam_max_mentions", max(2, max_mentions))
    db.set_guild_setting(ctx.guild.id, "antispam_action", action)
    await ctx.send(f"✅ الحد الأقصى للمنشن بالرسالة الواحدة الآن: {max_mentions}.")


# ============================================================
# لوحة النجوم (Starboard)
# ============================================================

@bot.hybrid_command(name="ضبط_لوحة_النجوم", description="أي رسالة تحصل على عدد كافٍ من تفاعل ⭐ تُنشر تلقائياً بالقناة المحددة")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def set_starboard(ctx: commands.Context, channel: discord.TextChannel, threshold: int = 3, emoji: str = "⭐") -> None:
    db.set_guild_setting(ctx.guild.id, "starboard_enabled", True)
    db.set_guild_setting(ctx.guild.id, "starboard_channel_id", channel.id)
    db.set_guild_setting(ctx.guild.id, "starboard_threshold", max(1, threshold))
    db.set_guild_setting(ctx.guild.id, "starboard_emoji", emoji)
    await ctx.send(f"✅ لوحة النجوم مفعّلة الآن بقناة {channel.mention} (الحد: {threshold} {emoji}).")


@bot.hybrid_command(name="تعطيل_لوحة_النجوم")
@commands.has_permissions(administrator=True)
@commands.guild_only()
async def disable_starboard(ctx: commands.Context) -> None:
    db.set_guild_setting(ctx.guild.id, "starboard_enabled", False)
    await ctx.send("✅ تم تعطيل لوحة النجوم.")


# ============================================================
# المسابقات (Giveaways) — ميزة شهيرة من بوتات مثل MEE6/ProBot
# ============================================================

@bot.hybrid_command(name="مسابقة", description="أنشئ مسابقة: !مسابقة 1h 1 نيترو مجاني")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def create_giveaway_command(ctx: commands.Context, duration: str, winners: int, *, prize: str) -> None:
    """!مسابقة المدة عدد_الفائزين الجائزة
    أمثلة على المدة: 30s (30 ثانية)، 10m (10 دقائق)، 2h (ساعتين)، 1d (يوم).
    الأعضاء يشاركون بالضغط على 🎉 على رسالة المسابقة، والسحب تلقائي عند
    انتهاء الوقت (تفحصه مهمة دورية كل دقيقة، تعمل حتى لو أُعيد تشغيل البوت)."""
    seconds = parse_duration(duration)
    if seconds is None or seconds < 10:
        await ctx.send("❌ صيغة المدة غير صحيحة. أمثلة: `30s`، `10m`، `2h`، `1d`.")
        return
    if seconds > 30 * 86400:
        await ctx.send("❌ أقصى مدة مسموحة للمسابقة 30 يوماً.")
        return
    if winners < 1 or winners > 20:
        await ctx.send("❌ عدد الفائزين يجب أن يكون بين 1 و20.")
        return
    prize = prize.strip()[:200]
    if not prize:
        await ctx.send("❌ اكتب اسم الجائزة.")
        return
    ends_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    fake_giveaway = {"prize": prize, "winners_count": winners, "ends_at": ends_at.isoformat()}
    embed = build_giveaway_embed(fake_giveaway, ended=False)
    embed.set_footer(text=f"بواسطة {ctx.author.display_name} • رقم المسابقة يظهر بعد النشر")
    message = await ctx.send(embed=embed)
    await message.add_reaction("🎉")
    giveaway_id = await db_call(db.create_giveaway, ctx.guild.id, ctx.channel.id, message.id, prize, winners, ctx.author.id, ends_at.isoformat())
    # نحدّث الفوتر برقم المسابقة الحقيقي بعد إنشائها، يفيد لاحقاً بأوامر
    # الإنهاء المبكر/الحذف/إعادة السحب (تستخدم معرّف الرسالة، لكن رقم
    # المسابقة الداخلي مفيد للمتابعة من لوحة التحكم مستقبلاً).
    try:
        embed.set_footer(text=f"بواسطة {ctx.author.display_name} • رقم المسابقة #{giveaway_id}")
        await message.edit(embed=embed)
    except discord.HTTPException:
        pass


@bot.hybrid_command(name="اعادة_سحب_مسابقة", description="يسحب فائزاً جديداً لمسابقة انتهت بالفعل")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def reroll_giveaway_command(ctx: commands.Context, message_id: str) -> None:
    try:
        target_message_id = int(message_id)
    except ValueError:
        await ctx.send("❌ معرّف الرسالة غير صحيح.")
        return
    # مهم: get_giveaway_by_message تعيد channel_id الحقيقي المخزَّن بقاعدة
    # البيانات، ولا نستبدله بقناة تنفيذ هذا الأمر — قد يكون الأدمن يشغّل
    # الأمر من قناة إدارية مختلفة تماماً عن قناة المسابقة الأصلية.
    giveaway = await db_call(db.get_giveaway_by_message, ctx.guild.id, target_message_id)
    if not giveaway or not giveaway.get("ended"):
        await ctx.send("❌ لم أجد مسابقة منتهية بهذا المعرّف. (لازم تكون المسابقة انتهت فعلاً حتى تقدر تعيد السحب)")
        return
    winners = await draw_giveaway_winners(giveaway)
    if not winners:
        await ctx.send("😕 ما فيه مشاركين لإعادة السحب منهم.")
        return
    mentions = "، ".join(winner.mention for winner in winners)
    channel = ctx.guild.get_channel(giveaway["channel_id"])
    target = channel if isinstance(channel, discord.TextChannel) else ctx.channel
    await target.send(f"🎉 فائز جديد بإعادة السحب: {mentions} — الجائزة: **{giveaway['prize']}**", allowed_mentions=ALLOWED_MENTIONS)
    if target != ctx.channel:
        await ctx.send(f"✅ تم إعلان الفائز الجديد بقناة {target.mention}.")


@bot.hybrid_command(name="انهاء_مسابقة", description="ينهي مسابقة فوراً قبل موعدها ويسحب الفائزين الآن")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def end_giveaway_early_command(ctx: commands.Context, message_id: str) -> None:
    try:
        target_message_id = int(message_id)
    except ValueError:
        await ctx.send("❌ معرّف الرسالة غير صحيح.")
        return
    giveaway = await db_call(db.get_giveaway_by_message, ctx.guild.id, target_message_id)
    if not giveaway or giveaway.get("ended"):
        await ctx.send("❌ لم أجد مسابقة نشطة بهذا المعرّف (إما انتهت بالفعل أو المعرّف غير صحيح).")
        return
    await finish_giveaway(giveaway)
    await ctx.send("✅ تم إنهاء المسابقة وسحب الفائزين فوراً.")


@bot.hybrid_command(name="حذف_مسابقة", description="يلغي مسابقة نهائياً بدون سحب أي فائز (يحذفها من القائمة فقط)")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def delete_giveaway_command(ctx: commands.Context, message_id: str) -> None:
    try:
        target_message_id = int(message_id)
    except ValueError:
        await ctx.send("❌ معرّف الرسالة غير صحيح.")
        return
    giveaway = await db_call(db.get_giveaway_by_message, ctx.guild.id, target_message_id)
    if not giveaway:
        await ctx.send("❌ لم أجد مسابقة بهذا المعرّف.")
        return
    await db_call(db.delete_giveaway, giveaway["id"])
    channel = ctx.guild.get_channel(giveaway["channel_id"])
    if isinstance(channel, discord.TextChannel):
        try:
            message = await channel.fetch_message(target_message_id)
            cancelled_embed = discord.Embed(title="🎉 أُلغيت المسابقة", description=f"**الجائزة:** {giveaway['prize']}\n\n🚫 ألغاها أحد المشرفين.", color=discord.Color.greyple())
            await message.edit(embed=cancelled_embed)
        except (discord.NotFound, discord.Forbidden):
            pass
    await ctx.send("✅ أُلغيت المسابقة نهائياً بدون إعلان أي فائز.")


@bot.hybrid_command(name="المسابقات_النشطة", description="يعرض كل المسابقات الجارية حالياً بهذا السيرفر")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def list_active_giveaways_command(ctx: commands.Context) -> None:
    active = await db_call(db.get_active_giveaways, ctx.guild.id)
    if not active:
        await ctx.send("لا توجد مسابقات نشطة حالياً.")
        return
    lines = []
    for item in active:
        ends_at = datetime.fromisoformat(item["ends_at"])
        lines.append(f"🎉 **{item['prize']}** — تنتهي <t:{int(ends_at.timestamp())}:R> — معرّف: `{item['message_id']}`")
    await ctx.send(embed=discord.Embed(title="المسابقات النشطة", description="\n".join(lines), color=discord.Color.gold()))


# ============================================================
# الرولات الذاتية (اضغط إيموجي ⇐ تحصل على رتبة)
# ============================================================

def emoji_key(raw: str) -> str:
    """يوحّد صيغة أي إيموجي (يونيكود من الهاتف أو مخصص من السيرفر) إلى نص ثابت
    يُستخدم كمفتاح تخزين ومطابقة، حتى تتطابق القيمة المحفوظة مع ما يصل من حدث التفاعل."""
    parsed = discord.PartialEmoji.from_str(raw.strip())
    return str(parsed)


@bot.command(name="انشاء_رولات_تفاعليه", aliases=["رسالة_رولات"], description="ينشئ رسالة يضغط عليها الأعضاء لأخذ رتبة")
@staff_only()
@commands.guild_only()
async def create_reaction_roles_message(ctx: commands.Context, *, data: str) -> None:
    """!انشاء_رولات_تفاعليه العنوان | الوصف
    بعدها استخدم `!اضافة_رول_تفاعلي` لربط كل إيموجي (من السيرفر أو الهاتف) برتبة."""
    parts = [part.strip() for part in data.split("|")]
    title = parts[0] if parts else "اختر رتبتك"
    description = parts[1] if len(parts) > 1 else "اضغط الإيموجي المناسب لأخذ الرتبة، واضغطه مرة أخرى لسحبها."
    embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
    message = await ctx.send(embed=embed)
    await ctx.send(f"✅ تم إنشاء الرسالة. معرّف الرسالة (message_id): `{message.id}`\nاستخدم الآن: `!اضافة_رول_تفاعلي {message.id} الإيموجي @الرتبة`", ephemeral=True)


@bot.command(name="اضافة_رول_تفاعلي", description="يربط إيموجي (من السيرفر أو الهاتف) برتبة على رسالة رولات تفاعلية")
@staff_only()
@commands.guild_only()
async def add_reaction_role_command(ctx: commands.Context, message_id: str, emoji: str, role: discord.Role) -> None:
    """!اضافة_رول_تفاعلي معرف_الرسالة الإيموجي @الرتبة"""
    try:
        target_message_id = int(message_id)
    except ValueError:
        await ctx.send("❌ معرّف الرسالة غير صحيح.")
        return
    target_message = None
    for channel in ctx.guild.text_channels:
        try:
            target_message = await channel.fetch_message(target_message_id)
            break
        except (discord.NotFound, discord.Forbidden):
            continue
    if target_message is None:
        await ctx.send("❌ لم أجد رسالة بهذا المعرّف في أي قناة نصية أستطيع الوصول إليها.")
        return
    if role >= ctx.guild.me.top_role:
        await ctx.send("❌ رتبتي أدنى من هذه الرتبة، ضع رتبة البوت أعلى منها في إعدادات السيرفر.")
        return
    parsed = parse_emoji(emoji)
    try:
        await target_message.add_reaction(parsed)
    except discord.HTTPException:
        await ctx.send("❌ تعذّر إضافة هذا الإيموجي. تأكد أنه إيموجي صحيح من هذا السيرفر أو إيموجي عادي.")
        return
    key = emoji_key(emoji)
    await db_call(db.add_reaction_role, ctx.guild.id, target_message.channel.id, target_message.id, key, role.id)
    await ctx.send(f"✅ الآن أي عضو يضغط {parsed} على الرسالة سيحصل على رتبة {role.mention}.")


@bot.command(name="حذف_رول_تفاعلي", description="يفك ربط إيموجي برتبة على رسالة رولات تفاعلية")
@staff_only()
@commands.guild_only()
async def remove_reaction_role_command(ctx: commands.Context, message_id: str, emoji: str) -> None:
    try:
        target_message_id = int(message_id)
    except ValueError:
        await ctx.send("❌ معرّف الرسالة غير صحيح.")
        return
    key = emoji_key(emoji)
    removed = await db_call(db.remove_reaction_role, ctx.guild.id, target_message_id, key)
    if removed:
        await ctx.send("✅ تم فك الربط.")
    else:
        await ctx.send("❌ لم أجد ربطاً بهذه المواصفات.")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    if payload.guild_id is None:
        return
    await handle_starboard_reaction(payload)
    if payload.member is None or payload.member.bot:
        return
    row = await db_call(db.get_reaction_role, payload.guild_id, payload.message_id, str(payload.emoji))
    if not row:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    role = guild.get_role(int(row["role_id"]))
    if role is None:
        return
    try:
        await payload.member.add_roles(role, reason="رول تفاعلي ذاتي")
    except discord.Forbidden:
        pass


async def handle_starboard_reaction(payload: discord.RawReactionActionEvent) -> None:
    """لوحة النجوم (Starboard): تُستدعى مع كل إضافة/إزالة تفاعل بالسيرفر (من
    كلا الحدثين add/remove)، وتتحقق فقط لو الإيموجي يطابق إيموجي الستاربورد
    المضبوط. نعيد حساب عدد التفاعلات *الفعلي* من الرسالة نفسها (مو عداد يدوي
    تراكمي) لتجنّب أي تزامن خاطئ لو حد أضاف وأزال تفاعله عدة مرات."""
    settings = await cached_guild_settings(payload.guild_id)
    if not bool(settings.get("starboard_enabled")):
        return
    configured_emoji = str(settings.get("starboard_emoji") or "⭐")
    if str(payload.emoji) != configured_emoji and str(payload.emoji.name) != configured_emoji:
        return
    starboard_channel_id = settings.get("starboard_channel_id")
    if not starboard_channel_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    starboard_channel = safe_channel(guild, int(starboard_channel_id))
    if not isinstance(starboard_channel, discord.TextChannel):
        return
    source_channel = guild.get_channel(payload.channel_id)
    if not isinstance(source_channel, discord.TextChannel) or source_channel.id == starboard_channel.id:
        return  # يمنع تحويل قناة الستاربورد نفسها إلى مصدر (حلقة لا نهائية محتملة)
    try:
        original_message = await source_channel.fetch_message(payload.message_id)
    except (discord.NotFound, discord.Forbidden):
        return

    star_count = 0
    for reaction in original_message.reactions:
        if str(reaction.emoji) == configured_emoji or str(getattr(reaction.emoji, "name", "")) == configured_emoji:
            star_count = reaction.count
            break

    threshold = int(settings.get("starboard_threshold", 3))
    entry = await db_call(db.get_starboard_entry, guild.id, original_message.id)

    if star_count < threshold:
        return  # لم يصل للحد بعد؛ لو كان منشوراً سابقاً ووصل لأقل من الحد، نتركه كما هو (لا نحذفه، حتى لا نضيّع أرشيف جيد بسبب إزالة نجمة واحدة)

    embed = discord.Embed(description=original_message.content or "*[رسالة بدون نص، شاهد المرفقات]*", color=discord.Color.gold(), timestamp=original_message.created_at)
    embed.set_author(name=original_message.author.display_name, icon_url=original_message.author.display_avatar.url)
    embed.add_field(name="القناة الأصلية", value=source_channel.mention, inline=True)
    embed.add_field(name="الرابط", value=f"[اذهب للرسالة]({original_message.jump_url})", inline=True)
    if original_message.attachments:
        embed.set_image(url=original_message.attachments[0].url)
    star_line = f"{configured_emoji} **{star_count}**"

    if entry:
        try:
            starboard_message = await starboard_channel.fetch_message(int(entry["starboard_message_id"]))
            await starboard_message.edit(content=star_line, embed=embed)
        except (discord.NotFound, discord.Forbidden):
            entry = None  # الرسالة القديمة اختفت، ننشر واحدة جديدة بدلها تحت
    if not entry:
        try:
            posted = await starboard_channel.send(content=star_line, embed=embed)
        except discord.Forbidden:
            return
        await db_call(db.save_starboard_entry, guild.id, original_message.id, posted.id, star_count)
    else:
        await db_call(db.save_starboard_entry, guild.id, original_message.id, int(entry["starboard_message_id"]), star_count)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent) -> None:
    if payload.guild_id is None:
        return
    await handle_starboard_reaction(payload)
    row = await db_call(db.get_reaction_role, payload.guild_id, payload.message_id, str(payload.emoji))
    if not row:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    member = guild.get_member(payload.user_id)
    if member is None or member.bot:
        return
    role = guild.get_role(int(row["role_id"]))
    if role is None:
        return
    try:
        await member.remove_roles(role, reason="سحب رول تفاعلي ذاتي")
    except discord.Forbidden:
        pass


# ============================================================
# الردود التلقائية (تريقر ⇐ رد جاهز)
# ============================================================

@bot.command(name="اضافة_رد_تلقائي", description="عند إرسال عبارة معينة، يرد البوت تلقائياً بنص جاهز")
@staff_only()
@commands.guild_only()
async def add_auto_response_command(ctx: commands.Context, match_type: str, *, data: str) -> None:
    """!اضافة_رد_تلقائي تطابق_تام السلام عليكم | وعليكم السلام ياهلا فيك يا {user} كيف حالك؟
    match_type: `تطابق_تام` (الرسالة تساوي العبارة تماماً) أو `يحتوي` (الرسالة تحتوي العبارة في أي مكان).
    استخدم {user} داخل الرد ليصير منشن للعضو تلقائياً."""
    normalized_match = "contains" if match_type.strip() in ("يحتوي", "contains") else "exact"
    parts = data.split("|", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        await ctx.send("❌ الصيغة: `!اضافة_رد_تلقائي تطابق_تام العبارة | نص الرد` (استخدم `{user}` في الرد لمنشن العضو).")
        return
    trigger, response = parts[0].strip(), parts[1].strip()
    response_id = await db_call(db.add_auto_response, ctx.guild.id, trigger, response, normalized_match)
    await ctx.send(f"✅ تم إضافة رد تلقائي رقم `{response_id}` على: `{trigger}`.")


@bot.command(name="حذف_رد_تلقائي")
@staff_only()
@commands.guild_only()
async def remove_auto_response_command(ctx: commands.Context, response_id: int) -> None:
    removed = await db_call(db.remove_auto_response, ctx.guild.id, response_id)
    await ctx.send("✅ تم الحذف." if removed else "❌ لم أجد رداً بهذا الرقم.")


@bot.command(name="عرض_الردود_التلقائيه", aliases=["الردود_التلقائيه"])
@staff_only()
@commands.guild_only()
async def list_auto_responses_command(ctx: commands.Context) -> None:
    responses = await db_call(db.get_auto_responses, ctx.guild.id)
    if not responses:
        await ctx.send("لا توجد ردود تلقائية مضبوطة.")
        return
    lines = [f"`#{item['id']}` [{'يحتوي' if item['match_type'] == 'contains' else 'تطابق تام'}] `{item['trigger_text']}` ⇦ {item['response_text'][:60]}" for item in responses]
    await ctx.send(embed=discord.Embed(title="💬 الردود التلقائية", description="\n".join(lines)[:4000], color=discord.Color.blurple()))


def find_matching_auto_response(responses: list[dict], content: str) -> dict | None:
    normalized = content.strip()
    for item in responses:
        if not item.get("enabled", 1):
            continue
        trigger = str(item["trigger_text"]).strip()
        if item["match_type"] == "contains":
            if trigger and trigger in normalized:
                return item
        elif normalized == trigger:
            return item
    return None


# ============================================================
# أوامر الإدارة والمعلومات
# ============================================================

@bot.hybrid_command(name="تنظيف")
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
@commands.guild_only()
async def clear_messages(ctx: commands.Context, amount: int = 10) -> None:
    if not 1 <= amount <= 100:
        await ctx.send("❌ اختر عدداً من 1 إلى 100.")
        return
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass
    try:
        deleted = await ctx.channel.purge(limit=amount)
    except (discord.NotFound, discord.HTTPException) as error:
        print(f"[Clear] purge failed after command handling: {error!r}")
        return
    try:
        await ctx.send(f"✅ تم تنظيف {len(deleted)} رسالة.", delete_after=4)
    except (discord.NotFound, discord.HTTPException) as error:
        print(f"[Clear] result message could not be sent: {error!r}")


@bot.hybrid_command(name="باند")
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
@commands.guild_only()
async def ban_member(ctx: commands.Context, member: discord.Member, *, reason: str = "غير محدد") -> None:
    allowed, message = can_moderate(ctx.author, member)
    if not allowed:
        await ctx.send(f"❌ {message}")
        return
    try:
        await member.send(f"تم حظرك من **{ctx.guild.name}**.\n**السبب:** {reason}")
    except discord.Forbidden:
        pass
    await member.ban(reason=f"{reason} | بواسطة {ctx.author}")
    await ctx.send(embed=discord.Embed(description=f"🔨 تم حظر {member.mention}\n**السبب:** {reason}", color=discord.Color.red()))
    await send_mod_log(ctx.guild, discord.Embed(title="🔨 حظر عضو", description=f"**العضو:** {member.mention} (`{member.id}`)\n**بواسطة:** {ctx.author.mention}\n**السبب:** {reason}\n**القناة:** {ctx.channel.mention}", color=discord.Color.red()))


@bot.hybrid_command(name="فك_الباند")
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
@commands.guild_only()
async def unban_member(ctx: commands.Context, user: discord.User, *, reason: str = "غير محدد") -> None:
    await ctx.guild.unban(user, reason=f"{reason} | بواسطة {ctx.author}")
    await ctx.send(f"✅ تم فك الحظر عن {user.mention}.")
    await send_mod_log(ctx.guild, discord.Embed(title="✅ فك حظر", description=f"**العضو:** {user.mention} (`{user.id}`)\n**بواسطة:** {ctx.author.mention}\n**السبب:** {reason}\n**القناة:** {ctx.channel.mention}", color=discord.Color.green()))


@bot.hybrid_command(name="طرد")
@commands.has_permissions(kick_members=True)
@commands.bot_has_permissions(kick_members=True)
@commands.guild_only()
async def kick_member(ctx: commands.Context, member: discord.Member, *, reason: str = "غير محدد") -> None:
    allowed, message = can_moderate(ctx.author, member)
    if not allowed:
        await ctx.send(f"❌ {message}")
        return
    try:
        await member.send(f"تم طردك من **{ctx.guild.name}**.\n**السبب:** {reason}")
    except discord.Forbidden:
        pass
    await member.kick(reason=f"{reason} | بواسطة {ctx.author}")
    await ctx.send(embed=discord.Embed(description=f"👢 تم طرد {member.mention}\n**السبب:** {reason}", color=discord.Color.orange()))
    await send_mod_log(ctx.guild, discord.Embed(title="👢 طرد عضو", description=f"**العضو:** {member.mention} (`{member.id}`)\n**بواسطة:** {ctx.author.mention}\n**السبب:** {reason}\n**القناة:** {ctx.channel.mention}", color=discord.Color.orange()))


@bot.hybrid_command(name="تايم_اوت")
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
@commands.guild_only()
async def timeout_member(ctx: commands.Context, member: discord.Member, minutes: int, *, reason: str = "غير محدد") -> None:
    if not 1 <= minutes <= 40320:
        await ctx.send("❌ المدة يجب أن تكون بين دقيقة و40320 دقيقة (28 يوماً).")
        return
    allowed, message = can_moderate(ctx.author, member)
    if not allowed:
        await ctx.send(f"❌ {message}")
        return
    await member.timeout(timedelta(minutes=minutes), reason=f"{reason} | بواسطة {ctx.author}")
    await ctx.send(embed=discord.Embed(description=f"⏱️ تم إعطاء {member.mention} تايم أوت لمدة **{minutes} دقيقة**\n**السبب:** {reason}", color=discord.Color.orange()))
    await send_mod_log(ctx.guild, discord.Embed(title="⏱️ تايم أوت", description=f"**العضو:** {member.mention} (`{member.id}`)\n**المدة:** {minutes} دقيقة\n**بواسطة:** {ctx.author.mention}\n**السبب:** {reason}\n**القناة:** {ctx.channel.mention}", color=discord.Color.orange()))


@bot.hybrid_command(name="الغاء_تايم_اوت")
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
@commands.guild_only()
async def remove_timeout(ctx: commands.Context, member: discord.Member) -> None:
    allowed, message = can_moderate(ctx.author, member)
    if not allowed:
        await ctx.send(f"❌ {message}")
        return
    await member.timeout(None, reason=f"إلغاء تايم أوت بواسطة {ctx.author}")
    await ctx.send(f"✅ تم إلغاء التايم أوت عن {member.mention}.")
    await send_mod_log(ctx.guild, discord.Embed(title="✅ إلغاء تايم أوت", description=f"**العضو:** {member.mention} (`{member.id}`)\n**بواسطة:** {ctx.author.mention}\n**القناة:** {ctx.channel.mention}", color=discord.Color.green()))


@bot.hybrid_command(name="تحذير")
@commands.has_permissions(moderate_members=True)
@commands.guild_only()
async def warn_member(ctx: commands.Context, member: discord.Member, *, reason: str = "غير محدد") -> None:
    allowed, message = can_moderate(ctx.author, member)
    if not allowed:
        await ctx.send(f"❌ {message}")
        return
    warning_id = db.add_warning(ctx.guild.id, member.id, ctx.author.id, reason)
    try:
        await member.send(f"⚠️ تلقيت تحذيراً في **{ctx.guild.name}**.\n**السبب:** {reason}")
    except discord.Forbidden:
        pass
    await ctx.send(f"⚠️ تم تحذير {member.mention} برقم #{warning_id}. السبب: {reason}")


@bot.hybrid_command(name="تحذيرات")
@commands.has_permissions(moderate_members=True)
@commands.guild_only()
async def member_warnings(ctx: commands.Context, member: discord.Member) -> None:
    warnings = db.get_warnings(ctx.guild.id, member.id)
    if not warnings:
        await ctx.send(f"✅ لا توجد تحذيرات محفوظة على {member.mention}.")
        return
    lines = [f"`#{item['id']}` — {item['reason']} (بواسطة <@{item['moderator_id']}>)" for item in warnings[:10]]
    await ctx.send(embed=discord.Embed(title=f"تحذيرات {member.display_name}", description="\n".join(lines), color=discord.Color.orange()))


@bot.hybrid_command(name="مسح_التحذيرات")
@commands.has_permissions(moderate_members=True)
@commands.guild_only()
async def clear_member_warnings(ctx: commands.Context, member: discord.Member) -> None:
    count = db.clear_warnings(ctx.guild.id, member.id)
    await ctx.send(f"✅ تم مسح {count} تحذير من {member.mention}.")


@bot.hybrid_command(name="قفل")
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
@commands.guild_only()
async def lock_channel(ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=False, reason=f"قفل بواسطة {ctx.author}")
    await ctx.send(f"🔒 تم قفل {channel.mention}.")


@bot.hybrid_command(name="فتح")
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
@commands.guild_only()
async def unlock_channel(ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=None, reason=f"فتح بواسطة {ctx.author}")
    await ctx.send(f"🔓 تم فتح {channel.mention}.")


@bot.hybrid_command(name="اعطاء_رتبة")
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
@commands.guild_only()
async def give_role(ctx: commands.Context, member: discord.Member, role: discord.Role) -> None:
    allowed, message = can_moderate(ctx.author, member)
    if not allowed:
        await ctx.send(f"❌ {message}")
        return
    if role >= ctx.guild.me.top_role:
        await ctx.send("❌ ارفع رتبة البوت أعلى من الرتبة المطلوبة أولاً.")
        return
    await member.add_roles(role, reason=f"منح رتبة بواسطة {ctx.author}")
    await ctx.send(f"✅ تم إعطاء {role.mention} إلى {member.mention}.")


@bot.hybrid_command(name="سحب_رتبة")
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
@commands.guild_only()
async def remove_role(ctx: commands.Context, member: discord.Member, role: discord.Role) -> None:
    allowed, message = can_moderate(ctx.author, member)
    if not allowed:
        await ctx.send(f"❌ {message}")
        return
    if role >= ctx.guild.me.top_role:
        await ctx.send("❌ ارفع رتبة البوت أعلى من الرتبة المطلوبة أولاً.")
        return
    await member.remove_roles(role, reason=f"سحب رتبة بواسطة {ctx.author}")
    await ctx.send(f"✅ تم سحب {role.mention} من {member.mention}.")


@bot.hybrid_command(name="معلومات_عضو")
@commands.guild_only()
async def member_info(ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
    member = member or ctx.author
    roles = [role.mention for role in member.roles if not role.is_default()]
    embed = discord.Embed(title=f"معلومات {member.display_name}", color=member.color)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="المعرف", value=str(member.id), inline=True)
    embed.add_field(name="تاريخ الانضمام", value=discord.utils.format_dt(member.joined_at, "D") if member.joined_at else "غير معروف", inline=True)
    embed.add_field(name="الرتب", value=" ".join(roles[-10:]) or "لا توجد", inline=False)
    await ctx.send(embed=embed)


@bot.hybrid_command(name="معلومات_سيرفر")
@commands.guild_only()
async def server_info(ctx: commands.Context) -> None:
    guild = ctx.guild
    embed = discord.Embed(title=guild.name, description=guild.description or "لا يوجد وصف.", color=discord.Color.blurple())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="الأعضاء", value=str(guild.member_count), inline=True)
    embed.add_field(name="القنوات", value=str(len(guild.channels)), inline=True)
    embed.add_field(name="المالك", value=f"<@{guild.owner_id}>", inline=True)
    await ctx.send(embed=embed)


# ============================================================
# الأذكار والآيات: جدولة بتوقيت مكة المكرمة
# ============================================================

MECCA_TZ = ZoneInfo("Asia/Riyadh")


def _parse_interval(value: str, fallback: int = 0) -> int:
    try:
        return max(0, min(int(value), 10080)) if int(value) == 0 else max(10, min(int(value), 10080))
    except (TypeError, ValueError):
        return fallback


def _parse_clock(value: str, fallback: str) -> str:
    try:
        hour, minute = (int(part) for part in value.strip().split(":", 1))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    except (TypeError, ValueError):
        pass
    return fallback


async def _resolve_text_channel(ctx: commands.Context, raw: str) -> discord.TextChannel | None:
    try:
        return await commands.TextChannelConverter().convert(ctx, raw.strip())
    except commands.BadArgument:
        return None


ADHKAR_LAST_ERROR: dict[int, str] = {}


def _adhkar_failure(guild_id: int, reason: str) -> bool:
    ADHKAR_LAST_ERROR[guild_id] = reason
    print(f"[Adhkar] guild={guild_id} delivery_failed: {reason}")
    return False


async def send_adhkar_embed(guild: discord.Guild, category: str, *, force: bool = False) -> bool:
    config = db.get_adhkar_config(guild.id)
    if not config.get("enabled") and not force:
        return _adhkar_failure(guild.id, "الإرسال المجدول غير مفعّل")
    try:
        channel_id = int(config.get("channel_id", 0) or 0)
    except (TypeError, ValueError):
        return _adhkar_failure(guild.id, "معرّف قناة الأذكار غير صالح")
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return _adhkar_failure(guild.id, f"القناة المحفوظة غير موجودة أو ليست نصية (ID: {channel_id})")
    me = guild.me
    if me is not None:
        permissions = channel.permissions_for(me)
        missing = [name for name, allowed in (("View Channel", permissions.view_channel), ("Send Messages", permissions.send_messages), ("Embed Links", permissions.embed_links)) if not allowed]
        if missing:
            return _adhkar_failure(guild.id, f"صلاحيات ناقصة في {channel.mention}: {', '.join(missing)}")
    items = adhkar.items_for(category)
    if not items:
        return _adhkar_failure(guild.id, f"لا يوجد محتوى للفئة: {category}")
    previous_keys = config.get("last_item_keys") if isinstance(config.get("last_item_keys"), dict) else {}
    previous_key = str(previous_keys.get(category, ""))
    item = adhkar.select_next_item(items, previous_key)
    mention = str(config.get("mention", "")).strip()
    try:
        color = int(str(config.get("color", "2fa47a")).replace("#", ""), 16)
    except ValueError:
        color = 0x2FA47A
    try:
        await channel.send(content=mention or None, embed=adhkar.build_embed(item, color=color), allowed_mentions=ALLOWED_MENTIONS)
    except discord.Forbidden:
        return _adhkar_failure(guild.id, f"Discord رفض الإرسال في {channel.mention}; راجع View Channel وSend Messages وEmbed Links")
    except discord.HTTPException as error:
        return _adhkar_failure(guild.id, f"Discord HTTP {error.status}: {str(error)[:160]}")
    except Exception as error:
        traceback.print_exc()
        return _adhkar_failure(guild.id, f"خطأ داخلي {type(error).__name__}: {str(error)[:180]}")
    updated_keys = dict(previous_keys)
    updated_keys[category] = item.key
    config["last_item_keys"] = updated_keys
    db.save_adhkar_config(guild.id, config)
    ADHKAR_LAST_ERROR.pop(guild.id, None)
    print(f"[Adhkar] guild={guild.id} sent category={category} item={item.key} channel={channel.id}")
    return True


def adhkar_last_error(guild_id: int) -> str:
    return ADHKAR_LAST_ERROR.get(guild_id, "تعذر تحديد السبب؛ راجع سجل الاستضافة")


@bot.command(name="ضبط_الأذكار", description="إعداد قناة وأوقات أذكار الصباح والمساء بتوقيت مكة")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def configure_adhkar(ctx: commands.Context, *, data: str) -> None:
    parts = [part.strip() for part in data.split("|")]
    if len(parts) < 3:
        await ctx.send("❌ الصيغة: `!ضبط_الأذكار #القناة | 07:00 | 18:00 | المنشن | اللون | فترة الأذكار المطلقة بالدقائق` بتوقيت مكة. استخدم 0 لتعطيل الفترة العامة.")
        return
    channel = await _resolve_text_channel(ctx, parts[0])
    if channel is None:
        await ctx.send("❌ لم أجد قناة نصية صالحة. استخدم منشن القناة أو معرّفها.")
        return
    previous = db.get_adhkar_config(ctx.guild.id)
    raw_color = (parts[4] if len(parts) > 4 else str(previous.get("color", "2fa47a"))).replace("#", "").strip()
    try:
        int(raw_color, 16)
        color = raw_color[:6]
    except ValueError:
        color = "2fa47a"
    config = {
        "enabled": True,
        "channel_id": channel.id,
        "morning_time": _parse_clock(parts[1], "07:00"),
        "evening_time": _parse_clock(parts[2], "18:00"),
        "mention": ("" if len(parts) > 3 and parts[3].strip() == "-" else (parts[3][:200] if len(parts) > 3 else previous.get("mention", ""))),
        "color": color,
        "general_interval_minutes": _parse_interval(parts[5] if len(parts) > 5 else str(previous.get("general_interval_minutes", 0)), 0),
        "last_sent": previous.get("last_sent", {}),
        "last_general_at": previous.get("last_general_at", 0),
        "last_item_keys": previous.get("last_item_keys", {}),
    }
    db.save_adhkar_config(ctx.guild.id, config)
    await ctx.send(f"✅ تم ضبط الأذكار في {channel.mention}. الصباح {config['morning_time']} والمساء {config['evening_time']} بتوقيت مكة.")


@bot.command(name="تعطيل_الأذكار", description="تعطيل الإرسال المجدول للأذكار")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def disable_adhkar(ctx: commands.Context) -> None:
    config = db.get_adhkar_config(ctx.guild.id)
    config["enabled"] = False
    db.save_adhkar_config(ctx.guild.id, config)
    await ctx.send("✅ تم تعطيل الإرسال المجدول للأذكار.")


@bot.hybrid_command(name="أذكار_الآن", aliases=["اذكار_الان", "أذكار_العام", "اذكار_العام"], description="إرسال ذكر أو آية فوراً")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def send_adhkar_now(ctx: commands.Context, category: str = "صباح") -> None:
    normalized = category.strip().lower()
    selected = "quran" if normalized in {"قرآن", "ايات", "آيات", "quran"} else ("general" if normalized in {"عام", "مطلق", "اذكار", "general"} else ("evening" if normalized in {"مساء", "مسائي", "evening"} else "morning"))
    if await send_adhkar_embed(ctx.guild, selected, force=True):
        await ctx.send("✅ تم إرسال الرسالة المضمّنة إلى قناة الأذكار.")
    else:
        await ctx.send(f"❌ لم يتم إرسال الذكر: {adhkar_last_error(ctx.guild.id)}")


@tasks.loop(minutes=1)
async def schedule_adhkar_messages() -> None:
    now = datetime.now(MECCA_TZ)
    clock = now.strftime("%H:%M")
    date_key = now.strftime("%Y-%m-%d")
    for guild in bot.guilds:
        config = db.get_adhkar_config(guild.id)
        if not config.get("enabled") or not config.get("channel_id"):
            continue
        last_sent = config.get("last_sent") if isinstance(config.get("last_sent"), dict) else {}
        for category, key in (("morning", "morning_time"), ("evening", "evening_time")):
            if clock == _parse_clock(str(config.get(key, "")), "--:--") and last_sent.get(category) != date_key:
                try:
                    if await send_adhkar_embed(guild, category):
                        config = db.get_adhkar_config(guild.id)
                        last_sent = config.get("last_sent") if isinstance(config.get("last_sent"), dict) else {}
                        last_sent[category] = date_key
                        config["last_sent"] = last_sent
                        db.save_adhkar_config(guild.id, config)
                    else:
                        print(f"[Adhkar] scheduled {category} skipped: {adhkar_last_error(guild.id)}")
                except (discord.Forbidden, discord.HTTPException) as error:
                    print(f"[Adhkar] Failed for guild {guild.id}: {type(error).__name__}: {error}")
        interval = _parse_interval(str(config.get("general_interval_minutes", 0)), 0)
        try:
            last_general_at = int(config.get("last_general_at", 0) or 0)
        except (TypeError, ValueError):
            last_general_at = 0
        if interval and int(now.timestamp()) - last_general_at >= interval * 60:
            try:
                if await send_adhkar_embed(guild, "general"):
                    config = db.get_adhkar_config(guild.id)
                    config["last_general_at"] = int(now.timestamp())
                    db.save_adhkar_config(guild.id, config)
                else:
                    print(f"[Adhkar] scheduled general skipped: {adhkar_last_error(guild.id)}")
            except (discord.Forbidden, discord.HTTPException) as error:
                print(f"[Adhkar] General failed for guild {guild.id}: {type(error).__name__}: {error}")


# ============================================================
# المساعدة والأخطاء والتشغيل
# ============================================================

@bot.command(name="ضبط_الألعاب", description="ضبط عدد جولات لعبة الأعلام")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def configure_games_command(ctx: commands.Context, rounds: int = 5, timeout: int = 20) -> None:
    rounds = max(1, min(int(rounds), 20))
    timeout = max(5, min(int(timeout), 120))
    current = db.get_games_config(ctx.guild.id)
    current["flags_rounds"] = rounds
    current["flags_timeout"] = timeout
    db.save_games_config(ctx.guild.id, current)
    await ctx.send(f"✅ تم ضبط فعالية الأعلام على **{rounds}** جولات، و**{timeout}** ثانية لكل جولة.")


@bot.command(name="توقف_الأعلام", aliases=["وقف_الأعلام", "إيقاف_الأعلام"], description="إيقاف فعالية الأعلام المستمرة")
@staff_only()
@commands.guild_only()
async def stop_flags_event_command(ctx: commands.Context) -> None:
    if not await games.stop_flag_event(ctx):
        await ctx.send("لا توجد فعالية أعلام تعمل حاليًا.")


@bot.command(name="ضبط_اسم_لعبة", description="تخصيص اسم أمر إحدى الألعاب")
@commands.has_permissions(manage_guild=True)
@commands.guild_only()
async def configure_game_name_command(ctx: commands.Context, game: str, name: str) -> None:
    game_key = {"flags": "flags", "اعلام": "flags", "الأعلام": "flags", "xo": "xo", "إكس_أو": "xo", "rps": "rps", "حجر_ورق_مقص": "rps", "dice": "dice", "نرد": "dice"}.get(game.strip().lower())
    if not game_key:
        await ctx.send("❌ اللعبة غير معروفة. استخدم: flags أو xo أو rps أو dice.")
        return
    try:
        custom_name = games.set_custom_game_name(ctx.guild.id, game_key, name)
        games.apply_custom_aliases(bot)
    except ValueError as error:
        await ctx.send(f"❌ {error}")
        return
    await ctx.send(f"✅ أصبح اختصار لعبة **{game_key}** هو `{custom_name}`. يبقى الأمر الأصلي متاحًا أيضًا.")


@bot.hybrid_command(name="لعبة_الأعلام", aliases=["اعلام", "تخمين_الدولة"], description="ابدأ لعبة تخمين الدولة من العلم")
@commands.guild_only()
async def flags_game_command(ctx: commands.Context) -> None:
    await games.start_flag_game(ctx)


@bot.hybrid_command(name="لعبة_xo", aliases=["xo", "إكس_أو"], description="تحدَّ لاعبًا في لعبة XO")
@commands.guild_only()
async def xo_game_command(ctx: commands.Context, opponent: Optional[discord.Member] = None) -> None:
    await games.start_xo_game(ctx, opponent)


@bot.hybrid_command(name="لعبة_حجر_ورق_مقص", aliases=["rps", "حجر_ورق_مقص"], description="تحدَّ لاعبًا في حجر ورق مقص")
@commands.guild_only()
async def rps_game_command(ctx: commands.Context, opponent: Optional[discord.Member] = None) -> None:
    await games.start_rps_game(ctx, opponent)


@bot.hybrid_command(name="لعبة_النرد", aliases=["dice", "نرد"], description="تحدَّ لاعبًا في لعبة النرد")
@commands.guild_only()
async def dice_game_command(ctx: commands.Context, opponent: Optional[discord.Member] = None) -> None:
    await games.start_dice_game(ctx, opponent)


@bot.hybrid_command(name="متصدرو_الألعاب", aliases=["متصدرين_الألعاب", "game_leaderboard"], description="عرض متصدري نقاط الألعاب")
@commands.guild_only()
async def games_leaderboard_command(ctx: commands.Context) -> None:
    await games.send_games_leaderboard(ctx)


@bot.hybrid_command(name="العاب", aliases=["games"], description="عرض ألعاب Spectre المتاحة")
@commands.guild_only()
async def games_list_command(ctx: commands.Context) -> None:
    await ctx.send(embed=games.games_help_embed())


@bot.hybrid_command(name="نسخة_البوت", aliases=["version", "البناء"], description="يعرض نسخة/إصدار البوت الحالي المُشغَّل فعلياً على هذه الاستضافة")
async def show_bot_version(ctx: commands.Context) -> None:
    """مفيد جداً عند التحديث: بعد رفع نسخة كود جديدة على الاستضافة وإعادة
    التشغيل، شغّل هذا الأمر للتأكد أن BOT_BUILD_ID تغيّر فعلاً — لو ظهر نفس
    الإصدار القديم يعني الرفع أو إعادة التشغيل لم تكتمل بعد."""
    await ctx.send(f"🔧 نسخة البوت المُشغَّلة حالياً: `{BOT_BUILD_ID}`")


@bot.hybrid_command(name="اوامر", aliases=["مساعدة", "help"])
@commands.guild_only()
async def help_command(ctx: commands.Context) -> None:
    embed = discord.Embed(title="📖 أوامر البوت العربي", color=discord.Color.blurple())
    embed.add_field(name="الرسائل والأزرار", value="`!تضمين`، `/embed`، `!اضافة_زر`، `!نشر_الازرار`", inline=False)
    embed.add_field(name="التقديم والتذاكر", value="`!اعداد_التقديم`، `!ضبط_قناة_المراجعة`، `!اعداد_التذاكر`، `!ضبط_قسم_التذاكر`", inline=False)
    embed.add_field(name="اللفلات", value="`!رتبتي`، `!المتصدرين`، `!ضبط_قناة_اللفلات`، `!اضافة_لفل_رتبة`، `!رتب_اللفلات`، `!تعديل_خبرة @عضو 100`، `!نقل_خبرة الحساب_القديم @الحساب_الجديد`", inline=False)
    embed.add_field(name="العد والإذاعة والحضور", value="`!اعداد_روم_العد`، `!حذف_روم_العد`، `!تصفير_العد`، `!رومات_العد`، `!تشغيل_القرآن #الروم`، `!ايقاف_القرآن`، `!ضبط_الحضور 60 عبارة 1 | عبارة 2`", inline=False)
    embed.add_field(name="الأذكار والآيات", value="`!ضبط_الأذكار #القناة | 07:00 | 18:00 | منشن | اللون | الفترة بالدقائق`، `!أذكار_الآن صباح`، `!أذكار_الآن مساء`، `!أذكار_الآن عام`، `!أذكار_الآن قرآن`، `!تعطيل_الأذكار`", inline=False)
    embed.add_field(name="الرولات الذاتية", value="`!انشاء_رولات_تفاعليه العنوان | الوصف`، `!اضافة_رول_تفاعلي معرف_الرسالة الإيموجي @الرتبة`، `!حذف_رول_تفاعلي`", inline=False)
    embed.add_field(name="الردود التلقائية", value="`!اضافة_رد_تلقائي تطابق_تام العبارة | الرد`، `!عرض_الردود_التلقائيه`، `!حذف_رد_تلقائي الرقم`", inline=False)
    embed.add_field(name="الإدارة والسجل", value="`!تنظيف`، `!باند`، `!فك_الباند`، `!طرد`، `!تايم_اوت`، `!تحذير`، `!قفل`، `!فتح`، `!اعطاء_رتبة`، `!ضبط_قناة_اللوق #القناة`", inline=False)
    embed.add_field(name="تخصيص الإيموجي", value="`!اختيار_ايموجي` لاختيار إيموجي من إيموجيات السيرفر لزر التذاكر أو التقديم", inline=False)
    embed.add_field(name="🛡️ الحماية من التخريب", value="`!تفعيل_الحماية`، `!عقوبة_الحماية`، `!اضافة_كلمة_ممنوعة`، `!اضافة_صلاحية_خطيرة`، `!استثناء_عضو @الأدمن`، `!اضافة_بوت_موثوق آيدي`، `!حدود_الحماية`، `!حالة_الحماية`", inline=False)
    embed.add_field(name="🎣 فلتر التصيّد", value="`!تفعيل_فلتر_التصيد`، `!اجراء_فلتر_التصيد`، `!اضافة_نطاق_تصيد`، `!حذف_نطاق_تصيد`", inline=False)
    embed.add_field(name="🚨 الحماية من الغارات", value="`!تفعيل_الحماية_من_الغارات`، `!ضبط_الحماية_من_الغارات`", inline=False)
    embed.add_field(name="👤 حظر الحسابات الحديثة", value="`!تفعيل_حظر_الحسابات_الحديثة`، `!ضبط_عمر_الحساب`", inline=False)
    embed.add_field(name="📌 الرتب اللاصقة ومنشن السبام", value="`!تفعيل_الرتب_اللاصقة`، `!تفعيل_حماية_المنشن`، `!ضبط_حماية_المنشن`", inline=False)
    embed.add_field(name="⭐ لوحة النجوم والمسابقات", value="`!ضبط_لوحة_النجوم #القناة 3 ⭐`، `!مسابقة 1h 1 الجائزة`، `!انهاء_مسابقة معرف`، `!اعادة_سحب_مسابقة معرف`، `!حذف_مسابقة معرف`، `!المسابقات_النشطة`", inline=False)
    await ctx.send(embed=embed)


@bot.hybrid_command(name="مزامنة")
@staff_only()
@commands.guild_only()
async def sync_commands(ctx: commands.Context) -> None:
    synced = await bot.tree.sync()
    await ctx.send(f"✅ تمت مزامنة {len(synced)} أمر سلاش.")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions) and getattr(ctx.message, "_spectre_dashboard_command", False) and not getattr(ctx, "_spectre_dashboard_bypass_attempted", False):
        setattr(ctx, "_spectre_dashboard_bypass_attempted", True)
        try:
            await ctx.command.callback(*ctx.args, **ctx.kwargs)
        except Exception as retry_error:
            original = getattr(retry_error, "original", retry_error)
            traceback.print_exc()
            command_name = getattr(ctx.command, "qualified_name", "غير معروف")
            if isinstance(original, discord.Forbidden):
                detail = "Discord رفض العملية؛ راجع View Channel وSend Messages وEmbed Links أو رتبة البوت."
            elif isinstance(original, discord.HTTPException):
                detail = f"Discord أعاد HTTP {original.status}: {str(original)[:160]}"
            else:
                detail = f"{type(original).__name__}: {str(original)[:220]}"
            await ctx.send(f"❌ فشل أمر الداشبورد `{command_name}`. {detail}")
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ لا تملك الصلاحية اللازمة لهذا الأمر.")
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send(f"❌ البوت يفتقد هذه الصلاحيات: {', '.join(error.missing_permissions)}")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ هناك مُدخل ناقص: `{error.param.name}`. اكتب `!اوامر` للمساعدة.")
    elif isinstance(error, (commands.MemberNotFound, commands.UserNotFound)):
        await ctx.send("❌ لم أجد العضو. استخدم المنشن الصحيح.")
    elif isinstance(error, commands.RoleNotFound):
        await ctx.send("❌ لم أجد الرتبة. استخدم منشن الرتبة الصحيح.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ أحد المدخلات غير صحيح. راجع صيغة الأمر عبر `!اوامر`.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ هذا الأمر يعمل داخل السيرفر فقط.")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("❌ لا يمكنك تنفيذ هذا الأمر.")
    else:
        original = getattr(error, "original", error)
        print(f"[CommandError] command={getattr(ctx.command, 'qualified_name', '<unknown>')} type={type(original).__name__}: {original!r}")
        if isinstance(original, discord.Forbidden):
            await ctx.send("❌ رفض Discord العملية. تحقق من صلاحيات البوت في القناة، ومن أن رتبة البوت أعلى من الرتبة المستهدفة، ومن عدم وجود حماية تمنع التعديل.")
        elif isinstance(original, discord.HTTPException):
            command_name = getattr(ctx.command, "qualified_name", "غير معروف")
            print(f"[CommandError-HTTP404Detail] command={command_name} status={original.status} text={str(original)[:300]}")
            await ctx.send(f"❌ رفض Discord الطلب أثناء تنفيذ `{command_name}` (HTTP {original.status}). تحقق من المعرّفات والصلاحيات ثم أعد المحاولة.")
        elif isinstance(original, (ValueError, TypeError)):
            await ctx.send(f"❌ بيانات الأمر غير صالحة: {str(original)[:180]}")
        else:
            traceback.print_exc()
            await ctx.send(f"❌ فشل تنفيذ الأمر `{getattr(ctx.command, 'qualified_name', 'غير معروف')}` بسبب `{type(original).__name__}: {str(original)[:220]}`. راجع سجل الاستضافة.")


views_registered = False
commands_synced = False
health_runner: web.AppRunner | None = None
presence_index = 0


async def apply_next_presence() -> None:
    global presence_index
    messages = presence_config.get_presence_messages(db)
    message = messages[presence_index % len(messages)]
    presence_index = (presence_index + 1) % len(messages)
    await bot.change_presence(status=discord.Status.online, activity=discord.Game(name=message[:128]))


@tasks.loop(seconds=60)
async def rotate_presence() -> None:
    await apply_next_presence()


@tasks.loop(minutes=1)
async def poll_social_notifications() -> None:
    try:
        await social_notifications.poll_all(bot)
    except Exception as error:
        print(f"[SocialNotifications] poll loop recovered from: {type(error).__name__}: {error}")


@poll_social_notifications.before_loop
async def before_social_notifications() -> None:
    await bot.wait_until_ready()


async def health_check(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "discord_ready": bot.is_ready()})


@bot.event
async def setup_hook() -> None:
    global health_runner
    port = int(os.getenv("PORT") or os.getenv("SERVER_PORT") or "10000")

    # لو نشرت لوحة التحكم بمكان منفصل (مثل Render، مفيد لو ديسكورد يرفض
    # رابط استضافة البوت لأنه بدون HTTPS)، عطّل نسخة الداشبورد المدمجة هنا
    # عشان توفّر معالج/ذاكرة — استهلاكها إضافي غير ضروري لو مو مستخدمة أصلاً.
    # فعّل هذا الخيار بوضع DISABLE_EMBEDDED_DASHBOARD=1 بملف .env.
    if os.getenv("DISABLE_EMBEDDED_DASHBOARD", "").strip() in ("1", "true", "yes"):
        print("[Spectre] الداشبورد المدمجة معطّلة (DISABLE_EMBEDDED_DASHBOARD=1) — توفير موارد.", flush=True)
    else:
        # الترتيب المهم هنا: نحاول تشغيل الداشبورد المدمجة أولاً (بخيط منفصل على
        # نفس المنفذ) — وهذا يحل مشكلة استضافات المنفذ الواحد (مثل Wispbyte) نهائياً:
        # سيرفر واحد فقط يخدم كل من البوت + صفحة الويب + كل الـ API الداخلي، بدون
        # أي شبكة بين عمليتين. لو فشل ذلك لأي سبب (Flask غير مثبتة مثلاً)، نتراجع
        # لسيرفر health-check البسيط بنفس المنفذ بدل ترك البوت بلا أي منفذ مفتوح.
        try:
            import threading
            from dashboard.app import run_embedded

            threading.Thread(target=run_embedded, args=(bot, port), daemon=True, name="spectre-dashboard").start()
            print(f"[Spectre] لوحة التحكم المدمجة تعمل على المنفذ {port} (نفس عملية البوت، بدون منفذ إضافي)", flush=True)
            return
        except Exception as error:
            print(f"[Spectre] تعذّر تشغيل الداشبورد المدمجة، سيعمل البوت بدونها: {type(error).__name__}: {error}", flush=True)

    # نفس منطق الحماية القديم — يبقى فقط كخط دفاع أخير لو الداشبورد ما اشتغلت.
    try:
        app = web.Application()
        app.router.add_get("/", health_check)
        app.router.add_get("/healthz", health_check)
        health_runner = web.AppRunner(app)
        await health_runner.setup()
        site = web.TCPSite(health_runner, "0.0.0.0", port)
        await site.start()
        print(f"[Spectre] Health-check server listening on port {port}", flush=True)
    except Exception as error:
        print(f"[Spectre] Health-check server failed to start (بوت مستمر بالعمل بشكل طبيعي بدونه): {type(error).__name__}: {error}", flush=True)


@bot.event
async def on_ready() -> None:
    global views_registered, commands_synced
    db.init_db()
    rotate_presence.change_interval(seconds=presence_config.get_presence_interval(db))
    await apply_next_presence()
    if not rotate_presence.is_running():
        rotate_presence.start()
    if not poll_social_notifications.is_running():
        poll_social_notifications.start()
    if not schedule_adhkar_messages.is_running():
        schedule_adhkar_messages.start()

    if not views_registered:
        bot.add_view(TicketCloseView())
        for guild in bot.guilds:
            settings = db.get_guild_settings(guild.id)
            bot.add_view(TicketCreateView(settings["ticket_emoji"], settings["ticket_label"], settings["ticket_style"]))
            bot.add_view(build_apply_view(guild.id, settings["apply_emoji"], settings["apply_style"]))
            faqs = db.get_faqs(guild.id)
            if faqs:
                bot.add_view(build_faq_view(guild.id, faqs))
            # يعيد تسجيل أزرار قوالب التذاكر/التقديم (تحديث_تدفق) واللوحات
            # المخصصة (تحديث_لوحة) بعد كل إعادة تشغيل. بدون هذا كانت هذه
            # الأزرار تتوقف عن الرد بعد أي إعادة تشغيل للبوت برسالة ديسكورد
            # "the application didn't respond in time".
            for workflow_type in ("ticket", "application"):
                workflow = db.get_workflow(guild.id, workflow_type)
                if not workflow or not workflow.get("enabled", 1):
                    continue
                try:
                    workflow_config = json.loads(workflow["config_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(workflow_config, dict):
                    bot.add_view(build_custom_workflow_view(guild.id, workflow_type, workflow_config))
            for panel in db.get_panels(guild.id):
                try:
                    panel_config = json.loads(panel["config_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(panel_config, dict):
                    bot.add_view(build_panel_view(guild.id, panel_config))
        for application_id in db.get_pending_application_ids():
            bot.add_view(ReviewActionView(application_id))
        views_registered = True

    games.apply_custom_aliases(bot)
    if not commands_synced:
        print(f"[Spectre] Runtime command count: prefix={len(bot.commands)} slash={len(bot.tree.get_commands())} source={__file__}", flush=True)
        try:
            registered_names = {command.name for command in bot.tree.get_commands()}
            for command in bot.commands:
                app_command = getattr(command, "app_command", None)
                if app_command is not None and app_command.name not in registered_names:
                    bot.tree.add_command(app_command)
                    registered_names.add(app_command.name)
            synced = await bot.tree.sync()
            synced_names = ", ".join(command.name for command in synced)
            print(f"تمت مزامنة {len(synced)} أمر سلاش: {synced_names}")
            commands_synced = True
        except Exception as error:
            print(f"تعذرت مزامنة أوامر السلاش، ستتم إعادة المحاولة: {error}")
            commands_synced = False

    if not update_member_count.is_running():
        update_member_count.start()
        print(f"تم تسجيل دخول البوت باسم: {bot.user}")
    if not cleanup_memory_caches.is_running():
        cleanup_memory_caches.start()
        print(f"[Spectre] Build: {BOT_BUILD_ID}")
        print("[DashboardControl] Workflow command available: " + str(any(command.name == "تحديث_تدفق" for command in bot.commands)))
    if not check_pending_giveaways.is_running():
        check_pending_giveaways.start()


if __name__ == "__main__":
    db.init_db()
    if not TOKEN:
        raise RuntimeError("لم أجد DISCORD_TOKEN. أنشئ ملف .env وضع فيه DISCORD_TOKEN=توكن_البوت")
    bot.run(TOKEN)
