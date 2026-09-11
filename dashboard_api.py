"""جسر API داخلي بين البوت ولوحة التحكم (dashboard/app.py).

يعمل هذا الملف داخل نفس عملية البوت (نفس aiohttp الموجود أصلاً لـ health check)،
فأي طلب يصل من لوحة التحكم يُنفَّذ مباشرة بواسطة discord.py بلا أي وسيط ولا تأخير:
نشر لوحة تذاكر، إرسال Embed، تعديل خبرة عضو مع منح الرتب، تنفيذ إجراء إداري... كل هذا
فوري لحظة الطلب لأنه نفس عملية البوت المتصلة بديسكورد.

الإعدادات البسيطة (بادئة السيرفر، رسالة الترحيب، ألوان الأزرار...) لا تحتاج المرور من
هنا؛ لوحة التحكم تقرأها/تكتبها مباشرة من db.py لأنها نفس قاعدة البيانات (SQLite بوضع
WAL يدعم القراءة/الكتابة من عمليتين بأمان)، فالحفظ من الداشبورد يظهر أثره في البوت
مباشرة بلا أي endpoint إضافي.

كل الطلبات هنا محمية بمفتاح سري مشترك (DASHBOARD_API_SECRET) يُرسَل في هيدر
X-Api-Key، ويجب أن تبقى لوحة التحكم وحدها من يعرف هذا المفتاح (لا يُكشف للمتصفح).
"""

from __future__ import annotations

import os
from typing import Any

import discord
from aiohttp import web

import db

API_SECRET = os.getenv("DASHBOARD_API_SECRET", "").strip()


def _check_auth(request: web.Request) -> bool:
    if not API_SECRET:
        # لا تشغّل الـ API إطلاقاً بدون مفتاح سري مضبوط، حماية من أي استخدام غير مقصود.
        return False
    return request.headers.get("X-Api-Key", "") == API_SECRET


def _error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


