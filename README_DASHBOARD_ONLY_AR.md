# Spectre Dashboard Only

هذه الحزمة مخصصة لـ Render لتشغيل لوحة التحكم فقط، بدون تشغيل بوت Discord أو FFmpeg أو ألعاب أو مهام البوت.

## المتغيرات المطلوبة
- DISCORD_CLIENT_ID
- DISCORD_CLIENT_SECRET
- DASHBOARD_SECRET_KEY
- DASHBOARD_REDIRECT_URI
- DATABASE_URL (PostgreSQL / Supabase)
- SPECTRE_BOT_API_URL (رابط API للبوت على Wispbyte)
- SPECTRE_BOT_API_SECRET (مفتاح API مشترك)

## مهم
لوحة التحكم وحدها لا تشغّل البوت. العمليات التي تحتاج اتصال البوت (نشر الرسائل، التذاكر، XP، الإشراف، رفع الصور، وغيرها) تمر إلى API البوت الموجود على Wispbyte. يجب أن تكون نسخة Wispbyte مفعّل فيها dashboard API المتوافق مع هذه اللوحة.

يجب أن يكون SPECTRE_BOT_API_URL رابط HTTPS عام للوصول إلى Wispbyte. لا تضع Discord Bot Token داخل Render؛ التوكن يبقى في Wispbyte.
