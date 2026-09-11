"""محتوى الأذكار والآيات الموثق لإشعارات Spectre.

لا تُضاف فضائل أو أعداد جديدة هنا إلا بعد مراجعة التخريج. الآيات محفوظة
بشكل منفصل عن الأحاديث مع اسم السورة ورقم الآية.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["adhkar", "quran"]

BINBAZ_TIMING_URL = "https://binbaz.org.sa/fatwas/12824/"
DORAR_ADHKAR_URL = "https://dorar.net/hadith-category/cat/0cd6cd007af56fc4cd2f6b9602ddf43b"
QURAN_COMPLEX_URL = "https://qurancomplex.gov.sa/quran-hafs/"


@dataclass(frozen=True)
class AdhkarItem:
    key: str
    title: str
    text: str
    category: Kind
    repeat: str
    benefit: str
    source: str
    source_url: str
    grade: str
    surah: str = ""
    ayah: str = ""


ADHKAR: tuple[AdhkarItem, ...] = (
    AdhkarItem(
        key="sayyid_al_istighfar",
        title="سيد الاستغفار",
        text="اللهم أنت ربي لا إله إلا أنت، خلقتني وأنا عبدك، وأنا على عهدك ووعدك ما استطعت، أعوذ بك من شر ما صنعت، أبوء لك بنعمتك علي، وأبوء لك بذنبي، فاغفر لي؛ فإنه لا يغفر الذنوب إلا أنت.",
        category="adhkar",
        repeat="مرة واحدة",
        benefit="ورد في الحديث أن من قاله موقناً به من النهار فمات قبل أن يمسي دخل الجنة، ومن قاله من الليل فمات قبل أن يصبح دخل الجنة.",
        source="صحيح البخاري، حديث 6306",
        source_url=DORAR_ADHKAR_URL,
        grade="صحيح",
    ),
    AdhkarItem(
        key="tahlil_100",
        title="فضل التهليل",
        text="لا إله إلا الله وحده لا شريك له، له الملك وله الحمد، وهو على كل شيء قدير.",
        category="adhkar",
        repeat="100 مرة في اليوم",
        benefit="ورد في الحديث: كانت له عدل عشر رقاب، وكُتبت له مائة حسنة، ومُحيت عنه مائة سيئة، وكان في حرز من الشيطان يومه ذلك.",
        source="صحيح البخاري 6403، وصحيح مسلم 2691",
        source_url=DORAR_ADHKAR_URL,
        grade="متفق عليه بأصل المعنى، مع اختلاف يسير في اللفظ",
    ),
    AdhkarItem(
        key="tasbih_100",
        title="التسبيح والتحميد",
        text="سبحان الله وبحمده.",
        category="adhkar",
        repeat="100 مرة في اليوم",
        benefit="ورد في الحديث أن من قالها مائة مرة حُطّت خطاياه وإن كانت مثل زبد البحر.",
        source="صحيح البخاري 6405، وصحيح مسلم 2691",
        source_url=DORAR_ADHKAR_URL,
        grade="صحيح",
    ),
)

GENERAL_ADHKAR: tuple[AdhkarItem, ...] = (
    AdhkarItem(
        key="light_on_tongue",
        title="ذكر خفيف عظيم الأجر",
        text="سبحان الله وبحمده، سبحان الله العظيم.",
        category="adhkar",
        repeat="بدون عدد محدد",
        benefit="كلمتان حبيبتان إلى الرحمن، خفيفتان على اللسان، ثقيلتان في الميزان.",
        source="صحيح البخاري 6682، وصحيح مسلم 2694",
        source_url=DORAR_ADHKAR_URL,
        grade="متفق عليه",
    ),
    AdhkarItem(
        key="la_hawla",
        title="لا حول ولا قوة إلا بالله",
        text="لا حول ولا قوة إلا بالله.",
        category="adhkar",
        repeat="بدون عدد محدد",
        benefit="ورد وصفها بأنها كنز من كنوز الجنة.",
        source="صحيح البخاري 6384، وصحيح مسلم 2704",
        source_url=DORAR_ADHKAR_URL,
        grade="متفق عليه",
    ),
    AdhkarItem(
        key="four_words",
        title="أحب الكلام إلى الله",
        text="سبحان الله، والحمد لله، ولا إله إلا الله، والله أكبر.",
        category="adhkar",
        repeat="بدون عدد محدد",
        benefit="ورد أن هذه الكلمات من أحب الكلام إلى الله، ولا يضر بأيهن بدأ.",
        source="صحيح مسلم 2137",
        source_url=DORAR_ADHKAR_URL,
        grade="صحيح",
    ),
)


QURAN_VERSES: tuple[AdhkarItem, ...] = (
    AdhkarItem(
        key="dua_musa",
        title="دعاء موسى عليه السلام",
        text="رَبِّ اشْرَحْ لِي صَدْرِي ۝ وَيَسِّرْ لِي أَمْرِي ۝ وَاحْلُلْ عُقْدَةً مِنْ لِسَانِي ۝ يَفْقَهُوا قَوْلِي",
        category="quran",
        repeat="للتدبر والدعاء",
        benefit="دعاء قرآني بطلب انشراح الصدر وتيسير الأمر ووضوح القول.",
        source="سورة طه، الآيات 25–28",
        source_url=QURAN_COMPLEX_URL,
        grade="آية من القرآن الكريم",
        surah="طه",
        ayah="25–28",
    ),
    AdhkarItem(
        key="steadfast_hearts",
        title="دعاء الثبات",
        text="رَبَّنَا لَا تُزِغْ قُلُوبَنَا بَعْدَ إِذْ هَدَيْتَنَا وَهَبْ لَنَا مِنْ لَدُنْكَ رَحْمَةً ۚ إِنَّكَ أَنْتَ الْوَهَّابُ",
        category="quran",
        repeat="للتدبر والدعاء",
        benefit="دعاء قرآني بطلب الثبات والهداية والرحمة.",
        source="سورة آل عمران، الآية 8",
        source_url=QURAN_COMPLEX_URL,
        grade="آية من القرآن الكريم",
        surah="آل عمران",
        ayah="8",
    ),
    AdhkarItem(
        key="good_in_both",
        title="دعاء جامع",
        text="رَبَّنَا آتِنَا فِي الدُّنْيَا حَسَنَةً وَفِي الْآخِرَةِ حَسَنَةً وَقِنَا عَذَابَ النَّارِ",
        category="quran",
        repeat="للتدبر والدعاء",
        benefit="دعاء جامع يجمع سؤال الخير في الدنيا والآخرة والاستعاذة من عذاب النار.",
        source="سورة البقرة، الآية 201",
        source_url=QURAN_COMPLEX_URL,
        grade="آية من القرآن الكريم",
        surah="البقرة",
        ayah="201",
    ),
    AdhkarItem(
        key="accountability",
        title="تذكير بالتقوى",
        text="يَا أَيُّهَا الَّذِينَ آمَنُوا اتَّقُوا اللَّهَ وَلْتَنْظُرْ نَفْسٌ مَا قَدَّمَتْ لِغَدٍ ۖ وَاتَّقُوا اللَّهَ ۚ إِنَّ اللَّهَ خَبِيرٌ بِمَا تَعْمَلُونَ",
        category="quran",
        repeat="للتدبر",
        benefit="تذكير قرآني بمراجعة العمل والاستعداد للآخرة.",
        source="سورة الحشر، الآية 18",
        source_url=QURAN_COMPLEX_URL,
        grade="آية من القرآن الكريم",
        surah="الحشر",
        ayah="18",
    ),
)

ALL_ITEMS = ADHKAR + GENERAL_ADHKAR + QURAN_VERSES


def get_item(key: str) -> AdhkarItem | None:
    return next((item for item in ALL_ITEMS if item.key == key), None)


def items_for(category: str) -> tuple[AdhkarItem, ...]:
    if category == "morning" or category == "evening":
        return ADHKAR
    if category == "general":
        return GENERAL_ADHKAR + QURAN_VERSES
    if category == "quran":
        return QURAN_VERSES
    return ALL_ITEMS


def select_next_item(items: tuple[AdhkarItem, ...], last_key: str = "") -> AdhkarItem:
    """Return the next item in a circular sequence, never repeating the previous key."""
    if not items:
        raise ValueError("لا يوجد محتوى للاختيار")
    keys = [item.key for item in items]
    if last_key in keys:
        return items[(keys.index(last_key) + 1) % len(items)]
    return items[0]


def build_embed(item: AdhkarItem, color: int = 0x2FA47A):
    import discord

    title = f"أذكار {'الصباح' if item.category == 'adhkar' else 'آية وتدبر'} | {item.title}"
    embed = discord.Embed(title=title, description=f"**{item.text}**", color=discord.Color(color))
    embed.add_field(name="العدد", value=item.repeat, inline=True)
    embed.add_field(name="الفضل / الفائدة", value=item.benefit[:1024], inline=False)
    embed.add_field(name="المصدر", value=f"{item.source}\n[{item.grade}]({item.source_url})", inline=False)
    embed.set_footer(text="محتوى مُراجع | لا يُغني عن الرجوع إلى المصدر")
    return embed