def register_dashboard_routes(app: web.Application, bot: Any) -> None:
    """يضيف مسارات لوحة التحكم إلى تطبيق aiohttp الموجود أصلاً داخل البوت."""

    async def auth_middleware(request: web.Request, handler):
        if request.path.startswith("/api/") and not _check_auth(request):
            return _error("غير مصرّح. تحقق من DASHBOARD_API_SECRET.", 401)
        return await handler(request)

    app.middlewares.append(auth_middleware)

    def get_guild(guild_id: str) -> discord.Guild | None:
        try:
            return bot.get_guild(int(guild_id))
        except ValueError:
            return None

    # ---------------------------------------------------------------- عام
    async def list_guilds(request: web.Request) -> web.Response:
        data = [
            {
                "id": str(guild.id),
                "name": guild.name,
                "icon": str(guild.icon.url) if guild.icon else None,
                "member_count": guild.member_count,
            }
            for guild in bot.guilds
        ]
        return web.json_response({"ok": True, "guilds": data})

    async def guild_overview(request: web.Request) -> web.Response:
        guild = get_guild(request.match_info["guild_id"])
        if guild is None:
            return _error("لم أجد هذا السيرفر ضمن سيرفرات البوت.", 404)
        channels = [
            {"id": str(c.id), "name": c.name, "type": "text"}
            for c in guild.text_channels
        ]
        voice_channels = [{"id": str(c.id), "name": c.name} for c in guild.voice_channels]
        categories = [{"id": str(c.id), "name": c.name} for c in guild.categories]
        roles = [
            {"id": str(r.id), "name": r.name, "color": str(r.color)}
            for r in reversed(guild.roles)
            if not r.is_default() and not r.managed
        ]
        emojis = [
            {"id": str(e.id), "name": e.name, "url": str(e.url), "animated": e.animated}
            for e in guild.emojis
        ]
        return web.json_response(
            {
                "ok": True,
                "id": str(guild.id),
                "name": guild.name,
                "icon": str(guild.icon.url) if guild.icon else None,
                "member_count": guild.member_count,
                "channels": channels,
                "voice_channels": voice_channels,
                "categories": categories,
                "roles": roles,
                "emojis": emojis,
            }
        )

    async def find_member(request: web.Request) -> web.Response:
        guild = get_guild(request.match_info["guild_id"])
        if guild is None:
            return _error("لم أجد هذا السيرفر.", 404)
        query = request.query.get("q", "").strip().lower()
        if not query:
            return web.json_response({"ok": True, "members": []})
        results = []
        for member in guild.members:
            if query in member.name.lower() or query in member.display_name.lower() or query == str(member.id):
                results.append(
                    {
                        "id": str(member.id),
                        "name": member.name,
                        "display_name": member.display_name,
                        "avatar": str(member.display_avatar.url),
                    }
                )
            if len(results) >= 15:
                break
        return web.json_response({"ok": True, "members": results})

    # ------------------------------------------------------------ التذاكر
    async def publish_ticket_panel(request: web.Request) -> web.Response:
        guild = get_guild(request.match_info["guild_id"])
        if guild is None:
            return _error("لم أجد هذا السيرفر.", 404)
        payload = await request.json()
        channel = guild.get_channel(int(payload.get("channel_id", 0)))
        if not isinstance(channel, discord.TextChannel):
            return _error("قناة غير صحيحة.")

        from spectre_bot_latest import TicketCreateView, parse_emoji  # استيراد متأخر لتفادي حلقة استيراد

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
        image_url = payload.get("image_url")
        if image_url:
            embed.set_image(url=image_url)
        view = TicketCreateView(emoji, label, style)
        bot.add_view(view)
        message = await channel.send(embed=embed, view=view)
        return web.json_response({"ok": True, "message_id": str(message.id), "channel_id": str(channel.id)})

    # ------------------------------------------------------------ التقديم
    async def publish_apply_panel(request: web.Request) -> web.Response:
        guild = get_guild(request.match_info["guild_id"])
        if guild is None:
            return _error("لم أجد هذا السيرفر.", 404)
        payload = await request.json()
        channel = guild.get_channel(int(payload.get("channel_id", 0)))
        if not isinstance(channel, discord.TextChannel):
            return _error("قناة غير صحيحة.")

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
        return web.json_response({"ok": True, "message_id": str(message.id), "channel_id": str(channel.id)})

    # -------------------------------------------------------- Embed حر
    async def send_embed(request: web.Request) -> web.Response:
        guild = get_guild(request.match_info["guild_id"])
        if guild is None:
            return _error("لم أجد هذا السيرفر.", 404)
        payload = await request.json()
        channel = guild.get_channel(int(payload.get("channel_id", 0)))
        if not isinstance(channel, discord.TextChannel):
            return _error("قناة غير صحيحة.")

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
        return web.json_response({"ok": True, "message_id": str(message.id)})

    # --------------------------------------------------- الرولات الذاتية
    async def create_reaction_role_message(request: web.Request) -> web.Response:
        guild = get_guild(request.match_info["guild_id"])
        if guild is None:
            return _error("لم أجد هذا السيرفر.", 404)
        payload = await request.json()
        channel = guild.get_channel(int(payload.get("channel_id", 0)))
        if not isinstance(channel, discord.TextChannel):
            return _error("قناة غير صحيحة.")
        embed = discord.Embed(
            title=payload.get("title") or "اختر رتبتك",
            description=payload.get("description") or "اضغط الإيموجي المناسب لأخذ الرتبة.",
            color=discord.Color.blurple(),
        )
        message = await channel.send(embed=embed)
        return web.json_response({"ok": True, "message_id": str(message.id), "channel_id": str(channel.id)})

    async def link_reaction_role(request: web.Request) -> web.Response:
        guild = get_guild(request.match_info["guild_id"])
        if guild is None:
            return _error("لم أجد هذا السيرفر.", 404)
        payload = await request.json()
        try:
            message_id = int(payload["message_id"])
            role_id = int(payload["role_id"])
        except (KeyError, ValueError):
            return _error("بيانات غير صحيحة.")
        emoji_raw = str(payload.get("emoji", "")).strip()
        if not emoji_raw:
            return _error("حدد إيموجي.")

        from spectre_bot_latest import parse_emoji, emoji_key

        target_message = None
        for channel in guild.text_channels:
            try:
                target_message = await channel.fetch_message(message_id)
                break
            except (discord.NotFound, discord.Forbidden):
                continue
        if target_message is None:
            return _error("لم أجد الرسالة.", 404)
        role = guild.get_role(role_id)
        if role is None:
            return _error("لم أجد الرتبة.", 404)
        try:
            await target_message.add_reaction(parse_emoji(emoji_raw))
        except discord.HTTPException:
            return _error("تعذّر إضافة هذا الإيموجي.")
        db.add_reaction_role(guild.id, target_message.channel.id, target_message.id, emoji_key(emoji_raw), role.id)
        return web.json_response({"ok": True})

    # -------------------------------------------------------------- الخبرة
    async def adjust_xp(request: web.Request) -> web.Response:
        guild = get_guild(request.match_info["guild_id"])
        if guild is None:
            return _error("لم أجد هذا السيرفر.", 404)
        payload = await request.json()
        try:
            user_id = int(payload["user_id"])
            amount = int(payload["amount"])
        except (KeyError, ValueError):
            return _error("بيانات غير صحيحة.")
        if amount == 0:
            return _error("الكمية لا يمكن أن تكون صفراً.")
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
        return web.json_response({"ok": True, "level": new_level, "xp": new_xp})

    async def transfer_xp(request: web.Request) -> web.Response:
        guild = get_guild(request.match_info["guild_id"])
        if guild is None:
            return _error("لم أجد هذا السيرفر.", 404)
        payload = await request.json()
        try:
            old_user_id = int(payload["old_user_id"])
            new_user_id = int(payload["new_user_id"])
        except (KeyError, ValueError):
            return _error("بيانات غير صحيحة.")
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
        return web.json_response({"ok": True, "level": new_level, "xp": new_xp})

    # ----------------------------------------------------------- الإدارة
    async def mod_action(request: web.Request) -> web.Response:
        guild = get_guild(request.match_info["guild_id"])
        if guild is None:
            return _error("لم أجد هذا السيرفر.", 404)
        payload = await request.json()
        action = payload.get("action")
        reason = payload.get("reason") or "بواسطة لوحة التحكم"
        try:
            user_id = int(payload["user_id"])
        except (KeyError, ValueError):
            return _error("بيانات غير صحيحة.")
        member = guild.get_member(user_id)

        from spectre_bot_latest import send_mod_log
        from datetime import timedelta

        try:
            if action == "kick":
                if not member:
                    return _error("العضو غير موجود في السيرفر.", 404)
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
                    return _error("العضو غير موجود في السيرفر.", 404)
                minutes = int(payload.get("minutes", 10))
                await member.timeout(timedelta(minutes=minutes), reason=reason)
                await send_mod_log(guild, discord.Embed(title="⏱️ تايم أوت (من لوحة التحكم)", description=f"**العضو:** {member.mention} (`{member.id}`)\n**المدة:** {minutes} دقيقة\n**السبب:** {reason}", color=discord.Color.orange()))
            elif action == "untimeout":
                if not member:
                    return _error("العضو غير موجود في السيرفر.", 404)
                await member.timeout(None, reason=reason)
                await send_mod_log(guild, discord.Embed(title="✅ إلغاء تايم أوت (من لوحة التحكم)", description=f"**العضو:** {member.mention} (`{member.id}`)", color=discord.Color.green()))
            else:
                return _error("إجراء غير معروف.")
        except discord.Forbidden:
            return _error("صلاحيات البوت غير كافية لتنفيذ هذا الإجراء.", 403)
        return web.json_response({"ok": True})

    # -------------------------------------------------------------- المسابقات
    async def create_giveaway_api(request: web.Request) -> web.Response:
        """ينشر مسابقة فورية من لوحة التحكم — نفس منطق أمر `!مسابقة` بالضبط،
        لكن يُستدعى مباشرة عبر HTTP بدل أمر نصي، حتى يقدر الأدمن ينشئ مسابقة
        من المتصفح مباشرة."""
        guild = get_guild(request.match_info["guild_id"])
        if guild is None:
            return _error("لم أجد هذا السيرفر.", 404)
        payload = await request.json()
        channel = guild.get_channel(int(payload.get("channel_id", 0)))
        if not isinstance(channel, discord.TextChannel):
            return _error("قناة غير صحيحة.")

        from spectre_bot_latest import parse_duration
        from datetime import datetime, timedelta, timezone

        seconds = parse_duration(str(payload.get("duration", "")))
        if seconds is None or seconds < 10:
            return _error("صيغة المدة غير صحيحة. أمثلة: 30s، 10m، 2h، 1d.")
        winners_count = max(1, int(payload.get("winners", 1)))
        prize = str(payload.get("prize", "")).strip()
        if not prize:
            return _error("اكتب اسم الجائزة.")

        ends_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        embed = discord.Embed(
            title="🎉 مسابقة جديدة!",
            description=f"**الجائزة:** {prize}\n**عدد الفائزين:** {winners_count}\n**تنتهي:** <t:{int(ends_at.timestamp())}:R>\n\nاضغط 🎉 للمشاركة!",
            color=discord.Color.gold(),
        )
        message = await channel.send(embed=embed)
        await message.add_reaction("🎉")
        db.create_giveaway(guild.id, channel.id, message.id, prize, winners_count, guild.owner_id or 0, ends_at.isoformat())
        return web.json_response({"ok": True, "message_id": str(message.id)})

    app.router.add_get("/api/guilds", list_guilds)
    app.router.add_get("/api/guilds/{guild_id}/overview", guild_overview)
    app.router.add_get("/api/guilds/{guild_id}/members", find_member)
    app.router.add_post("/api/guilds/{guild_id}/ticket-panel", publish_ticket_panel)
    app.router.add_post("/api/guilds/{guild_id}/apply-panel", publish_apply_panel)
    app.router.add_post("/api/guilds/{guild_id}/embed", send_embed)
    app.router.add_post("/api/guilds/{guild_id}/reaction-role-message", create_reaction_role_message)
    app.router.add_post("/api/guilds/{guild_id}/reaction-role-link", link_reaction_role)
    app.router.add_post("/api/guilds/{guild_id}/xp-adjust", adjust_xp)
    app.router.add_post("/api/guilds/{guild_id}/xp-transfer", transfer_xp)
    app.router.add_post("/api/guilds/{guild_id}/mod-action", mod_action)
    app.router.add_post("/api/guilds/{guild_id}/giveaway", create_giveaway_api)
