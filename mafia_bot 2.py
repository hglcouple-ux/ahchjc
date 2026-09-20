import asyncio
import html
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError
from telegram.request import HTTPXRequest

# ============ НАСТРОЙКИ ============
BOT_TOKEN = "8764996048:AAGZtoWwEjlT8trYjV7FxYM-hq5SWKAhZ9k"

# Путь к БАЗЕ ДАННЫХ ЭКОНОМИЧЕСКОГО БОТА (app.py).
# ВАЖНО: должно указывать на тот же самый файл bot_data.db, который использует
# app.py (там DB_PATH = 'bot_data.db'). Если mafia_bot.py запускается из другой
# папки — пропишите здесь абсолютный путь до этого же файла, иначе бот мафии
# не найдёт балансы игроков.
ECONOMY_DB_PATH = os.environ.get("DB_PATH", "bot_data.db")

REGISTRATION_SECONDS = 120     # 2 минуты - базовое время регистрации
BET_INPUT_SECONDS = 30         # ожидание ставки после команды /mafia
EXTEND_SECONDS = 30            # +30 сек по команде продления
EXTEND_CAP_SECONDS = 150       # максимум 2.5 минуты продления за один "запас"
RESET_THRESHOLD_SECONDS = 120  # когда таймер скатывается до 2 минут - запас продления обнуляется
NIGHT_SECONDS = 60              # время на выбор действия ночью (убить/вылечить/проверить) — 1 минута всем
VOTING_SECONDS = 60             # время каждой фазы дневного голосования (номинация и подтверждение) — всегда ждём до конца таймера
DAY_DISCUSS_SECONDS = 45

# Гифки для ночи и утра. Можно заменить на свои ссылки или file_id.
NIGHT_GIF_URL = "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExanZzc2VuN2I0eHFmdG9taGVwbHpqcjllY29oazduMXdtMnVwcWdhciZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/ypv6RH7qPZC6Skvxht/giphy.gif"
DAY_GIF_URL = "https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExbnE2cXUxMzA0anV5N2wzYTdwY3Z0OWE4ZzU3NmpkODJtemIxMGNpaCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/nengggZCIwKDiMyvGX/giphy.gif" 

NIGHT_STATUS_INTERVAL = 30  # каждые сколько секунд ночью присылать список живых + оставшееся время

logging.basicConfig(level=logging.INFO)

# Юзернейм бота - заполняется автоматически при запуске (нужен для кнопки "Перейти к боту")
BOT_USERNAME: Optional[str] = None


# ============ ЭКОНОМИКА (общая БД с app.py) ============
#
# Мы не дублируем логику экономического бота, а работаем напрямую с той же
# таблицей users в bot_data.db, читая/изменяя только колонку balance_normal.
# Списание сделано одним атомарным UPDATE с условием "хватает ли денег" в
# WHERE, поэтому даже если два игрока жмут "Вступить" одновременно, баланс
# никогда не уйдёт в минус.

async def get_economy_balance(user_id: int) -> Optional[int]:
    """Возвращает баланс обычных монет игрока или None, если игрок ещё
    ни разу не запускал экономического бота (нет записи в users)."""
    async with aiosqlite.connect(ECONOMY_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT balance_normal FROM users WHERE _id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def try_charge_bet(user_id: int, amount: int) -> bool:
    """Пытается атомарно списать ставку с баланса игрока в экономическом
    боте. Возвращает True, если денег хватило и списание прошло, False -
    если игрока нет в базе или у него недостаточно средств."""
    if amount <= 0:
        return True
    async with aiosqlite.connect(ECONOMY_DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE users SET balance_normal = balance_normal - ? "
            "WHERE _id = ? AND balance_normal >= ?",
            (amount, user_id, amount),
        )
        await db.commit()
        return cursor.rowcount > 0


async def refund_bet(user_id: int, amount: int) -> None:
    """Возвращает ранее списанную ставку игроку (отмена игры, нехватка
    игроков, техническая ошибка и т.п.)."""
    if amount <= 0:
        return
    async with aiosqlite.connect(ECONOMY_DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance_normal = balance_normal + ? WHERE _id = ?",
            (amount, user_id),
        )
        await db.commit()


async def payout_winnings(user_id: int, amount: int) -> None:
    """Начисляет игроку его долю банка после победы."""
    if amount <= 0:
        return
    async with aiosqlite.connect(ECONOMY_DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance_normal = balance_normal + ? WHERE _id = ?",
            (amount, user_id),
        )
        await db.commit()


async def refund_all_players(game: "Game") -> None:
    """Возвращает ставки всем игрокам, которые успели вступить в игру
    (используется при отмене / провале / нехватке игроков)."""
    for p in game.players.values():
        if p.bet > 0:
            try:
                await refund_bet(p.user_id, p.bet)
            except Exception:
                logging.exception(
                    f"Не удалось вернуть ставку игроку {p.user_id} в чате {game.chat_id}"
                )


# ============ СОСТОЯНИЕ ИГРЫ ============

@dataclass
class Player:
    user_id: int
    name: str
    role: str = "civilian"   # civilian / mafia / doctor / sheriff
    alive: bool = True
    bet: int = 0
    self_heal_used: bool = False  # доктор уже лечил сам себя один раз за игру


@dataclass
class Game:
    chat_id: int
    bet: int
    host_id: int
    players: Dict[int, Player] = field(default_factory=dict)
    state: str = "registration"  # registration / night / day / voting / finished
    reg_message_id: Optional[int] = None
    reg_seconds_left: int = REGISTRATION_SECONDS
    extend_used: int = 0  # сколько секунд продления уже использовано с последнего сброса

    # ---- ночь ----
    night_actions: dict = field(default_factory=dict)          # kill / save
    night_msg: Dict[int, int] = field(default_factory=dict)    # user_id -> message_id личного сообщения ночью
    night_role_announced: Set[str] = field(default_factory=set)  # какие роли уже "засветились" в группе этой ночью
    night_locked: Set[int] = field(default_factory=set)         # user_id тех, кто уже сделал свой ночной выбор — повторно нельзя
    night_seconds_left: int = 0

    day_number: int = 0
    game_start_time: Optional[float] = None

    # ---- день / голосование ----
    day_phase: str = "none"                                    # nominating / confirming / none
    day_votes: Dict[int, int] = field(default_factory=dict)    # voter_id -> кого обвиняет
    nomination_msg: Dict[int, int] = field(default_factory=dict)  # voter_id -> message_id в лс
    vote_target: Optional[int] = None
    confirm_likes: Set[int] = field(default_factory=set)
    confirm_dislikes: Set[int] = field(default_factory=set)
    confirm_message_id: Optional[int] = None

    task: Optional[asyncio.Task] = None
    night_task: Optional[asyncio.Task] = None
    voting_task: Optional[asyncio.Task] = None
    confirm_task: Optional[asyncio.Task] = None
    pot: int = 0

    def alive_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.alive]

    def mafia_alive(self) -> List[Player]:
        return [p for p in self.alive_players() if p.role == "mafia"]

    def civilians_alive(self) -> List[Player]:
        return [p for p in self.alive_players() if p.role != "mafia"]


