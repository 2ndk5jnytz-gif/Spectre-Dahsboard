"""نظام الحماية من التخريب (Anti-Nuke) لبوت Spectre.

يراقب هذا الملف الأفعال الخطيرة على السيرفر لحظياً (عبر أحداث ديسكورد نفسها،
وليس فحصاً دورياً)، ويتدخل فور اكتشاف أي منها:

- كلمات ممنوعة بأسماء الرومات (عند الإنشاء أو التعديل) ⇐ يرجّع الاسم القديم فوراً.
- إنشاء/حذف رومات بمعدل مشبوه (نمط تخريب جماعي) ⇐ يعاقب الفاعل فوراً.
- طرد/حظر/تايم أوت بمعدل مشبوه ⇐ يعاقب الفاعل فوراً.
- رتبة جديدة أو مُعدَّلة فيها صلاحية خطيرة من قائمة قابلة للتخصيص (مثل الأدمن) ⇐
  يحذف الرتبة أو يرجّع صلاحياتها القديمة فوراً، ويعاقب الفاعل.
- انضمام بوت غير موثوق (ليس بقائمة السماح) ⇐ يُطرَد فوراً.

العقوبة نفسها قابلة للاختيار من لوحة التحكم أو أوامر البوت: طرد / حظر / سحب
كل الرتب / تايم أوت. مالك السيرفر مستثنى دائماً، وأي عضو آخر يمكن استثناؤه
عبر قائمة بيضاء (Whitelist) حتى لا يُعاقَب الأدمن الموثوق بالخطأ.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import discord

import db

# تتبّع الأفعال بالذاكرة (بدون قاعدة بيانات، لأنها بيانات مؤقتة جداً):
# {(guild_id, actor_id, action_name): [توقيتات الأفعال الأخيرة]}
_action_timestamps: dict[tuple[int, int, str], list[datetime]] = defaultdict(list)

# آخر اسم معروف لكل قناة، لإرجاعه فوراً عند تغيير مرفوض (أدق من انتظار audit log
# القديم لأنه يُحدَّث لحظة كل تعديل ناجح تراه أحداث البوت نفسها).
_last_known_channel_names: dict[int, str] = {}

# آخر صلاحيات معروفة لكل رتبة، لإرجاعها فوراً عند تعديل يضيف صلاحية خطيرة.
_last_known_role_permissions: dict[int, int] = {}


def load_json_list(settings: dict[str, Any], key: str) -> list:
    try:
        value = json.loads(settings.get(key) or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def is_enabled(settings: dict[str, Any]) -> bool:
    return bool(settings.get("antinuke_enabled"))


def is_whitelisted(guild: discord.Guild, user: discord.Member | discord.User | None, settings: dict[str, Any]) -> bool:
    if user is None:
        return True  # لا نعرف الفاعل، لا نعاقب أحداً عشوائياً
    if user.id == guild.owner_id:
        return True
    if guild.me is not None and user.id == guild.me.id:
        return True
    whitelist = {int(value) for value in load_json_list(settings, "antinuke_whitelist_json") if str(value).isdigit()}
    return user.id in whitelist


def contains_banned_word(name: str, settings: dict[str, Any]) -> str | None:
    """يعيد الكلمة الممنوعة إذا وُجدت باسم القناة، وإلا None."""
    banned_words = [str(word).strip().lower() for word in load_json_list(settings, "antinuke_banned_words_json") if str(word).strip()]
    lowered = name.lower()
    for word in banned_words:
        if word and word in lowered:
            return word
    return None


def dangerous_permissions_present(permissions: discord.Permissions, settings: dict[str, Any]) -> list[str]:
    watched = [str(perm).strip().lower() for perm in load_json_list(settings, "antinuke_dangerous_perms_json")]
    found = []
    for perm_name in watched:
        if getattr(permissions, perm_name, False):
            found.append(perm_name)
    return found


# ==================== فلتر روابط التصيّد (Anti-Phishing) ====================
# نطاقات معروفة تُستخدم بكثرة بسكامات "نيترو مجاني" ونسخ ديسكورد المزيفة
# (typosquatting) وسكامات ستيم المزيفة. هذي قائمة أساسية يستطيع الأدمن توسيعها
# من الداشبورد أو بأمر `!اضافة_نطاق_تصيد` بدون تعديل الكود.
DEFAULT_PHISHING_DOMAINS = [
    "dlscord.gift", "discorcl.com", "discordgift.site", "discrod-nitro.com",
    "discord-nltro.com", "discordapp.gift", "discordnitro.gift", "steamcommunlty.com",
    "steancommunity.com", "steamcomminuty.com", "dlscordapp.com", "discord-app.net",
]

_URL_PATTERN = re.compile(r"https?://([a-zA-Z0-9\-\.]+)", re.IGNORECASE)


def is_phishing_enabled(settings: dict[str, Any]) -> bool:
    return bool(settings.get("antiphishing_enabled"))


def find_phishing_domain(content: str, settings: dict[str, Any]) -> str | None:
    """يفحص كل الروابط بنص الرسالة، ويعيد أول نطاق مطابق لقائمة نطاقات
    التصيد (الافتراضية + المخصصة من الأدمن)، أو None إذا كانت الرسالة نظيفة."""
    custom_domains = [str(domain).strip().lower() for domain in load_json_list(settings, "antiphishing_domains_json")]
    watched_domains = {domain.lower() for domain in DEFAULT_PHISHING_DOMAINS} | set(custom_domains)
    if not watched_domains:
        return None
    for match in _URL_PATTERN.finditer(content):
        host = match.group(1).lower()
        for domain in watched_domains:
            if host == domain or host.endswith(f".{domain}"):
                return domain
    return None


def record_action(guild_id: int, actor_id: int, action: str, window_seconds: int) -> int:
    """يسجّل فعلاً جديداً للفاعل، وينظّف الأفعال الأقدم من النافذة الزمنية،
    ويعيد عدد الأفعال المتبقية ضمن النافذة (المعدّل الحالي)."""
    now = datetime.now(timezone.utc)
    key = (guild_id, actor_id, action)
    entries = [stamp for stamp in _action_timestamps[key] if (now - stamp).total_seconds() <= window_seconds]
    entries.append(now)
    _action_timestamps[key] = entries
    return len(entries)


def reset_action(guild_id: int, actor_id: int, action: str) -> None:
    _action_timestamps.pop((guild_id, actor_id, action), None)


def cleanup_stale_actions(max_age_seconds: int = 3600) -> None:
    """تنظيف دوري لمنع تراكم القاموس بلا حدود بمرور الوقت."""
    now = datetime.now(timezone.utc)
    stale_keys = [
        key for key, stamps in _action_timestamps.items()
        if not stamps or (now - stamps[-1]).total_seconds() > max_age_seconds
    ]
    for key in stale_keys:
        _action_timestamps.pop(key, None)


async def find_actor(guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None = None, within_seconds: int = 8) -> discord.Member | discord.User | None:
    """يبحث بسجل تدقيق ديسكورد (Audit Log) عن آخر فاعل نفّذ حدثاً معيناً خلال
    ثوانٍ قليلة، لمعرفة من يستحق العقاب حتى لو الفعل نُفِّذ يدوياً من ديسكورد
    مباشرة (مو بالضرورة عبر أمر بالبوت)."""
    if guild.me is None or not guild.me.guild_permissions.view_audit_log:
        return None
    try:
        async for entry in guild.audit_logs(limit=6, action=action):
            age = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
            if age > within_seconds:
                break
            if target_id is not None and getattr(entry.target, "id", None) != target_id:
                continue
            return entry.user
    except (discord.Forbidden, discord.HTTPException):
        return None
    return None


async def punish(
    guild: discord.Guild,
    actor: discord.Member,
    settings: dict[str, Any],
    reason: str,
    send_log: Callable[[discord.Guild, discord.Embed], Awaitable[None]],
) -> None:
    """ينفّذ العقوبة المضبوطة على الفاعل (طرد/حظر/سحب رتب/تايم أوت)."""
    if is_whitelisted(guild, actor, settings):
        return
    punishment = settings.get("antinuke_punishment", "kick")
    executed = punishment
    try:
        if punishment == "ban":
            await guild.ban(actor, reason=reason[:512], delete_message_seconds=0)
        elif punishment == "remove_roles":
            await actor.edit(roles=[], reason=reason[:512])
        elif punishment == "timeout":
            await actor.timeout(timedelta(hours=1), reason=reason[:512])
        else:
            executed = "kick"
            await actor.kick(reason=reason[:512])
    except discord.Forbidden:
        executed = "فشل (صلاحيات البوت غير كافية)"
    except discord.HTTPException as error:
        executed = f"فشل ({error})"

    punishment_labels = {"ban": "حظر", "kick": "طرد", "remove_roles": "سحب كل الرتب", "timeout": "تايم أوت ساعة"}
    embed = discord.Embed(
        title="🛡️ تدخّل نظام الحماية من التخريب",
        description=(
            f"**الفاعل:** {actor.mention} (`{actor.id}`)\n"
            f"**السبب:** {reason}\n"
            f"**الإجراء:** {punishment_labels.get(executed, executed)}"
        ),
        color=discord.Color.red(),
    )
    await send_log(guild, embed)
