# Spectre — خطة E: Wispbyte + Render + Supabase

## Wispbyte
يشغل البوت فقط.

متغيرات البيئة:
- DISCORD_TOKEN
- DATABASE_URL
- DASHBOARD_API_SECRET
- PORT=10000
- DISABLE_EMBEDDED_DASHBOARD=1

## Render
يشغل Dashboard فقط.

Build Command:
`pip install -r requirements.txt`

Start Command:
`python dashboard/app.py`

متغيرات البيئة:
- DISCORD_CLIENT_ID
- DISCORD_CLIENT_SECRET
- DASHBOARD_SECRET_KEY
- DASHBOARD_REDIRECT_URI
- DATABASE_URL
- SPECTRE_BOT_API_URL
- SPECTRE_BOT_API_SECRET

## Supabase
ضع Connection String الخاص بـ PostgreSQL في DATABASE_URL في كلا الخادمين.

## الربط
يجب أن تكون قيمة SPECTRE_BOT_API_SECRET في Render مطابقة لقيمة DASHBOARD_API_SECRET في Wispbyte.
ولا تضع DISCORD_TOKEN في Render.
