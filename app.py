"""لوحة تحكم Spectre (Flask) — النسخة المدمجة.

تعمل هذي النسخة بخيط (Thread) داخل نفس عملية البوت — وليست عملية منفصلة تحتاج
منفذاً ورابطاً داخلياً بينها وبين البوت. هذا يحل مشكلة حقيقية واجهناها مع
استضافات مثل Wispbyte التي تخصص منفذاً خارجياً واحداً فقط لكل سيرفر، فيصعب
تشغيل خدمتين منفصلتين تتواصلان عبر الشبكة.

كل استدعاء يحتاج تنفيذاً حياً على ديسكورد (نشر رسالة، طرد عضو...) يمر عبر
`call_bot(coro)` التي ترسل المهمة لحلقة أحداث البوت (asyncio event loop) بأمان
من هذا الخيط المنفصل، وتنتظر النتيجة — هذا هو الجسر الآمن الوحيد المسموح بين
خيط Flask (متزامن تقليدي) وخيط البوت (غير متزامن asyncio)؛ استدعاء دوال
discord.py مباشرة من هذا الملف بدون المرور من هذا الجسر يسبب أخطاء عشوائية
لأن discord.py غير آمن للاستخدام من خيوط متعددة مباشرة.
"""

from __future__ import annotations

import asyncio
import secrets
import os
import sys
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Flask, redirect, render_template, request, session, url_for, jsonify
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402
import bot_actions  # noqa: E402

load_dotenv(ROOT / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET_KEY", "").strip() or os.urandom(32)


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "").strip()
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
DASHBOARD_REDIRECT_URI = os.getenv("DASHBOARD_REDIRECT_URI", "").strip()

DISCORD_API = "https://discord.com/api/v10"
MANAGE_GUILD = 0x20

db.init_db()

_bot_instance: Any = None
_bot_loop: asyncio.AbstractEventLoop | None = None


def call_bot(coro):
    """يرسل Coroutine لحلقة أحداث البوت من خيط Flask المنفصل، وينتظر النتيجة."""
    if _bot_instance is None or _bot_loop is None:
        raise RuntimeError("الداشبورد ما زالت غير مربوطة بالبوت — شغّلها عبر bot.py وليس مباشرة.")
    future = asyncio.run_coroutine_threadsafe(coro, _bot_loop)
    return future.result(timeout=25)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("guild_picker"))
    return render_template("index.html")


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "bot_connected": _bot_instance is not None and _bot_instance.is_ready()})


@app.route("/login")
def login():
    if not DISCORD_CLIENT_ID or not DASHBOARD_REDIRECT_URI:
        return "لوحة التحكم غير مُهيّأة بعد: أضف DISCORD_CLIENT_ID و DASHBOARD_REDIRECT_URI في .env", 500
    import urllib.parse
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DASHBOARD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
    }
    query = urllib.parse.urlencode(params)
    return redirect(f"https://discord.com/oauth2/authorize?{query}")


