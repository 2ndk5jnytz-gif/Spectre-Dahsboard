"""قاعدة بيانات SQLite لبوت ديسكورد العربي.
ضع هذا الملف في نفس مجلد bot.py. لا تشغّله وحده.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).with_name("bot_data.sqlite3")

DEFAULT_SETTINGS: dict[str, Any] = {
    "welcome_channel_id": None,
    "level_up_mode": "channel",
    "level_up_channel_id": None,
    "level_up_message": "مبروك {user}! وصلت للفل **{level}**.{role}",
    "xp_min": 15,
    "xp_max": 25,
    "xp_cooldown_seconds": 60,
    "xp_event_json": "{}",
    "review_channel_id": None,
    "apply_emoji": "🛠️",
    "apply_style": "blurple",
    "apply_image_url": "",
    "ticket_category_id": None,
    "welcome_enabled": True,
    "welcome_config_json": "{}",
    "tickets_enabled": True,
    "levels_enabled": True,
    "faq_enabled": True,
    "prefix": "!",
    "social_sources_json": "[]",
    "adhkar_config_json": "{}",
    "blocked_application_role_ids": "[]",
    "blocked_ticket_role_ids": "[]",
    "games_config_json": "{}",
    "mod_log_channel_id": None,
    "ticket_emoji": "🎫",
    "ticket_label": "فتح تذكرة دعم",
    "ticket_style": "success",
    # ==================== نظام الحماية من التخريب (Anti-Nuke) ====================
    "antinuke_enabled": False,
    "antinuke_punishment": "kick",  # kick | ban | remove_roles | timeout
    "antinuke_banned_words_json": "[]",  # كلمات ممنوعة بأسماء الرومات
    "antinuke_dangerous_perms_json": json.dumps([
        "administrator", "ban_members", "kick_members", "manage_guild",
        "manage_roles", "manage_channels", "manage_webhooks", "mention_everyone",
        "manage_messages", "moderate_members",
    ]),
    "antinuke_whitelist_json": "[]",  # آيدي أعضاء مستثناة (غير مالك السيرفر، مستثنى دائماً)
    "antinuke_bot_whitelist_json": "[]",  # آيدي بوتات مسموح دخولها بدون طرد تلقائي
    "antinuke_max_channel_delete": 3,
    "antinuke_max_channel_create": 5,
    "antinuke_max_kicks": 3,
    "antinuke_max_bans": 3,
    "antinuke_window_seconds": 10,
    # ==================== فلتر روابط التصيّد (Anti-Phishing) ====================
    "antiphishing_enabled": False,
    "antiphishing_domains_json": "[]",  # نطاقات إضافية يضيفها الأدمن فوق القائمة الافتراضية المدمجة بالكود
    "antiphishing_action": "delete",  # delete | timeout | kick | ban — ماذا يحصل لمرسل رابط التصيد

    # ==================== الحماية من الغارات الجماعية (Anti-Raid) ====================
    # ميزة مستوحاة من بوتات الحماية الشهيرة (Wick, Dyno, Vexera): تكشف عندما
    # ينضم عدد كبير من الأعضاء خلال وقت قصير جداً (نمط "غارة" منظّمة عادة
    # بحسابات وهمية/بوتات لإغراق السيرفر أو تحضير هجوم)، وتتدخل تلقائياً.
    "antiraid_enabled": False,
    "antiraid_max_joins": 10,          # كم عضو ينضم يُعتبر "غارة"
    "antiraid_window_seconds": 20,      # خلال كم ثانية
    "antiraid_action": "kick_new",      # kick_new | ban_new | lockdown_only — ماذا يحدث للمنضمين أثناء الغارة
    "antiraid_lockdown_minutes": 10,    # مدة رفع مستوى التحقق (Verification Level) للحد الأقصى مؤقتاً

    # ==================== الحماية من الحسابات الحديثة (Anti-Alt) ====================
    # يمنع/يطرد الحسابات المُنشأة حديثاً جداً بديسكورد نفسه (وليس تاريخ انضمامها
    # للسيرفر) — هذا يوقف أغلب الحسابات المزيفة (Alt accounts) التي تُصنع
    # للتحايل على الحظر أو تنفيذ هجمات منظّمة (نفس فكرة ميزة "Account Age" الشهيرة
    # ببوتات الحماية الكبرى).
    "antialt_enabled": False,
    "antialt_min_age_days": 7,
    "antialt_action": "kick",  # kick | ban

    # ==================== الرتب اللاصقة (Sticky Roles) ====================
    # عند مغادرة عضو ثم عودته، تُعاد له تلقائياً كل رتبه القديمة. هذه ميزة
    # أمنية مهمة أيضاً: تمنع عضواً مُعاقَباً (رتبة كتم/تقييد مؤقت من نشاط معين)
    # من "الهروب" من عقوبته بمغادرة السيرفر والعودة إليه لتصفير رتبه.
    "sticky_roles_enabled": False,

    # ==================== حماية من سبام المنشن الجماعي ====================
    # امتداد لنظام مكافحة السبام الأساسي: يراقب عدد المنشنات (منشن أعضاء أو
    # رتب) داخل رسالة واحدة تحديداً — أسلوب هجوم شائع (منشن عشرات الأعضاء
    # برسالة واحدة لإزعاجهم أو التشويش على القناة).
    "antispam_mention_enabled": False,
    "antispam_max_mentions": 6,
    "antispam_action": "timeout",  # delete_only | timeout | kick

    # ==================== لوحة النجوم (Starboard) ====================
    # ميزة شهيرة (من بوتات مثل Starboard/MEE6/Carl-bot): أي رسالة تحصل على
    # عدد كافٍ من تفاعل ⭐ (أو أي إيموجي تختاره) تُنشر تلقائياً بقناة مخصصة،
    # كأرشيف لأفضل/أطرف الرسائل بالسيرفر.
    "starboard_enabled": False,
    "starboard_channel_id": None,
    "starboard_threshold": 3,
    "starboard_emoji": "⭐",
}


def _connect() -> sqlite3.Connection:
    # timeout: تجعل sqlite3 تنتظر بدل رمي "database is locked" فوراً عند التعارض بين
    # كتابة/قراءة متزامنة (مثل رسائل متعددة تصل لحظياً)، وبذلك لا يتوقف رد أزرار
    # التذاكر/التقديم بسبب قفل قصير على قاعدة البيانات.
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 8000")
    return connection


def init_db() -> None:
    with _connect() as connection:
        # WAL يسمح بالقراءة أثناء الكتابة بدل قفل كامل للملف، فتقل جداً حالات
        # التأخر التي تسبب رسالة ديسكورد "the application didn't respond in time".
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER NOT NULL,
                setting_key TEXT NOT NULL,
                setting_value TEXT,
                PRIMARY KEY (guild_id, setting_key)
            );

            CREATE TABLE IF NOT EXISTS bot_presence (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                messages_json TEXT NOT NULL,
                interval_seconds INTEGER NOT NULL DEFAULT 60,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_levels (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS level_roles (
                guild_id INTEGER NOT NULL,
                level INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, level)
            );

            CREATE TABLE IF NOT EXISTS faqs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '❓',
                style TEXT NOT NULL DEFAULT 'blurple'
            );

            CREATE TABLE IF NOT EXISTS workflows (
                guild_id INTEGER NOT NULL,
                workflow_type TEXT NOT NULL,
                config_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, workflow_type)
            );

            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                applicant_id INTEGER NOT NULL,
                age TEXT NOT NULL,
                reason TEXT NOT NULL,
                experience TEXT NOT NULL,
                position TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewer_id INTEGER,
                review_reason TEXT,
                review_message_id INTEGER,
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS counting_channels (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                current_count INTEGER NOT NULL DEFAULT 0,
                invalid_attempts INTEGER NOT NULL DEFAULT 0,
                emoji TEXT NOT NULL DEFAULT '✅',
                timeout_seconds INTEGER NOT NULL DEFAULT 60,
                enabled INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS game_scores (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                game_id TEXT NOT NULL,
                points INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, game_id)
            );

            CREATE TABLE IF NOT EXISTS panels (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                config_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, message_id)
            );

            CREATE TABLE IF NOT EXISTS reaction_roles (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                emoji_key TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, message_id, emoji_key)
            );

            CREATE TABLE IF NOT EXISTS auto_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                trigger_text TEXT NOT NULL,
                response_text TEXT NOT NULL,
                match_type TEXT NOT NULL DEFAULT 'exact',
                enabled INTEGER NOT NULL DEFAULT 1
            );

            -- فهارس تسريع: هذه الجداول تُستعلَم دائماً بـ guild_id، وبدون فهرس
            -- عليه يفحص SQLite كل صفوف الجدول (كل السيرفرات) في كل استعلام،
            -- وهذا يتضاعف بطؤه مع نمو عدد السيرفرات والبيانات بمرور الوقت.
            CREATE INDEX IF NOT EXISTS idx_faqs_guild ON faqs (guild_id);
            CREATE INDEX IF NOT EXISTS idx_applications_guild_status ON applications (guild_id, status);
            CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings (guild_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_auto_responses_guild ON auto_responses (guild_id);
            CREATE INDEX IF NOT EXISTS idx_reaction_roles_guild_message ON reaction_roles (guild_id, message_id);
            CREATE INDEX IF NOT EXISTS idx_user_levels_leaderboard ON user_levels (guild_id, level DESC, xp DESC);
            CREATE INDEX IF NOT EXISTS idx_game_scores_guild_game ON game_scores (guild_id, game_id, points DESC);

            -- الرتب اللاصقة: نحفظ رتب العضو لحظة مغادرته، ونعيدها له تلقائياً
            -- إذا عاد للسيرفر لاحقاً (والميزة مفعّلة). صف واحد لكل عضو لكل
            -- سيرفر، يُستبدَل عند كل مغادرة جديدة (ON CONFLICT).
            CREATE TABLE IF NOT EXISTS sticky_roles (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role_ids_json TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            -- لوحة النجوم: نتتبع أي رسالة أصلية تم نشرها بالفعل بقناة الستاربورد
            -- حتى لا تُنشر مرتين، ونحدّث عدد النجوم على رسالة الستاربورد نفسها
            -- كل ما زاد التفاعل بدل نشر نسخة جديدة.
            CREATE TABLE IF NOT EXISTS starboard_messages (
                guild_id INTEGER NOT NULL,
                original_message_id INTEGER NOT NULL,
                starboard_message_id INTEGER NOT NULL,
                star_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, original_message_id)
            );

            -- المسابقات (Giveaways): كل سطر يمثل مسابقة واحدة منشورة، تُفحص
            -- دورياً (كل دقيقة) لمعرفة أي مسابقة انتهى وقتها لسحب الفائزين.
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                prize TEXT NOT NULL,
                winners_count INTEGER NOT NULL DEFAULT 1,
                host_id INTEGER NOT NULL,
                ends_at TEXT NOT NULL,
                ended INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_giveaways_pending ON giveaways (ended, ends_at);
            """
        )


