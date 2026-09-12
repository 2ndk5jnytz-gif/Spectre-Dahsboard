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
import json

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

    from spectre_bot_latest import workflow_embed
    embed = workflow_embed({
        "title": payload.get("title") or "مركز المساعدة والدعم",
        "description": payload.get("description") or "اضغط الزر في الأسفل لفتح تذكرة خاصة بك.",
        "color": payload.get("color") or "#5865F2",
        "imageUrl": payload.get("image_url") or "",
        "thumbnailUrl": payload.get("thumbnail_url") or "",
        "footer": payload.get("footer") or {},
        "timestamp": bool(payload.get("timestamp")),
    })
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

    from spectre_bot_latest import workflow_embed
    embed = workflow_embed({
        "title": payload.get("title") or "التقديم للإدارة 🛡️",
        "description": payload.get("description") or "هذه الغرفة مخصصة لطلبات الإدارة. اضغط الزر في الأسفل ثم املأ النموذج.",
        "color": payload.get("color") or style,
        "imageUrl": image_url,
        "thumbnailUrl": payload.get("thumbnail_url") or "",
        "footer": payload.get("footer") or {},
        "timestamp": bool(payload.get("timestamp")),
    })
    view = build_apply_view(guild.id, emoji, style)
    bot.add_view(view)
    message = await channel.send(embed=embed, view=view)
    return {"message_id": str(message.id), "channel_id": str(channel.id)}


# ==================== Embed حر ====================
async def send_embed(bot: Any, guild_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Advanced message/Embed publisher used by the dashboard.

    Supports normal message content, full Discord embed styling, up to 25 fields,
    and persistent interactive buttons. Button responses may themselves contain
    text, embeds, images and thumbnails. Link buttons use Discord's native URL
    button style.
    """
    guild = get_guild(bot, guild_id)
    channel = guild.get_channel(int(payload.get("channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("قناة غير صحيحة.")

    from spectre_bot_latest import workflow_embed, build_panel_view

    config = {
        "title": payload.get("title") or "",
        "description": payload.get("description") or "",
        "color": payload.get("color") or "#5865F2",
        "imageUrl": payload.get("image_url") or "",
        "thumbnailUrl": payload.get("thumbnail_url") or "",
        "author": payload.get("author") or {},
        "footer": payload.get("footer") or {},
        "fields": payload.get("fields") or [],
        "timestamp": bool(payload.get("timestamp")),
        "buttons": payload.get("buttons") or [],
    }
    content = str(payload.get("content") or "")[:2000] or None
    embed = workflow_embed(config)
    buttons = config["buttons"][:25]
    view = build_panel_view(guild.id, config) if buttons else None
    if view:
        bot.add_view(view)
    message = await channel.send(
        content=content,
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False),
    )
    if buttons:
        db.save_panel(guild.id, channel.id, message.id, json.dumps(config, ensure_ascii=False))
    return {"message_id": str(message.id), "channel_id": str(channel.id)}



# ==================== رفع صور الداشبورد ====================
async def upload_dashboard_image(bot: Any, guild_id: int, filename: str, content_type: str, data: bytes) -> dict[str, Any]:
    """يرفع صورة اختارها المستخدم من هاتفه إلى قناة أصول خاصة بالبوت، ثم يعيد رابط Discord CDN.
    نحتفظ برسالة الصورة حتى يبقى الرابط صالحاً بدلاً من الاعتماد على قرص Render المؤقت."""
    guild = get_guild(bot, guild_id)
    if not content_type.lower().startswith("image/"):
        raise ValueError("الملف يجب أن يكون صورة.")
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("حجم الصورة يجب ألا يتجاوز 8MB.")
    allowed = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
    if content_type.lower() not in allowed:
        raise ValueError("الصيغ المدعومة: PNG و JPG و GIF و WEBP.")

    channel = discord.utils.find(lambda c: isinstance(c, discord.TextChannel) and c.name == "spectre-assets", guild.text_channels)
    if channel is None:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
        }
        try:
            channel = await guild.create_text_channel("spectre-assets", overwrites=overwrites, reason="قناة أصول صور لوحة تحكم Spectre")
        except discord.Forbidden:
            raise ValueError("البوت يحتاج صلاحية Manage Channels لإنشاء قناة الصور الخاصة.")
    safe_name = (filename or "image.png").replace("/", "_").replace("\\", "_")[:100]
    file = discord.File(__import__("io").BytesIO(data), filename=safe_name)
    message = await channel.send(file=file)
    attachment = message.attachments[0] if message.attachments else None
    if attachment is None:
        raise ValueError("تعذّر الحصول على رابط الصورة من ديسكورد.")
    return {"url": attachment.url, "filename": safe_name}

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
    from spectre_bot_latest import send_mod_log

    try:
        user_id = int(payload.get("user_id", 0))
    except (TypeError, ValueError):
        user_id = 0
    member = guild.get_member(user_id) if user_id else None

    try:
        if action == "kick":
            if not member: raise ValueError("العضو غير موجود في السيرفر.")
            await member.kick(reason=reason)
        elif action == "ban":
            if not user_id: raise ValueError("أدخل آيدي العضو.")
            await guild.ban(member or discord.Object(id=user_id), reason=reason)
        elif action == "unban":
            if not user_id: raise ValueError("أدخل آيدي المستخدم.")
            await guild.unban(discord.Object(id=user_id), reason=reason)
        elif action == "timeout":
            if not member: raise ValueError("العضو غير موجود في السيرفر.")
            minutes = max(1, min(40320, int(payload.get("minutes", 10))))
            await member.timeout(timedelta(minutes=minutes), reason=reason)
        elif action == "untimeout":
            if not member: raise ValueError("العضو غير موجود في السيرفر.")
            await member.timeout(None, reason=reason)
        elif action == "warn":
            if not member: raise ValueError("العضو غير موجود في السيرفر.")
            db.add_warning(guild.id, member.id, int(payload.get("moderator_id", guild.owner_id or 0)), reason)
        elif action == "clear":
            channel = guild.get_channel(int(payload.get("channel_id", 0)))
            if not isinstance(channel, discord.TextChannel): raise ValueError("اختر قناة نصية.")
            amount = max(1, min(100, int(payload.get("amount", 10))))
            await channel.purge(limit=amount)
        elif action in {"lock", "unlock"}:
            channel = guild.get_channel(int(payload.get("channel_id", 0)))
            if not isinstance(channel, discord.TextChannel): raise ValueError("اختر قناة نصية.")
            overwrite = channel.overwrites_for(guild.default_role)
            overwrite.send_messages = False if action == "lock" else None
            await channel.set_permissions(guild.default_role, overwrite=overwrite, reason=reason)
        elif action in {"give_role", "remove_role"}:
            if not member: raise ValueError("العضو غير موجود في السيرفر.")
            role = guild.get_role(int(payload.get("role_id", 0)))
            if not role: raise ValueError("الرتبة غير موجودة.")
            if action == "give_role":
                await member.add_roles(role, reason=reason)
            else:
                await member.remove_roles(role, reason=reason)
        else:
            raise ValueError("إجراء غير معروف.")
    except discord.Forbidden:
        raise ValueError("صلاحيات البوت غير كافية لتنفيذ هذا الإجراء.")
    except discord.HTTPException as error:
        raise ValueError(f"رفض Discord الإجراء: {error}")

    try:
        await send_mod_log(guild, discord.Embed(
            title=f"🛠️ {action} — لوحة Spectre",
            description=f"**العضو:** `{user_id}`\n**السبب:** {reason}",
            color=discord.Color.blurple(),
        ))
    except Exception:
        pass
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