# chat_id -> Game
games: Dict[int, Game] = {}

# chat_id -> user_id автора команды /mafia, который сейчас вводит ставку
pending_mafia_hosts: Dict[int, int] = {}
# chat_id -> задача ожидания ставки
pending_mafia_bet_tasks: Dict[int, asyncio.Task] = {}


# ============ ФОРМАТИРОВАНИЕ ============

def pluralize(n: int, one: str, few: str, many: str) -> str:
    n_abs = abs(n) % 100
    n1 = n_abs % 10
    if 10 < n_abs < 20:
        return many
    if 1 < n1 < 5:
        return few
    if n1 == 1:
        return one
    return many


def format_time(seconds: int) -> str:
    m = seconds // 60
    s = seconds % 60
    parts = []
    if m > 0:
        parts.append(f"{m} {pluralize(m, 'минута', 'минуты', 'минут')}")
    if s > 0 or m == 0:
        parts.append(f"{s} {pluralize(s, 'секунда', 'секунды', 'секунд')}")
    return " ".join(parts)


def alive_players_text(game: Game) -> str:
    alive = game.alive_players()
    names = "\n".join(
        f"— {mention(player.user_id, player.name)}" for player in alive
    )
    return f"<b>Живые игроки ({len(alive)}):</b>\n{names or 'никого'}"


def mention(user_id: int, name: str) -> str:
    """HTML-ссылка-упоминание пользователя, работает даже если у него нет @username."""
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


# ============ КЛАВИАТУРЫ ============

def registration_kb(chat_id: int) -> InlineKeyboardMarkup:
    join_button = InlineKeyboardButton(
        "✅ Вступить в игру", url=f"https://t.me/{BOT_USERNAME}?start=join_{chat_id}"
    )
    return InlineKeyboardMarkup([
        [join_button],
        [InlineKeyboardButton("▶️ Начать игру", callback_data=f"startnow:{chat_id}")],
        [
            InlineKeyboardButton("⏱ +30 сек", callback_data=f"extend:{chat_id}"),
            InlineKeyboardButton("❌ Отменить игру", callback_data=f"cancel:{chat_id}"),
        ],
    ])


def night_action_kb(game: Game, action: str, viewer_id: int) -> InlineKeyboardMarkup:
    if action == "kill":
        # мафия не может "выбрать" другого члена мафии
        targets = [p for p in game.alive_players() if p.role != "mafia"]
    elif action == "check":
        # комиссар/шериф не может проверять самого себя
        targets = [p for p in game.alive_players() if p.user_id != viewer_id]
    elif action == "save":
        targets = game.alive_players()
        viewer = game.players.get(viewer_id)
        # доктор может вылечить себя только один раз за игру — после этого своя кнопка исчезает
        if viewer and viewer.self_heal_used:
            targets = [p for p in targets if p.user_id != viewer_id]
    else:
        targets = game.alive_players()
    buttons = [[InlineKeyboardButton(p.name, callback_data=f"{action}:{game.chat_id}:{p.user_id}")]
               for p in targets]
    return InlineKeyboardMarkup(buttons)


def bot_link_kb() -> Optional[InlineKeyboardMarkup]:
    if not BOT_USERNAME:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Перейти к боту", url=f"https://t.me/{BOT_USERNAME}")]
    ])


def nomination_kb(game: Game, voter_id: int) -> InlineKeyboardMarkup:
    targets = [p for p in game.alive_players() if p.user_id != voter_id]
    buttons = [[InlineKeyboardButton(p.name, callback_data=f"nominate:{game.chat_id}:{p.user_id}")]
               for p in targets]
    return InlineKeyboardMarkup(buttons)


def voting_link_kb(chat_id: int) -> Optional[InlineKeyboardMarkup]:
    if not BOT_USERNAME:
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🗳 Перейти к голосованию",
            url=f"https://t.me/{BOT_USERNAME}?start=vote_{chat_id}",
        )
    ]])


def confirm_kb(game: Game) -> InlineKeyboardMarkup:
    likes = len(game.confirm_likes)
    dislikes = len(game.confirm_dislikes)
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"👍 {likes}", callback_data=f"clike:{game.chat_id}"),
        InlineKeyboardButton(f"👎 {dislikes}", callback_data=f"cdislike:{game.chat_id}"),
    ]])


# ============ ХЕЛПЕРЫ ============

async def safe_send(bot, chat_id, text, **kwargs):
    """
    Обычная отправка, но временная сетевая ошибка (таймаут и т.п.) просто
    логируется и пропускается, а не роняет всю игру. Использовать для
    некритичных/периодических сообщений (напоминания, статус, объявления) —
    если одно такое сообщение потеряется, игра всё равно должна продолжаться.
    Возвращает Message или None, если отправить не удалось.
    """
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except TelegramError as e:
        logging.warning(f"Не удалось отправить сообщение в {chat_id}: {e}")
        return None


async def safe_edit(bot, chat_id, message_id, text, **kwargs):
    try:
        return await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, **kwargs)
    except TelegramError as e:
        logging.warning(f"Не удалось отредактировать сообщение {message_id} в {chat_id}: {e}")
        return None


