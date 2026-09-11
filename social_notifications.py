"""مصادر إشعارات المحتوى الجديد لـ Spectre.

YouTube يستخدم WebSub/RSS-compatible feed بدون API key، بينما Twitch وKick
يستخدمان yt-dlp لاستخراج حالة البث العامة عند الفحص الدوري. لا تُحفظ أي أسرار
في هذا الملف؛ الإعدادات تُحفظ في SQLite عبر db.py.
"""

from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import aiohttp
import discord

import db

SUPPORTED_PLATFORMS = {"youtube", "twitch", "kick"}
DEFAULT_MESSAGE = "📢 {platform}: {title}"
DEFAULT_COLOR = 0x2CA77A
YT_NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def platform_from_url(url: str) -> str | None:
    host = (urlparse(url.strip()).hostname or "").lower().removeprefix("www.")
    if host in {"youtube.com", "youtu.be"} or host.endswith(".youtube.com"):
        return "youtube"
    if host in {"twitch.tv", "m.twitch.tv"} or host.endswith(".twitch.tv"):
        return "twitch"
    if host == "kick.com" or host.endswith(".kick.com"):
        return "kick"
    return None


def _validate_channel_url(platform: str, url: str) -> None:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if platform == "youtube":
        valid = bool(parts) and ((parts[0] == "channel" and len(parts) == 2) or (parts[0] in {"c", "user"} and len(parts) == 2) or (parts[0].startswith("@") and len(parts) == 1))
        if not valid:
            raise ValueError("استخدم رابط قناة YouTube مثل https://www.youtube.com/@name أو /channel/UC... فقط")
    elif platform == "twitch":
        if len(parts) != 1 or parts[0].lower() in {"directory", "videos", "clips", "downloads", "p"}:
            raise ValueError("استخدم رابط قناة Twitch مثل https://www.twitch.tv/channel_name وليس رابط بث أو مقطع")
    elif platform == "kick":
        if len(parts) != 1 or parts[0].lower() in {"categories", "videos", "search", "discover"}:
            raise ValueError("استخدم رابط قناة Kick مثل https://kick.com/channel_name وليس رابط بث")


def normalize_source(platform: str, url: str, channel_id: int, mention: str = "", message: str = DEFAULT_MESSAGE, color: int = DEFAULT_COLOR) -> dict[str, Any]:
    platform = platform.strip().lower()
    url = url.strip().rstrip("/")
    detected = platform_from_url(url)
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError("المنصة يجب أن تكون youtube أو twitch أو kick")
    if detected != platform:
        raise ValueError("الرابط لا يطابق المنصة المحددة")
    if not url.startswith(("https://", "http://")):
        raise ValueError("يجب استخدام رابط HTTPS صالح")
    if not channel_id:
        raise ValueError("يجب تحديد قناة Discord للإشعار")
    _validate_channel_url(platform, url)
    clean_message = (message or DEFAULT_MESSAGE).strip()[:2500] or DEFAULT_MESSAGE
    if "@everyone" in mention or "@here" in mention:
        raise ValueError("منشن everyone وhere غير مسموح بهما")
    return {
        "platform": platform,
        "url": url,
        "channel_id": int(channel_id),
        "mention": mention.strip()[:300],
        "message": clean_message,
        "color": max(0, min(int(color), 0xFFFFFF)),
        "enabled": True,
        "last_event_id": "",
        "last_state": "offline",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _youtube_channel_id(url: str) -> str | None:
    path = urlparse(url).path.strip("/")
    match = re.match(r"channel/([A-Za-z0-9_-]{10,})", path)
    return match.group(1) if match else None


def _resolve_youtube_channel_id_sync(url: str) -> str | None:
    try:
        import yt_dlp
        options = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
        resolved = str(info.get("channel_id") or "").strip() if info else ""
        if resolved.startswith("UC"):
            return resolved
    except Exception:
        pass
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SpectreBot/1.0)"})
        with urlopen(request, timeout=15) as response:
            html = response.read().decode("utf-8", errors="ignore")
        for pattern in (r'"channelId":"(UC[A-Za-z0-9_-]+)"', r'"externalId":"(UC[A-Za-z0-9_-]+)"', r'channel_id=(UC[A-Za-z0-9_-]+)'):
            match = re.search(pattern, html)
            if match:
                return match.group(1)
    except Exception:
        return None
    return None