def set_presence_config(messages: list[str], interval_seconds: int) -> None:
    cleaned = [str(message).strip()[:128] for message in messages if str(message).strip()]
    if not cleaned:
        raise ValueError("يجب إضافة عبارة Presence واحدة على الأقل")
    interval = max(15, min(int(interval_seconds), 86400))
    with _connect() as connection:
        connection.execute(
            "INSERT INTO bot_presence (id, messages_json, interval_seconds, updated_at) VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET messages_json = excluded.messages_json, interval_seconds = excluded.interval_seconds, updated_at = excluded.updated_at",
            (json.dumps(cleaned, ensure_ascii=False), interval, datetime.now(timezone.utc).isoformat()),
        )


def get_presence_config() -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT messages_json, interval_seconds FROM bot_presence WHERE id = 1").fetchone()
    if not row:
        return None
    try:
        messages = [str(item).strip()[:128] for item in json.loads(row["messages_json"]) if str(item).strip()]
        interval = int(row["interval_seconds"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not messages:
        return None
    return {"messages": messages, "interval_seconds": max(15, min(interval, 86400))}


def get_welcome_config(guild_id: int) -> dict[str, Any]:
    settings = get_guild_settings(guild_id)
    raw = settings.get("welcome_config_json", "{}")
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def save_welcome_config(guild_id: int, config: dict[str, Any]) -> None:
    safe = dict(config)
    safe["enabled"] = bool(safe.get("enabled", True))
    safe["title"] = str(safe.get("title", "عضو جديد انضم إلينا!") or "")[:256]
    safe["description"] = str(safe.get("description", "مرحباً بك {user} في سيرفرنا!") or "")[:1000]
    safe["background_url"] = str(safe.get("background_url", "") or "")[:500]
    safe["channel_id"] = int(safe.get("channel_id") or 0)
    safe["avatar_size"] = max(96, min(int(safe.get("avatar_size", 220)), 520))
    safe["avatar_x"] = max(0, min(int(safe.get("avatar_x", 600)), 1206))
    safe["avatar_y"] = max(0, min(int(safe.get("avatar_y", 246)), 700))
    safe["avatar_border_color"] = str(safe.get("avatar_border_color", "#20D6A7"))[:7]
    safe["avatar_border_width"] = max(0, min(int(safe.get("avatar_border_width", 8)), 30))
    safe["text_color"] = str(safe.get("text_color", "#FFFFFF"))[:7]
    set_guild_setting(guild_id, "welcome_config_json", json.dumps(safe, ensure_ascii=False))


def get_games_config(guild_id: int) -> dict[str, Any]:
    settings = get_guild_settings(guild_id)
    raw = settings.get("games_config_json", "{}")
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def save_games_config(guild_id: int, config: dict[str, Any]) -> None:
    save_value = dict(config)
    save_value["flags_rounds"] = max(1, min(int(save_value.get("flags_rounds", 5)), 20))
    save_value["flags_timeout"] = max(5, min(int(save_value.get("flags_timeout", 20)), 120))
    set_guild_setting(guild_id, "games_config_json", json.dumps(save_value, ensure_ascii=False))


def get_adhkar_config(guild_id: int) -> dict[str, Any]:
    settings = get_guild_settings(guild_id)
    raw = settings.get("adhkar_config_json", "{}")
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def save_adhkar_config(guild_id: int, config: dict[str, Any]) -> None:
    set_guild_setting(guild_id, "adhkar_config_json", json.dumps(config, ensure_ascii=False))


def get_social_sources(guild_id: int) -> list[dict[str, Any]]:
    settings = get_guild_settings(guild_id)
    raw = settings.get("social_sources_json", "[]")
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in value if isinstance(item, dict) and item.get("platform") and item.get("url") and item.get("channel_id")] if isinstance(value, list) else []


def save_social_sources(guild_id: int, sources: list[dict[str, Any]]) -> None:
    set_guild_setting(guild_id, "social_sources_json", json.dumps(sources[:25], ensure_ascii=False))


def get_guild_settings(guild_id: int) -> dict[str, Any]:
    settings = DEFAULT_SETTINGS.copy()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT setting_key, setting_value FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()

    integer_keys = {"welcome_channel_id", "level_up_channel_id", "review_channel_id", "ticket_category_id", "xp_min", "xp_max", "xp_cooldown_seconds"}
    boolean_keys = {"welcome_enabled", "tickets_enabled", "levels_enabled", "faq_enabled"}
    for row in rows:
        key, value = row["setting_key"], row["setting_value"]
        if key in integer_keys:
            settings[key] = int(value) if value else None
        elif key in boolean_keys:
            settings[key] = str(value).lower() not in {"0", "false", "off", "no"}
        elif key in settings:
            settings[key] = value
    return settings


def get_xp_event(guild_id: int) -> dict[str, Any]:
    settings = get_guild_settings(guild_id)
    try:
        event = json.loads(settings.get("xp_event_json", "{}"))
    except (TypeError, json.JSONDecodeError):
        return {"multiplier": 1.0, "expires_at": ""}
    if not isinstance(event, dict):
        return {"multiplier": 1.0, "expires_at": ""}
    try:
        multiplier = max(1.0, min(float(event.get("multiplier", 1.0)), 4.0))
        expires_at = datetime.fromisoformat(str(event.get("expires_at", "")))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return {"multiplier": 1.0, "expires_at": ""}
        return {"multiplier": multiplier, "expires_at": expires_at.isoformat()}
    except (TypeError, ValueError):
        return {"multiplier": 1.0, "expires_at": ""}


def save_xp_event(guild_id: int, multiplier: float, duration_minutes: int) -> dict[str, Any]:
    multiplier = max(1.0, min(float(multiplier), 4.0))
    duration_minutes = max(1, min(int(duration_minutes), 10080))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
    event = {"multiplier": multiplier, "expires_at": expires_at.isoformat()}
    set_guild_setting(guild_id, "xp_event_json", json.dumps(event, ensure_ascii=False))
    return event


def clear_xp_event(guild_id: int) -> None:
    set_guild_setting(guild_id, "xp_event_json", "{}")


def set_guild_setting(guild_id: int, key: str, value: Any) -> None:
    if key not in DEFAULT_SETTINGS:
        raise ValueError(f"إعداد غير معروف: {key}")
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO guild_settings (guild_id, setting_key, setting_value)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, setting_key)
            DO UPDATE SET setting_value = excluded.setting_value
            """,
            (guild_id, key, None if value is None else str(value)),
        )


def save_workflow(guild_id: int, workflow_type: str, config_json: str, enabled: bool = True) -> None:
    if workflow_type not in {"ticket", "application"}:
        raise ValueError("نوع التدفق غير صالح")
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO workflows (guild_id, workflow_type, config_json, enabled, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, workflow_type)
            DO UPDATE SET config_json = excluded.config_json, enabled = excluded.enabled, updated_at = excluded.updated_at
            """,
            (guild_id, workflow_type, config_json, 1 if enabled else 0, datetime.now(timezone.utc).isoformat()),
        )


