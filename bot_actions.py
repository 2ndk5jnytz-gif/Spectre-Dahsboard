"""منطق أعمال لوحة التحكم — يُستدعى مباشرة من نفس عملية البوت.

بخلاف التصميم القديم (dashboard_api.py) الذي كان يفترض عمليتين منفصلتين
تتواصلان عبر HTTP، هذا الملف دوال Python عادية (async) تُستدعى مباشرة من
الداشبورد المدمجة (dashboard/app.py) عبر asyncio.run_coroutine_threadsafe.
هذا يلغي تماماً الحاجة لأي "منفذ ثانٍ" أو "رابط داخلي" أو مفتاح API مشترك —
مشكلة حقيقية واجهناها مع استضافات تخصص منفذاً خارجياً واحداً فقط (مثل
Wispbyte)، حيث كان يصعب أو يستحيل جعل عمليتين منفصلتين تتواصلان بأمان.

كل دالة هنا تعيد dict عادي (JSON-serializable) أو ترمي ValueError برسالة
عربية واضحة عند الخطأ — الداشبورد تلتقط الاستثناء وتحوّله لرسالة خطأ للمستخدم.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import discord

import db


def get_guild(bot: Any, guild_id: int) -> discord.Guild:
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        raise ValueError("لم أجد هذا السيرفر ضمن سيرفرات البوت.")
    return guild


# ==================== عام ====================
def list_guilds(bot: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": str(guild.id),
            "name": guild.name,
            "icon": str(guild.icon.url) if guild.icon else None,
            "member_count": guild.member_count,
        }
        for guild in bot.guilds
    ]


def guild_overview(bot: Any, guild_id: int) -> dict[str, Any]:
    guild = get_guild(bot, guild_id)
    return {
        "id": str(guild.id),
        "name": guild.name,
        "icon": str(guild.icon.url) if guild.icon else None,
        "member_count": guild.member_count,
        "channels": [{"id": str(c.id), "name": c.name, "type": "text"} for c in guild.text_channels],
        "voice_channels": [{"id": str(c.id), "name": c.name} for c in guild.voice_channels],
        "categories": [{"id": str(c.id), "name": c.name} for c in guild.categories],
        "roles": [
            {"id": str(r.id), "name": r.name, "color": str(r.color)}
            for r in reversed(guild.roles) if not r.is_default() and not r.managed
        ],
        "emojis": [{"id": str(e.id), "name": e.name, "url": str(e.url), "animated": e.animated} for e in guild.emojis],
    }


def find_members(bot: Any, guild_id: int, query: str) -> list[dict[str, Any]]:
    guild = get_guild(bot, guild_id)
    query = query.strip().lower()
    if not query:
        return []
    results = []
    for member in guild.members:
        if query in member.name.lower() or query in member.display_name.lower() or query == str(member.id):
            results.append({
                "id": str(member.id), "name": member.name,
                "display_name": member.display_name, "avatar": str(member.display_avatar.url),
            })
        if len(results) >= 15:
            break
    return results


# ==================== التذاكر ====================
async def publish_ticket_panel(bot: Any, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    guild = get_guild(bot, guild_id)
    channel = guild.get_channel(int(payload.get("channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("قناة غير صحيحة.")

    from spectre_bot_latest import TicketCreateView

    emoji = payload.get("emoji") or "🎫"
    label = payload.get("label") or "فتح تذكرة دعم"
    style = payload.get("style") or "success"
    db.set_guild_setting(guild.id, "ticket_emoji", emoji)
    db.set_guild_setting(guild.id, "ticket_label", label)
    db.set_guild_setting(guild.id, "ticket_style", style)

    embed = discord.Embed(
        title=payload.get("title") or "مركز المساعدة والدعم",
        description=payload.get("description") or "اضغط الزر في الأسفل لفتح تذكرة خاصة بك.",
        color=discord.Color.blurple(),
    )
    if payload.get("image_url"):
        embed.set_image(url=payload["image_url"])
    view = TicketCreateView(emoji, label, style)
    bot.add_view(view)
    message = await channel.send(embed=embed, view=view)
    return {"message_id": str(message.id), "channel_id": str(channel.id)}


# ==================== التقديم ====================
async def publish_apply_panel(bot: Any, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    guild = get_guild(bot, guild_id)
    channel = guild.get_channel(int(payload.get("channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("قناة غير صحيحة.")

    from spectre_bot_latest import build_apply_view, parse_color

    emoji = payload.get("emoji") or "🛠️"
    style = payload.get("style") or "blurple"
    image_url = payload.get("image_url") or ""
    db.set_guild_setting(guild.id, "apply_emoji", emoji)
    db.set_guild_setting(guild.id, "apply_style", style)
    db.set_guild_setting(guild.id, "apply_image_url", image_url)

    embed = discord.Embed(
        title=payload.get("title") or "التقديم للإدارة 🛡️",
        description=payload.get("description") or "هذه الغرفة مخصصة لطلبات الإدارة. اضغط الزر في الأسفل ثم املأ النموذج.",
        color=parse_color(style),
    )
    if image_url:
        embed.set_image(url=image_url)
    view = build_apply_view(guild.id, emoji, style)
    bot.add_view(view)
    message = await channel.send(embed=embed, view=view)
    return {"message_id": str(message.id), "channel_id": str(channel.id)}


# ==================== Embed حر ====================
async def send_embed(bot: Any, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    guild = get_guild(bot, guild_id)
    channel = guild.get_channel(int(payload.get("channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("قناة غير صحيحة.")

    from spectre_bot_latest import parse_color

    embed = discord.Embed(
        title=payload.get("title") or None,
        description=payload.get("description") or "",
        color=parse_color(payload.get("color") or "blurple"),
    )
    if payload.get("image_url"):
        embed.set_image(url=payload["image_url"])
    if payload.get("thumbnail_url"):
        embed.set_thumbnail(url=payload["thumbnail_url"])
    message = await channel.send(embed=embed)
    return {"message_id": str(message.id)}


# ==================== الرولات الذاتية ====================
async def create_reaction_role_message(bot: Any, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    guild = get_guild(bot, guild_id)
    channel = guild.get_channel(int(payload.get("channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("قناة غير صحيحة.")
    embed = discord.Embed(
        title=payload.get("title") or "اختر رتبتك",
        description=payload.get("description") or "اضغط الإيموجي المناسب لأخذ الرتبة.",
        color=discord.Color.blurple(),
    )
    message = await channel.send(embed=embed)
    return {"message_id": str(message.id), "channel_id": str(channel.id)}


async def link_reaction_role(bot: Any, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    guild = get_guild(bot, guild_id)
    try:
        message_id = int(payload["message_id"])
        role_id = int(payload["role_id"])
    except (KeyError, ValueError):
        raise ValueError("بيانات غير صحيحة.")
    emoji_raw = str(payload.get("emoji", "")).strip()
    if not emoji_raw:
        raise ValueError("حدد إيموجي.")

    from spectre_bot_latest import parse_emoji, emoji_key

    target_message = None
    for channel in guild.text_channels:
        try:
            target_message = await channel.fetch_message(message_id)
            break
        except (discord.NotFound, discord.Forbidden):
            continue
    if target_message is None:
        raise ValueError("لم أجد الرسالة.")
    role = guild.get_role(role_id)
    if role is None:
        raise ValueError("لم أجد الرتبة.")
    try:
        await target_message.add_reaction(parse_emoji(emoji_raw))
    except discord.HTTPException:
        raise ValueError("تعذّر إضافة هذا الإيموجي.")
    db.add_reaction_role(guild.id, target_message.channel.id, target_message.id, emoji_key(emoji_raw), role.id)
    return {}


# ==================== الخبرة ====================
async def adjust_xp(bot: Any, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    guild = get_guild(bot, guild_id)
    try:
        user_id = int(payload["user_id"])
        amount = int(payload["amount"])
    except (KeyError, ValueError):
        raise ValueError("بيانات غير صحيحة.")
    if amount == 0:
        raise ValueError("الكمية لا يمكن أن تكون صفراً.")
    member = guild.get_member(user_id)
    new_level, new_xp = db.add_xp_delta(guild.id, user_id, amount)
    if member:
        for level, role_id in db.get_level_roles(guild.id):
            if level <= new_level:
                role = guild.get_role(role_id)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason="تعديل خبرة من لوحة التحكم")
                    except discord.Forbidden:
                        pass
    return {"level": new_level, "xp": new_xp}


async def transfer_xp(bot: Any, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    guild = get_guild(bot, guild_id)
    try:
        old_user_id = int(payload["old_user_id"])
        new_user_id = int(payload["new_user_id"])
    except (KeyError, ValueError):
        raise ValueError("بيانات غير صحيحة.")
    new_level, new_xp = db.transfer_xp(guild.id, old_user_id, new_user_id)
    member = guild.get_member(new_user_id)
    if member:
        for level, role_id in db.get_level_roles(guild.id):
            if level <= new_level:
                role = guild.get_role(role_id)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason="نقل خبرة من لوحة التحكم")
                    except discord.Forbidden:
                        pass
    return {"level": new_level, "xp": new_xp}


# ==================== الإدارة ====================
async def mod_action(bot: Any, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    guild = get_guild(bot, guild_id)
    action = payload.get("action")
    reason = payload.get("reason") or "بواسطة لوحة التحكم"
    try:
        user_id = int(payload["user_id"])
    except (KeyError, ValueError):
        raise ValueError("بيانات غير صحيحة.")
    member = guild.get_member(user_id)

    from spectre_bot_latest import send_mod_log

    try:
        if action == "kick":
            if not member:
                raise ValueError("العضو غير موجود في السيرفر.")
            await member.kick(reason=reason)
            await send_mod_log(guild, discord.Embed(title="👢 طرد عضو (من لوحة التحكم)", description=f"**العضو:** {member.mention} (`{member.id}`)\n**السبب:** {reason}", color=discord.Color.orange()))
        elif action == "ban":
            user = member or discord.Object(id=user_id)
            await guild.ban(user, reason=reason)
            await send_mod_log(guild, discord.Embed(title="🔨 حظر عضو (من لوحة التحكم)", description=f"**العضو:** `{user_id}`\n**السبب:** {reason}", color=discord.Color.red()))
        elif action == "unban":
            await guild.unban(discord.Object(id=user_id), reason=reason)
            await send_mod_log(guild, discord.Embed(title="✅ فك حظر (من لوحة التحكم)", description=f"**العضو:** `{user_id}`\n**السبب:** {reason}", color=discord.Color.green()))
        elif action == "timeout":
            if not member:
                raise ValueError("العضو غير موجود في السيرفر.")
            minutes = int(payload.get("minutes", 10))
            await member.timeout(timedelta(minutes=minutes), reason=reason)
            await send_mod_log(guild, discord.Embed(title="⏱️ تايم أوت (من لوحة التحكم)", description=f"**العضو:** {member.mention} (`{member.id}`)\n**المدة:** {minutes} دقيقة\n**السبب:** {reason}", color=discord.Color.orange()))
        elif action == "untimeout":
            if not member:
                raise ValueError("العضو غير موجود في السيرفر.")
            await member.timeout(None, reason=reason)
            await send_mod_log(guild, discord.Embed(title="✅ إلغاء تايم أوت (من لوحة التحكم)", description=f"**العضو:** {member.mention} (`{member.id}`)", color=discord.Color.green()))
        else:
            raise ValueError("إجراء غير معروف.")
    except discord.Forbidden:
        raise ValueError("صلاحيات البوت غير كافية لتنفيذ هذا الإجراء.")
    return {}


# ==================== المسابقات ====================
async def create_giveaway(bot: Any, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    guild = get_guild(bot, guild_id)
    channel = guild.get_channel(int(payload.get("channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("قناة غير صحيحة.")

    from spectre_bot_latest import parse_duration, build_giveaway_embed

    seconds = parse_duration(str(payload.get("duration", "")))
    if seconds is None or seconds < 10:
        raise ValueError("صيغة المدة غير صحيحة. أمثلة: 30s، 10m، 2h، 1d.")
    winners_count = max(1, min(20, int(payload.get("winners", 1))))
    prize = str(payload.get("prize", "")).strip()[:200]
    if not prize:
        raise ValueError("اكتب اسم الجائزة.")

    ends_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    fake_giveaway = {"prize": prize, "winners_count": winners_count, "ends_at": ends_at.isoformat()}
    embed = build_giveaway_embed(fake_giveaway, ended=False)
    message = await channel.send(embed=embed)
    await message.add_reaction("🎉")
    db.create_giveaway(guild.id, channel.id, message.id, prize, winners_count, guild.owner_id or 0, ends_at.isoformat())
    return {"message_id": str(message.id)}