@app.route("/callback")
def callback():
    import requests

    code = request.args.get("code")
    state = request.args.get("state", "")
    expected_state = session.pop("oauth_state", "")
    if not code:
        return redirect(url_for("index"))
    if not expected_state or not secrets.compare_digest(state, expected_state):
        return "طلب تسجيل الدخول غير صالح أو انتهت صلاحيته. أعد المحاولة.", 400
    token_response = requests.post(
        f"{DISCORD_API}/oauth2/token",
        data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DASHBOARD_REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if token_response.status_code != 200:
        return "فشل تسجيل الدخول عبر ديسكورد. حاول مرة أخرى.", 400
    token_data = token_response.json()
    access_token = token_data["access_token"]

    user_response = requests.get(f"{DISCORD_API}/users/@me", headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    guilds_response = requests.get(f"{DISCORD_API}/users/@me/guilds", headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    if user_response.status_code != 200 or guilds_response.status_code != 200:
        return "تعذّر جلب بيانات حسابك من ديسكورد.", 400

    user = user_response.json()
    manageable_guild_ids = [
        guild["id"] for guild in guilds_response.json() if (int(guild.get("permissions", 0)) & MANAGE_GUILD) == MANAGE_GUILD
    ]

    session["user"] = {
        "id": user["id"],
        "username": user.get("global_name") or user["username"],
        "avatar": (
            f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.png"
            if user.get("avatar")
            else "https://cdn.discordapp.com/embed/avatars/0.png"
        ),
    }
    session["manageable_guild_ids"] = manageable_guild_ids
    return redirect(url_for("guild_picker"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def guild_picker():
    try:
        bot_guilds = call_bot(_list_guilds_coro())
        api_error = None
    except Exception as error:
        bot_guilds = []
        api_error = str(error)
    allowed_ids = set(session.get("manageable_guild_ids", []))
    guilds = [guild for guild in bot_guilds if guild["id"] in allowed_ids]
    return render_template("guild_picker.html", guilds=guilds, api_error=api_error)


async def _list_guilds_coro():
    return bot_actions.list_guilds(_bot_instance)


def guild_or_403(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return None
    try:
        return call_bot(_guild_overview_coro(int(guild_id)))
    except Exception:
        return None


async def _guild_overview_coro(guild_id: int):
    return bot_actions.guild_overview(_bot_instance, guild_id)


TABS = [
    ("🏠 الرئيسية والإعدادات", "general"),
    ("📝 الرسائل و Embed", "messages"),
    ("🎫 التذاكر", "tickets"),
    ("🛡️ التقديم للإدارة", "applications"),
    ("🎭 الرولات الذاتية", "reaction_roles"),
    ("⚡ الأتمتة والردود", "automation"),
    ("👋 الترحيب", "welcome"),
    ("📈 اللفلات والخبرة", "leveling"),
    ("🛡️ الحماية — Anti-Nuke", "antinuke"),
    ("🚨 الحماية المتقدمة", "advanced_security"),
    ("🔨 الإشراف", "moderation"),
    ("⭐ المجتمع والمسابقات", "extras"),
    ("📡 التنبيهات الاجتماعية", "social"),
    ("🕋 القرآن والأذكار", "spiritual"),
    ("🎮 الألعاب و Counting", "games"),
    ("📋 سجل الإدارة", "modlog"),
]

ANTINUKE_PERMISSION_CHOICES = [
    ("administrator", "أدمنستريتور (تحكم كامل)"),
    ("ban_members", "حظر أعضاء"),
    ("kick_members", "طرد أعضاء"),
    ("manage_guild", "إدارة السيرفر"),
    ("manage_roles", "إدارة الرتب"),
    ("manage_channels", "إدارة الرومات"),
    ("manage_webhooks", "إدارة الويبهوكس"),
    ("manage_messages", "إدارة الرسائل"),
    ("mention_everyone", "منشن الكل @everyone"),
    ("moderate_members", "تايم أوت الأعضاء"),
]


@app.route("/dashboard/<guild_id>")
@app.route("/dashboard/<guild_id>/<tab>")
@login_required
def guild_dashboard(guild_id: str, tab: str = "general"):
    overview = guild_or_403(guild_id)
    if overview is None:
        return redirect(url_for("guild_picker"))
    settings = db.get_guild_settings(int(guild_id))
    context = {"guild": overview, "guild_id": guild_id, "tabs": TABS, "active_tab": tab, "settings": settings}
    if tab == "leveling":
        context["level_roles"] = db.get_level_roles(int(guild_id))
    if tab == "auto_responses":
        context["auto_responses"] = db.get_auto_responses(int(guild_id))
    if tab == "antinuke":
        import json as json_module
        context["antinuke_permission_choices"] = ANTINUKE_PERMISSION_CHOICES
        context["banned_words"] = json_module.loads(settings.get("antinuke_banned_words_json") or "[]")
        context["dangerous_perms"] = json_module.loads(settings.get("antinuke_dangerous_perms_json") or "[]")
        context["phishing_domains"] = json_module.loads(settings.get("antiphishing_domains_json") or "[]")
        context["whitelist_ids"] = json_module.loads(settings.get("antinuke_whitelist_json") or "[]")
        context["bot_whitelist_ids"] = json_module.loads(settings.get("antinuke_bot_whitelist_json") or "[]")
    if tab == "messages":
        context["faqs"] = db.get_faqs(int(guild_id))
        context["panels"] = db.get_panels(int(guild_id))
    if tab == "automation":
        context["auto_responses"] = db.get_auto_responses(int(guild_id))
        context["presence"] = db.get_presence_config()
    if tab == "social":
        context["social_sources"] = db.get_social_sources(int(guild_id))
    if tab == "spiritual":
        context["adhkar"] = db.get_adhkar_config(int(guild_id))
    if tab == "games":
        context["games_config"] = db.get_games_config(int(guild_id))
        context["counting_channels"] = db.get_counting_channels(int(guild_id))
    if tab == "welcome":
        context["welcome_config"] = db.get_welcome_config(int(guild_id))
    template = f"tabs/{tab}.html"
    if not (Path(__file__).parent / "templates" / template).is_file():
        template = "tabs/general.html"
        tab = "general"
    return render_template("guild_dashboard.html", template=template, **context)


@app.route("/dashboard/<guild_id>/save-settings", methods=["POST"])
@login_required
def save_settings(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    payload = request.get_json(force=True)
    allowed_keys = set(db.DEFAULT_SETTINGS.keys())
    saved = []
    for key, value in payload.items():
        if key in allowed_keys:
            db.set_guild_setting(int(guild_id), key, value)
            saved.append(key)
    return jsonify({"ok": True, "saved": saved})


@app.route("/dashboard/<guild_id>/level-roles", methods=["POST"])
@login_required
def save_level_role(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    payload = request.get_json(force=True)
    try:
        level = int(payload["level"])
        role_id = int(payload["role_id"])
    except (KeyError, ValueError):
        return jsonify({"ok": False, "error": "بيانات غير صحيحة"}), 400
    db.add_level_role(int(guild_id), level, role_id)
    return jsonify({"ok": True})


@app.route("/dashboard/<guild_id>/auto-responses", methods=["POST"])
@login_required
def add_auto_response(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    payload = request.get_json(force=True)
    trigger = (payload.get("trigger") or "").strip()
    response_text = (payload.get("response") or "").strip()
    if not trigger or not response_text:
        return jsonify({"ok": False, "error": "أدخل العبارة والرد."}), 400
    match_type = "contains" if payload.get("match_type") == "contains" else "exact"
    response_id = db.add_auto_response(int(guild_id), trigger, response_text, match_type)
    return jsonify({"ok": True, "id": response_id})


@app.route("/dashboard/<guild_id>/auto-responses/<int:response_id>", methods=["DELETE"])
@login_required
def delete_auto_response(guild_id: str, response_id: int):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    removed = db.remove_auto_response(int(guild_id), response_id)
    return jsonify({"ok": removed})


@app.route("/dashboard/<guild_id>/antinuke/banned-words", methods=["POST"])
@login_required
def add_banned_word_route(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    import json as json_module
    word = (request.get_json(force=True).get("word") or "").strip().lower()
    if not word:
        return jsonify({"ok": False, "error": "اكتب كلمة."}), 400
    settings = db.get_guild_settings(int(guild_id))
    words = json_module.loads(settings.get("antinuke_banned_words_json") or "[]")
    if word not in words:
        words.append(word)
        db.set_guild_setting(int(guild_id), "antinuke_banned_words_json", json_module.dumps(words, ensure_ascii=False))
    return jsonify({"ok": True, "words": words})


@app.route("/dashboard/<guild_id>/antinuke/banned-words", methods=["DELETE"])
@login_required
def remove_banned_word_route(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    import json as json_module
    word = (request.get_json(force=True).get("word") or "").strip().lower()
    settings = db.get_guild_settings(int(guild_id))
    words = json_module.loads(settings.get("antinuke_banned_words_json") or "[]")
    if word in words:
        words.remove(word)
        db.set_guild_setting(int(guild_id), "antinuke_banned_words_json", json_module.dumps(words, ensure_ascii=False))
    return jsonify({"ok": True, "words": words})


@app.route("/dashboard/<guild_id>/antiphishing/domains", methods=["POST"])
@login_required
def add_phishing_domain_route(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    import json as json_module
    domain = (request.get_json(force=True).get("domain") or "").strip().lower()
    domain = domain.removeprefix("http://").removeprefix("https://").split("/")[0]
    if not domain:
        return jsonify({"ok": False, "error": "اكتب نطاقاً صحيحاً."}), 400
    settings = db.get_guild_settings(int(guild_id))
    domains = json_module.loads(settings.get("antiphishing_domains_json") or "[]")
    if domain not in domains:
        domains.append(domain)
        db.set_guild_setting(int(guild_id), "antiphishing_domains_json", json_module.dumps(domains))
    return jsonify({"ok": True, "domains": domains})


@app.route("/dashboard/<guild_id>/antiphishing/domains", methods=["DELETE"])
@login_required
def remove_phishing_domain_route(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    import json as json_module
    domain = (request.get_json(force=True).get("domain") or "").strip().lower()
    settings = db.get_guild_settings(int(guild_id))
    domains = json_module.loads(settings.get("antiphishing_domains_json") or "[]")
    if domain in domains:
        domains.remove(domain)
        db.set_guild_setting(int(guild_id), "antiphishing_domains_json", json_module.dumps(domains))
    return jsonify({"ok": True, "domains": domains})


@app.route("/dashboard/<guild_id>/antinuke/whitelist", methods=["POST"])
@login_required
def add_whitelist_route(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    import json as json_module
    payload = request.get_json(force=True)
    kind = payload.get("kind", "member")
    try:
        target_id = int(payload["id"])
    except (KeyError, ValueError):
        return jsonify({"ok": False, "error": "آيدي غير صحيح."}), 400
    key = "antinuke_bot_whitelist_json" if kind == "bot" else "antinuke_whitelist_json"
    settings = db.get_guild_settings(int(guild_id))
    ids = json_module.loads(settings.get(key) or "[]")
    if target_id not in ids:
        ids.append(target_id)
        db.set_guild_setting(int(guild_id), key, json_module.dumps(ids))
    return jsonify({"ok": True, "ids": ids})


@app.route("/dashboard/<guild_id>/antinuke/whitelist", methods=["DELETE"])
@login_required
def remove_whitelist_route(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    import json as json_module
    payload = request.get_json(force=True)
    kind = payload.get("kind", "member")
    try:
        target_id = int(payload["id"])
    except (KeyError, ValueError):
        return jsonify({"ok": False, "error": "آيدي غير صحيح."}), 400
    key = "antinuke_bot_whitelist_json" if kind == "bot" else "antinuke_whitelist_json"
    settings = db.get_guild_settings(int(guild_id))
    ids = json_module.loads(settings.get(key) or "[]")
    if target_id in ids:
        ids.remove(target_id)
        db.set_guild_setting(int(guild_id), key, json_module.dumps(ids))
    return jsonify({"ok": True, "ids": ids})



@app.route("/dashboard/<guild_id>/save-json/<config_name>", methods=["POST"])
@login_required
def save_json_config(guild_id: str, config_name: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    payload = request.get_json(force=True) or {}
    gid = int(guild_id)
    if config_name == "welcome":
        db.save_welcome_config(gid, payload)
        if "channel_id" in payload:
            db.set_guild_setting(gid, "welcome_channel_id", int(payload.get("channel_id") or 0) or None)
        if "enabled" in payload:
            db.set_guild_setting(gid, "welcome_enabled", bool(payload.get("enabled")))
    elif config_name == "games":
        db.save_games_config(gid, payload)
    elif config_name == "adhkar":
        db.save_adhkar_config(gid, payload)
    elif config_name == "social":
        db.save_social_sources(gid, payload if isinstance(payload, list) else [])
    else:
        return jsonify({"ok": False, "error": "إعداد غير معروف"}), 404
    return jsonify({"ok": True})


@app.route("/dashboard/<guild_id>/social", methods=["POST"])
@login_required
def add_social(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    import social_notifications
    payload = request.get_json(force=True) or {}
    try:
        source = social_notifications.normalize_source(
            payload.get("platform", ""),
            payload.get("url", ""),
            int(payload.get("channel_id", 0)),
            payload.get("mention", ""),
            payload.get("message", social_notifications.DEFAULT_MESSAGE),
            int(str(payload.get("color", "2ca77a")).lstrip("#"), 16),
        )
    except (TypeError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    sources = db.get_social_sources(int(guild_id))
    sources = [x for x in sources if not (x.get("platform") == source["platform"] and x.get("url") == source["url"])]
    sources.append(source)
    db.save_social_sources(int(guild_id), sources)
    return jsonify({"ok": True, "source": source, "sources": sources})


@app.route("/dashboard/<guild_id>/social", methods=["DELETE"])
@login_required
def delete_social(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    payload = request.get_json(force=True) or {}
    url = str(payload.get("url", "")).strip()
    sources = [x for x in db.get_social_sources(int(guild_id)) if x.get("url") != url]
    db.save_social_sources(int(guild_id), sources)
    return jsonify({"ok": True, "sources": sources})


@app.route("/dashboard/<guild_id>/adhkar-now", methods=["POST"])
@login_required
def adhkar_now(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    category = (request.get_json(force=True) or {}).get("category", "morning")
    try:
        from spectre_bot_latest import send_adhkar_embed
        guild = _bot_instance.get_guild(int(guild_id))
        if guild is None:
            raise ValueError("السيرفر غير متصل بالبوت")
        result = call_bot(send_adhkar_embed(guild, category, force=True))
        return jsonify({"ok": bool(result)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/dashboard/<guild_id>/quran/<action_name>", methods=["POST"])
@login_required
def quran_action(guild_id: str, action_name: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    gid = int(guild_id)
    guild = _bot_instance.get_guild(gid)
    if guild is None:
        return jsonify({"ok": False, "error": "السيرفر غير متصل بالبوت"}), 400
    payload = request.get_json(force=True) or {}
    try:
        from spectre_bot_latest import radio_manager
        if action_name == "stop":
            call_bot(radio_manager.stop(guild))
            return jsonify({"ok": True, "status": "stopped"})
        if action_name == "start":
            channel = guild.get_channel(int(payload.get("channel_id", 0)))
            if not channel or not hasattr(channel, "connect"):
                return jsonify({"ok": False, "error": "اختر قناة صوتية صحيحة."}), 400
            call_bot(radio_manager.start(guild, channel, os.getenv("QURAN_RADIO_STREAM_URL")))
            return jsonify({"ok": True, "status": "playing", "channel": channel.name})
        return jsonify({"ok": False, "error": "إجراء غير معروف"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/dashboard/<guild_id>/counting", methods=["POST"])
@login_required
def configure_counting_dashboard(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    p = request.get_json(force=True) or {}
    try:
        db.set_counting_channel(int(guild_id), int(p["channel_id"]), p.get("emoji") or "✅", int(p.get("timeout_seconds", 60)), True)
    except (KeyError, ValueError):
        return jsonify({"ok": False, "error": "بيانات Counting غير صحيحة"}), 400
    return jsonify({"ok": True})


@app.route("/dashboard/<guild_id>/counting", methods=["DELETE"])
@login_required
def delete_counting_dashboard(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    p = request.get_json(force=True) or {}
    try:
        removed = db.remove_counting_channel(int(guild_id), int(p["channel_id"]))
    except (KeyError, ValueError):
        removed = False
    return jsonify({"ok": removed})


@app.route("/dashboard/<guild_id>/faq", methods=["POST"])
@login_required
def create_faq_dashboard(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    p = request.get_json(force=True) or {}
    if not str(p.get("question","")).strip() or not str(p.get("answer","")).strip():
        return jsonify({"ok": False, "error": "اكتب نص الزر والرد."}), 400
    faq_id = db.add_faq(int(guild_id), str(p["question"])[:80], str(p["answer"])[:2000], str(p.get("emoji") or "❓")[:10], str(p.get("style") or "blurple"))
    return jsonify({"ok": True, "id": faq_id})


@app.route("/dashboard/<guild_id>/faq/<int:faq_id>", methods=["DELETE"])
@login_required
def delete_faq_dashboard(guild_id: str, faq_id: int):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    return jsonify({"ok": db.delete_faq(int(guild_id), faq_id)})


@app.route("/dashboard/<guild_id>/presence", methods=["POST"])
@login_required
def save_presence_dashboard(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    p = request.get_json(force=True) or {}
    messages = [str(x).strip() for x in (p.get("messages") or []) if str(x).strip()][:10]
    interval = max(15, min(86400, int(p.get("interval_seconds", 60))))
    db.set_presence_config(messages, interval)
    try:
        from spectre_bot_latest import rotate_presence, apply_next_presence
        rotate_presence.change_interval(seconds=interval)
        call_bot(apply_next_presence())
    except Exception:
        pass
    return jsonify({"ok": True})


_ACTION_COROUTINES = {
    "ticket-panel": bot_actions.publish_ticket_panel,
    "apply-panel": bot_actions.publish_apply_panel,
    "embed": bot_actions.send_embed,
    "reaction-role-message": bot_actions.create_reaction_role_message,
    "reaction-role-link": bot_actions.link_reaction_role,
    "xp-adjust": bot_actions.adjust_xp,
    "xp-transfer": bot_actions.transfer_xp,
    "mod-action": bot_actions.mod_action,
    "giveaway": bot_actions.create_giveaway,
}


@app.route("/dashboard/<guild_id>/action/<action_name>", methods=["POST"])
@login_required
def proxy_action(guild_id: str, action_name: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    action_func = _ACTION_COROUTINES.get(action_name)
    if action_func is None:
        return jsonify({"ok": False, "error": "إجراء غير معروف"}), 404
    payload = request.get_json(force=True)
    try:
        result = call_bot(action_func(_bot_instance, int(guild_id), payload))
        return jsonify({"ok": True, **result})
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        return jsonify({"ok": False, "error": f"تعذّر تنفيذ الإجراء: {error}"}), 500


@app.route("/dashboard/<guild_id>/search-members")
@login_required
def search_members(guild_id: str):
    if guild_id not in session.get("manageable_guild_ids", []):
        return jsonify({"ok": False, "error": "غير مصرّح"}), 403
    query = request.args.get("q", "")
    try:
        members = call_bot(_find_members_coro(int(guild_id), query))
        return jsonify({"ok": True, "members": members})
    except Exception as error:
        return jsonify({"ok": False, "error": str(error)}), 500


async def _find_members_coro(guild_id: int, query: str):
    return bot_actions.find_members(_bot_instance, guild_id, query)


def run_embedded(bot_instance: Any, port: int) -> None:
    """تُستدعى من bot.py لتشغيل الداشبورد بخيط منفصل داخل نفس العملية."""
    global _bot_instance, _bot_loop
    _bot_instance = bot_instance
    _bot_loop = bot_instance.loop
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    port = int(os.getenv("PORT") or os.getenv("DASHBOARD_PORT", "5000"))
    print("⚠️ تشغيل الداشبورد بشكل منفصل بدون بوت مربوط — الإجراءات الحية لن تعمل.")
    print("للتشغيل الصحيح: شغّل bot.py، وهو يشغّل الداشبورد تلقائياً بخيط مدمج.")
    app.run(host="0.0.0.0", port=port, debug=False)