def get_workflow(guild_id: int, workflow_type: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT workflow_type, config_json, enabled, updated_at FROM workflows WHERE guild_id = ? AND workflow_type = ?",
            (guild_id, workflow_type),
        ).fetchone()
    return dict(row) if row else None


# ==================== لوحات الأزرار المخصصة (تحديث_لوحة) ====================
# تُحفظ هنا حتى يستطيع البوت إعادة تسجيل أزرارها (Persistent View) بعد كل
# إعادة تشغيل؛ بدون هذا الحفظ تتوقف اللوحة عن الاستجابة بعد أي إعادة تشغيل
# ويظهر للمستخدم خطأ "the application didn't respond in time".
def save_panel(guild_id: int, channel_id: int, message_id: int, config_json: str) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO panels (guild_id, channel_id, message_id, config_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, message_id)
            DO UPDATE SET channel_id = excluded.channel_id, config_json = excluded.config_json, updated_at = excluded.updated_at
            """,
            (guild_id, channel_id, message_id, config_json, datetime.now(timezone.utc).isoformat()),
        )


def get_panels(guild_id: int) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT guild_id, channel_id, message_id, config_json FROM panels WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_panel(guild_id: int, message_id: int) -> None:
    with _connect() as connection:
        connection.execute(
            "DELETE FROM panels WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        )


# ==================== اللفلات ====================

def xp_for_level(level: int) -> int:
    return 100 + (max(0, level) * 50)


def get_user_level(guild_id: int, user_id: int) -> tuple[int, int]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT xp, level FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
    return (int(row["xp"]), int(row["level"])) if row else (0, 0)


def add_xp(guild_id: int, user_id: int, amount: int) -> tuple[bool, int, int, int]:
    xp, old_level = get_user_level(guild_id, user_id)
    xp += max(0, int(amount))
    new_level = old_level
    while xp >= xp_for_level(new_level):
        xp -= xp_for_level(new_level)
        new_level += 1

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO user_levels (guild_id, user_id, xp, level)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id)
            DO UPDATE SET xp = excluded.xp, level = excluded.level
            """,
            (guild_id, user_id, xp, new_level),
        )
    return (new_level > old_level, old_level, new_level, xp)