async def safe_delete(bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramError:
        # Частая причина: бот не админ в группе или у него нет права "Удаление сообщений"
        pass


async def fail_game(bot, game: "Game", error: BaseException, where: str):
    """
    Единая точка аварийного завершения игры.

    Раньше любое необработанное исключение внутри фоновой задачи (night_timer,
    voting_timer, confirmation_timer, registration_timer) тихо убивало эту задачу:
    asyncio просто "хоронит" исключение (в лучшем случае строчка
    "Task exception was never retrieved" в логах), бот ничего не пишет в чат,
    а запись в games[chat_id] никто не удаляет — поэтому чат навсегда "зависал"
    и /mafia <ставка> потом отвечал "игра уже идёт". Эта функция это чинит:
    гарантированно чистит state и всегда уведомляет чат, что бы ни случилось.
    """
    logging.exception(f"Игра в чате {game.chat_id} упала на этапе '{where}'")

    for t in (game.task, game.night_task, game.voting_task, game.confirm_task):
        if t and not t.done():
            t.cancel()

    games.pop(game.chat_id, None)
    pending_mafia_hosts.pop(game.chat_id, None)
    await refund_all_players(game)

    try:
        await bot.send_message(
            game.chat_id,
            "⚠️ Произошла техническая ошибка, и игра была прервана.\n"
            "Ставки возвращены. Начните новую командой /mafia <ставка>.",
        )
    except Exception:
        logging.exception(f"Не удалось уведомить чат {game.chat_id} об аварийном завершении игры")


async def cmd_endmafia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной аварийный сброс — на случай, если игра всё же где-то зависла."""
    chat = update.effective_chat
    chat_id = chat.id
    game = games.get(chat_id)
    if not game:
        await context.bot.send_message(chat_id, "В этом чате сейчас нет активной игры.")
        return

    is_admin = False
    try:
        member = await context.bot.get_chat_member(chat_id, update.effective_user.id)
        is_admin = member.status in ("administrator", "creator")
    except Exception:
        pass

    if update.effective_user.id != game.host_id and not is_admin:
        await context.bot.send_message(
            chat_id, "Завершить игру может только тот, кто её создал, или админ чата."
        )
        return

    for t in (game.task, game.night_task, game.voting_task, game.confirm_task):
        if t and not t.done():
            t.cancel()
    games.pop(chat_id, None)
    await refund_all_players(game)
    await context.bot.send_message(chat_id, "🛑 Игра принудительно завершена. Ставки возвращены. Можно начать новую: /mafia <ставка>")


# ============ КОМАНДА СТАРТА ЛОББИ ============

async def cmd_mafia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_id = chat.id

    if chat.type not in ("group", "supergroup"):
        await context.bot.send_message(chat_id, "Эту команду можно использовать только в группе.")
        return

    if chat_id in games:
        existing = games[chat_id]
        if existing.state == "registration":
            text = "⚠️ Регистрация уже идёт в этом чате! Дождись её окончания или жми «Вступить в игру»."
        else:
            text = "⚠️ Игра уже идёт в этом чате. Дождись её окончания, чтобы начать новую."
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logging.exception("Не удалось отправить сообщение о том, что игра уже идёт")
        return

    if chat_id in pending_mafia_hosts:
        await context.bot.send_message(
            chat_id,
            "⚠️ Сначала введи ставку для уже начатой настройки игры."
        )
        return

    pending_mafia_hosts[chat_id] = update.effective_user.id
    pending_mafia_bet_tasks[chat_id] = asyncio.create_task(
        bet_input_timer(context.bot, chat_id, update.effective_user.id)
    )
    await context.bot.send_message(
        chat_id,
        "🎭 На какую ставку вы хотите сыграть?\n"
        f"Напишите сумму в течение {BET_INPUT_SECONDS} секунд. "
        "Можно написать <b>0</b>, тогда ставки не будет.",
        parse_mode="HTML",
    )


async def bet_input_timer(bot, chat_id: int, host_id: int):
    try:
        await asyncio.sleep(BET_INPUT_SECONDS)
        if pending_mafia_hosts.get(chat_id) != host_id or chat_id in games:
            return

        pending_mafia_hosts.pop(chat_id, None)
        game = Game(chat_id=chat_id, bet=0, host_id=host_id)
        games[chat_id] = game
        await safe_send(
            bot,
            chat_id,
            "⏱ Время ожидания ставки вышло. Игра начинается без ставки (0).",
        )
        await open_registration(bot, game)
    except asyncio.CancelledError:
        pass
    except Exception:
        logging.exception(f"Не удалось автоматически начать игру без ставки в чате {chat_id}")
    finally:
        if pending_mafia_bet_tasks.get(chat_id) is asyncio.current_task():
            pending_mafia_bet_tasks.pop(chat_id, None)


async def handle_mafia_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    if not message.text:
        await moderate_chat(update, context)
        return

    chat_id = message.chat.id
    host_id = pending_mafia_hosts.get(chat_id)
    if host_id is None:
        await moderate_chat(update, context)
        return

    if message.from_user.id != host_id:
        await moderate_chat(update, context)
        return

    value = message.text.strip()
    if not value.isdigit():
        await context.bot.send_message(
            chat_id,
            "❌ Напиши ставку целым числом от 0 и выше. Например: 500 или 0.",
        )
        return

    bet = int(value)
    pending_mafia_hosts.pop(chat_id, None)
    bet_task = pending_mafia_bet_tasks.pop(chat_id, None)
    if bet_task and not bet_task.done():
        bet_task.cancel()
    if chat_id in games:
        await context.bot.send_message(chat_id, "⚠️ Игра уже запущена в этом чате.")
        return

    game = Game(chat_id=chat_id, bet=bet, host_id=message.from_user.id)
    games[chat_id] = game
    await open_registration(context.bot, game)


async def open_registration(bot, game: Game):
    text = (
        f"🎭 <b>МАФИЯ</b>\n"
        f"Ставка: <b>{game.bet}</b>\n"
        f"Регистрация открыта: <b>{format_time(game.reg_seconds_left)}</b>\n\n"
        f"Игроков: 0"
    )
    msg = await bot.send_message(
        chat_id=game.chat_id, text=text, reply_markup=registration_kb(game.chat_id), parse_mode="HTML"
    )
    game.reg_message_id = msg.message_id

    game.task = asyncio.create_task(registration_timer(bot, game))


async def registration_timer(bot, game: Game):
    try:
        while game.reg_seconds_left > 0 and game.state == "registration":
            prev_seconds = game.reg_seconds_left
            await asyncio.sleep(1)
            game.reg_seconds_left -= 1

            # если таймер скатился до порога сброса (или ниже) - обнуляем запас продления
            if prev_seconds > RESET_THRESHOLD_SECONDS >= game.reg_seconds_left:
                game.extend_used = 0

            # каждые 30 секунд - отдельное сообщение с напоминанием
            if game.reg_seconds_left > 0 and game.reg_seconds_left % 30 == 0:
                await safe_send(
                    bot,
                    game.chat_id,
                    f"⏳ До окончания регистрации осталось <b>{format_time(game.reg_seconds_left)}</b>",
                    parse_mode="HTML"
                )

            if game.reg_seconds_left % 5 == 0 or game.reg_seconds_left <= 5:
                await update_registration_message(bot, game)

        if game.state == "registration":
            await finish_registration(bot, game)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        await fail_game(bot, game, e, "registration_timer")


async def update_registration_message(bot, game: Game):
    names = "\n".join(f"— {p.name}" for p in game.players.values()) or "пока никого"
    text = (
        f"🎭 <b>МАФИЯ</b>\n"
        f"Ставка: <b>{game.bet}</b>\n"
        f"Регистрация открыта: <b>{format_time(game.reg_seconds_left)}</b>\n\n"
        f"Игроков ({len(game.players)}):\n{names}"
    )
    try:
        await bot.edit_message_text(
            text, chat_id=game.chat_id, message_id=game.reg_message_id,
            reply_markup=registration_kb(game.chat_id), parse_mode="HTML"
        )
    except TelegramError:
        # BadRequest (сообщение не изменилось) или временная сетевая ошибка -
        # в обоих случаях это не повод рушить игру, просто пропускаем этот тик.
        pass


async def finish_registration(bot, game: Game):
    # Таймер и кнопка старта могут сработать почти одновременно. Переводим
    # игру в промежуточное состояние до первого await, чтобы запуск был один.
    if game.state == "registration":
        game.state = "starting"
    elif game.state != "starting":
        return

    if len(game.players) < 4:
        await refund_all_players(game)
        await bot.send_message(game.chat_id, "❌ Недостаточно игроков (минимум 4). Игра отменена, ставки возвращены.")
        games.pop(game.chat_id, None)
        return

    assign_roles(game)
    game.pot = sum(p.bet for p in game.players.values())
    game.state = "night"
    game.game_start_time = time.monotonic()

    names = "\n".join(f"— {mention(p.user_id, p.name)}" for p in game.players.values())
    await safe_send(
        bot,
        game.chat_id,
        f"✅ Регистрация окончена!\nИгроков: {len(game.players)}\n{names}\n\n"
        f"💰 Банк: <b>{game.pot}</b>\n\n"
        f"🎭 Роли ушли в личные сообщения от бота. Открой чат с ботом, чтобы посмотреть свою роль.",
        parse_mode="HTML"
    )

    failed = []
    for p in game.players.values():
        try:
            await bot.send_message(p.user_id, f"Твоя роль: <b>{role_name(p.role)}</b>", parse_mode="HTML")
        except TelegramError:
            failed.append(p)

    if failed:
        names_failed = ", ".join(mention(p.user_id, p.name) for p in failed)
        await safe_send(
            bot,
            game.chat_id,
            f"⚠️ Не удалось отправить роль в личку: {names_failed}\n"
            f"Им нужно открыть чат с ботом, нажать /start и сообщить организатору.",
            parse_mode="HTML"
        )

    await start_night(bot, game)


def role_name(role: str) -> str:
    return {
        "mafia": "🤵🏻 Мафия",
        "doctor": "👨🏼‍⚕️ Доктор",
        "sheriff": "🕵 Шериф",
        "civilian": "👨🏼 Мирный житель",
    }.get(role, role)


def assign_roles(game: Game):
    players = list(game.players.values())
    random.shuffle(players)
    n = len(players)
    mafia_count = max(1, n // 4)

    for i, p in enumerate(players):
        if i < mafia_count:
            p.role = "mafia"
        elif i == mafia_count:
            p.role = "doctor"
        elif i == mafia_count + 1:
            p.role = "sheriff"
        else:
            p.role = "civilian"


# ============ НОЧЬ ============

async def start_night(bot, game: Game):
    game.state = "night"
    game.night_actions = {}
    game.night_msg = {}
    game.night_role_announced = set()
    game.night_locked = set()
    game.night_seconds_left = NIGHT_SECONDS

    intro = (
        "🌃 <b>Наступает ночь</b>\n"
        f"Спать осталось <b>{format_time(NIGHT_SECONDS)}</b>.\n"
        "На улицы города выходят лишь самые отважные и бесстрашные.\n\n"
        f"{alive_players_text(game)}"
    )
    kb = bot_link_kb()
    try:
        await bot.send_animation(game.chat_id, NIGHT_GIF_URL, caption=intro, parse_mode="HTML", reply_markup=kb)
    except Exception:
        logging.exception("Не удалось отправить гифку ночи, отправляю обычным текстом")
        await safe_send(bot, game.chat_id, intro, parse_mode="HTML", reply_markup=kb)

    # Личные приглашения ролям уходят сразу и тихо (без объявлений в группе).
    # Сообщение "роль начала действовать" в группе появится только тогда,
    # когда эта роль реально сделает свой первый выбор — см. cb_kill / cb_save / cb_check.
    for m in game.mafia_alive():
        try:
            msg = await bot.send_message(
                m.user_id,
                "Мафия проводит голосование за следующую жертву:",
                reply_markup=night_action_kb(game, "kill", m.user_id),
            )
            game.night_msg[m.user_id] = msg.message_id
        except Exception:
            pass

    for d in [p for p in game.alive_players() if p.role == "doctor"]:
        try:
            msg = await bot.send_message(
                d.user_id, "Кого будем лечить?", reply_markup=night_action_kb(game, "save", d.user_id)
            )
            game.night_msg[d.user_id] = msg.message_id
        except Exception:
            pass

    for s in [p for p in game.alive_players() if p.role == "sheriff"]:
        try:
            msg = await bot.send_message(
                s.user_id, "Кого проверить?", reply_markup=night_action_kb(game, "check", s.user_id)
            )
            game.night_msg[s.user_id] = msg.message_id
        except Exception:
            pass

    game.night_task = asyncio.create_task(night_timer(bot, game))


async def maybe_resolve_night(bot, game: Game):
    required_actions = set()
    if game.mafia_alive():
        required_actions.add("kill")
    if any(p.role == "doctor" for p in game.alive_players()):
        required_actions.add("save")
    if any(p.role == "sheriff" for p in game.alive_players()):
        required_actions.add("check")

    if game.state == "night" and required_actions <= game.night_actions.keys():
        game.state = "resolving_night"
        if game.night_task and game.night_task is not asyncio.current_task():
            game.night_task.cancel()
        await resolve_night(bot, game)


async def night_timer(bot, game: Game):
    try:
        while game.night_seconds_left > 0 and game.state == "night":
            await asyncio.sleep(1)
            game.night_seconds_left -= 1
        if game.state == "night":
            game.state = "resolving_night"
            await resolve_night(bot, game)
    except asyncio.CancelledError:
        pass 
    except Exception as e:
        await fail_game(bot, game, e, "night_timer")


async def resolve_night(bot, game: Game):
    killed_id = game.night_actions.get("kill")
    saved_id = game.night_actions.get("save")

    # финальное сообщение мафии о том, кого они выбрали жертвой этой ночью
    mafia_members = game.mafia_alive()
    if mafia_members:
        if killed_id and killed_id in game.players:
            victim_for_mafia = game.players[killed_id]
            mafia_text = (
                "Голосование мафии завершено\n"
                f"Мафия принесла в жертву {mention(victim_for_mafia.user_id, victim_for_mafia.name)}."
            )
        else:
            mafia_text = "Голосование мафии завершено\nМафия не выбрала жертву этой ночью."
        for m in mafia_members:
            try:
                await bot.send_message(m.user_id, mafia_text, parse_mode="HTML")
            except TelegramError:
                pass

    text = "☀️ <b>Наступило утро.</b>\n"
    if killed_id and killed_id != saved_id and killed_id in game.players:
        victim = game.players[killed_id]
        victim.alive = False
        text += f"Сегодня был жестоко убит {html.escape(victim.name)}. Его роль: {role_name(victim.role)}."
    else:
        text += "Этой ночью никто не погиб."

    await bot.send_message(game.chat_id, text, parse_mode="HTML")

    if await check_game_over(bot, game):
        return

    await start_day(bot, game)


# ============ ДЕНЬ ============

async def start_day(bot, game: Game):
    game.state = "day"
    game.day_number += 1

    text = (
        f"🏙 <b>День {game.day_number}</b>\n"
        "Солнце всходит, подсушивая на тротуарах пролитую ночью кровь...\n\n"
        f"{alive_players_text(game)}"
    )
    try:
        await bot.send_animation(game.chat_id, DAY_GIF_URL, caption=text, parse_mode="HTML")
    except Exception:
        logging.exception("Не удалось отправить гифку дня, отправляю обычным текстом")
        await bot.send_message(game.chat_id, text, parse_mode="HTML")

    await bot.send_message(
        game.chat_id,
        f"💬 Обсуждение {DAY_DISCUSS_SECONDS} секунд. Только живые игроки могут писать.",
    )
    await asyncio.sleep(DAY_DISCUSS_SECONDS)
    await start_voting(bot, game)


# ---- Фаза 1: номинация (кого подозреваем) ----

async def start_voting(bot, game: Game):
    game.state = "voting"
    game.day_phase = "nominating"
    game.day_votes = {}
    game.nomination_msg = {}
    game.vote_target = None
    game.confirm_likes = set()
    game.confirm_dislikes = set()

    text = (
        "⚖️ <b>Пришло время определить и наказать виноватых.</b>\n"
        f"Голосование продлится {format_time(VOTING_SECONDS)}.\n"
        f"Каждому живому игроку бот уже написал в личные сообщения.\n\n"
        f"{alive_players_text(game)}"
    )
    await bot.send_message(
        game.chat_id,
        text,
        parse_mode="HTML",
        reply_markup=voting_link_kb(game.chat_id),
    )

    # Бот сам присылает бюллетень каждому живому игроку — ждать нажатия кнопки не нужно
    for p in game.alive_players():
        await send_nomination_prompt(bot, game, p)

    game.voting_task = asyncio.create_task(voting_timer(bot, game))


async def send_nomination_prompt(bot, game: Game, player: Player):
    text = "Пришло время искать виноватых!\nКого ты хочешь линчевать?"
    target_id = game.day_votes.get(player.user_id)
    if target_id and target_id in game.players:
        text += f"\n\nТы выбрал: {mention(game.players[target_id].user_id, game.players[target_id].name)}"
    try:
        msg = await bot.send_message(
            player.user_id, text, reply_markup=nomination_kb(game, player.user_id), parse_mode="HTML"
        )
        game.nomination_msg[player.user_id] = msg.message_id
    except TelegramError:
        pass


async def voting_timer(bot, game: Game):
    try:
        await asyncio.sleep(VOTING_SECONDS)
        if game.state == "voting" and game.day_phase == "nominating":
            await resolve_nomination_timeout(bot, game)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        await fail_game(bot, game, e, "voting_timer")


async def resolve_nomination_timeout(bot, game: Game):
    if game.state != "voting" or game.day_phase != "nominating":
        return
    game.day_phase = "resolving"

    if not game.day_votes:
        await safe_send(bot, game.chat_id, "Город никого не заподозрил — сегодня никого не тронут.")
        game.state = "night"
        if await check_game_over(bot, game):
            return
        await start_night(bot, game)
        return

    tally: Dict[int, int] = {}
    for target_id in game.day_votes.values():
        tally[target_id] = tally.get(target_id, 0) + 1
    top_target = max(tally, key=tally.get)
    await start_confirmation(bot, game, top_target)


# ---- Фаза 2: подтверждение (вешаем/не вешаем) ----

async def start_confirmation(bot, game: Game, target_id: int):
    game.day_phase = "confirming"
    game.vote_target = target_id
    game.confirm_likes = set()
    game.confirm_dislikes = set()

    target = game.players[target_id]
    text = f"Вы точно хотите линчевать {mention(target.user_id, target.name)}?"
    msg = await bot.send_message(game.chat_id, text, reply_markup=confirm_kb(game), parse_mode="HTML")
    game.confirm_message_id = msg.message_id
    game.confirm_task = asyncio.create_task(confirmation_timer(bot, game))


async def maybe_resolve_confirmation(bot, game: Game):
    if game.state != "voting" or game.day_phase != "confirming":
        return
    eligible_ids = {
        p.user_id for p in game.alive_players() if p.user_id != game.vote_target
    }
    answered_ids = game.confirm_likes | game.confirm_dislikes
    if eligible_ids <= answered_ids:
        await resolve_confirmation(bot, game)


async def confirmation_timer(bot, game: Game):
    try:
        await asyncio.sleep(VOTING_SECONDS)
        if game.state == "voting" and game.day_phase == "confirming":
            await resolve_confirmation(bot, game)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        await fail_game(bot, game, e, "confirmation_timer")


async def update_confirm_message(bot, game: Game):
    try:
        await bot.edit_message_reply_markup(
            chat_id=game.chat_id, message_id=game.confirm_message_id, reply_markup=confirm_kb(game)
        )
    except TelegramError:
        pass


async def resolve_confirmation(bot, game: Game):
    if game.day_phase != "confirming":
        return
    game.day_phase = "resolving"
    if game.confirm_task and game.confirm_task is not asyncio.current_task():
        game.confirm_task.cancel()

    likes = len(game.confirm_likes)
    dislikes = len(game.confirm_dislikes)
    target = game.players.get(game.vote_target)

    game.state = "night"  # блокируем поздние клики, пока переходим дальше

    if target is None:
        await bot.send_message(game.chat_id, "Голосование окончено\nЦель голосования выбыла — никого не повесили.")
    elif likes == dislikes:
        await bot.send_message(
            game.chat_id,
            f"Мнения жителей разошлись ({likes} 👍 | {dislikes} 👎)... "
            f"Разошлись и сами жители, так никого и не повесив...",
        )
    elif likes > dislikes:
        target.alive = False
        await bot.send_message(
            game.chat_id,
            f"Результаты голосования:\n{likes} 👍 | {dislikes} 👎\n\n"
            f"Вешаем {mention(target.user_id, target.name)} :)\n"
            f"Его роль: {role_name(target.role)}.",
            parse_mode="HTML",
        )
        try:
            await bot.send_message(target.user_id, "Тебя линчевали на дневном собрании :(")
        except TelegramError:
            pass
    else:
        await bot.send_message(
            game.chat_id,
            "Голосование окончено\nМнения жителей разошлись... "
            "Разошлись и сами жители, так никого и не повесив...",
        )

    if await check_game_over(bot, game):
        return

    await start_night(bot, game)


# ============ ПРОВЕРКА ОКОНЧАНИЯ ============

async def check_game_over(bot, game: Game) -> bool:
    mafia = game.mafia_alive()
    civilians = game.civilians_alive()

    winners_role = None
    if not mafia:
        winners_role = "civilians"
    elif len(mafia) >= len(civilians):
        winners_role = "mafia"

    if winners_role is None:
        return False

    # ВАЖНО: победители и выплата - только среди ЖИВЫХ игроков.
    # Изгнанные/убитые ничего не получают, даже если их сторона победила.
    if winners_role == "mafia":
        winners = game.mafia_alive()
        title_line = "Победила Мафия"
    else:
        winners = game.civilians_alive()
        title_line = "Победили Мирные жители"

    winner_ids = {p.user_id for p in winners}
    others = [p for p in game.players.values() if p.user_id not in winner_ids]

    share = game.pot // len(winners) if winners else 0
    winners_lines = "\n".join(
        f"    {mention(p.user_id, p.name)} - {role_name(p.role)} (+{share})" for p in winners
    ) if winners else "    никто не дожил до победы"
    others_lines = "\n".join(
        f"    {mention(p.user_id, p.name)} - {role_name(p.role)}" for p in others
    ) if others else "    —"

    elapsed = int(time.monotonic() - game.game_start_time) if game.game_start_time else 0

    text = (
        f"🏁 <b>Игра окончена!</b>\n"
        f"{title_line}\n\n"
        f"<b>Победители:</b>\n{winners_lines}\n\n"
        f"<b>Остальные участники:</b>\n{others_lines}\n\n"
        f"💰 Банк: {game.pot}\n"
        f"⏱ Игра длилась: {format_time(elapsed)}."
    )

    await bot.send_message(game.chat_id, text, parse_mode="HTML")

    # начисляем реальный выигрыш каждому победителю в экономическом боте
    for p in winners:
        try:
            await payout_winnings(p.user_id, share)
        except Exception:
            logging.exception(
                f"Не удалось начислить выигрыш игроку {p.user_id} в чате {game.chat_id}"
            )

    # личное уведомление об окончании игры каждому участнику
    for p in game.players.values():
        if p.user_id in winner_ids:
            personal_text = (
                f"🏁 <b>Игра окончена!</b>\n{title_line}\n\n"
                f"🎉 Ты дожил до победы!\nТвой выигрыш: <b>{share}</b>."
            )
        else:
            personal_text = (
                f"🏁 <b>Игра окончена!</b>\n{title_line}\n\n"
                f"К сожалению, в этот раз ты не дожил до победы."
            )
        try:
            await bot.send_message(p.user_id, personal_text, parse_mode="HTML")
        except TelegramError:
            pass

    game.state = "finished"
    del games[game.chat_id]
    return True


# ============ КОМАНДА /start (ВСТУПЛЕНИЕ / ГОЛОСОВАНИЕ ЧЕРЕЗ DEEP-LINK) ============

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "Привет! Чтобы сыграть в «Мафию», добавь бот в группу и используй команду /mafia "
            "Так же подписывайся на наш канал что бы быть в курсе последних новостей: @IncMafia."
        )
        return

    payload = args[0]

    if payload.startswith("join_"):
        await handle_join(update, context, payload)
        return

    if payload.startswith("vote_"):
        await handle_vote_deeplink(update, context, payload)
        return

    await update.message.reply_text(
        "Не получилось распознать ссылку. Попробуй нажать кнопку в группе ещё раз."
    )


async def handle_join(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    try:
        chat_id = int(payload.split("_", 1)[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Не получилось распознать ссылку. Попробуй нажать кнопку в группе ещё раз.")
        return

    game = games.get(chat_id)
    if not game or game.state != "registration":
        await update.message.reply_text("Регистрация в этой игре уже закрыта.")
        return

    user_id = update.effective_user.id
    user_name = update.effective_user.full_name

    if user_id in game.players:
        await update.message.reply_text("Ты уже в игре. Жди начала!")
        return

    if game.bet > 0:
        # Списываем ставку с баланса в экономическом боте ДО того, как добавить
        # игрока в игру. В режиме без ставки аккаунт экономического бота не нужен.
        balance = await get_economy_balance(user_id)
        if balance is None:
            await update.message.reply_text(
                "⚠️ Не нашёл твой аккаунт в экономическом боте. "
                "Сначала напиши /start экономическому боту, а потом возвращайся сюда."
            )
            return

        charged = await try_charge_bet(user_id, game.bet)
        if not charged:
            await update.message.reply_text(
                f"❌ Недостаточно монет для этой ставки.\n"
                f"Нужно: <b>{game.bet}</b>\nУ тебя: <b>{balance}</b>",
                parse_mode="HTML",
            )
            return

    try:
        chat = await context.bot.get_chat(chat_id)
    except Exception:
        chat = None

    chat_title = chat.title if chat else "чат"
    invite_link = None
    if chat is not None:
        try:
            invite_link = await context.bot.export_chat_invite_link(chat_id)
        except Exception:
            if chat.username:
                invite_link = f"https://t.me/{chat.username}"

    if invite_link:
        chat_link_html = f'<a href="{invite_link}">{html.escape(chat_title)}</a>'
    else:
        chat_link_html = html.escape(chat_title)

    game.players[user_id] = Player(user_id=user_id, name=user_name, bet=game.bet)

    await update.message.reply_text(
        f"✅ Ты присоединился к игре в {chat_link_html}!\nРоль придёт сюда, когда начнётся игра.",
        parse_mode="HTML"
    )

    await update_registration_message(context.bot, game)

    try:
        await context.bot.send_message(
            chat_id,
            f"{mention(user_id, user_name)} вступил(а) в игру!",
            parse_mode="HTML"
        )
    except Exception:
        pass


async def handle_vote_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    try:
        chat_id = int(payload.split("_", 1)[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Не получилось распознать ссылку.")
        return

    game = games.get(chat_id)
    if not game or game.state != "voting" or game.day_phase != "nominating":
        await update.message.reply_text("Голосование сейчас недоступно.")
        return

    player = game.players.get(update.effective_user.id)
    if not player:
        await update.message.reply_text("Ты не участвуешь в этой игре.")
        return
    if not player.alive:
        await update.message.reply_text("Голосовать могут только живые игроки.")
        return

    await send_nomination_prompt(context.bot, game, player)


async def cb_extend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    call = update.callback_query
    chat_id = int(call.data.split(":")[1])
    game = games.get(chat_id)
    if not game or game.state != "registration":
        await call.answer("Регистрация уже закрыта.", show_alert=True)
        return

    if call.from_user.id != game.host_id:
        await call.answer("Только тот, кто создал игру, может продлевать регистрацию.", show_alert=True)
        return

    if game.extend_used + EXTEND_SECONDS > EXTEND_CAP_SECONDS:
        await call.answer(
            f"Нельзя продлить больше. Лимит продления исчерпан — подожди, "
            f"пока таймер не скатится до {format_time(RESET_THRESHOLD_SECONDS)}.",
            show_alert=True
        )
        return

    game.reg_seconds_left += EXTEND_SECONDS
    game.extend_used += EXTEND_SECONDS
    await call.answer(f"Регистрация продлена на {EXTEND_SECONDS} сек.")
    await update_registration_message(context.bot, game)


async def cb_start_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    call = update.callback_query
    chat_id = int(call.data.split(":")[1])
    game = games.get(chat_id)
    if not game:
        await call.answer("Регистрация уже закрыта.", show_alert=True)
        return

    if game.state == "starting":
        await call.answer("Игра уже запускается, подожди немного.", show_alert=True)
        return
    if game.state != "registration":
        await call.answer("Регистрация уже закрыта.", show_alert=True)
        return

    if call.from_user.id != game.host_id:
        await call.answer("Только тот, кто создал игру, может начать её досрочно.", show_alert=True)
        return

    if len(game.players) < 4:
        await call.answer(
            f"Недостаточно игроков для старта (сейчас {len(game.players)}, нужно минимум 4).",
            show_alert=True
        )
        return

    # Меняем состояние до await, чтобы таймер регистрации не запустил вторую
    # копию finish_registration в тот же момент.
    game.state = "starting"
    if game.task:
        game.task.cancel()
    await call.answer("Игра начинается!")
    try:
        await finish_registration(context.bot, game)
    except Exception as e:
        await fail_game(context.bot, game, e, "cb_start_now/finish_registration")


async def cb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    call = update.callback_query
    chat_id = int(call.data.split(":")[1])
    game = games.get(chat_id)
    if not game:
        await call.answer("Игры нет.", show_alert=True)
        return

    if call.from_user.id != game.host_id:
        await call.answer("Только создатель игры может её отменить.", show_alert=True)
        return

    if game.task:
        game.task.cancel()
    if game.night_task:
        game.night_task.cancel()
    if game.voting_task:
        game.voting_task.cancel()
    if game.confirm_task:
        game.confirm_task.cancel()
    del games[chat_id]
    pending_mafia_hosts.pop(chat_id, None)
    await refund_all_players(game)
    await call.answer("Игра отменена.")
    await context.bot.send_message(chat_id, "❌ Игра отменена создателем. Ставки возвращены.")


# ============ CALLBACK: НОЧНЫЕ ДЕЙСТВИЯ ============

async def cb_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    call = update.callback_query
    _, chat_id, target_id = call.data.split(":")
    chat_id, target_id = int(chat_id), int(target_id)
    game = games.get(chat_id)
    if not game or game.state != "night":
        await call.answer("Действие недоступно.", show_alert=True)
        return
    if call.from_user.id in game.night_locked:
        await call.answer("Ты уже сделал свой выбор этой ночью — изменить нельзя.", show_alert=True)
        return
    target = game.players.get(target_id)
    if not target or not target.alive:
        await call.answer("Недоступно.", show_alert=True)
        return

    is_first_action = "mafia" not in game.night_role_announced
    game.night_actions["kill"] = target_id
    game.night_locked.add(call.from_user.id)
    await call.answer("Цель выбрана. Изменить выбор больше нельзя.")

    msg_id = game.night_msg.get(call.from_user.id)
    if msg_id:
        try:
            await context.bot.edit_message_text(
                f"Мафия проводит голосование за следующую жертву:\n\n"
                f"Ты выбрал: {mention(target.user_id, target.name)}",
                chat_id=call.from_user.id, message_id=msg_id,
                reply_markup=None, parse_mode="HTML",
            )
        except TelegramError:
            pass

    if is_first_action:
        game.night_role_announced.add("mafia")
        try:
            await context.bot.send_message(game.chat_id, "🤵🏻 Мафия начала охоту за очередной жертвой...")
        except Exception:
            pass
    await maybe_resolve_night(context.bot, game)


async def cb_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    call = update.callback_query
    _, chat_id, target_id = call.data.split(":")
    chat_id, target_id = int(chat_id), int(target_id)
    game = games.get(chat_id)
    if not game or game.state != "night":
        await call.answer("Действие недоступно.", show_alert=True)
        return
    if call.from_user.id in game.night_locked:
        await call.answer("Ты уже сделал свой выбор этой ночью — изменить нельзя.", show_alert=True)
        return
    target = game.players.get(target_id)
    if not target or not target.alive:
        await call.answer("Недоступно.", show_alert=True)
        return

    doctor = game.players.get(call.from_user.id)
    if target_id == call.from_user.id and doctor and doctor.self_heal_used:
        await call.answer("Ты уже лечил себя один раз за игру — больше нельзя.", show_alert=True)
        return

    is_first_action = "doctor" not in game.night_role_announced
    game.night_actions["save"] = target_id
    game.night_locked.add(call.from_user.id)
    if target_id == call.from_user.id and doctor:
        doctor.self_heal_used = True
    await call.answer("Выбор сохранён. Изменить его больше нельзя.")

    msg_id = game.night_msg.get(call.from_user.id)
    if msg_id:
        try:
            await context.bot.edit_message_text(
                f"Кого будем лечить?\n\nТы выбрал: {mention(target.user_id, target.name)}",
                chat_id=call.from_user.id, message_id=msg_id,
                reply_markup=None, parse_mode="HTML",
            )
        except TelegramError:
            pass

    if is_first_action:
        game.night_role_announced.add("doctor")
        try:
            await context.bot.send_message(game.chat_id, "👨🏼‍⚕️ Доктор вышел на ночное дежурство...")
        except Exception:
            pass
    await maybe_resolve_night(context.bot, game)


async def cb_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    call = update.callback_query
    _, chat_id, target_id = call.data.split(":")
    chat_id, target_id = int(chat_id), int(target_id)
    game = games.get(chat_id)
    if not game or game.state != "night":
        await call.answer("Действие недоступно.", show_alert=True)
        return
    if call.from_user.id in game.night_locked:
        await call.answer("Ты уже проверил игрока этой ночью — повторно нельзя.", show_alert=True)
        return
    if target_id == call.from_user.id:
        await call.answer("Нельзя проверять самого себя.", show_alert=True)
        return
    target = game.players.get(target_id)
    if not target:
        await call.answer("Недоступно.", show_alert=True)
        return

    is_first_action = "sheriff" not in game.night_role_announced
    game.night_actions["check"] = target_id
    game.night_locked.add(call.from_user.id)
    await call.answer("Выбор сохранён.")

    msg_id = game.night_msg.get(call.from_user.id)
    if msg_id:
        try:
            await context.bot.edit_message_text(
                f"Кого проверить?\n\nТы выбрал: {mention(target.user_id, target.name)}",
                chat_id=call.from_user.id, message_id=msg_id,
                reply_markup=None, parse_mode="HTML",
            )
        except TelegramError:
            pass

    if is_first_action:
        game.night_role_announced.add("sheriff")
        try:
            await context.bot.send_message(game.chat_id, "🕵 Шериф начал своё расследование...")
        except Exception:
            pass

    result = "МАФИЯ 🕵️‍♂️" if target.role == "mafia" else "не мафия"
    try:
        await context.bot.send_message(
            call.from_user.id,
            f"🔍 Результат проверки: {mention(target.user_id, target.name)} — <b>{result}</b>",
            parse_mode="HTML",
        )
    except TelegramError:
        pass
    await maybe_resolve_night(context.bot, game)


# ============ CALLBACK: ДНЕВНОЕ ГОЛОСОВАНИЕ ============

async def cb_nominate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    call = update.callback_query
    _, chat_id, target_id = call.data.split(":")
    chat_id, target_id = int(chat_id), int(target_id)
    game = games.get(chat_id)
    if not game or game.state != "voting" or game.day_phase != "nominating":
        await call.answer("Голосование сейчас недоступно.", show_alert=True)
        return

    voter = game.players.get(call.from_user.id)
    if not voter or not voter.alive:
        await call.answer("Голосовать могут только живые игроки.", show_alert=True)
        return
    target = game.players.get(target_id)
    if not target or not target.alive:
        await call.answer("Этот игрок уже выбыл.", show_alert=True)
        return

    if voter.user_id in game.day_votes:
        await call.answer("Ты уже проголосовал в этом голосовании.", show_alert=True)
        return

    msg_id = game.nomination_msg.get(voter.user_id)

    game.day_votes[voter.user_id] = target_id
    await call.answer("Голос учтён.")

    if msg_id:
        try:
            await context.bot.edit_message_text(
                "Пришло время искать виноватых!\nКого ты хочешь линчевать?\n\n"
                f"Ты выбрал: {mention(target.user_id, target.name)}",
                chat_id=voter.user_id, message_id=msg_id,
                reply_markup=None, parse_mode="HTML",
            )
        except TelegramError:
            pass

    await safe_send(
        context.bot,
        game.chat_id,
        f"{mention(voter.user_id, voter.name)} проголосовал за {mention(target.user_id, target.name)}",
        parse_mode="HTML",
    )
    alive_ids = {p.user_id for p in game.alive_players()}
    if alive_ids <= game.day_votes.keys():
        if game.voting_task:
            game.voting_task.cancel()
        await resolve_nomination_timeout(context.bot, game)


async def cb_confirm_like(update: Update, context: ContextTypes.DEFAULT_TYPE):
    call = update.callback_query
    chat_id = int(call.data.split(":")[1])
    game = games.get(chat_id)
    if not game or game.state != "voting" or game.day_phase != "confirming":
        await call.answer("Голосование сейчас недоступно.", show_alert=True)
        return

    voter = game.players.get(call.from_user.id)
    if not voter or not voter.alive:
        await call.answer("Голосовать могут только живые игроки.", show_alert=True)
        return
    if voter.user_id == game.vote_target:
        await call.answer("Обвиняемый не может голосовать в этом опросе.", show_alert=True)
        return
    if voter.user_id in game.confirm_likes or voter.user_id in game.confirm_dislikes:
        await call.answer("Ты уже проголосовал в этом голосовании.", show_alert=True)
        return

    game.confirm_likes.add(voter.user_id)
    game.confirm_dislikes.discard(voter.user_id)
    await call.answer("Голос учтён.")
    await update_confirm_message(context.bot, game)
    await maybe_resolve_confirmation(context.bot, game)


async def cb_confirm_dislike(update: Update, context: ContextTypes.DEFAULT_TYPE):
    call = update.callback_query
    chat_id = int(call.data.split(":")[1])
    game = games.get(chat_id)
    if not game or game.state != "voting" or game.day_phase != "confirming":
        await call.answer("Голосование сейчас недоступно.", show_alert=True)
        return

    voter = game.players.get(call.from_user.id)
    if not voter or not voter.alive:
        await call.answer("Голосовать могут только живые игроки.", show_alert=True)
        return
    if voter.user_id == game.vote_target:
        await call.answer("Обвиняемый не может голосовать в этом опросе.", show_alert=True)
        return
    if voter.user_id in game.confirm_likes or voter.user_id in game.confirm_dislikes:
        await call.answer("Ты уже проголосовал в этом голосовании.", show_alert=True)
        return

    game.confirm_dislikes.add(voter.user_id)
    game.confirm_likes.discard(voter.user_id)
    await call.answer("Голос учтён.")
    await update_confirm_message(context.bot, game)
    await maybe_resolve_confirmation(context.bot, game)


# ============ ФИЛЬТРАЦИЯ СООБЩЕНИЙ В ЧАТЕ ============

async def moderate_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game:
        return  # игры нет — не трогаем чат

    if message.text and message.text.startswith("/"):
        return

    if game.state == "registration":
        return  # во время регистрации можно писать свободно

    if game.state == "night":
        await safe_delete(context.bot, chat_id, message.message_id)
        return

    if game.state in ("day", "voting"):
        p = game.players.get(message.from_user.id)
        if not p or not p.alive:
            await safe_delete(context.bot, chat_id, message.message_id)


# ============ ЗАПУСК ============

async def on_startup(application: Application):
    global BOT_USERNAME
    me = await application.bot.get_me()
    BOT_USERNAME = me.username
    logging.info(f"Бот запущен как @{BOT_USERNAME}")


def main():
    # Увеличенные таймауты вместо значений по умолчанию (5 сек), чтобы обычные
    # заминки сети не превращались в TimedOut на каждый второй запрос.
    request = HTTPXRequest(
        connect_timeout=15.0,
        read_timeout=15.0,
        write_timeout=15.0,
        pool_timeout=15.0,
    )
    app = Application.builder().token(BOT_TOKEN).request(request).post_init(on_startup).build()

    app.add_handler(CommandHandler("mafia", cmd_mafia))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("endmafia", cmd_endmafia))

    app.add_handler(CallbackQueryHandler(cb_extend, pattern=r"^extend:"))
    app.add_handler(CallbackQueryHandler(cb_start_now, pattern=r"^startnow:"))
    app.add_handler(CallbackQueryHandler(cb_cancel, pattern=r"^cancel:"))
    app.add_handler(CallbackQueryHandler(cb_kill, pattern=r"^kill:"))
    app.add_handler(CallbackQueryHandler(cb_save, pattern=r"^save:"))
    app.add_handler(CallbackQueryHandler(cb_check, pattern=r"^check:"))
    app.add_handler(CallbackQueryHandler(cb_nominate, pattern=r"^nominate:"))
    app.add_handler(CallbackQueryHandler(cb_confirm_like, pattern=r"^clike:"))
    app.add_handler(CallbackQueryHandler(cb_confirm_dislike, pattern=r"^cdislike:"))

    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, handle_mafia_bet))

    print("🎭 Бот мафии запущен!")
    app.run_polling(bootstrap_retries=-1)


if __name__ == "__main__":
    main()
