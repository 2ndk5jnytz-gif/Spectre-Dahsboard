"""نواة ألعاب Spectre: لعبة الأعلام/تخمين الدولة.

التنفيذ أصلي ومصمم لعمله داخل Discord دون خدمة خارجية أو أصول مدفوعة.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any

import discord

import db


COUNTRIES: list[tuple[str, str]] = [
    ("🇸🇦", "السعودية"), ("🇦🇪", "الإمارات"), ("🇪🇬", "مصر"), ("🇯🇴", "الأردن"),
    ("🇰🇼", "الكويت"), ("🇶🇦", "قطر"), ("🇴🇲", "عُمان"), ("🇧🇭", "البحرين"),
    ("🇲🇦", "المغرب"), ("🇩🇿", "الجزائر"), ("🇹🇳", "تونس"), ("🇹🇷", "تركيا"),
    ("🇵🇰", "باكستان"), ("🇮🇩", "إندونيسيا"), ("🇯🇵", "اليابان"), ("🇰🇷", "كوريا الجنوبية"),
    ("🇨🇳", "الصين"), ("🇮🇳", "الهند"), ("🇫🇷", "فرنسا"), ("🇩🇪", "ألمانيا"),
    ("🇮🇹", "إيطاليا"), ("🇪🇸", "إسبانيا"), ("🇬🇧", "المملكة المتحدة"), ("🇺🇸", "الولايات المتحدة"),
    ("🇨🇦", "كندا"), ("🇧🇷", "البرازيل"), ("🇦🇺", "أستراليا"), ("🇿🇦", "جنوب أفريقيا"),
]
ACTIVE_GAMES: dict[int, "FlagGame"] = {}


def _display_scores(game: "FlagGame") -> str:
    if not game.scores:
        return "لا توجد نقاط بعد."
    ordered = sorted(game.scores.items(), key=lambda item: item[1], reverse=True)
    return "\n".join(f"{index}. <@{user_id}> — **{score}**" for index, (user_id, score) in enumerate(ordered[:10], 1))


@dataclass
class FlagGame:
    ctx: Any
    host_id: int
    rounds: int = 5
    players: set[int] = field(default_factory=set)
    scores: dict[int, int] = field(default_factory=dict)
    round_number: int = 0
    current: tuple[str, str] | None = None
    options: list[tuple[str, str]] = field(default_factory=list)
    winner_for_round: int | None = None
    message: discord.Message | None = None
    finished: bool = False
    continuous: bool = True
    round_started_at: float = 0.0
    round_task: asyncio.Task | None = None

    async def lobby(self) -> None:
        self.players.add(self.host_id)
        embed = discord.Embed(
            title="🏳️ لعبة الأعلام — اللوبي",
            description="اضغط **انضمام** للمشاركة، ثم يضغط المضيف **بدء اللعب**.\n\nالهدف: تخمين الدولة من العلم قبل بقية اللاعبين.",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(name="الجولة", value=f"{self.rounds} جولات", inline=True)
        embed.add_field(name="اللاعبون", value="1 لاعب — المضيف", inline=True)
        self.message = await self.ctx.send(embed=embed, view=FlagLobbyView(self))

    async def start(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.host_id:
            await interaction.response.send_message("فقط صاحب اللعبة يستطيع بدء الجولة.", ephemeral=True)
            return
        if self.finished:
            return
        await interaction.response.defer()
        await self.next_round()

    async def next_round(self) -> None:
        if self.finished or not self.message:
            return
        if not self.continuous and self.round_number >= self.rounds:
            await self.finish()
            return
        self.round_number += 1
        self.winner_for_round = None
        self.current = random.choice(COUNTRIES)
        self.round_started_at = time.monotonic()
        self.options = []
        embed = discord.Embed(
            title=f"🏳️ تخمين العلم — الجولة {self.round_number}/{self.rounds}",
            description=f"ما الدولة التي يمثلها هذا العلم؟\n\n# {self.current[0]}",
            colour=discord.Colour.gold(),
        )
        embed.set_footer(text="اكتب اسم الدولة في الدردشة — أول إجابة صحيحة تفوز. ينتهي الوقت بعد 20 ثانية.")
        await self.message.edit(embed=embed, view=None)
        if self.continuous:
            if self.round_task and not self.round_task.done():
                self.round_task.cancel()
            self.round_task = asyncio.create_task(self._timeout_round())

    async def _timeout_round(self) -> None:
        try:
            timeout_seconds = db.get_games_config(self.ctx.guild.id).get("flags_timeout", 20)
            await asyncio.sleep(max(5, min(int(timeout_seconds), 120)))
        except asyncio.CancelledError:
            return
        if self.finished or self.winner_for_round is not None or not self.current or not self.message:
            return
        self.winner_for_round = -1
        embed = discord.Embed(title=f"⏱️ انتهى وقت الجولة {self.round_number}", description=f"لم يجب أحد. الإجابة الصحيحة: **{self.current[1]}**\n\nسيظهر العلم التالي بعد لحظات.", colour=discord.Colour.orange())
        await self.message.edit(embed=embed, view=None)
        await asyncio.sleep(2)
        await self.next_round()

    @staticmethod
    def _normalize_answer(value: str) -> str:
        return "".join(value.casefold().strip().split()).replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي")

    async def answer_text(self, message: Any) -> bool:
        if self.finished or not self.continuous or not self.current or self.winner_for_round is not None:
            return False
        if self._normalize_answer(message.content) != self._normalize_answer(self.current[1]):
            return False
        self.winner_for_round = message.author.id
        if self.round_task and not self.round_task.done():
            self.round_task.cancel()
        elapsed = max(0.0, time.monotonic() - self.round_started_at)
        points = max(1, 10 - int(elapsed // 2))
        self.players.add(message.author.id)
        self.scores[message.author.id] = self.scores.get(message.author.id, 0) + points
        db.add_game_points(message.guild.id, message.author.id, "flags", points, True)
        total = next((row["points"] for row in db.get_game_leaderboard(message.guild.id, "flags", 100) if row["user_id"] == message.author.id), points)
        embed = discord.Embed(title="✅ إجابة صحيحة!", description=f"الفائز: {message.author.mention}\nالإجابة: **{self.current[1]}**\n\nالزيادة: **+{points}** نقطة\nرصيدك الآن: **{total}** نقطة\n\nسيظهر العلم التالي بعد لحظات.", colour=discord.Colour.green())
        await self.message.edit(embed=embed, view=None)
        await asyncio.sleep(2)
        await self.next_round()
        return True

    async def answer(self, interaction: discord.Interaction, option_index: int) -> None:
        if self.finished or not self.current:
            await interaction.response.send_message("انتهت هذه اللعبة.", ephemeral=True)
            return
        self.players.add(interaction.user.id)
        if self.winner_for_round is not None:
            await interaction.response.send_message("تمت الإجابة عن هذه الجولة، انتظر الجولة التالية.", ephemeral=True)
            return
        selected = self.options[option_index]
        if selected != self.current:
            await interaction.response.send_message("إجابة غير صحيحة، حاول مرة أخرى.", ephemeral=True)
            return
        self.winner_for_round = interaction.user.id
        self.scores[interaction.user.id] = self.scores.get(interaction.user.id, 0) + 1
        db.add_game_points(interaction.guild.id if interaction.guild else 0, interaction.user.id, "flags", 1)
        await interaction.response.send_message("✅ إجابة صحيحة! حصلت على نقطة.", ephemeral=True)
        if self.message:
            embed = discord.Embed(
                title=f"✅ الجولة {self.round_number} انتهت",
                description=f"الفائز: {interaction.user.mention}\nالعلم: {self.current[0]} — **{self.current[1]}**\n\n**النقاط الحالية**\n{_display_scores(self)}",
                colour=discord.Colour.green(),
            )
            await self.message.edit(embed=embed, view=None)
        await asyncio.sleep(2)
        await self.next_round()

    async def finish(self) -> None:
        self.finished = True
        if self.round_task and not self.round_task.done():
            self.round_task.cancel()
        ACTIVE_GAMES.pop(self.ctx.guild.id, None)
        winner = max(self.scores, key=self.scores.get) if self.scores else None
        winner_text = f"الفائز النهائي: <@{winner}>" if winner else "لم يحصل أي لاعب على نقاط."
        embed = discord.Embed(title="🏆 انتهت لعبة الأعلام", description=f"{winner_text}\n\n**المتصدّرون**\n{_display_scores(self)}", colour=discord.Colour.green())
        if self.message:
            await self.message.edit(embed=embed, view=None)


class FlagLobbyView(discord.ui.View):
    def __init__(self, game: FlagGame):
        super().__init__(timeout=300)
        self.game = game

    @discord.ui.button(label="انضمام", emoji="🙋", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.game.players.add(interaction.user.id)
        await interaction.response.send_message("✅ انضممت إلى اللعبة.", ephemeral=True)

    @discord.ui.button(label="بدء اللعب", emoji="▶️", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.game.start(interaction)

    @discord.ui.button(label="إلغاء", emoji="✖️", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.game.host_id:
            await interaction.response.send_message("فقط المضيف يستطيع إلغاء اللعبة.", ephemeral=True)
            return
        self.game.finished = True
        ACTIVE_GAMES.pop(self.game.ctx.guild.id, None)
        await interaction.response.edit_message(content="تم إلغاء لعبة الأعلام.", embed=None, view=None)


class FlagAnswerView(discord.ui.View):
    def __init__(self, game: FlagGame):
        super().__init__(timeout=30)
        self.game = game
        for index, (_, country) in enumerate(game.options):
            button = discord.ui.Button(label=country, style=discord.ButtonStyle.secondary, custom_id=f"flags:{id(game)}:{index}")
            button.callback = self._callback(index)
            self.add_item(button)

    def _callback(self, index: int):
        async def callback(interaction: discord.Interaction) -> None:
            await self.game.answer(interaction, index)
        return callback


async def start_flag_game(ctx: Any) -> None:
    if not ctx.guild:
        await ctx.send("هذه اللعبة تعمل داخل السيرفر فقط.")
        return
    if ctx.guild.id in ACTIVE_GAMES:
        await ctx.send("هناك لعبة أعلام جارية في هذا السيرفر بالفعل.")
        return
    configured_rounds = db.get_games_config(ctx.guild.id).get("flags_rounds", 5)
    try:
        rounds = max(1, min(int(configured_rounds), 20))
    except (TypeError, ValueError):
        rounds = 5
    game = FlagGame(ctx=ctx, host_id=ctx.author.id, rounds=rounds, continuous=True)
    ACTIVE_GAMES[ctx.guild.id] = game
    game.message = await ctx.send(embed=discord.Embed(title="🏳️ أعلام", description="جاري تجهيز أول علم...", colour=discord.Colour.blurple()))
    await game.next_round()


async def handle_flag_guess(message: Any) -> bool:
    game = ACTIVE_GAMES.get(message.guild.id if message.guild else 0)
    if not game or not game.continuous:
        return False
    return await game.answer_text(message)


async def stop_flag_event(ctx: Any) -> bool:
    game = ACTIVE_GAMES.get(ctx.guild.id if ctx.guild else 0)
    if not game:
        return False
    await game.finish()
    await ctx.send("⏹️ تم إيقاف فعالية الأعلام.")
    return True


def games_help_embed() -> discord.Embed:
    return discord.Embed(
        title="🎮 ألعاب Spectre",
        description="الألعاب المتاحة حاليًا:\n\n**🏳️ فعالية الأعلام** — استخدم `/لعبة_الأعلام` أو `!لعبة_الأعلام` لعرض علم والإجابة بكتابة اسم الدولة. تستمر الجولات حتى `!توقف_الأعلام` بواسطة الإدارة.\n\n**⭕ XO** و**🪨📄✂️ حجر-ورق-مقص** و**🎲 النرد** — استخدم الأمر مع منشن لاعب آخر.\n\nقريبًا: Roulette وGuess The Draw.",
        colour=discord.Colour.blurple(),
    )


@dataclass
class XOGame:
    ctx: Any
    player_x: int
    player_o: int
    board: list[str] = field(default_factory=lambda: [" "] * 9)
    turn: str = "X"
    message: discord.Message | None = None
    finished: bool = False

    def current_user(self) -> int:
        return self.player_x if self.turn == "X" else self.player_o

    def winner(self) -> str | None:
        lines = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))
        for first, second, third in lines:
            if self.board[first] != " " and self.board[first] == self.board[second] == self.board[third]:
                return self.board[first]
        return None

    async def render(self, notice: str = "") -> None:
        if not self.message:
            return
        embed = discord.Embed(title="⭕ لعبة XO", description=f"{notice}\n\nالدور الآن: <@{self.current_user()}> ({self.turn})", colour=discord.Colour.blurple())
        embed.add_field(name="اللاعب X", value=f"<@{self.player_x}>", inline=True)
        embed.add_field(name="اللاعب O", value=f"<@{self.player_o}>", inline=True)
        await self.message.edit(embed=embed, view=XOView(self))

    async def play(self, interaction: discord.Interaction, index: int) -> None:
        if self.finished:
            await interaction.response.send_message("انتهت اللعبة.", ephemeral=True)
            return
        if interaction.user.id != self.current_user():
            await interaction.response.send_message("ليس دورك الآن.", ephemeral=True)
            return
        if self.board[index] != " ":
            await interaction.response.send_message("هذه الخانة مستخدمة.", ephemeral=True)
            return
        self.board[index] = self.turn
        result = self.winner()
        if result or " " not in self.board:
            self.finished = True
            if result:
                winner_id = self.player_x if result == "X" else self.player_o
                loser_id = self.player_o if result == "X" else self.player_x
                db.add_game_points(self.ctx.guild.id, winner_id, "xo", 3, True)
                db.add_game_points(self.ctx.guild.id, loser_id, "xo", 0, False)
                notice = f"🏆 الفائز: <@{winner_id}> — حصل على **3 نقاط**"
            else:
                notice = "🤝 تعادل!"
            await interaction.response.edit_message(embed=discord.Embed(title="⭕ انتهت لعبة XO", description=notice, colour=discord.Colour.green()), view=None)
            return
        self.turn = "O" if self.turn == "X" else "X"
        await interaction.response.defer()
        await self.render()


class XOView(discord.ui.View):
    def __init__(self, game: XOGame):
        super().__init__(timeout=300)
        self.game = game
        for index, value in enumerate(game.board):
            button = discord.ui.Button(label=value if value != " " else "·", style=discord.ButtonStyle.primary if value == " " else discord.ButtonStyle.secondary, row=index // 3, custom_id=f"xo:{id(game)}:{index}")
            button.callback = self._callback(index)
            self.add_item(button)

    def _callback(self, index: int):
        async def callback(interaction: discord.Interaction) -> None:
            await self.game.play(interaction, index)
        return callback


async def start_xo_game(ctx: Any, opponent: Any | None = None) -> None:
    if not ctx.guild:
        await ctx.send("هذه اللعبة تعمل داخل السيرفر فقط.")
        return
    if opponent is None or opponent.bot or opponent.id == ctx.author.id:
        await ctx.send("استخدم الأمر مع لاعب آخر، مثال: `/لعبة_xo @العضو`.")
        return
    game = XOGame(ctx=ctx, player_x=ctx.author.id, player_o=opponent.id)
    game.message = await ctx.send(embed=discord.Embed(title="⭕ لعبة XO", description=f"الدور الأول: {ctx.author.mention} (X)", colour=discord.Colour.blurple()), view=XOView(game))


RPS_CHOICES = {"حجر": "🪨", "ورق": "📄", "مقص": "✂️"}
RPS_BEATS = {"حجر": "مقص", "ورق": "حجر", "مقص": "ورق"}


@dataclass
class RPSGame:
    ctx: Any
    player_a: int
    player_b: int
    choices: dict[int, str] = field(default_factory=dict)
    message: discord.Message | None = None
    finished: bool = False

    async def choose(self, interaction: discord.Interaction, choice: str) -> None:
        if self.finished:
            await interaction.response.send_message("انتهت اللعبة.", ephemeral=True)
            return
        if interaction.user.id not in {self.player_a, self.player_b}:
            await interaction.response.send_message("هذه اللعبة بين اللاعبين المحددين فقط.", ephemeral=True)
            return
        self.choices[interaction.user.id] = choice
        await interaction.response.send_message(f"تم تسجيل اختيارك: {RPS_CHOICES[choice]}", ephemeral=True)
        if len(self.choices) < 2:
            return
        self.finished = True
        first, second = self.choices[self.player_a], self.choices[self.player_b]
        if first == second:
            result = "🤝 تعادل!"
            colour = discord.Colour.gold()
        else:
            first_wins = RPS_BEATS[first] == second
            winner = self.player_a if first_wins else self.player_b
            db.add_game_points(self.ctx.guild.id, winner, "rps", 2, True)
            result = f"🏆 الفائز: <@{winner}> — حصل على **نقطتين**"
            colour = discord.Colour.green()
        embed = discord.Embed(title="🪨📄✂️ انتهت لعبة حجر-ورق-مقص", description=f"<@{self.player_a}>: {RPS_CHOICES[first]}\n<@{self.player_b}>: {RPS_CHOICES[second]}\n\n{result}", colour=colour)
        if self.message:
            await self.message.edit(embed=embed, view=None)


class RPSView(discord.ui.View):
    def __init__(self, game: RPSGame):
        super().__init__(timeout=120)
        self.game = game
        for choice, emoji in RPS_CHOICES.items():
            button = discord.ui.Button(label=choice, emoji=emoji, style=discord.ButtonStyle.primary, custom_id=f"rps:{id(game)}:{choice}")
            button.callback = self._callback(choice)
            self.add_item(button)

    def _callback(self, choice: str):
        async def callback(interaction: discord.Interaction) -> None:
            await self.game.choose(interaction, choice)
        return callback


async def start_rps_game(ctx: Any, opponent: Any | None = None) -> None:
    if not ctx.guild:
        await ctx.send("هذه اللعبة تعمل داخل السيرفر فقط.")
        return
    if opponent is None or opponent.bot or opponent.id == ctx.author.id:
        await ctx.send("استخدم الأمر مع لاعب آخر، مثال: `/لعبة_حجر_ورق_مقص @العضو`.")
        return
    game = RPSGame(ctx=ctx, player_a=ctx.author.id, player_b=opponent.id)
    embed = discord.Embed(title="🪨📄✂️ لعبة حجر-ورق-مقص", description=f"{ctx.author.mention} ضد {opponent.mention}\nاختاروا الحركة من الأزرار أدناه.", colour=discord.Colour.blurple())
    game.message = await ctx.send(embed=embed, view=RPSView(game))


@dataclass
class DiceGame:
    ctx: Any
    player_a: int
    player_b: int
    rolls: dict[int, int] = field(default_factory=dict)
    message: discord.Message | None = None
    finished: bool = False

    async def roll(self, interaction: discord.Interaction) -> None:
        if self.finished:
            await interaction.response.send_message("انتهت اللعبة.", ephemeral=True)
            return
        if interaction.user.id not in {self.player_a, self.player_b}:
            await interaction.response.send_message("هذه اللعبة بين اللاعبين المحددين فقط.", ephemeral=True)
            return
        if interaction.user.id in self.rolls:
            await interaction.response.send_message("لقد رميت النرد بالفعل، انتظر اللاعب الآخر.", ephemeral=True)
            return
        self.rolls[interaction.user.id] = random.randint(1, 6)
        await interaction.response.send_message(f"🎲 نتيجتك: **{self.rolls[interaction.user.id]}**", ephemeral=True)
        if len(self.rolls) < 2:
            return
        self.finished = True
        first, second = self.rolls[self.player_a], self.rolls[self.player_b]
        if first == second:
            result = "🤝 تعادل!"
            colour = discord.Colour.gold()
        else:
            winner = self.player_a if first > second else self.player_b
            db.add_game_points(self.ctx.guild.id, winner, "dice", 1, True)
            result = f"🏆 الفائز: <@{winner}> — حصل على **نقطة**"
            colour = discord.Colour.green()
        embed = discord.Embed(title="🎲 انتهت لعبة النرد", description=f"<@{self.player_a}>: **{first}**\n<@{self.player_b}>: **{second}**\n\n{result}", colour=colour)
        if self.message:
            await self.message.edit(embed=embed, view=None)


class DiceView(discord.ui.View):
    def __init__(self, game: DiceGame):
        super().__init__(timeout=120)
        self.game = game
        button = discord.ui.Button(label="ارمِ النرد", emoji="🎲", style=discord.ButtonStyle.primary, custom_id=f"dice:{id(game)}")
        button.callback = self._callback
        self.add_item(button)

    async def _callback(self, interaction: discord.Interaction) -> None:
        await self.game.roll(interaction)


async def start_dice_game(ctx: Any, opponent: Any | None = None) -> None:
    if not ctx.guild:
        await ctx.send("هذه اللعبة تعمل داخل السيرفر فقط.")
        return
    if opponent is None or opponent.bot or opponent.id == ctx.author.id:
        await ctx.send("استخدم الأمر مع لاعب آخر، مثال: `/لعبة_النرد @العضو`.")
        return
    game = DiceGame(ctx=ctx, player_a=ctx.author.id, player_b=opponent.id)
    game.message = await ctx.send(embed=discord.Embed(title="🎲 لعبة النرد", description=f"{ctx.author.mention} ضد {opponent.mention}\nاضغطوا زر رمي النرد.", colour=discord.Colour.blurple()), view=DiceView(game))


async def send_games_leaderboard(ctx: Any) -> None:
    if not ctx.guild:
        await ctx.send("هذا المتصدر يعمل داخل السيرفر فقط.")
        return
    rows = db.get_game_leaderboard(ctx.guild.id, limit=10)
    if not rows:
        await ctx.send("لا توجد نقاط ألعاب محفوظة في هذا السيرفر حتى الآن.")
        return
    lines = []
    for index, row in enumerate(rows, 1):
        game_name = {"flags": "🏳️ الأعلام", "xo": "⭕ XO", "rps": "🪨📄✂️ حجر-ورق-مقص", "dice": "🎲 النرد"}.get(row["game_id"], row["game_id"])
        lines.append(f"**{index}.** <@{row['user_id']}> — **{row['points']}** نقطة · {game_name}")
    await ctx.send(embed=discord.Embed(title="🏆 متصدرو ألعاب Spectre", description="\n".join(lines), colour=discord.Colour.gold()))


GAME_COMMAND_KEYS = {
    "flags": "لعبة_الأعلام",
    "xo": "لعبة_xo",
    "rps": "لعبة_حجر_ورق_مقص",
    "dice": "لعبة_النرد",
}


def normalize_command_name(value: str) -> str:
    raw = str(value or "").strip()
    if any(char.isspace() for char in raw):
        raise ValueError("اسم الأمر يجب أن يكون من 1 إلى 32 حرفًا دون مسافات أو رموز Discord")
    cleaned = raw
    if not cleaned or len(cleaned) > 32 or any(char in cleaned for char in "`!@#$%^&*()[]{}<>/\\|؟،"):
        raise ValueError("اسم الأمر يجب أن يكون من 1 إلى 32 حرفًا دون مسافات أو رموز Discord")
    return cleaned


def set_custom_game_name(guild_id: int, game_id: str, name: str) -> str:
    if game_id not in GAME_COMMAND_KEYS:
        raise ValueError("اللعبة غير معروفة")
    custom_name = normalize_command_name(name)
    config = db.get_games_config(guild_id)
    names = config.get("custom_names", {}) if isinstance(config.get("custom_names", {}), dict) else {}
    names[game_id] = custom_name
    config["custom_names"] = names
    db.save_games_config(guild_id, config)
    return custom_name


def resolve_custom_command(guild_id: int, token: str) -> str | None:
    normalized = str(token or "").strip().lower()
    for game_id, canonical in GAME_COMMAND_KEYS.items():
        if normalized == get_custom_game_name(guild_id, game_id).lower():
            return canonical
    return None


def get_custom_game_name(guild_id: int, game_id: str) -> str:
    config = db.get_games_config(guild_id)
    names = config.get("custom_names", {}) if isinstance(config.get("custom_names", {}), dict) else {}
    return str(names.get(game_id) or GAME_COMMAND_KEYS.get(game_id, game_id))


def apply_custom_aliases(bot: Any) -> None:
    for command in bot.commands:
        if getattr(command, "name", None) in GAME_COMMAND_KEYS.values():
            command_id = next(key for key, value in GAME_COMMAND_KEYS.items() if value == command.name)
            for guild in bot.guilds:
                custom = get_custom_game_name(guild.id, command_id)
                if custom != command.name and custom not in command.aliases:
                    command.aliases.append(custom)