def add_level_role(guild_id: int, level: int, role_id: int) -> None:
    if level < 1:
        raise ValueError("يجب أن يكون اللفل 1 أو أعلى")
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO level_roles (guild_id, level, role_id)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, level)
            DO UPDATE SET role_id = excluded.role_id
            """,
            (guild_id, level, role_id),
        )


def remove_level_role(guild_id: int, level: int) -> None:
    with _connect() as connection:
        connection.execute("DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (guild_id, level))


def get_level_roles(guild_id: int) -> list[tuple[int, int]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (guild_id,)
        ).fetchall()
    return [(int(row["level"]), int(row["role_id"])) for row in rows]


def get_leaderboard(guild_id: int, limit: int = 10) -> list[tuple[int, int, int]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT user_id, xp, level FROM user_levels
            WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT ?
            """,
            (guild_id, max(1, min(int(limit), 100))),
        ).fetchall()
    return [(int(row["user_id"]), int(row["xp"]), int(row["level"])) for row in rows]


def total_xp(level: int, xp: int) -> int:
    """يحسب مجموع نقاط الخبرة الكلية المتراكمة (كل اللفلات السابقة + خبرة اللفل الحالي)."""
    total = max(0, int(xp))
    for lvl in range(max(0, int(level))):
        total += xp_for_level(lvl)
    return total