async def _youtube_latest(url: str) -> dict[str, Any] | None:
    channel_id = _youtube_channel_id(url)
    if not channel_id:
        channel_id = await asyncio.to_thread(_resolve_youtube_channel_id_sync, url)
    if not channel_id:
        raise ValueError("تعذر استخراج Channel ID من رابط YouTube؛ استخدم رابط القناة /channel/UC... أو رابط @handle صالح")
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "SpectreBot/1.0"}) as session:
        async with session.get(feed_url) as response:
            if response.status != 200:
                raise RuntimeError(f"تعذر قراءة موجز YouTube (HTTP {response.status})")
            body = await response.text()
    root = ET.fromstring(body)
    entry = root.find("atom:entry", YT_NS)
    if entry is None:
        return None
    video_id = (entry.findtext("yt:videoId", default="", namespaces=YT_NS) or "").strip()
    title = (entry.findtext("atom:title", default="فيديو جديد", namespaces=YT_NS) or "فيديو جديد").strip()
    author = (entry.findtext("atom:author/atom:name", default="YouTube", namespaces=YT_NS) or "YouTube").strip()
    published = (entry.findtext("atom:published", default="", namespaces=YT_NS) or "").strip()
    if not video_id:
        return None
    return {"id": video_id, "title": title, "author": author, "url": f"https://www.youtube.com/watch?v={video_id}", "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg", "published": published, "status": "new"}


def _extract_live_sync(url: str) -> dict[str, Any]:
    try:
        import yt_dlp
    except ImportError as error:
        raise RuntimeError("دعم Twitch وKick يحتاج تثبيت yt-dlp من requirements.txt") from error
    options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "extract_flat": False}
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)
    if not info:
        return {"live": False}
    is_live = bool(info.get("is_live") or info.get("live_status") == "is_live")
    if not is_live:
        return {"live": False, "id": str(info.get("id") or "")}
    stream_id = str(info.get("id") or info.get("display_id") or "live")
    return {
        "live": True,
        "id": stream_id,
        "title": str(info.get("title") or "بث مباشر جديد"),
        "author": str(info.get("uploader") or info.get("channel") or "البث المباشر"),
        "url": str(info.get("webpage_url") or url),
        "thumbnail": str(info.get("thumbnail") or ""),
        "status": "live",
    }


async def _latest(source: dict[str, Any]) -> dict[str, Any] | None:
    if source["platform"] == "youtube":
        return await _youtube_latest(source["url"])
    return await asyncio.to_thread(_extract_live_sync, source["url"])


def _is_recent_youtube_item(item: dict[str, Any], window_minutes: int = 10) -> bool:
    published = str(item.get("published") or "").strip()
    if not published:
        return False
    try:
        published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - published_at
        return timedelta(seconds=0) <= age <= timedelta(minutes=window_minutes)
    except ValueError:
        return False


def _render(text: str, item: dict[str, Any], platform: str) -> str:
    replacements = {
        "{title}": item.get("title", ""),
        "{author}": item.get("author", ""),
        "{url}": item.get("url", ""),
        "{platform}": platform,
        "{status}": "بث مباشر" if item.get("status") == "live" else "فيديو جديد",
    }
    for key, value in replacements.items():
        text = text.replace(key, str(value))
    return text[:2500]


async def _send_embed(guild: discord.Guild, source: dict[str, Any], item: dict[str, Any]) -> None:
    channel = guild.get_channel(int(source["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        raise RuntimeError("قناة الإشعار غير موجودة أو ليست قناة نصية")
    platform_labels = {"youtube": "YouTube", "twitch": "Twitch", "kick": "Kick"}
    platform = platform_labels.get(source["platform"], source["platform"])
    embed = discord.Embed(
        title=_render(str(item.get("title") or "محتوى جديد"), item, platform)[:256],
        description=_render(str(source.get("message") or DEFAULT_MESSAGE), item, platform),
        url=str(item.get("url") or source["url"]),
        color=int(source.get("color") or DEFAULT_COLOR),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"Spectre • {platform}")
    thumbnail = str(item.get("thumbnail") or "")
    if thumbnail.startswith(("https://", "http://")):
        embed.set_thumbnail(url=thumbnail)
    mention = str(source.get("mention") or "").strip()
    await channel.send(content=mention or None, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False))


async def poll_source(guild: discord.Guild, source: dict[str, Any]) -> bool:
    if not source.get("enabled", True):
        return False
    item = await _latest(source)
    if source["platform"] != "youtube":
        is_live = bool(item and item.get("live"))
        if not is_live:
            source["last_state"] = "offline"
            return True
        event_id = str(item.get("id") or "live")
        if source.get("last_state") == "online" and source.get("last_event_id") == event_id:
            return False
        await _send_embed(guild, source, item)
        source["last_event_id"] = event_id
        source["last_state"] = "online"
        return True
    if not item:
        return False
    event_id = str(item["id"])
    if not source.get("last_event_id"):
        source["last_event_id"] = event_id
        if _is_recent_youtube_item(item):
            await _send_embed(guild, source, item)
        return True
    if source["last_event_id"] == event_id:
        return False
    await _send_embed(guild, source, item)
    source["last_event_id"] = event_id
    return True


async def poll_all(bot: discord.Client) -> None:
    for guild in bot.guilds:
        sources = db.get_social_sources(guild.id)
        changed = False
        for source in sources:
            try:
                changed = await poll_source(guild, source) or changed
            except Exception as error:
                print(f"[SocialNotifications] {guild.id}/{source.get('platform')}: {error}")
        if changed:
            db.save_social_sources(guild.id, sources)
