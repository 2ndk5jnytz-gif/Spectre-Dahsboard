# نقل بوت Spectre إلى JustRunMyApp

هذه الحزمة مخصصة لنقل النسخة العاملة من Spectre إلى JustRunMyApp. تحتوي على إصلاح إذاعة القرآن، مكتبات Discord Voice، وتدوير الأذكار والآيات دون إعادة إرسال العنصر نفسه.

## الملفات التي يجب رفعها

ارفع الحزمة كاملة وفكها داخل مجلد التطبيق. نقطة التشغيل هي `start_latest.py`، وهي تشغّل `spectre_bot_latest.py` مباشرة من المجلد الحالي.

يجب أن يكون الشكل النهائي بعد فك الضغط:

```text
start_latest.py
spectre_bot_latest.py
bot.py
adhkar.py
radio.py
requirements.txt
db.py
counting.py
presence_config.py
social_notifications.py
bin/ffmpeg
```

## إعداد JustRunMyApp

استخدم أمر البناء التالي إن توفر:

```text
pip install -r requirements.txt
```

واستخدم أمر التشغيل التالي:

```text
python3 start_latest.py
```

إذا كانت المنصة تشغّل `bot.py` تلقائياً، غيّر Startup إلى `python3 start_latest.py` حتى لا تعمل نسخة قديمة.

## التوكن والبيانات

لا تحتوي الحزمة على `.env` أو `bot_data.sqlite3` عمداً. احتفظ بنسخة `.env` الحالية أو أضف متغير البيئة التالي في إعدادات JustRunMyApp:

```env
DISCORD_TOKEN=توكن_البوت_الحالي
```

إذا أردت نقل إعدادات الأذكار واللفلات والتذاكر والعد المحفوظة، انسخ `bot_data.sqlite3` من Wispbyte إلى مجلد التطبيق بعد فك الحزمة. إذا أردت إعداداً نظيفاً، لا تنقل قاعدة البيانات وسيُنشئ البوت واحدة جديدة عند التشغيل.

## الإذاعة والأذكار

اترك `bin/ffmpeg` داخل مجلد `bin`، ولا تغيّر اسمه. يحتاج البوت إلى صلاحيات `View Channel` و`Connect` و`Speak` للروم الصوتي، وإلى `Send Messages` و`Embed Links` لقناة الأذكار.

لا تحتاج إلى إعادة ضبط التوكن أو تغيير إعدادات الداشبورد. بعد التشغيل اختبر:

```text
!حالة_القرآن
!أذكار_الآن عام
```

## ملاحظة عن CPU

إذا كانت الاستضافة تمنع التشغيل بسبب حد المعالج، فالمشكلة في خطة الاستضافة أو مواردها وليست في فك الحزمة. لا تشغّل النسخة نفسها في Wispbyte وJustRunMyApp في الوقت ذاته؛ أوقف النسخة القديمة أولاً حتى لا يتصل حساب البوت من عمليتين.

## التحقق من السجل

يجب أن يظهر أولاً:

```text
[Spectre] Starting spectre_bot_latest.py
```

ثم اتصال Discord Gateway. لا تشارك قيمة `DISCORD_TOKEN` أو محتوى `.env` في السجل أو الصور.