def set_user_xp(guild_id: int, user_id: int, level: int, xp: int) -> None:
    level = max(0, int(level))
    xp = max(0, int(xp))
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO user_levels (guild_id, user_id, xp, level)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id)
            DO UPDATE SET xp = excluded.xp, level = excluded.level
            """,
            (guild_id, user_id, xp, level),
        )


def _split_total_xp(total: int) -> tuple[int, int]:
    """يحوّل رقم خبرة كلي إلى (لفل، خبرة داخل اللفل)."""
    remaining = max(0, int(total))
    level = 0
    while remaining >= xp_for_level(level):
        remaining -= xp_for_level(level)
        level += 1
    return level, remaining


def add_xp_delta(guild_id: int, user_id: int, delta: int) -> tuple[int, int]:
    """يضيف أو يطرح كمية خبرة (delta قد تكون سالبة للنقصان) ويعيد (اللفل الجديد، الخبرة الجديدة)."""
    xp, level = get_user_level(guild_id, user_id)
    new_total = total_xp(level, xp) + int(delta)
    new_level, new_xp = _split_total_xp(new_total)
    set_user_xp(guild_id, user_id, new_level, new_xp)
    return new_level, new_xp


def transfer_xp(guild_id: int, from_user_id: int, to_user_id: int) -> tuple[int, int]:
    """ينقل كامل الخبرة المتراكمة من حساب إلى آخر (مفيد عند حظر حساب وعمل حساب جديد)
    ثم يصفّر رصيد الحساب المصدر بالكامل."""
    from_xp, from_level = get_user_level(guild_id, from_user_id)
    to_xp, to_level = get_user_level(guild_id, to_user_id)
    combined = total_xp(from_level, from_xp) + total_xp(to_level, to_xp)
    new_level, new_xp = _split_total_xp(combined)
    set_user_xp(guild_id, to_user_id, new_level, new_xp)
    set_user_xp(guild_id, from_user_id, 0, 0)
    return new_level, new_xp


# ==================== الرولات الذاتية (تفاعل إيموجي ⇐ رتبة) ====================
def add_reaction_role(guild_id: int, channel_id: int, message_id: int, emoji_key: str, role_id: int) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO reaction_roles (guild_id, channel_id, message_id, emoji_key, role_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, message_id, emoji_key) DO UPDATE SET role_id = excluded.role_id
            """,
            (guild_id, channel_id, message_id, emoji_key, role_id),
        )


