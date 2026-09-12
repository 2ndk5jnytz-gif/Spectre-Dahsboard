"""إدارة بث الصوت داخل Discord مع إعادة اتصال تلقائية."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

import discord


def ensure_opus_loaded() -> str:
    """Load libopus explicitly; some minimal hosting images omit auto-discovery."""
    if discord.opus.is_loaded():
        return "already-loaded"
    root = Path(__file__).resolve().parent
    configured = os.getenv("OPUS_PATH", "").strip()
    candidates: list[Path] = []
    if configured:
        configured_path = Path(configured).expanduser()
        candidates.append(configured_path if configured_path.is_absolute() else root / configured_path)
    candidates.extend(
        [
            root / "bin" / "libopus.so.0",
            Path("/usr/lib/x86_64-linux-gnu/libopus.so.0"),
            Path("/lib/x86_64-linux-gnu/libopus.so.0"),
            Path("/usr/lib/aarch64-linux-gnu/libopus.so.0"),
            Path("/lib/aarch64-linux-gnu/libopus.so.0"),
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            try:
                discord.opus.load_opus(str(candidate))
            except OSError as error:
                print(f"[QuranRadio] Opus load failed from {candidate}: {error}")
                continue
            if discord.opus.is_loaded():
                print(f"[QuranRadio] Using Opus: {candidate}")
                return str(candidate)
    raise RuntimeError("Opus library not found; expected bin/libopus.so.0 or OPUS_PATH")
# رابط "chunks.m3u8" القديم أصبح لا يستجيب (404) وهو سبب مشكلة توقف الإذاعة.
# الروابط بصيغة HLS (playlist.m3u8) تتطلب طلبات HTTP متكررة لكل مقطع صغير،
# وهذا أكثر عرضة لأخطاء "End of file" مع شبكات استضافة معينة (كل مقطع قد
# يفشل بشكل مستقل). لذلك نجعل الأساسي الآن رابط بث مستمر بسيط (اتصال HTTP
# واحد متواصل، بلا تجزئة) من qurango.net — مصدر معروف ومستخدم فعلياً بمشاريع
# بث حقيقية (سكربتات إعادة بث مباشر لتيليجرام تعمل 24/7)، وهذا النمط أكثر
# استقراراً بكثير من HLS مع معظم بيئات الاستضافة. نُبقي روابط kwikmotion
# القديمة كخيارات احتياطية إضافية لو تعطّل هذا المصدر لأي سبب.
DEFAULT_QURAN_RADIO_STREAM_URL = "https://backup.qurango.net/radio/tarateel"
DEFAULT_QURAN_RADIO_FALLBACK_URLS = [
    DEFAULT_QURAN_RADIO_STREAM_URL,
    "https://live.kwikmotion.com/sbrksaquranradiolive/ksaquranradio/playlist.m3u8",
    "https://live.kwikmotion.com/sbrksaquranradiolive/srpksaquranradio/playlist.m3u8",
]


class RadioManager:
    def __init__(self) -> None:
        self.jobs: dict[int, dict[str, Any]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, guild_id: int) -> asyncio.Lock:
        return self._locks.setdefault(guild_id, asyncio.Lock())

    @staticmethod
    def ffmpeg_executable() -> str:
        root = Path(__file__).resolve().parent
        configured = os.getenv("FFMPEG_PATH", "").strip()
        candidates = []
        if configured:
            configured_path = Path(configured).expanduser()
            candidates.append(configured_path if configured_path.is_absolute() else root / configured_path)
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            candidates.append(Path(system_ffmpeg))
        candidates.append(root / "bin" / "ffmpeg")
        for candidate in candidates:
            if candidate.is_file():
                try:
                    if not os.access(candidate, os.X_OK):
                        candidate.chmod(candidate.stat().st_mode | 0o111)
                except OSError as error:
                    print(f"[QuranRadio] Could not set FFmpeg executable bit: {error}")
                if os.access(candidate, os.X_OK):
                    return str(candidate)
        raise FileNotFoundError("FFmpeg not found; expected a system ffmpeg, bin/ffmpeg, or FFMPEG_PATH")

    @staticmethod
    def resolve_urls(url: str | None = None) -> list[str]:
        configured = (url or os.getenv("QURAN_RADIO_STREAM_URL", "")).strip()
        fallback_raw = os.getenv("QURAN_RADIO_FALLBACK_URLS", "")
        candidates = [configured] if configured else []
        candidates.extend(item.strip() for item in fallback_raw.split(",") if item.strip())
        candidates.extend(DEFAULT_QURAN_RADIO_FALLBACK_URLS)
        return list(dict.fromkeys(candidates))

    @staticmethod
    def resolve_url(url: str | None = None) -> str:
        return RadioManager.resolve_urls(url)[0]

    async def start(self, guild: discord.Guild, channel: discord.VoiceChannel, url: str | None = None) -> None:
        async with self._lock(guild.id):
            if os.getenv("QURAN_RADIO_AUDIO_MODE", "opus").strip().lower() == "pcm":
                ensure_opus_loaded()
            await self.stop(guild, disconnect=False)
            voice = guild.voice_client
            if voice is None:
                voice = await channel.connect()
            elif voice.channel != channel:
                await voice.move_to(channel)
            urls = self.resolve_urls(url)
            requested_mode = os.getenv("QURAN_RADIO_AUDIO_MODE", "opus").strip().lower()
            if requested_mode not in {"opus", "pcm"}:
                requested_mode = "opus"
            job = {"channel_id": channel.id, "urls": urls, "url_index": 0, "url": urls[0], "audio_mode": requested_mode, "stopped": False}
            self.jobs[guild.id] = job
            await self._play(guild, voice, job)

    async def _play(self, guild: discord.Guild, voice: discord.VoiceClient, job: dict[str, Any]) -> None:
        if job.get("stopped"):
            return
        if voice.is_playing():
            voice.stop()
        # -thread_queue_size: يمنع فيضان/نفاد المخزن المؤقت عند القراءة من شبكة
        #   بطيئة قليلاً، وهو سبب شائع لصوت "متقطع" أو "متلعثم".
        # -reconnect_at_eof / -reconnect_on_network_error: تغطي حالات انقطاع
        #   إضافية لم تكن مغطاة سابقاً (كان فقط reconnect_streamed).
        # -probesize / -analyzeduration أعلى: يمنع سوء تحليل بداية البث المباشر
        #   (HLS) الذي يسبب أحياناً تشويشاً واضحاً بالثواني الأولى.
        # ملاحظة مهمة: probesize/analyzeduration الكبيرة مفيدة لملفات عادية،
        # لكنها ضارة تحديداً مع بث مباشر (Live HLS) بلا نهاية — FFmpeg يحاول
        # "تحليل" حجماً كبيراً من بث لا ينتهي أصلاً، فيتأخر بدء التشغيل كثيراً
        # أو يبدو الراديو "متوقفاً" تماماً. لذلك نتركها بالحد الأدنى الافتراضي
        # المناسب لبث حي (لا نحددها صراحة إطلاقاً، FFmpeg يتعامل مع HLS تلقائياً
        # بسرعة بدون الحاجة لتحليل مسبق كبير).
        before_options = (
            "-nostdin -user_agent \"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36\" "
            "-rw_timeout 20000000 "
            "-reconnect 1 -reconnect_streamed 1 -reconnect_at_eof 1 -reconnect_on_network_error 1 "
            "-reconnect_on_http_error 4xx,5xx -reconnect_delay_max 5 -thread_queue_size 1024 "
            "-protocol_whitelist file,http,https,tcp,tls,crypto"
        )
        # -af aresample=async=1: يصحّح فجوات التوقيت الصغيرة الناتجة عن الانتقال
        #   بين مقاطع HLS المتتالية (كل مقطع قد يبدأ بفارق طفيف)، وهذا هو السبب
        #   الأكثر شيوعاً لـ"التشويش المزعج" (طقطقة/نقرات) في بث الراديو المباشر
        #   عبر FFmpeg لبوتات ديسكورد تحديداً.
        common_options = (
            "-map 0:a:0? -vn -threads 1 -filter_threads 1 -filter_complex_threads 1 "
            "-fflags +discardcorrupt -af aresample=async=1:min_hard_comp=0.100000:first_pts=0"
        )
        executable = self.ffmpeg_executable()
        audio_mode = str(job.get("audio_mode") or os.getenv("QURAN_RADIO_AUDIO_MODE", "opus")).strip().lower()
        if audio_mode == "pcm":
            source = discord.FFmpegPCMAudio(
                str(job["url"]),
                executable=executable,
                before_options=before_options,
                options=f"{common_options} -ar 48000 -ac 2 -loglevel warning",
            )
        else:
            # compression_level (0-10): كلما زادت الرقم زادت الجودة لكن زاد
            # استهلاك المعالج بشكل كبير جداً (10 هو الأقصى، ويعني ترميز مستمر
            # بأعلى تعقيد ممكن طوال مدة تشغيل الراديو بأكمله). خفّضناها لـ 5
            # (توازن ممتاز وموصى به لبث مباشر Real-time) بعد أن تسبب استخدام
            # القيمة القصوى بتجاوز حصة المعالج المسموحة على استضافات مجانية
            # صارمة (مثل Wispbyte) وإيقاف السيرفر تلقائياً — الفرق السمعي بين
            # 10 و5 غير محسوس تقريباً على بترست 128k، لكن الفرق باستهلاك
            # المعالج كبير جداً.
            source = discord.FFmpegOpusAudio(
                str(job["url"]),
                executable=executable,
                before_options=before_options,
                options=f"{common_options} -ar 48000 -ac 2 -b:a 128k -vbr on -compression_level 5 -application audio -loglevel warning",
            )

        loop = asyncio.get_running_loop()

        def after(error: Exception | None) -> None:
            if not job.get("stopped"):
                asyncio.run_coroutine_threadsafe(self._recover(guild, job, error), loop)

        voice.play(source, after=after)

    async def _recover(self, guild: discord.Guild, job: dict[str, Any], error: Exception | None) -> None:
        if job.get("stopped") or self.jobs.get(guild.id) is not job:
            return
        if error:
            print(f"[QuranRadio] FFmpeg ended: {error!r}")
        if not error:
            print("[QuranRadio] FFmpeg ended without a Discord player exception")
        if str(job.get("audio_mode", "opus")) == "opus":
            job["audio_mode"] = "pcm"
            print("[QuranRadio] Switching audio mode from opus to pcm for compatibility")
        urls = job.get("urls") or [job.get("url")]
        if len(urls) > 1:
            job["url_index"] = (int(job.get("url_index", 0)) + 1) % len(urls)
            job["url"] = urls[job["url_index"]]
            print(f"[QuranRadio] Switching stream source to fallback {job['url']}")
        else:
            print("[QuranRadio] FFmpeg ended without a Discord player exception; scheduling recovery")
        await asyncio.sleep(5)
        if job.get("stopped") or self.jobs.get(guild.id) is not job:
            return
        channel = guild.get_channel(int(job["channel_id"]))
        if not isinstance(channel, discord.VoiceChannel):
            print(f"[QuranRadio] Voice channel {job['channel_id']} no longer exists")
            return
        try:
            voice = guild.voice_client
            if voice is None or not voice.is_connected():
                voice = await channel.connect()
            elif voice.channel != channel:
                await voice.move_to(channel)
            await self._play(guild, voice, job)
        except Exception as retry_error:
            print(f"[QuranRadio] Reconnect failed: {retry_error}")
            if not job.get("stopped"):
                asyncio.create_task(self._recover(guild, job, retry_error))

    async def stop(self, guild: discord.Guild, disconnect: bool = True) -> None:
        job = self.jobs.pop(guild.id, None)
        if job:
            job["stopped"] = True
        voice = guild.voice_client
        if voice:
            if voice.is_playing():
                voice.stop()
            if disconnect:
                await voice.disconnect()