def remove_reaction_role(guild_id: int, message_id: int, emoji_key: str) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji_key = ?",
            (guild_id, message_id, emoji_key),
        )
    return cursor.rowcount > 0


def get_reaction_role(guild_id: int, message_id: int, emoji_key: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT role_id FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji_key = ?",
            (guild_id, message_id, emoji_key),
        ).fetchone()
    return dict(row) if row else None


def get_reaction_roles_for_message(guild_id: int, message_id: int) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT emoji_key, role_id FROM reaction_roles WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        ).fetchall()
    return [dict(row) for row in rows]


# ==================== الردود التلقائية ====================
def add_auto_response(guild_id: int, trigger_text: str, response_text: str, match_type: str = "exact") -> int:
    with _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO auto_responses (guild_id, trigger_text, response_text, match_type, enabled) VALUES (?, ?, ?, ?, 1)",
            (guild_id, trigger_text.strip(), response_text.strip(), match_type),
        )
    return int(cursor.lastrowid)


def remove_auto_response(guild_id: int, response_id: int) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM auto_responses WHERE guild_id = ? AND id = ?", (guild_id, response_id)
        )
    return cursor.rowcount > 0


def get_auto_responses(guild_id: int) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, trigger_text, response_text, match_type, enabled FROM auto_responses WHERE guild_id = ? ORDER BY id ASC",
            (guild_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_game_points(guild_id: int, user_id: int, game_id: str, points: int = 1, win: bool = False) -> None:
    if not guild_id or not user_id or not game_id:
        return
    with _connect() as connection:
        connection.execute(
            "INSERT INTO game_scores (guild_id, user_id, game_id, points, wins, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(guild_id, user_id, game_id) DO UPDATE SET points = points + excluded.points, wins = wins + excluded.wins, updated_at = excluded.updated_at",
            (guild_id, user_id, game_id[:32], max(0, int(points)), 1 if win else 0, datetime.now(timezone.utc).isoformat()),
        )


def get_game_leaderboard(guild_id: int, game_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    query = "SELECT user_id, game_id, points, wins FROM game_scores WHERE guild_id = ?"
    params: list[Any] = [guild_id]
    if game_id:
        query += " AND game_id = ?"
        params.append(game_id)
    query += " ORDER BY points DESC, wins DESC LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    with _connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_counting_channels(guild_id: int) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT guild_id, channel_id, current_count, invalid_attempts, emoji, timeout_seconds, enabled FROM counting_channels WHERE guild_id = ? ORDER BY channel_id",
            (guild_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_counting_channel(guild_id: int, channel_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT guild_id, channel_id, current_count, invalid_attempts, emoji, timeout_seconds, enabled FROM counting_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        ).fetchone()
    return dict(row) if row else None


def set_counting_channel(guild_id: int, channel_id: int, emoji: str = "✅", timeout_seconds: int = 60, enabled: bool = True) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO counting_channels (guild_id, channel_id, emoji, timeout_seconds, enabled) VALUES (?, ?, ?, ?, ?) ON CONFLICT(guild_id, channel_id) DO UPDATE SET emoji = excluded.emoji, timeout_seconds = excluded.timeout_seconds, enabled = excluded.enabled",
            (guild_id, channel_id, emoji or "✅", max(1, min(int(timeout_seconds), 3600)), 1 if enabled else 0),
        )


def reset_counting_channel(guild_id: int, channel_id: int, value: int = 0) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE counting_channels SET current_count = ?, invalid_attempts = 0 WHERE guild_id = ? AND channel_id = ?",
            (max(0, int(value)), guild_id, channel_id),
        )


def advance_counting(guild_id: int, channel_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        connection.execute(
            "UPDATE counting_channels SET current_count = current_count + 1, invalid_attempts = 0 WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        row = connection.execute(
            "SELECT * FROM counting_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        ).fetchone()
    return dict(row) if row else None


def register_counting_violation(guild_id: int, channel_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        connection.execute(
            "UPDATE counting_channels SET invalid_attempts = invalid_attempts + 1 WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        row = connection.execute(
            "SELECT * FROM counting_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        ).fetchone()
    return dict(row) if row else None


def clear_counting_violations(guild_id: int, channel_id: int) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE counting_channels SET invalid_attempts = 0 WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )


def remove_counting_channel(guild_id: int, channel_id: int) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM counting_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
    return cursor.rowcount > 0


# ==================== الأزرار والأسئلة الشائعة ====================

def add_faq(guild_id: int, question: str, answer: str, emoji: str, style: str) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO faqs (guild_id, question, answer, emoji, style) VALUES (?, ?, ?, ?, ?)",
            (guild_id, question, answer, emoji or "❓", style or "blurple"),
        )
    return int(cursor.lastrowid)


def get_faqs(guild_id: int) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, guild_id, question, answer, emoji, style FROM faqs WHERE guild_id = ? ORDER BY id ASC",
            (guild_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_faq(faq_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, guild_id, question, answer, emoji, style FROM faqs WHERE id = ?", (faq_id,)
        ).fetchone()
    return dict(row) if row else None


def delete_faq(guild_id: int, faq_id: int) -> bool:
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM faqs WHERE guild_id = ? AND id = ?", (guild_id, faq_id))
    return cursor.rowcount > 0


# ==================== التقديم للإدارة ====================

def create_application(guild_id: int, applicant_id: int, age: str, reason: str, experience: str, position: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO applications (guild_id, applicant_id, age, reason, experience, position, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, applicant_id, age, reason, experience, position, now),
        )
    return int(cursor.lastrowid)


def set_application_message(application_id: int, message_id: int) -> None:
    with _connect() as connection:
        connection.execute("UPDATE applications SET review_message_id = ? WHERE id = ?", (message_id, application_id))


def get_application(application_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    return dict(row) if row else None


def get_pending_application_ids() -> list[int]:
    with _connect() as connection:
        rows = connection.execute("SELECT id FROM applications WHERE status = 'pending'").fetchall()
    return [int(row["id"]) for row in rows]


def review_application(application_id: int, status: str, reviewer_id: int, reason: str) -> bool:
    if status not in {"accepted", "rejected"}:
        raise ValueError("حالة الطلب غير صالحة")
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE applications
            SET status = ?, reviewer_id = ?, review_reason = ?, reviewed_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (status, reviewer_id, reason, now, application_id),
        )
    return cursor.rowcount > 0


# ==================== التحذيرات ====================

def add_warning(guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason, now),
        )
    return int(cursor.lastrowid)


def get_warnings(guild_id: int, user_id: int) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, moderator_id, reason, created_at FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY id DESC",
            (guild_id, user_id),
        ).fetchall()
    return [dict(row) for row in rows]


def clear_warnings(guild_id: int, user_id: int) -> int:
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    return cursor.rowcount


# ==================== الرتب اللاصقة (Sticky Roles) ====================
def save_sticky_roles(guild_id: int, user_id: int, role_ids: list[int]) -> None:
    """تُستدعى لحظة مغادرة عضو (on_member_remove) لحفظ رتبه الحالية، حتى تُعاد
    له تلقائياً إذا رجع للسيرفر لاحقاً."""
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO sticky_roles (guild_id, user_id, role_ids_json, saved_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET role_ids_json = excluded.role_ids_json, saved_at = excluded.saved_at
            """,
            (guild_id, user_id, json.dumps(role_ids), datetime.now(timezone.utc).isoformat()),
        )


def get_sticky_roles(guild_id: int, user_id: int) -> list[int]:
    with _connect() as connection:
        row = connection.execute(
            "SELECT role_ids_json FROM sticky_roles WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        ).fetchone()
    if not row:
        return []
    try:
        return [int(value) for value in json.loads(row["role_ids_json"])]
    except (TypeError, json.JSONDecodeError):
        return []


def clear_sticky_roles(guild_id: int, user_id: int) -> None:
    """تُستدعى بعد إعادة تطبيق الرتب بنجاح، حتى لا تُطبَّق مرة ثانية بالخطأ
    لو العضو غادر السيرفر مرة أخرى بدون أن تتغيّر رتبه."""
    with _connect() as connection:
        connection.execute("DELETE FROM sticky_roles WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))


# ==================== لوحة النجوم (Starboard) ====================
def get_starboard_entry(guild_id: int, original_message_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT starboard_message_id, star_count FROM starboard_messages WHERE guild_id = ? AND original_message_id = ?",
            (guild_id, original_message_id),
        ).fetchone()
    return dict(row) if row else None


def save_starboard_entry(guild_id: int, original_message_id: int, starboard_message_id: int, star_count: int) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO starboard_messages (guild_id, original_message_id, starboard_message_id, star_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, original_message_id) DO UPDATE SET star_count = excluded.star_count
            """,
            (guild_id, original_message_id, starboard_message_id, star_count),
        )


# ==================== المسابقات (Giveaways) ====================
def create_giveaway(guild_id: int, channel_id: int, message_id: int, prize: str, winners_count: int, host_id: int, ends_at: str) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, winners_count, host_id, ends_at, ended) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (guild_id, channel_id, message_id, prize, winners_count, host_id, ends_at),
        )
    return int(cursor.lastrowid)


def get_pending_giveaways(before_iso: str) -> list[dict[str, Any]]:
    """يعيد كل المسابقات التي حان وقت سحبها ولم تُسحَب بعد. تُستدعى من مهمة
    دورية (كل دقيقة) بدل تخزين مؤقت (Timer) منفصل لكل مسابقة، حتى تبقى صحيحة
    حتى لو أُعيد تشغيل البوت أثناء انتظار مسابقة."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, guild_id, channel_id, message_id, prize, winners_count, host_id FROM giveaways WHERE ended = 0 AND ends_at <= ?",
            (before_iso,),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_giveaway_ended(giveaway_id: int) -> None:
    with _connect() as connection:
        connection.execute("UPDATE giveaways SET ended = 1 WHERE id = ?", (giveaway_id,))


def get_giveaway_by_message(guild_id: int, message_id: int) -> dict[str, Any] | None:
    """ملاحظة مهمة: تعيد channel_id أيضاً (وليس فقط prize/winners_count) لأن
    أوامر مثل إعادة السحب أو الإنهاء المبكر يجب أن تجلب رسالة المسابقة من
    قناتها *الأصلية* دائماً، وليس من قناة تنفيذ الأمر (قد تختلفان)."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, guild_id, channel_id, message_id, prize, winners_count, host_id, ended FROM giveaways WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        ).fetchone()
    return dict(row) if row else None


def get_active_giveaways(guild_id: int) -> list[dict[str, Any]]:
    """كل المسابقات الجارية حالياً بسيرفر معيّن (لم تنتهِ بعد)، مرتّبة حسب
    الأقرب انتهاءً أولاً — تُستخدم لأمر عرض المسابقات النشطة."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, channel_id, message_id, prize, winners_count, ends_at FROM giveaways WHERE guild_id = ? AND ended = 0 ORDER BY ends_at ASC",
            (guild_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_giveaway(giveaway_id: int) -> bool:
    """حذف نهائي من قاعدة البيانات (يُستخدم للإلغاء بدون إعلان فائزين، على
    عكس mark_giveaway_ended التي تُبقي السجل لأغراض إعادة السحب لاحقاً)."""
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM giveaways WHERE id = ?", (giveaway_id,))
    return cursor.rowcount > 0


init_db()
