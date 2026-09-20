import asyncio
import datetime
import random
import re
import html
import aiosqlite
import json
import traceback
import time
import uuid
import os

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
# --- Конфигурация ---
API_TOKEN = '8070912034:AAFKSa5KM8OkPuZaQLccdIkaiNwaUhdJ4_Q'
DB_PATH = os.environ.get('DB_PATH', 'bot_data.db') # Путь к файлу базы данных SQLite (можно переопределить переменной окружения DB_PATH)
ADMIN_IDS = [5152638249, 7895619658] # СПИСОК ID АДМИНИСТРАТОРОВ

# --- Инициализация бота и диспетчера ---
storage = MemoryStorage()
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher(storage=storage)

PENDING_DUELS: dict = {}
PENDING_RPS: dict = {}
DUEL_COMMISSION_RATE = 0.10



class TutorialStates(StatesGroup):
    step1 = State()
    step2 = State()
    step3 = State()
    step4 = State()
    step5 = State()
    step6 = State()
    step7 = State()
    step8 = State()


class ExchangeStates(StatesGroup):
    choosing_from = State()
    choosing_to = State()
    waiting_amount = State()


EXCHANGE_OPTION_MAP = {
    "normal": "balance_normal",
    "special": "balance_special",
    "galactic": "balance_galactic",
}

EXCHANGE_LABELS = {
    "balance_normal": "обычные",
    "balance_special": "особые",
    "balance_galactic": "галактические",
}


def get_exchange_rates(settings):
    return {
        ("balance_normal", "balance_special"): ("divide", 1_000_000),
        ("balance_special", "balance_normal"): ("multiply", 800_000),
        ("balance_halloween", "balance_normal"): ("multiply", 10_000),
        ("balance_special", "balance_galactic"): ("divide", settings.get('exchange_special_to_galactic_rate', 10)),
        ("balance_galactic", "balance_special"): ("multiply", settings.get('exchange_special_to_galactic_rate', 10)),
        ("balance_galactic", "balance_normal"): ("multiply", 800_000 * settings.get('exchange_special_to_galactic_rate', 10)),
        ("balance_normal", "balance_galactic"): ("divide", 1_000_000 * settings.get('exchange_special_to_galactic_rate', 10)),
    }


def exchange_start_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Обычные", callback_data=f"exchange_from_{user_id}_normal"),
            InlineKeyboardButton(text="💎 Особые", callback_data=f"exchange_from_{user_id}_special"),
            InlineKeyboardButton(text="🌌 Галактические", callback_data=f"exchange_from_{user_id}_galactic"),
        ]
    ])


def exchange_target_keyboard(from_currency: str, user_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for key, value in EXCHANGE_OPTION_MAP.items():
        if value == from_currency:
            continue
        buttons.append(InlineKeyboardButton(
            text=f"{EXCHANGE_LABELS[value]}",
            callback_data=f"exchange_to_{user_id}_{key}"
        ))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def tutorial_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])


def tutorial_step_text(step: int, text: str) -> str:
    return f"🎓 Шаг {step}/6\n\n{text}"


DEFAULT_SETTINGS = {


    
    '_id': 'bot_settings',
    'transfer_limits': {'standart': 500000, 'assassin': 1000000, 'vip': 300000, 'pro': 5000000, 'max': 10000000},
    'donat_prices': { 'vip': 100, 'pro': 300, 'max': 500 },
    'donat_coin_rate_rub': 2, 'donat_coin_to_normal_money': 5000,
    'donat_special_payouts_enabled': False,
    'bank_max_balance': 10000000, # Максимальный баланс в банке
    'crypto_market': {
        'INCCoin': {'symbol': 'INCCoin', 'price': 100000, 'base_price': 100000, 'change_percent': 0.0, 'hour_change_percent': 0.0, 'hour_start_price': 100000, 'last_hour_reset': datetime.datetime.now().isoformat(), 'min_price': 50000},
        'TOMCoin': {'symbol': 'TOMCoin', 'price': 10000, 'base_price': 10000, 'change_percent': 0.0, 'hour_change_percent': 0.0, 'hour_start_price': 10000, 'last_hour_reset': datetime.datetime.now().isoformat(), 'min_price': 2000}
    },
    'promo_codes': {
        'INC': {'type': 'normal_money', 'amount': 50000, 'activations_left': -1}
        
    },
    'referral_rewards': {
        'base_normal': 100000,
        'per_invite_bonus': 10000,
        'pass_exp': 1500,
        'new_user_bonus': 50000,
        'milestone_rewards': {
            5: {'type': 'normal_money', 'amount': 250000},
            10: {'type': 'special_money', 'amount': 1},
            25: {'type': 'galactic_money', 'amount': 1}
        }
    },
    'event_active': False, 'monster_battle_hp': 10000, 'monster_current_hp': 10000,
    'monster_damage_log': {}, 'event_start_time': None, 'event_reward_pool': 10000000, # Добавляем призовой фонд
    'exchange_special_to_galactic_rate': 10,
    'special_coins_on_max_purchase': 100, # Количество особых монет при покупке MAX
    'ore_types': { # Типы руды и их стоимость
        'Камень': {'min_amount': 1, 'max_amount': 5, 'value': 150, 'chance': 0.50},
        'Железо': {'min_amount': 1, 'max_amount': 3, 'value': 1000, 'chance': 0.35},
        'Золото': {'min_amount': 1, 'max_amount': 2, 'value': 2500, 'chance': 0.10},
        'Алмаз': {'min_amount': 1, 'max_amount': 1, 'value': 7000, 'chance': 0.04},
        'Кристалл': {'min_amount': 1, 'max_amount': 1, 'value': 15000, 'chance': 0.01}
    },

    

    'hunting_levels': {  
        1: {"range": (100, 1000),   "cost": 0},
        2: {"range": (500, 1500),   "cost": 100000},
        3: {"range": (1000, 5000),  "cost": 700000},
        4: {"range": (5000, 25000), "cost": 5000000},
        5: {"range": (15000, 75000), "cost": 15000000},
        6: {"range": (20000, 100000),"cost": 50000000},
        7: {"range": (50000, 150000),"cost": 200000000},
        8: {"range": (200000, 1000000),"cost": 650000000},
        9: {"range": (20000000, 1000000000),"cost": 65000000000},
        10: {"range": (100000000, 5000000000),"cost": 500000000000},
    },
    
    'hunting_limits': { 
        'standart': 10,
        'assassin': 10,
        'vip': 10,
        'pro': 10,
        'max': 10
    },
    'hunting_cooldown_minutes': 40,  # интервал сброса лимита охот


    
    'mining_limits': { # Лимиты вскапываний за интервал по донат-статусам
        'standart': 20,
        'assassin': 20,
        'vip': 20,
        'pro': 20,
        'max': 20
    },
    'mining_cooldown_minutes': 10, # Интервал сброса лимита вскапываний в минутах
    'fish_types': { # Типы рыбы и их стоимость
        'Обычная рыба': {'min_money': 100, 'max_money': 500, 'base_chance': 0.70, 'value': 1},
        'Редкая рыба': {'min_money': 500, 'max_money': 5000, 'base_chance': 0.20, 'value': 5},
        'Легендарная рыба': {'min_money': 5000, 'max_money': 15000, 'base_chance': 0.045, 'value': 20},
        'Мифическая рыба': {'min_money': 100000, 'max_money': 250000, 'base_chance': 0.01, 'value': 100}
    },
    'fishing_limits': { # Лимиты рыбалок за интервал по донат-статусам
        'standart': 15,
        'assassin': 15,
        'vip': 15,
        'pro': 15,
        'max': 15
    },
    'fishing_cooldown_minutes': 20, # Интервал сброса лимита рыбалок в минутах
    
    # --- INC PASS СИСТЕМА ---
    'pass_exp_requirements': { # Лимит очков для каждого уровня
        1: 1000, 2: 1000, 3: 1000, 4: 1000, 5: 1000,
        6: 2000, 7: 2000, 8: 2000, 9: 2000, 10: 2000,
        11: 2000, 12: 2000, 13: 2000, 14: 2000, 15: 2000,
        16: 5000, 17: 5000, 18: 5000, 19: 5000, 20: 5000,
        21: 7000, 22: 7000, 23: 7000, 24: 7000, 25: 7000,
        26: 10000, 27: 10000, 28: 10000, 29: 10000, 30: 10000,
        31: 15000, 32: 15000, 33: 15000, 34: 15000, 35: 15000,
        36: 20000, 37: 20000, 38: 20000, 39: 20000, 40: 20000,
        41: 25000, 42: 25000, 43: 25000, 44: 25000, 45: 25000,
        46: 40000, 47: 40000, 48: 40000, 49: 50000, 50: 100000
    },
    'pass_rewards': { # Награды за уровни
        1: {'type': 'normal_money', 'amount': 5000},
        2: {'type': 'normal_money', 'amount': 5000},
        3: {'type': 'normal_money', 'amount': 5000},
        4: {'type': 'normal_money', 'amount': 10000},
        5: {'type': 'normal_money', 'amount': 10000},
        6: {'type': 'normal_money', 'amount': 10000},
        7: {'type': 'normal_money', 'amount': 15000},
        8: {'type': 'normal_money', 'amount': 15000},
        9: {'type': 'normal_money', 'amount': 50000},
        10: {'type': 'case', 'case_name': 'money'},  # денежный кейс
        11: {'type': 'normal_money', 'amount': 10000},
        12: {'type': 'normal_money', 'amount': 10000},
        13: {'type': 'normal_money', 'amount': 15000},
        14: {'type': 'normal_money', 'amount': 50000},
        15: {'type': 'normal_money', 'amount': 50000},  # 5 особых монет
        16: {'type': 'normal_money', 'amount': 50000},
        17: {'type': 'normal_money', 'amount': 50000},
        18: {'type': 'normal_money', 'amount': 50000},
        19: {'type': 'normal_money', 'amount': 50000},
        20: {'type': 'normal_money', 'amount': 50000},
        21: {'type': 'normal_money', 'amount': 50000},
        22: {'type': 'normal_money', 'amount': 50000},
        23: {'type': 'normal_money', 'amount': 50000},
        24: {'type': 'normal_money', 'amount': 50000},
        25: {'type': 'galactic_money', 'amount': 1},  # 1 галактическая монета
        26: {'type': 'normal_money', 'amount': 150000},
        27: {'type': 'normal_money', 'amount': 150000},
        28: {'type': 'normal_money', 'amount': 150000},
        29: {'type': 'normal_money', 'amount': 150000},
        30: {'type': 'normal_money', 'amount': 150000},
        31: {'type': 'normal_money', 'amount': 150000},
        32: {'type': 'normal_money', 'amount': 150000},
        33: {'type': 'normal_money', 'amount': 150000},
        34: {'type': 'normal_money', 'amount': 150000},
        35: {'type': 'normal_money', 'amount': 500000},
        36: {'type': 'normal_money', 'amount': 500000},
        37: {'type': 'normal_money', 'amount': 500000},
        38: {'type': 'normal_money', 'amount': 500000},
        39: {'type': 'normal_money', 'amount': 500000},
        40: {'type': 'normal_money', 'amount': 1000000},  
        41: {'type': 'normal_money', 'amount': 1000000},
        42: {'type': 'normal_money', 'amount': 1000000},
        43: {'type': 'normal_money', 'amount': 1000000},
        44: {'type': 'normal_money', 'amount': 1000000},
        45: {'type': 'normal_money', 'amount': 1500000},
        46: {'type': 'normal_money', 'amount': 1500000},
        47: {'type': 'normal_money', 'amount': 1500000},
        48: {'type': 'normal_money', 'amount': 1500000},
        49: {'type': 'normal_money', 'amount': 1500000},
        50: {'type': 'case', 'case_name': 'mythical'}  
    },
    'pass_activity': { # Очки за действия
        'fishing': (20, 50),  # мин-макс очков за рыбалку
        'mining': (10, 15),   # за шахту
        'hunting': (50, 100), # за охоту
        'daily_login': 500,  # за ежедневный вход
        'open_case': 300 
    }
}

# --- Вспомогательные функции ---



    
async def parse_command_args(message: Message, command_args: str | None) -> tuple[int | None, list[str]]:
    """
    Парсит ID цели (если есть) и остальные аргументы.
    Приоритет: ID из аргументов, затем ID из ответа на сообщение.
    """
    target_id = None
    args_list = []

    if command_args:
        parts = command_args.split(maxsplit=1)
        try:
            potential_id = int(parts[0])
            target_id = potential_id
            if len(parts) > 1:
                args_list = parts[1].split()
        except ValueError:
            # Если первый аргумент не число, то это не ID, а часть команды.
            # Все command_args - это просто список аргументов.
            args_list = command_args.split()
            # ID все еще может быть в ответе на сообщение
    
    # Если ID не был найден в аргументах, но есть ответ на сообщение
    if target_id is None and message.reply_to_message:
        target_id = message.reply_to_message.from_user.id

    return target_id, args_list

# --- Вспомогательные функции для работы с БД ---



async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                _id INTEGER PRIMARY KEY,
                balance_normal INTEGER DEFAULT 100,
                balance_special INTEGER DEFAULT 0,
                balance_galactic INTEGER DEFAULT 0,
                balance_halloween INTEGER DEFAULT 0,
                balance_bank INTEGER DEFAULT 0,
                balance_inccoin INTEGER DEFAULT 0,
                balance_tomcoin INTEGER DEFAULT 0,
                mining_pickaxe_level INTEGER DEFAULT 1,
                fishing_rod_level INTEGER DEFAULT 1,
                theft_skill_level INTEGER DEFAULT 1,
                theft_protection_level INTEGER DEFAULT 1,
                theft_last_use TEXT,
                daily_login_streak INTEGER DEFAULT 0,
                last_login_date TEXT,
                invites_count INTEGER DEFAULT 0,
                donat_status TEXT DEFAULT 'standart',
                last_special_coin_payout TEXT,
                restaurants TEXT DEFAULT '{}',
                mining_luck_bonus INTEGER DEFAULT 0,
                fishing_luck_bonus INTEGER DEFAULT 0,
                transfer_limit_used INTEGER DEFAULT 0,
                last_transfer_reset TEXT,
                referred_by INTEGER,
                active_event_damage INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                activated_promos TEXT DEFAULT '[]',
                last_bank_payout TEXT,
                last_treasury_rob_pro TEXT,
                last_treasury_rob_max TEXT,
                restaurants_max_count TEXT DEFAULT '{"марс": 2, "юпитер": 2, "уран": 2}',
                mining_daily_count INTEGER DEFAULT 0,
                last_mine_reset TEXT,
                fishing_daily_count INTEGER DEFAULT 0,
                last_fish_reset TEXT,
                luck_potion_end_time TEXT,
                last_restaurant_payout TEXT,
                pass_level INTEGER DEFAULT 1,
                pass_experience INTEGER DEFAULT 0,
                pass_claimed_levels TEXT DEFAULT '[]',
                has_inc_pass_plus INTEGER DEFAULT 0,
                tutorial_completed INTEGER DEFAULT 0,
                referral_plus_awarded INTEGER DEFAULT 0,
                referral_plus_rewards_claimed INTEGER DEFAULT 0
            )
        ''')
        await db.commit()


        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_effects (
                user_id INTEGER PRIMARY KEY,
                effect_type TEXT,
                end_time TEXT
            )
        ''')
        await db.commit()

        # ---- START MIGRATION: добавляем колонки, которых не было в старой схеме ----
        cursor = await db.execute("PRAGMA table_info(users)")
        rows = await cursor.fetchall()
        existing_cols = [r[1] for r in rows]  # r[1] = name

        # Список колонок, которые мы хотим гарантированно иметь
        needed_columns = {
            'hunting_level': "INTEGER DEFAULT 1",
            'hunting_daily_count': "INTEGER DEFAULT 0",
            'last_hunt_reset': "TEXT",
            'last_pumpkin_hunt': "TEXT",
            'pass_level': "INTEGER DEFAULT 1",
            'pass_experience': "INTEGER DEFAULT 0",
            'pass_claimed_levels': "TEXT DEFAULT '[]'",
            'has_inc_pass_plus': "INTEGER DEFAULT 0",
            'last_herb_search': "TEXT",
            'last_crypto_mining': "TEXT",
            'pro_subscription_until': "TEXT",
            'tutorial_completed': "INTEGER DEFAULT 0",
            'titles': "TEXT DEFAULT '[]'",
            'active_title': "TEXT",
            'last_title_special_payout': "TEXT",
            'last_bday_galactic_payout': "TEXT",
            'balance_inccoin': "INTEGER DEFAULT 0",
            'balance_tomcoin': "INTEGER DEFAULT 0",
            'referral_plus_awarded': "INTEGER DEFAULT 0",
            'referral_plus_rewards_claimed': "INTEGER DEFAULT 0"
        }

        for col_name, col_def in needed_columns.items():
            if col_name not in existing_cols:
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                    print(f"Миграция: добавлена колонка users.{col_name}")
                except Exception as e:
                    print(f"Ошибка при добавлении колонки {col_name}: {e}")
        await db.commit()
        # ---- END MIGRATION ----




        # Создание таблицы global_data и прочего (ваш существующий код)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS global_data (
                _id TEXT PRIMARY KEY,
                settings TEXT
            )
        ''')
        await db.commit()


async def get_user_data(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT * FROM users WHERE _id = ?', (user_id,))
        user = await cursor.fetchone()

        
        default_user_structure = {
             '_id': user_id, 'balance_normal': 100, 'balance_special': 0, 'balance_galactic': 0, 'balance_bank': 0, 'balance_halloween': 0,
            'balance_inccoin': 0, 'balance_tomcoin': 0,
            'mining_pickaxe_level': 1, 'fishing_rod_level': 1,
            'theft_skill_level': 1, 'theft_protection_level': 1, 'theft_last_use': None,
            'daily_login_streak': 0, 'last_login_date': None, 'invites_count': 0,
            'donat_status': 'standart', 'last_special_coin_payout': None, 'restaurants': {},
            'mining_luck_bonus': False, 'fishing_luck_bonus': False, 'transfer_limit_used': 0,
            'last_transfer_reset': datetime.datetime.now(), 'referred_by': None,
            'active_event_damage': 0, 'is_admin': (user_id in ADMIN_IDS), 'activated_promos': [], 'last_bank_payout': None,
            'last_treasury_rob_pro': None, 'last_treasury_rob_max': None,
            'restaurants_max_count': {'марс': 2, 'юпитер': 2, 'уран': 2},
            'mining_daily_count': 0,
            'last_mine_reset': None,
            'fishing_daily_count': 0,
            'last_bday_galactic_payout': None,
            'last_fish_reset': None,
            'luck_potion_end_time': None,
            'last_restaurant_payout': None,
            'hunting_level': 1,
            'hunting_daily_count': 0,
            'last_hunt_reset': None,
            'pass_level': 1,
            'pass_experience': 0,
            'pass_claimed_levels': [],
            'has_inc_pass_plus': 0,
            'last_herb_search': None,
            'tutorial_completed': 0,
            'referral_plus_awarded': 0,
            'referral_plus_rewards_claimed': 0,
            'titles': [],
            'active_title': None,
            'last_title_special_payout': None
            
            
        }

        if not user:
            # Insert new user with default values
            columns = ', '.join(default_user_structure.keys())
            placeholders = ', '.join(['?' for _ in default_user_structure.keys()])
            values = []
            for k, v in default_user_structure.items():
                if isinstance(v, datetime.datetime):
                    values.append(v.isoformat())
                elif isinstance(v, (dict, list)):
                    values.append(json.dumps(v))
                else:
                    values.append(v)

            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_cases (
                    user_id INTEGER,
                    case_name TEXT,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, case_name)
                )
            ''')
            await db.commit()
            
            await db.execute(f'INSERT INTO users ({columns}) VALUES ({placeholders})', tuple(values))
            await db.commit()
            return default_user_structure
        else:
            # Convert row to dictionary and update if necessary
            user_dict = {}
            for i, col in enumerate(cursor.description):
                key = col[0]
                value = user[i]
                if key in ['theft_last_use', 'last_login_date', 'last_transfer_reset', 'last_special_coin_payout',
                                           'last_bank_payout', 'last_treasury_rob_pro', 'last_treasury_rob_max',
                                           'last_mine_reset', 'last_fish_reset', 'last_hunt_reset', 'last_herb_search', 'luck_potion_end_time', 'last_bday_galactic_payout', 'last_restaurant_payout', 
 'pro_subscription_until', 'last_title_special_payout'] and value is not None:
                    try:
                        user_dict[key] = datetime.datetime.fromisoformat(value)
                    except ValueError:
                        user_dict[key] = None # Handle invalid date strings
                elif key in ['restaurants', 'restaurants_max_count', 'activated_promos', 'pass_claimed_levels', 'titles']:
                    if key == 'pass_claimed_levels' or key == 'titles':
                        user_dict[key] = json.loads(value) if value else []
                    else:
                        user_dict[key] = json.loads(value) if value else {} if key.startswith('restaurants') else []
                else:
                    user_dict[key] = value
            
            updated = False
            user_dict['is_admin'] = (user_id in ADMIN_IDS) # Always update admin status
            for key, value in default_user_structure.items():
                if key not in user_dict:
                    user_dict[key] = value
                    updated = True
                elif isinstance(value, dict) and isinstance(user_dict.get(key), dict):
                    # Merge dictionaries for settings like restaurants_max_count
                    for sub_key, sub_value in value.items():
                        if sub_key not in user_dict[key]:
                            user_dict[key][sub_key] = sub_value
                            updated = True
                elif isinstance(value, list) and isinstance(user_dict.get(key), list):
                    # For lists like activated_promos, ensure it's a list
                    if not isinstance(user_dict[key], list):
                        user_dict[key] = value
                        updated = True

            if updated:
                await update_user_data(user_id, user_dict)
            return user_dict

async def update_user_data(user_id: int, data: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        # Prepare data for SQLite
        update_data = {}
        for k, v in data.items():
            if isinstance(v, datetime.datetime):
                update_data[k] = v.isoformat()
            elif isinstance(v, (dict, list)):
                update_data[k] = json.dumps(v)
            else:
                update_data[k] = v
        
        set_clause = ', '.join([f'{k} = ?' for k in update_data.keys()])
        values = list(update_data.values())
        values.append(user_id) # For WHERE clause

        await db.execute(f'UPDATE users SET {set_clause} WHERE _id = ?', tuple(values))
        await db.commit()

async def update_quest_progress(user_id: int, quest_key: str, amount: int):
    """Обновление прогресса задания. Если система заданий не реализована, заглушка ничего не делает."""
    # Если потребуется, можно добавить сохранение прогресса в пользователя здесь.
    return

async def set_user_effect(user_id: int, effect_type: str, duration_minutes: int):
    """Накладывает эффект на игрока на заданное время."""
    end_time = (datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO user_effects (user_id, effect_type, end_time)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
            effect_type = excluded.effect_type,
            end_time = excluded.end_time
        ''', (user_id, effect_type, end_time))
        await db.commit()

async def get_user_effect(user_id: int):
    """Возвращает текущий активный эффект игрока, если есть."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT effect_type, end_time FROM user_effects WHERE user_id = ?', (user_id,))
        row = await cursor.fetchone()

    if not row:
        return None

    effect_type, end_time_str = row
    try:
        end_time = datetime.datetime.fromisoformat(end_time_str)
    except Exception:
        return None

    # Проверяем, не истёк ли эффект
    if datetime.datetime.now() >= end_time:
        await clear_user_effect(user_id)
        return None

    return {"type": effect_type, "end_time": end_time}

async def clear_user_effect(user_id: int):
    """Удаляет активный эффект (например, после истечения времени)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM user_effects WHERE user_id = ?', (user_id,))
        await db.commit()


async def process_referral_plus(user_id: int):
    """Засчитывает реферал+ после первого завершения обучения."""
    user = await get_user_data(user_id)
    referrer_id = user.get('referred_by')
    if not referrer_id or user.get('referral_plus_awarded'):
        return

    user['referral_plus_awarded'] = 1
    await update_user_data(user_id, user)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'SELECT COUNT(*) FROM users WHERE referred_by = ? AND tutorial_completed = 1',
            (referrer_id,)
        )
        referral_plus_count = (await cursor.fetchone())[0]

    referrer = await get_user_data(referrer_id)
    rewards_claimed = int(referrer.get('referral_plus_rewards_claimed', 0) or 0)
    available_rewards = referral_plus_count // 5
    if available_rewards <= rewards_claimed:
        try:
            await bot.send_message(
                referrer_id,
                f"🎉 У вас появился новый реферал+!\n"
                f"Теперь рефералов+: <b>{referral_plus_count}</b>\n"
                f"До мифического кейса осталось: <b>{5 - (referral_plus_count % 5)}</b>.",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Referral+ notification error {referrer_id}: {e}")
        return

    rewards_to_grant = available_rewards - rewards_claimed
    await add_case_to_user(referrer_id, 'mythical', rewards_to_grant)
    referrer['referral_plus_rewards_claimed'] = available_rewards
    await update_user_data(referrer_id, referrer)

    try:
        await bot.send_message(
            referrer_id,
            f"🎉 У вас {referral_plus_count} рефералов+!\n"
            f"🎁 Вы получили мифический кейс x{rewards_to_grant}.",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Referral+ notification error {referrer_id}: {e}")


async def reconcile_referral_plus():
    """Досчитывает рефералов+, завершивших обучение до обновления бота."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'SELECT _id FROM users WHERE referred_by IS NOT NULL '
            'AND tutorial_completed = 1 AND referral_plus_awarded = 0'
        )
        user_ids = [row[0] for row in await cursor.fetchall()]

    for user_id in user_ids:
        await process_referral_plus(user_id)

async def get_global_settings():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT settings FROM global_data WHERE _id = ?', ('bot_settings',))
        settings_row = await cursor.fetchone()
        
        default_settings = DEFAULT_SETTINGS.copy()

        if not settings_row:
            # Insert new settings with default values
            await db.execute('INSERT INTO global_data (_id, settings) VALUES (?, ?)',
                            ('bot_settings', json.dumps(default_settings, default=str)))
            await db.commit()
            return default_settings
        else:
            settings = json.loads(settings_row[0])
            
            # Convert datetime strings back to datetime objects
            if 'event_start_time' in settings and settings['event_start_time'] is not None:
                try:
                    settings['event_start_time'] = datetime.datetime.fromisoformat(settings['event_start_time'])
                except ValueError:
                    settings['event_start_time'] = None

            # Обновляем только те поля, которые должны быть актуальными из default_settings
            settings['transfer_limits'] = default_settings['transfer_limits']
            settings['mining_limits'] = default_settings['mining_limits']
            settings['fishing_limits'] = default_settings['fishing_limits']
            
            updated = False
            for key, value in default_settings.items():
                if key not in settings:
                    settings[key] = value
                    updated = True
                elif isinstance(value, dict) and isinstance(settings.get(key), dict):
                    if key == 'promo_codes': # Специальная обработка для промокодов
                        for promo_name, promo_details in value.items():
                            if promo_name not in settings[key]:
                                settings[key][promo_name] = promo_details
                                updated = True
                            else: # Убедимся, что у существующих промокодов есть 'activations_left' и другие поля
                                for detail_key, detail_value in promo_details.items():
                                    if detail_key not in settings[key][promo_name]:
                                        settings[key][promo_name][detail_key] = detail_value
                                        updated = True
                    else: # Общая логика для других словарей
                        for sub_key, sub_value in value.items():
                            if sub_key not in settings[key]:
                                settings[key][sub_key] = sub_value
                                updated = True
                            elif isinstance(sub_value, dict) and isinstance(settings[key].get(sub_key), dict):
                                # Рекурсивно обновляем вложенные словари
                                for inner_key, inner_value in sub_value.items():
                                    if inner_key not in settings[key][sub_key]:
                                        settings[key][sub_key][inner_key] = inner_value
                                        updated = True
            if updated:
                await update_global_settings(settings)
            return settings

async def update_global_settings(data: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        # Convert datetime objects to string for storage
        data_to_store = data.copy()
        if 'event_start_time' in data_to_store and isinstance(data_to_store['event_start_time'], datetime.datetime):
            data_to_store['event_start_time'] = data_to_store['event_start_time'].isoformat()
        
        await db.execute('REPLACE INTO global_data (_id, settings) VALUES (?, ?)',
                         ('bot_settings', json.dumps(data_to_store, default=str)))
        await db.commit()

async def update_settings_on_startup():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT settings FROM global_data WHERE _id = ?', ('bot_settings',))
        settings_row = await cursor.fetchone()

    if not settings_row:
        await get_global_settings()
        return

    db_settings = json.loads(settings_row[0])
    promo_codes_from_db = db_settings.get('promo_codes', {})
    crypto_market_from_db = db_settings.get('crypto_market', {})
    donat_special_payouts_enabled = db_settings.get('donat_special_payouts_enabled', False)

    default_settings = DEFAULT_SETTINGS.copy()

    new_settings = default_settings.copy()
    new_settings['promo_codes'] = promo_codes_from_db
    new_settings['donat_special_payouts_enabled'] = donat_special_payouts_enabled
    if crypto_market_from_db:
        new_settings['crypto_market'] = crypto_market_from_db

    await update_global_settings(new_settings)
    print("Глобальные настройки обновлены, промокоды и крипто-рынок сохранены.")


def normalize_crypto_name(value: str) -> str:
    value = (value or '').strip().lower()
    aliases = {
        'inccoin': 'INCCoin',
        'inc': 'INCCoin',
        'inc_coin': 'INCCoin',
        'tomcoin': 'TOMCoin',
        'tom': 'TOMCoin',
        'tom_coin': 'TOMCoin',
    }
    return aliases.get(value, value.title())


async def update_crypto_market_random():
    settings = await get_global_settings()
    market = settings.get('crypto_market', {})
    if not market:
        return

    now = datetime.datetime.now()
    for coin_name, coin_data in market.items():
        if not isinstance(coin_data, dict):
            continue

        current_price = float(coin_data.get('price', coin_data.get('base_price', 0)))
        last_reset_str = coin_data.get('last_hour_reset')
        last_reset = None
        if last_reset_str:
            try:
                last_reset = datetime.datetime.fromisoformat(last_reset_str)
            except ValueError:
                last_reset = None

        if last_reset is None or now - last_reset >= datetime.timedelta(hours=1):
            coin_data['hour_start_price'] = current_price
            coin_data['last_hour_reset'] = now.isoformat()

        base_price = float(coin_data.get('hour_start_price', current_price))
        if base_price <= 0:
            base_price = current_price

        min_price = float(coin_data.get('min_price', current_price * 0.5))
        change = random.uniform(-1.5, 1.5)
        new_price = current_price * (1 + change / 100)
        new_price = max(min_price, new_price)
        coin_data['price'] = int(round(new_price))
        coin_data['change_percent'] = round(change, 2)
        coin_data['hour_change_percent'] = round(((new_price - base_price) / base_price) * 100, 2) if base_price else 0.0

    await update_global_settings(settings)


async def periodic_crypto_market():
    while True:
        await asyncio.sleep(60)
        await update_crypto_market_random()


# --- ФУНКЦИИ ДЛЯ СИСТЕМЫ ТИТУЛОВ ---
async def add_title_to_user(user_id: int, title_name: str):
    """Добавляет титул пользователю если его еще нет"""
    user = await get_user_data(user_id)
    titles = user.get('titles', [])
    if not isinstance(titles, list):
        titles = []
    if title_name not in titles:
        titles.append(title_name)
        user['titles'] = titles
        await update_user_data(user_id, user)
        return True
    return False

async def ensure_pass_completion_title(user_id: int) -> bool:
    """Выдаёт титул за полное прохождение пасса, если его ещё нет."""
    user = await get_user_data(user_id)
    if user.get('pass_level', 1) < 50:
        return False

    title_name = 'b-day ultimate' if bool(user.get('has_inc_pass_plus', 0)) else 'b-day'
    return await add_title_to_user(user_id, title_name)


def get_active_title_bonuses(user: dict) -> dict:
    title_bonuses = {
        'God of Grass': {'work_multiplier': 0.10, 'special_daily': 1},
        'God of Grass Ultimate': {'work_multiplier': 0.15, 'special_daily': 3},
        'Crypto': {'casino_win_bonus': 0.05, 'case_daily': 1},
        'Crypto Ultimate': {'casino_win_bonus': 0.08, 'case_daily': 2},
        'b-day': {'steal_bonus': 0.05, 'galactic_payout': 1},
        'b-day ultimate': {'steal_bonus': 0.10, 'galactic_payout': 3},
    }
    return title_bonuses.get(user.get('active_title'), {})

async def set_active_title(user_id: int, title_name: str):
    """Устанавливает активный титул пользователю"""
    user = await get_user_data(user_id)
    titles = user.get('titles', [])
    if title_name in titles or title_name is None:
        await update_user_data(user_id, {'active_title': title_name})
        return True
    return False

async def remove_title_from_user(user_id: int, title_name: str):
    """Удаляет титул пользователя"""
    user = await get_user_data(user_id)
    titles = user.get('titles', [])
    if title_name in titles:
        titles.remove(title_name)
        # Если активный титул был удален, то убираем активность
        if user.get('active_title') == title_name:
            await update_user_data(user_id, {'titles': titles, 'active_title': None})
        else:
            await update_user_data(user_id, {'titles': titles})
        return True
    return False


def register_tutorial_handlers(
    dp,
    bot,
    db_path,
    get_user_data,
    update_user_data,
    get_global_settings,
    add_pass_exp,
    add_case_to_user
):

    async def _finish_training(user_id: int):
        await update_user_data(user_id, {'tutorial_completed': 1})
        await process_referral_plus(user_id)

    def _build_final_keyboard(bot_username: str, user_id: int) -> InlineKeyboardMarkup:
        referral_link = f"https://t.me/{bot_username}?start={user_id}"
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="общие команды", callback_data="main_menu")],
            [InlineKeyboardButton(text="Чат", url="https://t.me/IncBotChat")],
            [InlineKeyboardButton(text="Канал", url="https://t.me/IncBotChannel")],
        ])

    async def _show_step(message: Message, step: int, text: str):
        await message.answer(tutorial_step_text(step, text), parse_mode="HTML", reply_markup=tutorial_button())

    async def _show_step_callback(call: CallbackQuery, step: int, text: str):
        await call.message.edit_text(tutorial_step_text(step, text), parse_mode="HTML", reply_markup=tutorial_button())
        await call.answer()

    @dp.callback_query(F.data == "start_tutorial")
    async def callback_start_tutorial(call: CallbackQuery, state: FSMContext):
        user = await get_user_data(call.from_user.id)
        current_state = await state.get_state()
        tutorial_states = {
            TutorialStates.step1.state,
            TutorialStates.step2.state,
            TutorialStates.step3.state,
            TutorialStates.step4.state,
            TutorialStates.step5.state,
            TutorialStates.step6.state,
            TutorialStates.step7.state,
            TutorialStates.step8.state,
        }

        if user.get('tutorial_completed'):
            await call.answer("Вы уже прошли обучение.", show_alert=True)
            return

        if current_state in tutorial_states:
            await call.answer("Продолжайте текущее обучение.", show_alert=True)
            return

        await state.set_state(TutorialStates.step1)
        await _show_step_callback(call, 1, "Добро пожаловать в обучение!\n\nСейчас я пошагово объясню, как играть и зарабатывать 💰\nВсего будет 8 шагов — и ты разберёшься во всём, а в конце получишь стартовый набор!\n\n👉 Выполняй задания, чтобы двигаться дальше\n\n⛏ Начнём с добычи\n\nТвоя первая задача — отправиться в шахту и заработать свои первые деньги\n\nИспользуй команду:\n👉 <b>шахта</b>")

    @dp.callback_query(F.data == "main_menu", F.state == TutorialStates)
    async def tutorial_cancel(call: CallbackQuery, state: FSMContext):
        await state.clear()
        await call.answer("Обучение прервано. Возвращаю тебя в главное меню.")

    @dp.message(TutorialStates.step1, F.text.lower().in_(('шахта', 'добыть руду', 'добывать руду')))
    async def tutorial_step1(message: Message, state: FSMContext):
        user = await get_user_data(message.from_user.id)
        user['balance_normal'] = user.get('balance_normal', 0) + 10_000
        await update_user_data(message.from_user.id, user)

        await message.answer("Вы добыли 4 ед. Железо и получили 5,000 обычных монет.\n⭐ Inc Pass: +15 очков\nОсталось вскапываний: 19.")
        await state.set_state(TutorialStates.step2)
        await _show_step(message, 2, "⛏ Отлично, ты справился!\n\nТеперь пора увеличить доход 💰\n\n🔧 Ты можешь улучшать инструменты, чтобы зарабатывать больше\n\nПопробуй улучшить кирку — так ты будешь получать больше денег за шахту\n\nИспользуй команду:\n👉 <b>улучшить кирку</b>")

    @dp.message(TutorialStates.step2, F.text.lower() == "улучшить кирку")
    async def tutorial_step2(message: Message, state: FSMContext):
        user = await get_user_data(message.from_user.id)
        current_level = user.get('mining_pickaxe_level', 1)
        if current_level >= 17:
            await message.answer("Кирка уже на максимуме. Продолжаем дальше.")
        else:
            required = 100_000
            if user.get('balance_normal', 0) < required:
                user['balance_normal'] = required
            user['balance_normal'] -= required
            user['mining_pickaxe_level'] = current_level + 1
            await update_user_data(message.from_user.id, user)
            await add_pass_exp(message.from_user.id, 300)
            await message.answer(f"⛏️ Кирка улучшена до <b>{user['mining_pickaxe_level']}</b> за <b>5,000</b> монет! Следующее улучшение будет стоить 100,000 монет\n+<b>300</b> очков Inc Pass")

        await state.set_state(TutorialStates.step3)
        await _show_step(message, 3, "⛏ Отличная работа!\n\nТеперь твоя кирка улучшена, и ты будешь получать больше денег за добычу 💰\n\nДавай проверим это на практике 👇\n\nСнова отправляйся в шахту и посмотри, сколько теперь заработаешь\n\nИспользуй команду:\n👉 <b>шахта</b>")

    @dp.message(TutorialStates.step3, F.text.lower().in_(('шахта', 'добыть руду', 'добывать руду')))
    async def tutorial_step3(message: Message, state: FSMContext):
        user = await get_user_data(message.from_user.id)
        user['balance_normal'] = user.get('balance_normal', 0) + 10_000
        await update_user_data(message.from_user.id, user)
        await add_pass_exp(message.from_user.id, 100)

        await message.answer("Вы добыли 8 ед. Железо и получили 10,000 обычных монет.\n⭐ Inc Pass: +15 очков\nОсталось вскапываний: 18.")
        await state.set_state(TutorialStates.step4)
        await _show_step(message, 4, "💰 Отлично, ты заработал свои первые деньги!\n\nТеперь давай посмотрим, сколько у тебя на балансе 👇\n\nИспользуй команду:\n👉 <b>баланс</b>\n\nТак ты сможешь отслеживать свой прогресс и понимать, сколько у тебя есть")

    @dp.message(TutorialStates.step4, F.text.lower().in_(('баланс', 'мой баланс', 'б', 'балик')))
    async def tutorial_step4(message: Message, state: FSMContext):
        user = await get_user_data(message.from_user.id)
        await message.answer(
            f"Ваш баланс:\n"
        f"💰Обычные монеты: <b>{user.get('balance_normal', 0):,}</b>\n"
        f"✨Особые монеты: <b>{user.get('balance_special', 0):,}</b>\n"
        f"🌌Галактические монеты: <b>{user.get('balance_galactic', 0):,}</b>\n"
        )
        await state.set_state(TutorialStates.step5)
        await _show_step(message, 5, "🎰 Отлично, теперь у тебя есть деньги!\n\nСамое время попробовать рискнуть и приумножить их!\n\nТы можешь сыграть в  — там можно как выиграть, так и проиграть\n\nИспользуй команду:\n👉 <b>Казино</b> [сумма]\nПопробуй сыграть и посмотри, что получится 👇" )

    @dp.message(TutorialStates.step5, F.text.lower().startswith("казино"))
    async def tutorial_step5(message: Message, state: FSMContext):
        user = await get_user_data(message.from_user.id)
        args = message.text.lower().split()
        if len(args) < 2:
            await message.answer("Напиши: <b>казино [сумма]</b>", parse_mode="HTML")
            return

        try:
            amount = int(args[1])
        except ValueError:
            await message.answer("Неверная сумма. Укажи число.", parse_mode="HTML")
            return

        if amount <= 0:
            await message.answer("Сумма должна быть больше нуля.", parse_mode="HTML")
            return

        if user.get('balance_normal', 0) < amount:
            await message.answer(f"У тебя недостаточно денег. Твой баланс: <b>{user.get('balance_normal', 0):,}</b>", parse_mode="HTML")
            return

        user['balance_normal'] -= amount
        winnings = amount * 2
        user['balance_normal'] += winnings
        await update_user_data(message.from_user.id, user)

        await message.answer(
            f"🎉 Ты выиграл <b>{winnings:,}</b> монет в обучении!\n"
            f"Твой баланс: <b>{user.get('balance_normal', 0):,}</b>.",
            parse_mode="HTML"
        )

        await state.set_state(TutorialStates.step6)
        await _show_step(message, 6, "Отлично, двигаемся дальше!\n\nВ игре есть система Inc Pass — это своего рода пропуск с наградами 🎁\nЗа выполнение действий ты получаешь очки и открываешь бонусы\n\nЧтобы начать получать очки, попробуй Задуть свечи 👇\n\nИспользуй команду:\n👉 <b>Задуть свечи</b>\n\n📖 Подробнее про Inc Pass можно узнать через команду:\n👉 помощь → Inc Pass")

    @dp.message(TutorialStates.step6, F.text.lower().startswith(("задуть свечи")))
    async def tutorial_step6(message: Message, state: FSMContext):
        await add_pass_exp(message.from_user.id, 300)
        await message.answer("Вы успешно задули свечи и получили 300 очков Inc Pass.")

        user = await get_user_data(message.from_user.id)
        user['balance_normal'] = user.get('balance_normal', 0) + 10_000
        await update_user_data(message.from_user.id, user)
        await add_pass_exp(message.from_user.id, 1000)
        await _finish_training(message.from_user.id)
        await state.clear()

        bot_user = await bot.get_me()
        final_text = ("🎉 Отлично! Ты прошёл обучение!\n\nТеперь ты знаешь основы и готов играть по-настоящему.\nЗарабатывай, рискуй и поднимайся в топ игроков 🏆\n\n🎁 Тебе выдан стартовый набор:\n— 10 000 монет\n— 1 000 очков Inc Pass\n\n👇 Дальше ты можешь:\n\n💬 Перейти в чат и общаться с игроками\n📢 Подписаться на канал\n📖 Посмотреть список команд\n(кнопки ниже )\n\n🎁 Не забывай забирать ежедневную награду:\n👉 ежедневно\n\n👥 И приглашай друзей по реферальной системе:\n👉 пригласить\n\nУдачи в игре! 🚀")
        await message.answer(final_text, parse_mode="HTML", reply_markup=_build_final_keyboard(bot_user.username or 'IncBot', message.from_user.id))

    @dp.message(F.state.in_(TutorialStates))
    async def tutorial_unknown(message: Message, state: FSMContext):
        current = await state.get_state()
        if not current:
            return

        state_map = {
            TutorialStates.step1.state: (1, ('шахта', 'добыть руду', 'добывать руду')),
            TutorialStates.step2.state: (2, ('улучшить кирку',)),
            TutorialStates.step3.state: (3, ('шахта', 'добыть руду', 'добывать руду')),
            TutorialStates.step4.state: (4, ('баланс', 'мой баланс', 'б', 'балик')),
            TutorialStates.step5.state: (5, None),
            TutorialStates.step6.state: (6, ('задуть свечи')),
        }

        state_entry = state_map.get(current)
        if not state_entry:
            await message.answer("Пожалуйста, используй нужную команду для текущего шага.", reply_markup=tutorial_button())
            return

        step_number, allowed_commands = state_entry
        text = message.text.lower().strip() if message.text else ''

        if allowed_commands:
            if text in allowed_commands:
                return
        elif step_number == 5 and text.startswith('казино'):
            return
        elif step_number == 7 and text.startswith(('Задуть свечи')):
            return

        expected = {
            1: 'шахта',
            2: 'улучшить кирку',
            3: 'шахта',
            4: 'баланс',
            5: 'казино [сумма]',
            7: 'задуть свечи',
        }.get(step_number, 'сообщение')

        await message.answer(
            tutorial_step_text(step_number, f"Сейчас нужно выполнить: <b>{expected}</b>."),
            parse_mode='HTML',
            reply_markup=tutorial_button()
        )

# --- Обработчики команд ---

async def add_case_to_user(user_id: int, case_name: str, count: int = 1):
    """Добавляет указанное количество кейсов данному пользователю."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO user_cases (user_id, case_name, count)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, case_name)
            DO UPDATE SET count = user_cases.count + excluded.count
        ''', (user_id, case_name, count))
        await db.commit()

async def get_user_case_count(user_id: int, case_name: str) -> int:
    """Возвращает количество кейсов данного типа у пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'SELECT count FROM user_cases WHERE user_id = ? AND case_name = ?',
            (user_id, case_name)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0



async def remove_case_from_user(user_id: int, case_name: str, count: int = 1) -> bool:
    """
    Уменьшает количество кейсов у пользователя.
    Возвращает False, если кейсов меньше запрашиваемого количества.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'SELECT count FROM user_cases WHERE user_id = ? AND case_name = ?',
            (user_id, case_name)
        )
        row = await cursor.fetchone()
        if not row or row[0] < count:
            return False
        new_count = row[0] - count
        if new_count > 0:
            await db.execute(
                'UPDATE user_cases SET count = ? WHERE user_id = ? AND case_name = ?',
                (new_count, user_id, case_name)
            )
        else:
            await db.execute(
                'DELETE FROM user_cases WHERE user_id = ? AND case_name = ?',
                (user_id, case_name)
            )
        await db.commit()
        return True
    
# --- INC PASS ФУНКЦИИ ---

async def add_pass_exp(user_id: int, exp_amount: int) -> dict:
    """
    Добавляет опыт в Inc Pass и автоматически выдает награды.
    Возвращает информацию о добытых уровнях и наградах.
    """
    user = await get_user_data(user_id)
    settings = await get_global_settings()
    
    current_exp = user.get('pass_experience', 0)
    current_level = user.get('pass_level', 1)
    claimed_levels = user.get('pass_claimed_levels', [])
    has_inc_pass_plus = bool(user.get('has_inc_pass_plus', 0))
    
    pass_exp_reqs = settings.get('pass_exp_requirements', {})
    pass_rewards = settings.get('pass_rewards', {})
    pass_multiplier = 3 if has_inc_pass_plus else 1
    
    # Добавляем опыт
    effective_exp = exp_amount * pass_multiplier
    current_exp += effective_exp
    new_level = current_level
    newly_unclaimed = []
    
    # Проверяем, прошли ли мы новые уровни
    while True:
        required_exp = pass_exp_reqs.get(new_level, 999999)  # Максимум 50 уровней
        
        if new_level >= 50:  # Максимум 50 уровней
            current_exp = 0
            break
        
        if current_exp >= required_exp:
            current_exp -= required_exp
            new_level += 1
            newly_unclaimed.append(new_level)
        else:
            break
    
    # Обновляем данные пользователя
    user['pass_experience'] = current_exp
    user['pass_level'] = new_level
    
    # Применяем награды за новые уровни (модифицируем user напрямую)
    reward_info = []
    for level in newly_unclaimed:
        if level not in claimed_levels:
            reward = pass_rewards.get(level)
            if reward:
                claimed_levels.append(level)
                reward_type = reward.get('type')
                
                # Применяем награду прямо в user
                if reward_type == 'normal_money':
                    amount = reward.get('amount', 0) * (3 if has_inc_pass_plus else 1)
                    user['balance_normal'] = user.get('balance_normal', 0) + amount
                    reward_text = f"💰 {amount:,} обычных монет" + (" (x3)" if has_inc_pass_plus else "")
                
                elif reward_type == 'special_money':
                    amount = reward.get('amount', 0) * (3 if has_inc_pass_plus else 1)
                    user['balance_special'] = user.get('balance_special', 0) + amount
                    reward_text = f"✨ {amount} особых монет" + (" (x3)" if has_inc_pass_plus else "")
                
                elif reward_type == 'galactic_money':
                    amount = reward.get('amount', 0) * (3 if has_inc_pass_plus else 1)
                    user['balance_galactic'] = user.get('balance_galactic', 0) + amount
                    reward_text = f"🌌 {amount} галактических монет" + (" (x3)" if has_inc_pass_plus else "")
                
                elif reward_type == 'case':
                    case_name = reward.get('case_name', '')
                    case_count = 3 if has_inc_pass_plus else 1
                    await add_case_to_user(user_id, case_name, case_count)
                    reward_text = f"🎁 Кейс: {case_name} x{case_count}" + (" (x3)" if has_inc_pass_plus else "")
                
                elif reward_type == 'pro_subscription':
                    max_time = datetime.datetime.max
                    user['pro_subscription_until'] = max_time
                    user['donat_status'] = 'pro'
                    reward_text = "👑 PRO подписка навсегда"
                
                else:
                    reward_text = "❓ Неизвестная награда"
                
                reward_info.append((level, reward, reward_text))
    
    user['pass_claimed_levels'] = claimed_levels

    # Выдаём титул за полное прохождение пасса
    if new_level >= 50:
        completion_title = 'b-day ultimate' if has_inc_pass_plus else 'b-day'
        if completion_title not in user.get('titles', []):
            user['titles'] = [*user.get('titles', []), completion_title]
        added = await add_title_to_user(user_id, completion_title)
        if added:
            try:
                await bot.send_message(user_id, f"🏆 Вы завершили Inc Pass!\n\nПолучен титул: <b>{completion_title}</b>", parse_mode="HTML")
            except Exception as e:
                print(f"Не удалось отправить сообщение о титуле за pass для {user_id}: {e}")
    
    # Сохраняем всё один раз
    await update_user_data(user_id, user)
    
    # Отправляем сообщения о повышении уровней
    if newly_unclaimed:
        try:
            for level in newly_unclaimed:
                for lv, rwd, rwd_text in reward_info:
                    if lv == level:
                        msg = f"🎉 <b>Поздравляем!</b>\n\n🎮 Вы достигли <b>уровня {level}</b> в Inc Pass!\n\n🎁 Награда: {rwd_text}"
                        try:
                            await bot.send_message(user_id, msg, parse_mode="HTML")
                        except Exception as e:
                            print(f"Не удалось отправить сообщение о Pass уровне {level} для {user_id}: {e}")
                        break
        except Exception as e:
            print(f"Ошибка при отправке сообщений о Pass: {e}")
    
    return {
        'new_level': new_level,
        'current_exp': current_exp,
        'newly_leveled': newly_unclaimed,
        'rewards': reward_info,
        'exp_gained': effective_exp
    }

async def apply_pass_reward(user_id: int, reward: dict, level: int) -> str:
    """
    Применяет награду за уровень пасса.
    Возвращает текст о полученной награде.
    НЕ СОХРАНЯЕТ В БД (это делает add_pass_exp)
    """
    user = await get_user_data(user_id)
    reward_type = reward.get('type')
    has_inc_pass_plus = bool(user.get('has_inc_pass_plus', 0))
    
    if reward_type == 'normal_money':
        amount = reward.get('amount', 0) * (3 if has_inc_pass_plus else 1)
        user['balance_normal'] = user.get('balance_normal', 0) + amount
        text = f"💰 {amount:,} обычных монет" + (" (x3)" if has_inc_pass_plus else "")
    
    elif reward_type == 'special_money':
        amount = reward.get('amount', 0) * (3 if has_inc_pass_plus else 1)
        user['balance_special'] = user.get('balance_special', 0) + amount
        text = f"✨ {amount} особых монет" + (" (x3)" if has_inc_pass_plus else "")
    
    elif reward_type == 'galactic_money':
        amount = reward.get('amount', 0) * (3 if has_inc_pass_plus else 1)
        user['balance_galactic'] = user.get('balance_galactic', 0) + amount
        text = f"🌌 {amount} галактических монет" + (" (x3)" if has_inc_pass_plus else "")
    
    elif reward_type == 'case':
        case_name = reward.get('case_name', '')
        case_count = 3 if has_inc_pass_plus else 1
        await add_case_to_user(user_id, case_name, case_count)
        text = f"🎁 Кейс: {case_name} x{case_count}" + (" (x3)" if has_inc_pass_plus else "")
    
    elif reward_type == 'pro_subscription':
        # Выдаем PRO статус иммортально (на максимальную дату)
        max_time = datetime.datetime.max
        user['pro_subscription_until'] = max_time
        user['donat_status'] = 'pro'
        text = "👑 PRO подписка навсегда"
    
    else:
        text = "❓ Неизвестная награда"
    
    # ВАЖНО: Не сохраняем здесь! Это делает add_pass_exp
    # await update_user_data(user_id, user)
    return text

async def get_pass_info(user_id: int) -> str:
    """
    Возвращает информацию о Inc Pass пользователя в формате текста.
    """
    user = await get_user_data(user_id)
    settings = await get_global_settings()
    
    level = user.get('pass_level', 1)
    exp = user.get('pass_experience', 0)
    pass_label = "INC Pass+" if user.get('has_inc_pass_plus', 0) else "Inc Pass"
    
    pass_exp_reqs = settings.get('pass_exp_requirements', {})
    pass_rewards = settings.get('pass_rewards', {})
    
    current_req = pass_exp_reqs.get(level, 0)
    next_reward = pass_rewards.get(level + 1, {})
    
    # Прогресс бара
    progress = int((exp / current_req) * 20) if current_req > 0 else 20
    bar = '█' * progress + '░' * (20 - progress)

    def format_timedelta(td: datetime.timedelta) -> str:
        days = td.days
        hours, remainder = divmod(td.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = []
        if days:
            parts.append(f"{days} дн.")
        if hours:
            parts.append(f"{hours} ч")
        if minutes:
            parts.append(f"{minutes} м")
        if seconds or not parts:
            parts.append(f"{seconds} с")
        return ' '.join(parts)

    season_end = datetime.datetime(2026, 10, 20, 15, 0)
    now = datetime.datetime.now()
    if now < season_end:
        remaining = format_timedelta(season_end - now)
        season_text = f"\n<b>До конца сезона:</b> {remaining}"
    else:
        season_text = "\n<b>Сезон:</b> завершён"

    text = f"""🎮 <b>{pass_label}</b>

<b>Уровень:</b> {level}/50
<b>Опыт:</b> {exp}/{current_req}
<b>Прогресс:</b> [{bar}]{season_text}

<b>Следующая награда (Уровень {level + 1}):</b>
"""
    
    if next_reward:
        has_inc_pass_plus = bool(user.get('has_inc_pass_plus', 0))
        boost_suffix = " (x3)" if has_inc_pass_plus else ""
        if next_reward.get('type') == 'normal_money':
            amount = next_reward.get('amount', 0) * (3 if has_inc_pass_plus else 1)
            text += f"💰 {amount:,} монет{boost_suffix}"
        elif next_reward.get('type') == 'special_money':
            amount = next_reward.get('amount', 0) * (3 if has_inc_pass_plus else 1)
            text += f"✨ {amount} особых монет{boost_suffix}"
        elif next_reward.get('type') == 'galactic_money':
            amount = next_reward.get('amount', 0) * (3 if has_inc_pass_plus else 1)
            text += f"🌌 {amount} галактических монет{boost_suffix}"
        elif next_reward.get('type') == 'case':
            case_count = 3 if has_inc_pass_plus else 1
            text += f"🎁 Кейс: {next_reward.get('case_name', '')} x{case_count}{boost_suffix}"
        elif next_reward.get('type') == 'pro_subscription':
            text += f"👑 PRO подписка навсегда!"
    
    # Если я на уровне 50, показываем информацию по-другому
    if level >= 50:
        text = f"""🎮 <b>{pass_label}</b>

<b>Уровень:</b> {level}/50 ✅
<b>Статус:</b> Пасс завершен!

Вы получили все награды, включая <b>титул b-day</b>! 👑{season_text}
"""
    
    return text

register_tutorial_handlers(
    dp,
    bot,
    DB_PATH,
    get_user_data,
    update_user_data,
    get_global_settings,
    add_pass_exp,
    add_case_to_user
)

@dp.message(CommandStart())
async def command_start_handler(message: Message, command: CommandObject):
    user_id = message.from_user.id
    user_name_escaped = html.escape(message.from_user.full_name)
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT _id FROM users WHERE _id = ?', (user_id,))
        user_doc_exists_before_get = await cursor.fetchone() is not None

    user = await get_user_data(user_id)
    settings = await get_global_settings()
    referral_config = settings.get('referral_rewards', {})
    referrer_id_str = command.args; referrer_id = None
    if referrer_id_str:
        try: referrer_id = int(referrer_id_str)
        except ValueError: pass
    
    welcome_message = "Добро пожаловать в игру!"
    if not user_doc_exists_before_get:
        if referrer_id and referrer_id != user_id:
            user['referred_by'] = referrer_id
            referral_base = referral_config.get('base_normal', 10000)
            referral_bonus_per = referral_config.get('per_invite_bonus', 1000)
            referral_pass_exp = referral_config.get('pass_exp', 1000)
            new_user_bonus = referral_config.get('new_user_bonus', 0)
            milestone_rewards = referral_config.get('milestone_rewards', {})

            referrer_user = await get_user_data(referrer_id)
            if referrer_user:
                current_invites = referrer_user.get('invites_count', 0)
                reward_amount = referral_base + (current_invites * referral_bonus_per)
                new_invite_count = current_invites + 1

                referrer_user['invites_count'] = new_invite_count
                referrer_user['balance_normal'] = referrer_user.get('balance_normal', 0) + reward_amount
                await update_user_data(referrer_id, referrer_user)

                await add_pass_exp(referrer_id, referral_pass_exp)

                milestone_text = ""
                milestone_reward = milestone_rewards.get(new_invite_count)
                if milestone_reward:
                    reward_type = milestone_reward.get('type')
                    if reward_type == 'normal_money':
                        amount = milestone_reward.get('amount', 0)
                        referrer_user['balance_normal'] = referrer_user.get('balance_normal', 0) + amount
                        milestone_text = f" + бонус за {new_invite_count}-е приглашение: {amount:,} монет"
                    elif reward_type == 'special_money':
                        amount = milestone_reward.get('amount', 0)
                        referrer_user['balance_special'] = referrer_user.get('balance_special', 0) + amount
                        milestone_text = f" + бонус за {new_invite_count}-е приглашение: {amount} особых монет"
                    elif reward_type == 'galactic_money':
                        amount = milestone_reward.get('amount', 0)
                        referrer_user['balance_galactic'] = referrer_user.get('balance_galactic', 0) + amount
                        milestone_text = f" + бонус за {new_invite_count}-е приглашение: {amount} галактических монет"
                    elif reward_type == 'case':
                        case_name = milestone_reward.get('case_name', '')
                        await add_case_to_user(referrer_id, case_name, 1)
                        milestone_text = f" + бонус за {new_invite_count}-е приглашение: кейс {case_name}"
                    await update_user_data(referrer_id, referrer_user)

                if new_user_bonus:
                    user['balance_normal'] = user.get('balance_normal', 0) + new_user_bonus
                    welcome_message = f"Привет! Вы были приглашены пользователем <code>{referrer_id}</code> и получили бонус {new_user_bonus:,} монет."
                else:
                    welcome_message = f"Привет! Вы были приглашены пользователем <code>{referrer_id}</code>."

                try:
                    await bot.send_message(
                        referrer_id,
                        f"Пользователь <code>{user_id}</code> (<b>{user_name_escaped}</b>) зарегистрировался по вашей ссылке! "
                        f"Вы получили <b>{reward_amount:,}</b> обычных монет, +<b>{referral_pass_exp}</b> очков Inc Pass.{milestone_text}",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    print(f"Сообщение рефереру {referrer_id} не отправлено: {e}")
                if new_user_bonus:
                    try:
                        await bot.send_message(
                            user_id,
                            f"Вы зарегистрировались по реферальной ссылке и получили бонус <b>{new_user_bonus:,}</b> монет!",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        print(f"Не удалось отправить сообщение новому пользователю {user_id}: {e}")
        await update_user_data(user_id, user) # Сохраняем 'referred_by' если было установлено
    else:
        welcome_message = "С возвращением в игру!"
    
    start_buttons = [
        [InlineKeyboardButton(text="наш чат", url="https://t.me/IncBotChat")],
        [InlineKeyboardButton(text="наш канал", url="https://t.me/IncBotChannel")],
        [InlineKeyboardButton(text="вопросник", url="https://t.me/IncBotHelp_bot")],
        [InlineKeyboardButton(text="общие команды", callback_data="main_menu")]
    ]
    if not user.get('tutorial_completed'):
        start_buttons.insert(0, [InlineKeyboardButton(text="🎓 Обучение", callback_data="start_tutorial")])

    await message.answer("🎰 Добро пожаловать в INC Bot!\n\n💰 Зарабатывай деньги, рискуй в казино, прокачивайся и поднимайся в топ игроков 🏆\nЗдесь каждый может стать богатым — всё зависит только от тебя\n\n🔥 Начни с нуля и попробуй дойти до вершины\n\n👇 Выбирай, что делать дальше\n\n❗ Если ты здесь впервые — обязательно пройди обучение\nЭто поможет быстро разобраться и начать зарабатывать",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=start_buttons),
        disable_web_page_preview=True
    )
    '''
    if not user_doc_exists_before_get: # Вызываем check_daily_login только для новых пользователей
        await check_daily_login(message.from_user.id)
    '''
@dp.message(Command('bones'))
@dp.message(F.text.lower().startswith("кости"))
async def command_bones_handler(message: Message, command: CommandObject = None):
    
    """
    Использование:
    - Ответ на сообщение игрока: 'кости 1000' или '/bones 1000'
    - Создаёт запрос на дуэль и предлагает оппоненту принять/отклонить.
    """
    args = None
    if command and command.args:
        args = command.args.strip()
    else:
        # если текст вида "кости 1000"
        parts = message.text.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else None

    # Должен быть ответ на сообщение (чтобы указать оппонента)
    if not message.reply_to_message:
        await message.answer("Использование: ответьте на сообщение игрока и напишите `кости [ставка]`.", parse_mode="HTML")
        return

    try:
        stake = int(args)
        if stake <= 0:
            raise ValueError()
    except Exception:
        await message.answer("Неверная ставка. Укажите целое положительное число, например: [кости 1000].", parse_mode="HTML")
        return

    challenger_id = message.from_user.id
    opponent_msg = message.reply_to_message
    opponent_id = opponent_msg.from_user.id
    if opponent_id == challenger_id:
        await message.answer("Нельзя бросать вызов самому себе.", parse_mode="HTML")
        return

    # Проверки баланса (предварительно)
    challenger = await get_user_data(challenger_id)
    if challenger.get('balance_normal', 0) < stake:
        await message.answer(f"У вас недостаточно монет для ставки {stake:,}.", parse_mode="HTML")
        return

    # Создаём уникальный id дуэли
    duel_id = str(int(time.time())) + "_" + uuid.uuid4().hex[:8]

    # Inline buttons для принятия / отклонения
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"bones_accept:{duel_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"bones_decline:{duel_id}")
        ]
    ])

  
    
    # Сохраняем ожидающую дуэль
    PENDING_DUELS[duel_id] = {
        "challenger_id": challenger_id,
        "opponent_id": opponent_id,
        "stake": stake,
        "chat_id": message.chat.id,
        "message_id": message.message_id,
        "lock": asyncio.Lock()
    }

    asyncio.create_task(auto_cancel_duel(duel_id, timeout=60))

    # Уведомление оппоненту (в т.ч. в группах оно придёт как reply-кнопка)
    
    challengernick = html.escape(message.from_user.full_name)
    opponent_nick = html.escape(opponent_msg.from_user.full_name)


    

    
    

      


    
    try:
        sent = await message.answer(
            f"🎲 <b>{challengernick}</b> бросил(а) вызов <b>{opponent_nick}</b> на кости.\n"
            f"Ставка: <b>{stake:,}</b> монет.\n\n"
            f"Оппоненту: нажмите <b>Принять</b>, чтобы начать дуэль.",
            parse_mode="HTML",
            reply_markup=kb
        )
    # Сохраняем message_id того сообщения, которое отправил бот
        PENDING_DUELS[duel_id] = {
            "challenger_id": challenger_id,
            "opponent_id": opponent_id,
            "stake": stake,
            "chat_id": message.chat.id,
            "message_id": sent.message_id,   # <-- важно: здесь sent.message_id, а не message.message_id
            "lock": asyncio.Lock()
        }
    except Exception:
    # fallback — если отправка не удалась, отменяем дуэль
        await message.answer("Ошибка при отправке вызова. Попробуйте ещё раз.")
        PENDING_DUELS.pop(duel_id, None)
        return


        
    except Exception:
        # fallback
        await message.answer("Ошибка при отправке вызова. Попробуйте ещё раз.")
        PENDING_DUELS.pop(duel_id, None)
        return

async def auto_cancel_duel(duel_id: str, timeout: int = 60):
    await asyncio.sleep(timeout)
    duel = PENDING_DUELS.pop(duel_id, None)
    if not duel:
        return

    chat_id = duel.get('chat_id')
    message_id = duel.get('message_id')

    try:
        if chat_id and message_id:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        print(f"[WARN] delete_message failed for duel {duel_id}: {e}", flush=True)

    # Всегда пытаемся отправить уведомление (даже если удаление прошло)
    try:
        if chat_id:
            await bot.send_message(chat_id, "⌛ Вызов на кости истёк — оппонент не ответил.", parse_mode="HTML")
    except Exception as e:
        print(f"[WARN] send_message failed for duel {duel_id}: {e}", flush=True)


    
            
@dp.callback_query(lambda c: c.data and c.data.startswith("bones_decline:"))
async def bones_decline_callback(callback: CallbackQuery):
    duel_id = callback.data.split(":", 1)[1]
    duel = PENDING_DUELS.get(duel_id)
    if not duel:
        await callback.answer("Этот вызов устарел или был отменён.", show_alert=True)
        return

    user_id = callback.from_user.id
    # Только оппонент может отказаться
    if user_id != duel['opponent_id']:
        await callback.answer("Только оппонент может отклонить вызов.", show_alert=True)
        return

    # Удаляем дуэль и уведомляем
    PENDING_DUELS.pop(duel_id, None)
    await callback.message.edit_text("❌ Вызов на кости отклонён.", parse_mode="HTML")
    await callback.answer("Вы отклонили вызов.", show_alert=False)


@dp.callback_query(lambda c: c.data and c.data.startswith("rps_decline:"))
async def rps_decline_callback(callback: CallbackQuery):
    rps_id = callback.data.split(":", 1)[1]
    rps = PENDING_RPS.get(rps_id)
    if not rps:
        await callback.answer("Этот вызов устарел или был отменён.", show_alert=True)
        return
    user_id = callback.from_user.id
    if user_id != rps['opponent_id']:
        await callback.answer("Только оппонент может отклонить вызов.", show_alert=True)
        return
    PENDING_RPS.pop(rps_id, None)
    try:
        await callback.message.edit_text("❌ Вызов на камень/ножницы/бумага отклонён.", parse_mode="HTML")
    except Exception:
        pass
    await callback.answer("Вы отклонили вызов.", show_alert=False)


@dp.callback_query(lambda c: c.data and c.data.startswith("rps_accept:"))
async def rps_accept_callback(callback: CallbackQuery):
    try:
        await callback.answer("Подождите, обрабатываю...", show_alert=False)
    except Exception:
        pass

    rps_id = callback.data.split(":", 1)[1]
    rps = PENDING_RPS.get(rps_id)
    if not rps:
        await callback.answer("Этот вызов устарел или был отменён.", show_alert=True)
        return

    user_id = callback.from_user.id
    if user_id != rps['opponent_id']:
        await callback.answer("Только оппонент может принять вызов.", show_alert=True)
        return

    lock: asyncio.Lock = rps.get('lock') or asyncio.Lock()
    async with lock:
        if rps_id not in PENDING_RPS:
            await callback.answer("Вызов уже отменён.", show_alert=True)
            return

        challenger_id = rps['challenger_id']
        opponent_id = rps['opponent_id']
        stake = int(rps['stake'])

        # Проверяем балансы ещё раз
        challenger = await get_user_data(challenger_id)
        opponent = await get_user_data(opponent_id)
        if challenger.get('balance_normal', 0) < stake:
            PENDING_RPS.pop(rps_id, None)
            try: await callback.message.edit_text("❌ Вызов отменён: у инициатора недостаточно монет.", parse_mode="HTML")
            except Exception: pass
            await callback.answer("У инициатора недостаточно монет.", show_alert=True)
            return
        if opponent.get('balance_normal', 0) < stake:
            PENDING_RPS.pop(rps_id, None)
            try: await callback.message.edit_text("❌ Вызов отменён: у оппонента недостаточно монет.", parse_mode="HTML")
            except Exception: pass
            await callback.answer("У вас недостаточно монет.", show_alert=True)
            return

        # Списываем ставки (резервируем)
        challenger['balance_normal'] = challenger.get('balance_normal', 0) - stake
        opponent['balance_normal'] = opponent.get('balance_normal', 0) - stake
        await update_user_data(challenger_id, challenger)
        await update_user_data(opponent_id, opponent)

        # Inline-кнопки для выбора камень/ножницы/бумага
        kb_choice = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✊ Камень", callback_data=f"rps_choice:{rps_id}:rock")],
            [InlineKeyboardButton(text="✌️ Ножницы", callback_data=f"rps_choice:{rps_id}:scissors")],
            [InlineKeyboardButton(text="🖐️ Бумага", callback_data=f"rps_choice:{rps_id}:paper")]
        ])

        # Отправляем в ЛС обоим игрокам. Если отправка в ЛС не удалась — возвращаем ставки и отменяем игру.
        try:
            await bot.send_message(challenger_id, f"Игра с <b>{html.escape((await bot.get_chat(opponent_id)).full_name or str(opponent_id))}</b> на <b>{stake:,}</b> монет. Выберите: камень / ножницы / бумага.", parse_mode="HTML", reply_markup=kb_choice)
            await bot.send_message(opponent_id, f"Игра с <b>{html.escape((await bot.get_chat(challenger_id)).full_name or str(challenger_id))}</b> на <b>{stake:,}</b> монет. Выберите: камень / ножницы / бумага.", parse_mode="HTML", reply_markup=kb_choice)
        except Exception as e:
            # попытка вернуть деньги
            challenger['balance_normal'] = challenger.get('balance_normal', 0) + stake
            opponent['balance_normal'] = opponent.get('balance_normal', 0) + stake
            await update_user_data(challenger_id, challenger)
            await update_user_data(opponent_id, opponent)
            PENDING_RPS.pop(rps_id, None)
            try:
                await callback.message.edit_text("❌ Не удалось отправить личные сообщения одному из игроков. Игра отменена.", parse_mode="HTML")
            except Exception:
                pass
            await callback.answer("Не удалось начать игру (ошибка отправки ЛС).", show_alert=True)
            return

        # Обозначаем, что игра началась, чтобы первоначальный таймаут не отменял её
        rps['started'] = True

        # Обновляем сенсорноe сообщение в чате, что игра началась
        try:
            await callback.message.edit_text(f"✊🖐️✌️ Игра между <b>{html.escape((await bot.get_chat(challenger_id)).full_name)}</b> и <b>{html.escape((await bot.get_chat(opponent_id)).full_name)}</b> началась! Каждый получил запрос в ЛС.", parse_mode="HTML")
        except Exception:
            pass

        # ставим таймаут на выборы — по истечении решаем по наличию выборов
        asyncio.create_task(auto_resolve_rps(rps_id, timeout=60))
        await callback.answer("Игра началась — выберите ход в личных сообщениях.", show_alert=False)

@dp.callback_query(lambda c: c.data and c.data.startswith("rps_choice:"))
async def rps_choice_callback(callback: CallbackQuery):
    data = callback.data.split(":")
    if len(data) != 3:
        await callback.answer("Неверный формат.", show_alert=True)
        return
    rps_id = data[1]
    choice = data[2]  # rock/scissors/paper
    rps = PENDING_RPS.get(rps_id)
    if not rps:
        await callback.answer("Эта игра уже завершена или отменена.", show_alert=True)
        return

    user_id = callback.from_user.id
    if user_id not in (rps['challenger_id'], rps['opponent_id']):
        await callback.answer("Вы не участник этой игры.", show_alert=True)
        return

    async with rps.get('lock', asyncio.Lock()):
        if user_id in rps['choices']:
            await callback.answer("Вы уже сделали выбор.", show_alert=True)
            return

        # сохраняем выбор
        rps['choices'][user_id] = choice
        choice_labels = {
            'rock': 'камень',
            'scissors': 'ножницы',
            'paper': 'бумагу',
        }
        choice_label = choice_labels.get(choice, choice)
        await callback.answer(f"Вы выбрали: {choice_label}", show_alert=False)

        # если оба выбрали — финализируем
        if len(rps['choices']) == 2:
            await finalize_rps(rps_id)
        else:
            try:
                await callback.message.edit_text(
                    f"✊🖐️✌️ Вы выбрали <b>{choice_label}</b>.\n\n"
                    "⏳ Ожидаем выбора другого игрока...",
                    parse_mode="HTML"
                )
            except Exception:
                pass




@dp.callback_query(lambda c: c.data and c.data.startswith("bones_accept:"))
async def bones_accept_callback(callback: CallbackQuery):
    # Сразу убираем крутилку в клиенте — короткое подтверждение
    try:
        await callback.answer("Подождите, обрабатываю...", show_alert=False)
    except Exception:
        # ignore if cannot answer (rare)
        pass

    duel_id = callback.data.split(":", 1)[1]
    try:
        duel = PENDING_DUELS.get(duel_id)
        if not duel:
            await callback.answer("Этот вызов устарел или был отменён.", show_alert=True)
            return

        user_id = callback.from_user.id
        # Только оппонент может принять
        if user_id != duel['opponent_id']:
            await callback.answer("Только оппонент может принять вызов.", show_alert=True)
            return

        # Берём lock из структуры, если нет — создаём временный
        lock: asyncio.Lock = duel.get('lock')
        if lock is None:
            lock = asyncio.Lock()
            duel['lock'] = lock

        async with lock:
            # После захвата lock ещё раз проверим дуэль
            if duel_id not in PENDING_DUELS:
                await callback.answer("Вызов уже отменён.", show_alert=True)
                return

            challenger_id = duel['challenger_id']
            opponent_id = duel['opponent_id']
            stake = int(duel['stake'])

            # Получаем актуальные данные
            challenger = await get_user_data(challenger_id)
            opponent = await get_user_data(opponent_id)

            # Проверка балансов
            if challenger.get('balance_normal', 0) < stake:
                PENDING_DUELS.pop(duel_id, None)
                try:
                    await callback.message.edit_text("❌ Вызов отменён: у инициатора недостаточно монет.", parse_mode="HTML")
                except Exception:
                    pass
                await callback.answer("У инициатора недостаточно монет.", show_alert=True)
                return

            if opponent.get('balance_normal', 0) < stake:
                PENDING_DUELS.pop(duel_id, None)
                try:
                    await callback.message.edit_text("❌ Вызов отменён: у оппонента недостаточно монет.", parse_mode="HTML")
                except Exception:
                    pass
                await callback.answer("У вас недостаточно монет.", show_alert=True)
                return

            # Резервируем (списываем) ставки — сохраняем изменения в БД
            challenger['balance_normal'] = challenger.get('balance_normal', 0) - stake
            opponent['balance_normal'] = opponent.get('balance_normal', 0) - stake
            await update_user_data(challenger_id, challenger)
            await update_user_data(opponent_id, opponent)

            # Кидаем кости
            roll_challenger = random.randint(1, 6)
            roll_opponent = random.randint(1, 6)

            # Подготовим имена (без долгих вызовов get_chat, чтобы не блокировать)
            try:
                # Пытаемся взять более дружелюбные имена; если get_chat медленный — можно убрать
                chall_user = await bot.get_chat(challenger_id)
                opp_user = await bot.get_chat(opponent_id)
                chall_name = getattr(chall_user, "full_name", None) or getattr(chall_user, "first_name", f"ID {challenger_id}")
                opp_name = getattr(opp_user, "full_name", None) or getattr(opp_user, "first_name", f"ID {opponent_id}")
            except Exception:
                # Фейлбек: имена из user структуры
                chall_name = html.escape((await get_user_data(challenger_id)).get('last_login_date') or f"ID {challenger_id}")
                opp_name = html.escape((await get_user_data(opponent_id)).get('last_login_date') or f"ID {opponent_id}")

            # Решаем победителя
            if roll_challenger > roll_opponent:
                pot = int(stake * 2 * (1 - DUEL_COMMISSION_RATE))
                # начисляем победителю (challenger)
                winner_id = challenger_id
                winner_user = await get_user_data(challenger_id)
                winner_user['balance_normal'] = winner_user.get('balance_normal', 0) + pot
                await update_user_data(challenger_id, winner_user)
                final_text = (
                    f"🎲 Результат дуэли на кости (ставка <b>{stake:,}</b>):\n\n"
                    f"👤 {html.escape(str(chall_name))}: <b>{roll_challenger}</b>\n"
                    f"👤 {html.escape(str(opp_name))}: <b>{roll_opponent}</b>\n\n"
                    f"🏆 Победитель: <b>{html.escape(str(chall_name))}</b> — получает <b>{pot:,}</b> монет!"
                )
            elif roll_opponent > roll_challenger:
                pot = int(stake * 2 * (1 - DUEL_COMMISSION_RATE))
                winner_id = opponent_id
                winner_user = await get_user_data(opponent_id)
                winner_user['balance_normal'] = winner_user.get('balance_normal', 0) + pot
                await update_user_data(opponent_id, winner_user)
                final_text = (
                    f"🎲 Результат дуэли на кости (ставка <b>{stake:,}</b>):\n\n"
                    f"👤 {html.escape(str(chall_name))}: <b>{roll_challenger}</b>\n"
                    f"👤 {html.escape(str(opp_name))}: <b>{roll_opponent}</b>\n\n"
                    f"🏆 Победитель: <b>{html.escape(str(opp_name))}</b> — получает <b>{pot:,}</b> монет!"
                )
            else:
                # Ничья — возвращаем ставки
                challenger_user = await get_user_data(challenger_id)
                opponent_user = await get_user_data(opponent_id)
                challenger_user['balance_normal'] = challenger_user.get('balance_normal', 0) + stake
                opponent_user['balance_normal'] = opponent_user.get('balance_normal', 0) + stake
                await update_user_data(challenger_id, challenger_user)
                await update_user_data(opponent_id, opponent_user)
           
                final_text = (
                    f"🎲 Результат дуэли на кости (ставка <b>{stake:,}</b>):\n\n"
                    f"👤 {html.escape(str(chall_name))}: <b>{roll_challenger}</b>\n"
                    f"👤 {html.escape(str(opp_name))}: <b>{roll_opponent}</b>\n\n"
                    f"⚖️ Ничья — оба получают ставку обратно."
                )

            # Удаляем дуэль из памяти
            PENDING_DUELS.pop(duel_id, None)

            # Обновляем сообщение: показываем результат (удаляем кнопки)
            try:
                await callback.message.edit_text(final_text, parse_mode="HTML")
            except Exception:
                # Если редактировать нельзя — просто отправим результат в чат
                await callback.message.answer(final_text, parse_mode="HTML")

            # Ответим пользователю, чтобы убрать возможную крутилку (ещё раз)
            await callback.answer("Дуэль завершена.", show_alert=False)
    except Exception:
        tb = traceback.format_exc()
        print("[ERROR] bones_accept exception:\n", tb, flush=True)
        # краткая часть трассировки пользователю (чтобы не заливать весь лог)
        short = tb if len(tb) <= 1000 else tb[:900] + "\n... (truncated)"
        try:
            await callback.message.reply(f"Ошибка при выполнении дуэли:\n<pre>{html.escape(short)}</pre>", parse_mode="HTML")
        except Exception:
            pass
        # Убираем крутилку (если осталась)
        try:
            await callback.answer("Произошла ошибка. Админ в логах.", show_alert=True)
        except Exception:
            pass

@dp.message(Command('hunt'))
@dp.message(F.text.lower().in_(("охота", "пойти на охоту", "поссадить на охоту", "поймать зверя")))
async def command_hunt_handler(message: Message):
    user = await get_user_data(message.from_user.id)
    settings = await get_global_settings()
    now = datetime.datetime.now()

    # Сброс лимита охот (аналогично рыбалке/шахте)
    last_hunt_reset_obj = user.get('last_hunt_reset')
    hunting_cooldown_minutes = settings.get('hunting_cooldown_minutes', 25)

    if last_hunt_reset_obj and isinstance(last_hunt_reset_obj, str):
        try:
            last_hunt_reset_obj = datetime.datetime.fromisoformat(last_hunt_reset_obj)
        except ValueError:
            last_hunt_reset_obj = None

    if last_hunt_reset_obj is None or (now - last_hunt_reset_obj) >= datetime.timedelta(minutes=hunting_cooldown_minutes):
        user['hunting_daily_count'] = 0
        user['last_hunt_reset'] = now

        await update_user_data(message.from_user.id, user)

    donat_status = user.get('donat_status', 'standart').lower()
    hunting_limit = settings.get('hunting_limits', {}).get(donat_status, 10)

    if user.get('hunting_daily_count', 0) >= hunting_limit:
        remaining_time = datetime.timedelta(minutes=hunting_cooldown_minutes) - (now - user['last_hunt_reset'])
        hours, rem = divmod(int(remaining_time.total_seconds()), 3600)
        mins, secs = divmod(rem, 60)
        await message.answer(f"Вы достигли лимита охот (<b>{hunting_limit}</b>). Лимит сбросится через <b>{hours}ч {mins}м {secs}с</b>.", parse_mode="HTML")
        return

    # Список животных (можешь расширить)
    animals = ['зайца', 'лису', 'волка', 'кабана', 'медведя', 'лося']
    animal = random.choice(animals)

    hunting_level = int(user.get('hunting_level', 1))
    hunting_levels = settings.get('hunting_levels', {})
    level_info = hunting_levels.get(hunting_level, {"range": (100, 300), "cost": 0})
    min_money, max_money = level_info['range']

    money_earned = random.randint(min_money, max_money)
    # небольшой бонус за уровень (опционально)
    money_earned += int(money_earned * (hunting_level * 0.03))  # +3% за уровень
    money_earned = int(money_earned * (1 + get_active_title_bonuses(user).get('work_multiplier', 0)))

    

    user['balance_normal'] = user.get('balance_normal', 0) + money_earned
    user['hunting_daily_count'] = user.get('hunting_daily_count', 0) + 1
    await update_user_data(message.from_user.id, user)

    # Добавляем опыт Inc Pass
    hunting_exp = random.randint(settings.get('pass_activity', {}).get('hunting', (50, 100))[0], 
                                 settings.get('pass_activity', {}).get('hunting', (50, 100))[1])
    pass_result = await add_pass_exp(message.from_user.id, hunting_exp)

    answer_text = f"🏹 Вы поймали {animal}, И получили <b>{money_earned:,}</b> монет."
    answer_text += f"\n⭐ Inc Pass: <b>+{hunting_exp}</b> очков"
    answer_text += f"\nОсталось охот: <b>{hunting_limit - user['hunting_daily_count']}</b>."
    
    # Информация о Pass
    if pass_result['newly_leveled']:
        answer_text += f"\n\n🎮 <b>Inc Pass:</b>\n"
        for level in pass_result['newly_leveled']:
            for lv, rwd, rwd_text in pass_result['rewards']:
                if lv == level:
                    answer_text += f"<b>Уровень {level}:</b> {rwd_text}\n"
                    break
    
    if user['hunting_daily_count'] == hunting_limit:
        remaining_time = datetime.timedelta(minutes=hunting_cooldown_minutes) - (now - user['last_hunt_reset'])
        hours, rem = divmod(int(remaining_time.total_seconds()), 3600)
        mins, secs = divmod(rem, 60)
        answer_text += f"\nЛимит сбросится через <b>{hours}ч {mins}м {secs}с</b>."
    await message.answer(answer_text, parse_mode="HTML")





@dp.message(Command('upgrade_hunting'))
@dp.message(F.text.lower().in_(("улучшить ружье","улучшить ружьё", )))
async def command_upgrade_hunting_handler(message: Message):
    try:
        user = await get_user_data(message.from_user.id)
        current_level = int(user.get('hunting_level', 1))

        settings = await get_global_settings()
        hunting_levels = settings.get('hunting_levels') or {}

        # 🔧 фиксим ключи (строки → числа)
        hunting_levels = {int(k): v for k, v in hunting_levels.items()}

        max_level = max(hunting_levels.keys())
        if current_level >= max_level:
            await message.answer(f"Ружье уже максимального уровня (<b>{max_level}</b>).", parse_mode="HTML")
            return

        next_level = current_level + 1
        cost = int(hunting_levels[next_level]['cost'])

        next_level2 = current_level + 2
        cost2 = hunting_levels.get(next_level2, {}).get('cost')
        next_cost_text = f"<b>{int(cost2):,}</b>" if cost2 is not None else "максимальная"

        if user.get('balance_normal', 0) >= cost:
            user['balance_normal'] -= cost
            user['hunting_level'] = next_level
            await update_user_data(message.from_user.id, user)
            await add_pass_exp(message.from_user.id, 300)
            await message.answer(
                f"🏹 Уровень ружья повышен до <b>{next_level}</b> за <b>{cost:,}</b> монет! Следующее улучшение будет стоить {next_cost_text} \n+<b>300</b> очков Inc Pass",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"Нужно <b>{cost:,}</b> монет (у вас: <b>{user.get('balance_normal', 0):,}</b>).",
                parse_mode="HTML"
            )

    except Exception:
        # теперь traceback работает
        tb = traceback.format_exc()
        print(tb)
        await message.answer(f"Ошибка при улучшении охоты:\n<pre>{tb}</pre>", parse_mode="HTML")

@dp.message(F.text.lower().startswith("кмн"))
async def command_rps_handler(message: Message):
    """
    Использование: ответьте на сообщение человека и напишите:
      кмн [ставка]
    """
    # Парсим ставку (после 'кмн ')
    parts = message.text.split(maxsplit=1)
    args = parts[1].strip() if len(parts) > 1 else None

    # Должен быть reply на сообщение — это наш оппонент
    if not message.reply_to_message:
        await message.answer("Использование: ответьте на сообщение игрока и напишите `кмн [ставка]`.", parse_mode="HTML")
        return

    # Проверка ставки
    try:
        stake = int(args)
        if stake <= 0:
            raise ValueError()
    except Exception:
        await message.answer("Неверная ставка. Укажите целое положительное число, например: `кмн 1000`.", parse_mode="HTML")
        return

    challenger_id = message.from_user.id
    opponent_msg = message.reply_to_message
    opponent_id = opponent_msg.from_user.id

    if opponent_id == challenger_id:
        await message.answer("Нельзя играть сам с собой.", parse_mode="HTML")
        return

    challenger = await get_user_data(challenger_id)
    if challenger.get('balance_normal', 0) < stake:
        await message.answer(f"У вас недостаточно монет для ставки {stake:,}.", parse_mode="HTML")
        return

    # Уникальный id игры
    rps_id = str(int(time.time())) + "_" + uuid.uuid4().hex[:8]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"rps_accept:{rps_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rps_decline:{rps_id}")
        ]
    ])

    PENDING_RPS[rps_id] = {
        "challenger_id": challenger_id,
        "opponent_id": opponent_id,
        "stake": stake,
        "chat_id": message.chat.id,
        "message_id": None,  # заполним после отправки
        "choices": {},       # сюда придут выборы игроков
        "lock": asyncio.Lock(),
        "started": False     # станет True после принятия вызова
    }

    try:
        sent = await message.answer(
            f"✊🖐✌️ <b>{html.escape(message.from_user.full_name)}</b> предлагает сыграть в камень/ножницы/бумага с <b>{html.escape(opponent_msg.from_user.full_name)}</b>\n"
            f"Ставка: <b>{stake:,}</b> монет.\n\nОппонент: нажмите <b>Принять</b>, чтобы продолжить.",
            parse_mode="HTML",
            reply_markup=kb
        )
        PENDING_RPS[rps_id]["message_id"] = sent.message_id
    except Exception:
        PENDING_RPS.pop(rps_id, None)
        await message.answer("Ошибка при отправке вызова. Попробуйте ещё раз.", parse_mode="HTML")
        return

    # Авто-отмена если никто не принял в 60 сек
    asyncio.create_task(auto_cancel_rps(rps_id, timeout=60))

async def auto_cancel_rps(rps_id: str, timeout: int = 60):
    await asyncio.sleep(timeout)

    rps = PENDING_RPS.get(rps_id)
    if not rps:
        return
    if rps.get('started'):
        # игра уже началась, отмена вызова не нужна
        return
    rps = PENDING_RPS.pop(rps_id, None)
    if not rps:
        return

    chat_id = rps.get("chat_id")
    message_id = rps.get("message_id")

    # сначала удаляем сообщение с вызовом, если оно ещё существует
    if chat_id and message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass

    # уведомляем чат
    try:
        await bot.send_message(
            chat_id,
            "⌛ Вызов на камень/ножницы/бумага истёк.",
            parse_mode="HTML"
        )
    except Exception:
        pass


async def auto_resolve_rps(rps_id: str, timeout: int = 60):
    await asyncio.sleep(timeout)
    rps = PENDING_RPS.get(rps_id)
    if not rps:
        return
    # если уже оба выбрали — ничего делать не нужно
    if len(rps.get('choices', {})) == 2:
        return
    challenger_id = rps['challenger_id']
    opponent_id = rps['opponent_id']
    # финализируем (учтёт неполные выборы)
    await finalize_rps(rps_id)
    await update_quest_progress(challenger_id, "rps_3", 1)
    await update_quest_progress(opponent_id, "rps_3", 1)


async def finalize_rps(rps_id: str):
    rps = PENDING_RPS.pop(rps_id, None)
    if not rps:
        return
    challenger_id = rps['challenger_id']
    opponent_id = rps['opponent_id']
    stake = int(rps['stake'])
    choices = rps.get('choices', {})

    # helper for readable names
    try:
        chall_name = (await bot.get_chat(challenger_id)).full_name
    except Exception:
        chall_name = f"ID {challenger_id}"
    try:
        opp_name = (await bot.get_chat(opponent_id)).full_name
    except Exception:
        opp_name = f"ID {opponent_id}"

    # Если оба не выбрали — вернуть ставки
    if len(choices) < 2:
        # вернуть деньги тому, кто уже был списан
        async def refund(uid, amount):
            user = await get_user_data(uid)
            user['balance_normal'] = user.get('balance_normal', 0) + amount
            await update_user_data(uid, user)

        # если никто не выбрал — возвращаем обоим
        await refund(challenger_id, stake)
        await refund(opponent_id, stake)

        text = f"⌛ Игра не завершена (несделаны оба выбора). Ставки возвращены."
        # попытаемся уведомить участников и чат
        try:
            await bot.send_message(challenger_id, text, parse_mode="HTML")
            await bot.send_message(opponent_id, text, parse_mode="HTML")
        except Exception:
            pass

        try:
            if rps.get('chat_id'):
                await bot.send_message(rps['chat_id'], text, parse_mode="HTML")
        except Exception:
            pass
        return

    # оба выбрали — определяем победителя
    a_choice = choices.get(challenger_id)
    b_choice = choices.get(opponent_id)

    # ничья
    if a_choice == b_choice:
        # вернуть ставки
        user_a = await get_user_data(challenger_id)
        user_b = await get_user_data(opponent_id)
        user_a['balance_normal'] = user_a.get('balance_normal', 0) + stake
        user_b['balance_normal'] = user_b.get('balance_normal', 0) + stake
        await update_user_data(challenger_id, user_a)
        await update_user_data(opponent_id, user_b)

        final_text = (
            f"✌️ Результат: Ничья\n\n"
            f"👤 {html.escape(chall_name)}: {a_choice}\n"
            f"👤 {html.escape(opp_name)}: {b_choice}\n\n"
            f"⚖️ Ставки возвращены каждому."
        )
    else:
        # правила: rock > scissors, scissors > paper, paper > rock
        wins = {'rock': 'scissors', 'scissors': 'paper', 'paper': 'rock'}
        if wins.get(a_choice) == b_choice:
            # challenger wins
            winner_id = challenger_id
            winner_name = chall_name
        elif wins.get(b_choice) == a_choice:
            winner_id = opponent_id
            winner_name = opp_name
        else:
            # непредвиденный случай — возвращаем ставки
            user_a = await get_user_data(challenger_id)
            user_b = await get_user_data(opponent_id)
            user_a['balance_normal'] = user_a.get('balance_normal', 0) + stake
            user_b['balance_normal'] = user_b.get('balance_normal', 0) + stake
            await update_user_data(challenger_id, user_a)
            await update_user_data(opponent_id, user_b)
            final_text = "Ошибка определения победителя — ставки возвращены."
            try:
                if rps.get('chat_id'):
                    await bot.send_message(rps['chat_id'], final_text, parse_mode="HTML")
            except Exception:
                pass
            return

        # выплата победителю (получает весь пот)
        pot = int(stake * 2 * (1 - DUEL_COMMISSION_RATE))
        winner_user = await get_user_data(winner_id)
        winner_user['balance_normal'] = winner_user.get('balance_normal', 0) + pot
        await update_user_data(winner_id, winner_user)


        final_text = (
            f"🏆 Результат игры камень/ножницы/бумага (ставка <b>{stake:,}</b>):\n\n"
            f"👤 {html.escape(chall_name)}: {a_choice}\n"
            f"👤 {html.escape(opp_name)}: {b_choice}\n\n"
            f"🏅 Победитель: <b>{html.escape(winner_name)}</b> — получает <b>{pot:,}</b> монет!"
        )

    # уведомляем чат и участников
    try:
        if rps.get('chat_id'):
            await bot.send_message(rps['chat_id'], final_text, parse_mode="HTML")
    except Exception:
        pass

    try:
        await bot.send_message(challenger_id, final_text, parse_mode="HTML")
        await bot.send_message(opponent_id, final_text, parse_mode="HTML")
    except Exception:
        pass

@dp.message(Command('profile'))
@dp.message(F.text.lower().in_(("профиль", "мой профиль")))
async def command_profile_handler(message: Message):
    user = await get_user_data(message.from_user.id)
    user_name_escaped = html.escape(message.from_user.full_name)
    money_cases = await get_user_case_count(message.from_user.id, "money")
    donat_cases = await get_user_case_count(message.from_user.id, "donat")
    mythical_cases = await get_user_case_count(message.from_user.id, "mythical")
    halloween_cases = await get_user_case_count(message.from_user.id, "halloween")

    # Inc Pass информация
    settings = await get_global_settings()
    pass_level = user.get('pass_level', 1)
    pass_exp = user.get('pass_experience', 0)
    pass_exp_reqs = settings.get('pass_exp_requirements', {})
    current_req = pass_exp_reqs.get(pass_level, 0)
    pass_label = "INC Pass+" if user.get('has_inc_pass_plus', 0) else "Inc Pass"
    
    # Прогресс бара для пасса
    if pass_level >= 50:
        pass_progress = "✅ Пасс завершен!"
        pass_info = f"🎮 {pass_label}: Уровень <b>{pass_level}</b>/50"
    else:
        progress_pct = int((pass_exp / current_req) * 100) if current_req > 0 else 0
        pass_progress = f"{progress_pct}% ({pass_exp}/{current_req})"
        pass_info = f"🎮 {pass_label}: Уровень <b>{pass_level}</b>/50 - {pass_progress}"

    def format_num(num):
        # Форматирует число, заменяя запятую на точку для разделения тысяч
        return f"{num:,}".replace(",", ".")

    def format_date_or_none(dt_obj):
        # Форматирует дату или возвращает 'None', если дата отсутствует
        if not dt_obj:
            return 'None'
        if isinstance(dt_obj, datetime.datetime):
            return dt_obj.strftime("%Y-%m-%d %H:%M")
        return html.escape(str(dt_obj))

    # Получаем активный титул
    active_title = user.get('active_title')
    title_line = f"🏆 Титул: <b>{html.escape(active_title)}</b>\n" if active_title else ""

    text = (
        f"👤 Профиль {user_name_escaped} (ID: {message.from_user.id})\n"
        f"\n{title_line}"
        f"{pass_info}\n"
        f"💰 Обычные монеты: {format_num(user.get('balance_normal', 0))}\n"
        f"✨ Особые монеты: {format_num(user.get('balance_special', 0))}\n"        
        f"🌌 Галактические монеты: {format_num(user.get('balance_galactic', 0))}\n"       
        f"🏦 Банк: {format_num(user.get('balance_bank', 0))}\n"
        f"👑 Статус доната: {html.escape(user.get('donat_status', 'standart'))}\n"
        f"⛏️ Уровень кирки: {user.get('mining_pickaxe_level', 1)}\n"
        f"🎣 Уровень удочки: {user.get('fishing_rod_level', 1)}\n"
        f"🏹 Уровень охоты: {user.get('hunting_level', 1)}\n"
        f"🔪 Уровень навыка кражи: {user.get('theft_skill_level', 1)}\n"
        f"🛡️ Уровень защиты от кражи: {user.get('theft_protection_level', 1)}\n"
        f"🗓️ Дневная серия входов: {user.get('daily_login_streak', 0)}\n"
        f"👥 Приглашенных: {user.get('invites_count', 0)}\n"
        f"💰 Последний грабёж казны: {format_date_or_none(user.get('last_treasury_rob_max'))}"
        f"\n\n🎁 Кейсы:\n"
        f" ├ Денежные: {money_cases}\n"   
        f" ├ Донат: {donat_cases}\n"
        f" ├ Мифические: {mythical_cases}\n"
    )
    # Отправляем с HTML парсингом для красивого форматирования
    # Разделяем на части, если сообщение слишком длинное
    max_length = 4000
    if len(text) > max_length:
        parts = []
        current_part = ""
        lines = text.split('\n')
        for line in lines:
            if len(current_part) + len(line) + 1 > max_length:
                if current_part:
                    parts.append(current_part)
                current_part = line
            else:
                current_part += '\n' + line if current_part else line
        if current_part:
            parts.append(current_part)
        for part in parts:
            await message.answer(part, parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")


async def get_crypto_market_text() -> str:
    settings = await get_global_settings()
    market = settings.get('crypto_market', {})
    lines = ["<b>📈 Крипто-рынок</b>", "", "<b>Текущий курс:</b>"]
    for coin_name in ("INCCoin", "TOMCoin"):
        coin = market.get(coin_name, {})
        price = int(coin.get('price', coin.get('base_price', 0)))
        change = float(coin.get('hour_change_percent', coin.get('change_percent', 0.0)))
        lines.append(f"• <b>{coin_name}</b>: <b>{price:,}</b> обычных монет  |  за час: {change:+.2f}%")
    lines.extend([
        "",
        "<b>Команды:</b>",
        "- <code>крипта</code> — рынок",
        "- <code>купить inccoin 100</code> — купить на 100 обычных монет",
        "- <code>продать tomcoin 0.5</code> — продать 0.5 крипто-единицы",
        "- <code>кошелек</code> — криптокошелек",
    ])
    return "\n".join(lines)


async def get_crypto_wallet_text(user_id: int) -> str:
    user = await get_user_data(user_id)
    settings = await get_global_settings()
    market = settings.get('crypto_market', {})
    lines = ["<b>💼 Криптокошелек</b>", ""]
    for coin_name in ("INCCoin", "TOMCoin"):
        holding_key = 'balance_inccoin' if coin_name == 'INCCoin' else 'balance_tomcoin'
        amount = float(user.get(holding_key, 0) or 0)
        price = int(market.get(coin_name, {}).get('price', market.get(coin_name, {}).get('base_price', 0)))
        value = int(round(amount * price))
        lines.append(f"• <b>{coin_name}</b>: {amount:.4f} | стоимость: <b>{value:,}</b> обычных монет")
    lines.append("")
    lines.append(f"Обычные монеты: <b>{user.get('balance_normal', 0):,}</b>")
    return "\n".join(lines)


async def execute_crypto_trade(user_id: int, coin_name: str, action: str, spend_or_amount: float):
    coin_name = normalize_crypto_name(coin_name)
    market = (await get_global_settings()).get('crypto_market', {})
    coin = market.get(coin_name)
    if not coin:
        return False, "Такой крипто-актив не найден."

    if spend_or_amount <= 0:
        return False, "Количество должно быть больше нуля."

    user = await get_user_data(user_id)
    price = float(coin.get('price', coin.get('base_price', 0)))
    holding_key = 'balance_inccoin' if coin_name == 'INCCoin' else 'balance_tomcoin'

    if action == 'buy':
        spend = int(spend_or_amount)
        if user.get('balance_normal', 0) < spend:
            return False, f"Недостаточно обычных монет. Нужно <b>{spend:,}</b>, а у вас <b>{user.get('balance_normal', 0):,}</b>."
        amount_received = spend / price
        user['balance_normal'] -= spend
        user[holding_key] = float(user.get(holding_key, 0) or 0) + amount_received
        await update_user_data(user_id, user)
        return True, f"✅ Куплено <b>{amount_received:.4f}</b> {coin_name} на <b>{spend:,}</b> обычных монет."

    if action == 'sell':
        amount = float(spend_or_amount)
        if float(user.get(holding_key, 0) or 0) < amount:
            return False, f"У вас недостаточно {coin_name}. У вас: <b>{float(user.get(holding_key, 0) or 0):.4f}</b>."
        payout = int(round(amount * price))
        user['balance_normal'] += payout
        user[holding_key] = float(user.get(holding_key, 0) or 0) - amount
        await update_user_data(user_id, user)
        return True, f"✅ Продано <b>{amount:.4f}</b> {coin_name} за <b>{payout:,}</b> обычных монет."

    return False, "Неизвестное действие: buy/sell."


@dp.message(Command('crypto'))
@dp.message(F.text.lower().in_(('крипта', 'биржа', 'рынок крипты')))
async def command_crypto_market_handler(message: Message):
    await message.answer(await get_crypto_market_text(), parse_mode="HTML")


@dp.message(F.text.lower().startswith(("кошелек", "кошелёк" )))
@dp.message(Command('wallet'))
async def command_crypto_wallet_handler(message: Message):
    await message.answer(await get_crypto_wallet_text(message.from_user.id), parse_mode="HTML")


@dp.message(F.text.lower().regexp(r"^купить\s+(?:inccoin|inc|inc_coin|tomcoin|tom|tom_coin)\s+"))
@dp.message(F.text.lower().startswith('крипта купить'))
async def command_buy_crypto_handler(message: Message):
    text = message.text.strip()
    parts = text.split()
    if len(parts) < 3:
        await message.answer("Неверный формат: <code>купить inccoin 100</code> или <code>купить крипту inccoin 100</code>", parse_mode="HTML")
        return

    if parts[1].lower() == 'крипту':
        if len(parts) < 4:
            await message.answer("Неверный формат: <code>купить крипту inccoin 100</code>", parse_mode="HTML")
            return
        coin_name = parts[2]
        value = parts[3]
    else:
        coin_name = parts[1]
        value = parts[2]

    try:
        spend_value = float(value)
    except ValueError:
        await message.answer("Сумма должна быть числом, например: <code>купить inccoin 100</code>", parse_mode="HTML")
        return

    ok, response = await execute_crypto_trade(message.from_user.id, coin_name, 'buy', spend_value)
    await message.answer(response, parse_mode="HTML")


@dp.message(F.text.lower().startswith('продать '))
@dp.message(F.text.lower().startswith('крипта продать'))
async def command_sell_crypto_handler(message: Message):
    text = message.text.strip()
    parts = text.split()
    if len(parts) < 3:
        await message.answer("Неверный формат: <code>продать tomcoin 0.5</code> или <code>продать крипту tomcoin 0.5</code>", parse_mode="HTML")
        return

    if parts[1].lower() == 'крипту':
        if len(parts) < 4:
            await message.answer("Неверный формат: <code>продать крипту tomcoin 0.5</code>", parse_mode="HTML")
            return
        coin_name = parts[2]
        value = parts[3]
    else:
        coin_name = parts[1]
        value = parts[2]

    try:
        amount = float(value)
    except ValueError:
        await message.answer("Количество должно быть числом, например: <code>продать tomcoin 0.5</code>", parse_mode="HTML")
        return

    ok, response = await execute_crypto_trade(message.from_user.id, coin_name, 'sell', amount)
    await message.answer(response, parse_mode="HTML")

@dp.message(Command('pass'))
@dp.message(F.text.lower().in_(("пасс", "inc pass")))
async def command_pass_handler(message: Message):
    """Показывает информацию о Inc Pass"""
    try:
        pass_info = await get_pass_info(message.from_user.id)
        await message.answer(pass_info, parse_mode="HTML")
    except Exception as e:
        print(f"Error in pass handler: {e}")
        await message.answer("❌ Ошибка при получении информации о пассе.", parse_mode="HTML")


@dp.message(Command('cases'))
@dp.message(F.text.lower().in_(("кейсы", "case", "кейс")))
async def command_cases_handler(message: Message):
    """Показывает информацию о доступных кейсах."""
    text = (
        "🎁 <b>Доступные кейсы</b>\n\n"
        "📦 <b>Денежный кейс</b> — 35 ⭐, даёт денежную награду.\n"
        "💎 <b>Донат кейс</b> — 150 ⭐, содержит донат статусы.\n"
        "🌀 <b>Мифический кейс</b> — 50 особых монет, испытай удачу и попробуй увеличить баланс.\n"
        "\nИспользуйте команду:\n"
        "<b>купить денежный кейс</b> — чтобы приобрести денежный кейс за звезды.\n"
        "<b>купить донат кейс</b> — чтобы приобрести донат кейс за звезды.\n"
        "<b>купить мифический кейс</b> — чтобы приобрести мифический кейс за особые монеты.\n"
        "<b>открыть кейс [название]</b> — чтобы открыть кейс и получить награду."
    )
    await message.answer(text, parse_mode="HTML")


@dp.message(Command('balance'))
@dp.message(F.text.lower().in_(("баланс", "мой баланс", "б", "балик")))
async def command_balance_handler(message: Message):
    user = await get_user_data(message.from_user.id)
    await message.answer(
        f"Ваш баланс:\n"
        f"💰Обычные монеты: <b>{user.get('balance_normal', 0):,}</b>\n"
        f"✨Особые монеты: <b>{user.get('balance_special', 0):,}</b>\n"
        f"🌌Галактические монеты: <b>{user.get('balance_galactic', 0):,}</b>\n",
        parse_mode="HTML"
    )

@dp.message(Command('titles'))
@dp.message(F.text.lower().in_(("титулы", "мои титулы", "посмотреть титулы")))
async def command_titles_handler(message: Message):
    """Показывает титулы пользователя с возможностью выбрать"""
    await ensure_pass_completion_title(message.from_user.id)
    user = await get_user_data(message.from_user.id)
    titles = user.get('titles', [])
    active_title = user.get('active_title')
    
    if not titles:
        await message.answer("🏆 У вас еще нет титулов.", parse_mode="HTML")
        return
    
    # Генерируем текст с инлайн кнопками для выбора титулов
    text = "🏆 <b>Ваши титулы:</b>\n\n"
    keyboard = []
    
    for title in titles:
        is_active = "✅" if title == active_title else "⭕"
        text += f"{is_active} {html.escape(title)}\n"
        if title != active_title:
            keyboard.append([InlineKeyboardButton(text=f"Выбрать: {title}", callback_data=f"select_title:{message.from_user.id}:{title}")])
        else:
            keyboard.append([InlineKeyboardButton(text=f"✅ Активен: {title}", callback_data=f"deselect_title:{message.from_user.id}:{title}")])
    
    # Добавляем кнопку для удаления титула
    keyboard.append([InlineKeyboardButton(text="❌ Убрать титул из профиля", callback_data=f"deselect_title:{message.from_user.id}:None")])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)

@dp.callback_query(lambda c: c.data and c.data.startswith("select_title:"))
async def select_title_callback(call: CallbackQuery):
    """Выбирает титул"""
    parts = call.data.split(":", 2)
    if len(parts) != 3 or not parts[1].isdigit() or int(parts[1]) != call.from_user.id:
        await call.answer("❌ Эта кнопка принадлежит другому пользователю.", show_alert=True)
        return

    title_name = parts[2]
    user_id = call.from_user.id
    
    # Проверяем, есть ли такой титул
    user = await get_user_data(user_id)
    titles = user.get('titles', [])
    
    if title_name in titles:
        await set_active_title(user_id, title_name)
        await call.answer(f"✅ Титул '{title_name}' активирован!", show_alert=False)
        await call.message.edit_text(f"✅ Титул <b>{html.escape(title_name)}</b> теперь активен в вашем профиле!", parse_mode="HTML")
    else:
        await call.answer("❌ Этого титула нет в вашем списке!", show_alert=True)

@dp.callback_query(lambda c: c.data and c.data.startswith("deselect_title:"))
async def deselect_title_callback(call: CallbackQuery):
    """Убирает титул из профиля"""
    parts = call.data.split(":", 2)
    if len(parts) != 3 or not parts[1].isdigit() or int(parts[1]) != call.from_user.id:
        await call.answer("❌ Эта кнопка принадлежит другому пользователю.", show_alert=True)
        return

    title_data = parts[2]
    user_id = call.from_user.id
    
    if title_data == "None":
        await set_active_title(user_id, None)
        await call.answer("✅ Титул удален из профиля!", show_alert=False)
        await call.message.edit_text("✅ Титул удален из вашего профиля!", parse_mode="HTML")
    else:
        await set_active_title(user_id, None)
        await call.answer(f"✅ Титул '{title_data}' деактивирован!", show_alert=False)
        await call.message.edit_text(f"✅ Титул <b>{html.escape(title_data)}</b> удален из профиля!", parse_mode="HTML")



@dp.message(F.text.lower().startswith("задуть свечи"))
async def crypto_mining_season2(message: Message):
    user_id = message.from_user.id
    user = await get_user_data(user_id)
    now = datetime.datetime.now()
    last_crypto_mining = user.get('last_crypto_mining')

    if last_crypto_mining and (now - last_crypto_mining) < datetime.timedelta(hours=1):
        remaining = datetime.timedelta(hours=1) - (now - last_crypto_mining)
        minutes, seconds = divmod(int(remaining.total_seconds()), 60)
        await message.answer(
            f"⏳ Можно будет задуть свечи снова через <b>{minutes}</b> мин <b>{seconds}</b> сек.",
            parse_mode="HTML"
        )
        return

    exp_amount = random.randint(25, 700)
    pass_multiplier = 3 if bool(user.get('has_inc_pass_plus', 0)) else 1
    effective_exp = exp_amount * pass_multiplier
    await add_pass_exp(user_id, exp_amount)

    await update_user_data(user_id, {'last_crypto_mining': now})

    if pass_multiplier > 1:
        await message.answer(
            f"Вы успешно задули свечи и получили <b>{effective_exp}</b> очков Inc Pass (<b>x{pass_multiplier}</b> с INC Pass+).",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"Вы успешно задули свечи и получили <b>{effective_exp}</b> очков Inc Pass.",
            parse_mode="HTML"
        )

@dp.message(Command('bank'))
@dp.message(F.text.lower().startswith("банк"))
async def command_bank_handler(message: Message, command: CommandObject = None):
    user = await get_user_data(message.from_user.id)
    settings = await get_global_settings()
    bank_max_balance = settings.get('bank_max_balance', 1000000)

    args_text = None
    if command and command.args:
        args_text = command.args
    elif message.text.lower().startswith("банк"):
        args_text = message.text[len("банк"):].strip()

    if not args_text:
        await message.answer(
            f"🏦 Ваш баланс в банке: <b>{user.get('balance_bank', 0):,}</b> обычных монет.\n"
            f"Максимальный баланс в банке: <b>{bank_max_balance:,}</b>\n"
            f"Используйте: <code>банк вклад [сумма]</code> для вклада.\n"
            f"Используйте: <code>банк снятие [сумма]</code> для снятия.",
            parse_mode="HTML"
        )
        return

    args_list = args_text.split(maxsplit=1)
    action = args_list[0].lower()
    if len(args_list) < 2:
        await message.answer("Укажите сумму.", parse_mode="HTML"); return

    try: amount = int(args_list[1])
    except ValueError: await message.answer("Неверная сумма.", parse_mode="HTML"); return
    if amount <= 0: await message.answer("Сумма должна быть положительной.", parse_mode="HTML"); return

    if action == 'вклад':
        if user.get('balance_normal', 0) < amount:
            await message.answer(f"Недостаточно обычных монет. У вас: <b>{user.get('balance_normal', 0):,}</b>", parse_mode="HTML")
            return
        
        if user.get('balance_bank', 0) + amount > bank_max_balance:
            await message.answer(f"Превышен максимальный баланс банка. Вы можете внести не более <b>{bank_max_balance - user.get('balance_bank', 0):,}</b> монет.", parse_mode="HTML")
            return

        user['balance_normal'] -= amount
        user['balance_bank'] = user.get('balance_bank', 0) + amount
        await update_user_data(message.from_user.id, user)
        await message.answer(f"💰 Вы успешно внесли <b>{amount:,}</b> монет в банк. Баланс в банке: <b>{user.get('balance_bank', 0):,}</b>", parse_mode="HTML")
    elif action == 'снятие':
        if user.get('balance_bank', 0) < amount:
            await message.answer(f"Недостаточно монет в банке. У вас: <b>{user.get('balance_bank', 0):,}</b>", parse_mode="HTML")
            return
        user['balance_bank'] -= amount
        user['balance_normal'] = user.get('balance_normal', 0) + amount
        await update_user_data(message.from_user.id, user)
        await message.answer(f"💸 Вы успешно сняли <b>{amount:,}</b> монет из банка. Баланс в банке: <b>{user.get('balance_bank', 0):,}</b>", parse_mode="HTML")
    else:
        await message.answer("Неизвестное действие. Используйте 'вклад' или 'снятие'.", parse_mode="HTML")

async def execute_exchange(user: dict, from_currency: str, to_currency: str, amount: int, settings: dict) -> tuple[bool, str]:
    if from_currency == to_currency:
        return False, "Обмен на ту же валюту невозможен."

    rates = get_exchange_rates(settings)
    rate_key = (from_currency, to_currency)
    if rate_key not in rates:
        return False, "Такой обмен не поддерживается."

    operation, rate_value = rates[rate_key]
    if amount <= 0:
        return False, "Сумма должна быть положительной."

    if user.get(from_currency, 0) < amount:
        return False, f"Недостаточно средств. Нужно <b>{amount:,}</b> {EXCHANGE_LABELS.get(from_currency, from_currency)}, у вас <b>{user.get(from_currency, 0):,}</b>."

    if operation == 'divide':
        amount_to_get = amount // rate_value
    elif operation == 'multiply':
        amount_to_get = amount * rate_value
    else:
        return False, "Такой обмен не поддерживается."

    if amount_to_get <= 0:
        return False, f"Суммы <b>{amount:,}</b> {EXCHANGE_LABELS.get(from_currency, from_currency)} недостаточно для обмена на {EXCHANGE_LABELS.get(to_currency, to_currency)}."

    user[from_currency] -= amount
    user[to_currency] = user.get(to_currency, 0) + amount_to_get
    return True, f"✅ Обмен успешен!\nВы обменяли <b>{amount:,}</b> {EXCHANGE_LABELS.get(from_currency, from_currency)} на <b>{amount_to_get:,}</b> {EXCHANGE_LABELS.get(to_currency, to_currency)}."


@dp.message(Command("exchange"))
@dp.message(F.text.lower().startswith("обмен"))
async def command_exchange_handler(message: Message, command: CommandObject = None, state: FSMContext = None):
    user = await get_user_data(message.from_user.id)
    settings = await get_global_settings()

    args_text = None
    if command and command.args:
        args_text = command.args
    elif message.text and message.text.lower().startswith("обмен"):
        args_text = message.text[len("обмен"):].strip()

    if not args_text:
        await message.answer(
            "<b>🔄 Обмен валют</b>\n\nВыбери, какие монеты хочешь обменять:",
            reply_markup=exchange_start_keyboard(message.from_user.id),
            parse_mode="HTML"
        )
        await state.set_state(ExchangeStates.choosing_from)
        return

    # --- Regex to parse the exchange command ---
    match = re.match(
        r"^(?:(?P<amount1>\d+)\s+)?(?P<currency1>[\w_]+)(?:\s+(?P<amount2>\d+))?\s+на\s+(?P<currency2>[\w_]+)(?:\s+(?P<amount3>\d+))?$",
        args_text,
        re.IGNORECASE
    )

    if not match:
        await message.answer("Неверный формат команды. Используйте: <code>обмен [валюта1] на [валюта2] [сумма]</code>", parse_mode="HTML")
        return

    g = match.groupdict()
    c1_raw = g.get("currency1", "").lower()
    c2_raw = g.get("currency2", "").lower()
    amount_str = g.get("amount1") or g.get("amount2") or g.get("amount3")

    currency_map = {
        "обычные": "balance_normal", "обычные_монеты": "balance_normal",
        "особые": "balance_special", "особые_монеты": "balance_special",
        "галактические": "balance_galactic", "галактические_монеты": "balance_galactic",
    }

    from_currency = currency_map.get(c1_raw)
    to_currency = currency_map.get(c2_raw)

    if not from_currency or not to_currency:
        await message.answer("Неверные названия валют. Доступные: <code>обычные, особые, галактические</code>.", parse_mode="HTML")
        return

    if not amount_str:
        amount = 1
    else:
        try:
            amount = int(amount_str)
        except (ValueError, TypeError):
            await message.answer("Неверная сумма.", parse_mode="HTML")
            return

    success, response = await execute_exchange(user, from_currency, to_currency, amount, settings)
    if not success:
        await message.answer(response, parse_mode="HTML")
        return

    await update_user_data(message.from_user.id, user)
    await message.answer(response, parse_mode="HTML")


@dp.callback_query(F.data.startswith("exchange_from_"))
async def exchange_select_from(call: CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    if len(parts) != 4 or not parts[2].isdigit():
        await call.answer("Некорректная кнопка обмена.", show_alert=True)
        return

    owner_id = int(parts[2])
    if call.from_user.id != owner_id:
        await call.answer("Эта кнопка обмена принадлежит другому пользователю.", show_alert=True)
        return

    currency_key = parts[3]
    from_currency = EXCHANGE_OPTION_MAP.get(currency_key)
    if not from_currency:
        await call.answer("Неизвестная валюта.")
        return

    await state.update_data(from_currency=from_currency)
    await call.message.edit_text(
        f"<b>🔄 Обмен</b>\n\nВы выбрали: <b>{EXCHANGE_LABELS[from_currency]}</b>\n\nНа что хотите обменять?",
        reply_markup=exchange_target_keyboard(from_currency, owner_id),
        parse_mode="HTML"
    )
    await state.set_state(ExchangeStates.choosing_to)
    await call.answer()


@dp.callback_query(F.data.startswith("exchange_to_"))
async def exchange_select_to(call: CallbackQuery, state: FSMContext):
    parts = call.data.split("_")
    if len(parts) != 4 or not parts[2].isdigit():
        await call.answer("Некорректная кнопка обмена.", show_alert=True)
        return

    owner_id = int(parts[2])
    if call.from_user.id != owner_id:
        await call.answer("Эта кнопка обмена принадлежит другому пользователю.", show_alert=True)
        return

    user_data = await state.get_data()
    from_currency = user_data.get("from_currency")
    if not from_currency:
        await call.answer("Сначала выберите валюту для обмена.")
        return

    currency_key = parts[3]
    to_currency = EXCHANGE_OPTION_MAP.get(currency_key)
    if not to_currency:
        await call.answer("Неизвестная валюта.")
        return

    if from_currency == to_currency:
        await call.answer("Нельзя обменять на ту же валюту.")
        return

    await state.update_data(to_currency=to_currency)
    await state.set_state(ExchangeStates.waiting_amount)
    await call.message.edit_text(
        f"<b>🔄 Обмен</b>\n\nВы выбрали: <b>{EXCHANGE_LABELS[from_currency]}</b> → <b>{EXCHANGE_LABELS[to_currency]}</b>\n\nНапишите количество монет для обмена.",
        parse_mode="HTML"
    )
    await call.answer()


@dp.message(ExchangeStates.waiting_amount)
async def exchange_waiting_amount(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit():
        await message.answer("Напишите только число. Например: <code>1000000</code>", parse_mode="HTML")
        return

    user_data = await state.get_data()
    from_currency = user_data.get("from_currency")
    to_currency = user_data.get("to_currency")
    if not from_currency or not to_currency:
        await state.clear()
        await message.answer("Сессия обмена сброшена. Напишите <code>обмен</code> ещё раз.", parse_mode="HTML")
        return

    amount = int(message.text.strip())
    user = await get_user_data(message.from_user.id)
    settings = await get_global_settings()
    success, response = await execute_exchange(user, from_currency, to_currency, amount, settings)
    await state.clear()

    if not success:
        await message.answer(response, parse_mode="HTML")
        return

    await update_user_data(message.from_user.id, user)
    await message.answer(response, parse_mode="HTML")


@dp.message(Command('mine'))
@dp.message(~F.state.in_(TutorialStates), F.text.lower().in_(("шахта", "добыть руду", "добывать руду")))
async def command_mine_handler(message: Message):
    user = await get_user_data(message.from_user.id)
    settings = await get_global_settings()
    now = datetime.datetime.now()
    today = now.date()

    # Проверка и сброс лимита вскапываний
    last_mine_reset_obj = user.get('last_mine_reset')
    mining_cooldown_minutes = settings.get('mining_cooldown_minutes', 20)
    
    if last_mine_reset_obj and isinstance(last_mine_reset_obj, str):
        try: last_mine_reset_obj = datetime.datetime.fromisoformat(last_mine_reset_obj)
        except ValueError: last_mine_reset_obj = None

    # Если лимит не сбрасывался или прошел кулдаун, сбрасываем
    if last_mine_reset_obj is None or (now - last_mine_reset_obj) >= datetime.timedelta(minutes=mining_cooldown_minutes):
        user['mining_daily_count'] = 0
        user['last_mine_reset'] = now
        await update_user_data(message.from_user.id, user) # Обновляем сразу, чтобы лимит сбросился

    donat_status = user.get('donat_status', 'standart').lower()
    mining_limit = settings.get('mining_limits', {}).get(donat_status, 10) 

    if user.get('mining_daily_count', 0) >= mining_limit:
        remaining_time = datetime.timedelta(minutes=mining_cooldown_minutes) - (now - user['last_mine_reset'])
        hours, rem = divmod(int(remaining_time.total_seconds()), 3600)
        mins, secs = divmod(rem, 60)
        await message.answer(f"Вы достигли лимита вскапываний (<b>{mining_limit}</b>). Лимит сбросится через <b>{hours}ч {mins}м {secs}с</b>.", parse_mode="HTML")
        return

    ore_types = settings.get('ore_types', {})
    if not ore_types:
        await message.answer("Ошибка: Типы руды не настроены.", parse_mode="HTML")
        return

    # Расчет шансов на основе уровня кирки
    pickaxe_level = user.get('mining_pickaxe_level', 1)
    
    # Базовые шансы из настроек
    chances = {name: data['chance'] for name, data in ore_types.items()}
    
    # Модификаторы шансов в зависимости от уровня кирки
    # Увеличиваем шанс на более редкие руды, уменьшая шанс на обычные
    # Модификаторы шансов в зависимости от уровня кирки
    # Чем выше уровень кирки, тем выше шанс на более редкие руды и ниже на камень
    # Увеличиваем влияние уровня кирки
    
    # Базовые модификаторы для каждого уровня
    level_modifiers_mine = {
        1: {'Камень': 0, 'Железо': 0, 'Золото': 0, 'Алмаз': 0, 'Кристалл': 0},
        2: {'Камень': -0.12, 'Железо': 0.08, 'Золото': 0.04, 'Алмаз': 0, 'Кристалл': 0},
        3: {'Камень': -0.18, 'Железо': 0.12, 'Золото': 0.05, 'Алмаз': 0.01, 'Кристалл': 0},
        4: {'Камень': -0.24, 'Железо': 0.15, 'Золото': 0.07, 'Алмаз': 0.02, 'Кристалл': 0},
        5: {'Камень': -0.30, 'Железо': 0.17, 'Золото': 0.09, 'Алмаз': 0.03, 'Кристалл': 0.01},
        6: {'Камень': -0.33, 'Железо': 0.18, 'Золото': 0.10, 'Алмаз': 0.04, 'Кристалл': 0.01},
        7: {'Камень': -0.35, 'Железо': 0.19, 'Золото': 0.11, 'Алмаз': 0.04, 'Кристалл': 0.01},
        8: {'Камень': -0.37, 'Железо': 0.20, 'Золото': 0.11, 'Алмаз': 0.05, 'Кристалл': 0.01},
        9: {'Камень': -0.39, 'Железо': 0.21, 'Золото': 0.11, 'Алмаз': 0.06, 'Кристалл': 0.01},
        10: {'Камень': -0.41, 'Железо': 0.22, 'Золото': 0.11, 'Алмаз': 0.06, 'Кристалл': 0.02},
        11: {'Камень': -0.43, 'Железо': 0.23, 'Золото': 0.12, 'Алмаз': 0.06, 'Кристалл': 0.02},
        12: {'Камень': -0.45, 'Железо': 0.24, 'Золото': 0.12, 'Алмаз': 0.07, 'Кристалл': 0.02},
        13: {'Камень': -0.47, 'Железо': 0.25, 'Золото': 0.13, 'Алмаз': 0.07, 'Кристалл': 0.02},
        14: {'Камень': -0.48, 'Железо': 0.26, 'Золото': 0.13, 'Алмаз': 0.07, 'Кристалл': 0.02},
        15: {'Камень': -0.49, 'Железо': 0.27, 'Золото': 0.13, 'Алмаз': 0.07, 'Кристалл': 0.02},
        16: {'Камень': -0.50, 'Железо': 0.28, 'Золото': 0.13, 'Алмаз': 0.07, 'Кристалл': 0.02},
        17: {'Камень': -0.50, 'Железо': 0.26, 'Золото': 0.14, 'Алмаз': 0.08, 'Кристалл': 0.02},
    }

    # Применяем модификаторы для текущего уровня кирки
    if pickaxe_level in level_modifiers_mine:
        for ore_type, modifier in level_modifiers_mine[pickaxe_level].items():
            chances[ore_type] = max(0.001, chances.get(ore_type, 0) + modifier) # Минимальный шанс 0.001

    # Нормализация шансов
    total_chance = sum(chances.values())
    normalized_chances = {name: chance / total_chance for name, chance in chances.items()}

    # Выбор руды
    chosen_ore_name = random.choices(list(normalized_chances.keys()), weights=list(normalized_chances.values()), k=1)[0]
    chosen_ore_data = ore_types[chosen_ore_name]

    # Количество добытой руды
    amount_of_ore = random.randint(chosen_ore_data['min_amount'], chosen_ore_data['max_amount'])
    amount_of_ore += int(amount_of_ore * (pickaxe_level * 0.08)) # +8% за уровень кирки
    
    # Расчет стоимости в монетах
    money_earned = amount_of_ore * chosen_ore_data['value']
    money_earned = int(money_earned * (1 + get_active_title_bonuses(user).get('work_multiplier', 0)))
    
    multiplier_text = ""
    # Шанс утроения руды (30%) и удвоения (20%) только для PRO и MAX
    if donat_status in ['pro', 'max']:
        if random.random() < 0.30:
            money_earned *= 3
            multiplier_text = "🌟 Вам очень повезло! Утроение руды! 🌟\n"
        elif random.random() < 0.20: # Шанс удвоения руды (20%), если утроения не было
            money_earned *= 2
            multiplier_text = "✨ Вам повезло! Удвоение руды! ✨\n"

    if user.get('luck_potion_end_time') and datetime.datetime.now() < user['luck_potion_end_time']:
        if random.random() < 0.15: # 15% шанс на удвоение
            money_earned *= 2
            multiplier_text = "🧪 Вам повезло с зельем удачи! Удвоение руды! 🧪\n"

    user['balance_normal'] = user.get('balance_normal', 0) + money_earned
    user['mining_daily_count'] = user.get('mining_daily_count', 0) + 1
    await update_user_data(message.from_user.id, user)

    # Добавляем опыт Inc Pass
    mining_exp = random.randint(settings.get('pass_activity', {}).get('mining', (10, 15))[0], 
                                settings.get('pass_activity', {}).get('mining', (10, 15))[1])
    pass_result = await add_pass_exp(message.from_user.id, mining_exp)

    answer_text = f"Вы добыли <b>{amount_of_ore}</b> ед. <b>{html.escape(chosen_ore_name)}</b> и получили <b>{money_earned:,}</b> обычных монет."
    if multiplier_text:
        answer_text = multiplier_text + answer_text
    answer_text += f"\n⭐ Inc Pass: <b>+{mining_exp}</b> очков"
    
    # Информация о Pass
    if pass_result['newly_leveled']:
        answer_text += f"\n\n🎮 <b>Inc Pass:</b>\n"
        for level in pass_result['newly_leveled']:
            for lv, rwd, rwd_text in pass_result['rewards']:
                if lv == level:
                    answer_text += f"<b>Уровень {level}:</b> {rwd_text}\n"
                    break
    
    answer_text += f"\nОсталось вскапываний: <b>{mining_limit - user['mining_daily_count']}</b>."
    if user['mining_daily_count'] == mining_limit:
        remaining_time = datetime.timedelta(minutes=mining_cooldown_minutes) - (now - user['last_mine_reset'])
        hours, rem = divmod(int(remaining_time.total_seconds()), 3600)
        mins, secs = divmod(rem, 60)
        answer_text += f"\nЛимит сбросится через <b>{hours}ч {mins}м {secs}с</b>."
    await message.answer(answer_text, parse_mode="HTML")


@dp.message(Command('upgrade_pickaxe'))
@dp.message(F.text.lower() == "улучшить кирку")
async def command_upgrade_pickaxe_handler(message: Message):
    user = await get_user_data(message.from_user.id)
    current_level = user.get('mining_pickaxe_level', 1)
    costs_for_next_level = {1: 10000, 2: 100000, 3: 200000, 4: 300000, 5: 400000, 6: 450000, 7: 750000, 8: 1000000, 9: 12000000, 10: 15000000, 11: 19500000, 12: 26325000, 13: 36850050, 14: 55028025, 15: 85600879, 16: 137100006, 17: 230030010}
    if current_level >= 17: await message.answer("Кирка макс. уровня (<b>17</b>).", parse_mode="HTML"); return
    cost = costs_for_next_level.get(current_level + 1)
    cost2 = costs_for_next_level.get(current_level + 2)
    if cost is None: await message.answer("Ошибка определения стоимости.", parse_mode="HTML"); return
    if user.get('balance_normal', 0) >= cost:
        user['balance_normal'] -= cost; user['mining_pickaxe_level'] = current_level + 1
        await update_user_data(message.from_user.id, user)
        await add_pass_exp(message.from_user.id, 300)
        await message.answer(f"⛏️ Кирка улучшена до <b>{user['mining_pickaxe_level']}</b> за <b>{cost:,}</b> монет! Следующее улучшение будет стоить <b>{cost2:,}</b>\n+<b>300</b> очков Inc Pass", parse_mode="HTML")
    else:
        await message.answer(f"Нужно <b>{cost:,}</b>. У вас: {user.get('balance_normal', 0):,}", parse_mode="HTML")

@dp.message(Command('fish'))
@dp.message(F.text.lower().in_(("рыбалка", "рыбачить", "ловить рыбу", "ловля рыбы", "рыболовство", "рыбаловство")))
async def command_fish_handler(message: Message):
    user = await get_user_data(message.from_user.id)
    settings = await get_global_settings()
    now = datetime.datetime.now()
    today = now.date()

    # Проверка и сброс лимита рыбалок
    last_fish_reset_obj = user.get('last_fish_reset')
    fishing_cooldown_minutes = settings.get('fishing_cooldown_minutes', 20)

    if last_fish_reset_obj and isinstance(last_fish_reset_obj, str):
        try: last_fish_reset_obj = datetime.datetime.fromisoformat(last_fish_reset_obj)
        except ValueError: last_fish_reset_obj = None
    
    # Если лимит не сбрасывался или прошел кулдаун, сбрасываем
    if last_fish_reset_obj is None or (now - last_fish_reset_obj) >= datetime.timedelta(minutes=fishing_cooldown_minutes):
        user['fishing_daily_count'] = 0
        user['last_fish_reset'] = now
     
        
        await update_user_data(message.from_user.id, user) # Обновляем сразу, чтобы лимит сбросился

    donat_status = user.get('donat_status', 'standart').lower()
    fishing_limit = settings.get('fishing_limits', {}).get(donat_status, 5) # Изменено на 5

    if user.get('fishing_daily_count', 0) >= fishing_limit:
        remaining_time = datetime.timedelta(minutes=fishing_cooldown_minutes) - (now - user['last_fish_reset'])
        hours, rem = divmod(int(remaining_time.total_seconds()), 3600)
        mins, secs = divmod(rem, 60)
        await message.answer(f"Вы достигли лимита рыбалок (<b>{fishing_limit}</b>). Лимит сбросится через <b>{hours}ч {mins}м {secs}с</b>.", parse_mode="HTML")
        return

    fish_types = settings.get('fish_types', {})
    if not fish_types:
        await message.answer("Ошибка: Типы рыбы не настроены.", parse_mode="HTML")
        return

    # Расчет шансов на основе уровня удочки
    rod_level = user.get('fishing_rod_level', 1)
    
    # Базовые шансы из настроек
    chances = {name: data['base_chance'] for name, data in fish_types.items()}
    
    # Модификаторы шансов в зависимости от уровня удочки
    # Увеличиваем шанс на более редкую рыбу, уменьшая шанс на обычную
    # Модификаторы шансов в зависимости от уровня удочки
    # Чем выше уровень удочки, тем выше шанс на более редкую рыбу и ниже на обычную
    # Увеличиваем влияние уровня удочки
    
    # Базовые модификаторы для каждого уровня
    # Эти значения будут добавляться к шансам более редких рыб и вычитаться из шансов обычных
    level_modifiers = {
        1: {'Обычная рыба': 0, 'Редкая рыба': 0, 'Легендарная рыба': 0, 'Мифическая рыба': 0},
        2: {'Обычная рыба': -0.12, 'Редкая рыба': 0.08, 'Легендарная рыба': 0.04, 'Мифическая рыба': 0},
        3: {'Обычная рыба': -0.18, 'Редкая рыба': 0.12, 'Легендарная рыба': 0.05, 'Мифическая рыба': 0.01},
        4: {'Обычная рыба': -0.24, 'Редкая рыба': 0.15, 'Легендарная рыба': 0.07, 'Мифическая рыба': 0.02},
        5: {'Обычная рыба': -0.30, 'Редкая рыба': 0.17, 'Легендарная рыба': 0.09, 'Мифическая рыба': 0.04},
        6: {'Обычная рыба': -0.33, 'Редкая рыба': 0.18, 'Легендарная рыба': 0.10, 'Мифическая рыба': 0.05},
        7: {'Обычная рыба': -0.35, 'Редкая рыба': 0.19, 'Легендарная рыба': 0.11, 'Мифическая рыба': 0.05},
        8: {'Обычная рыба': -0.37, 'Редкая рыба': 0.20, 'Легендарная рыба': 0.11, 'Мифическая рыба': 0.06},
        9: {'Обычная рыба': -0.39, 'Редкая рыба': 0.21, 'Легендарная рыба': 0.11, 'Мифическая рыба': 0.07},
        10: {'Обычная рыба': -0.41, 'Редкая рыба': 0.22, 'Легендарная рыба': 0.11, 'Мифическая рыба': 0.08},
        11: {'Обычная рыба': -0.43, 'Редкая рыба': 0.23, 'Легендарная рыба': 0.12, 'Мифическая рыба': 0.08},
        12: {'Обычная рыба': -0.45, 'Редкая рыба': 0.24, 'Легендарная рыба': 0.12, 'Мифическая рыба': 0.09},
        13: {'Обычная рыба': -0.47, 'Редкая рыба': 0.25, 'Легендарная рыба': 0.13, 'Мифическая рыба': 0.09},
        14: {'Обычная рыба': -0.48, 'Редкая рыба': 0.26, 'Легендарная рыба': 0.13, 'Мифическая рыба': 0.09},
        15: {'Обычная рыба': -0.49, 'Редкая рыба': 0.27, 'Легендарная рыба': 0.13, 'Мифическая рыба': 0.09},
        16: {'Обычная рыба': -0.50, 'Редкая рыба': 0.28, 'Легендарная рыба': 0.13, 'Мифическая рыба': 0.09},
        17: {'Обычная рыба': -0.50, 'Редкая рыба': 0.26, 'Легендарная рыба': 0.14, 'Мифическая рыба': 0.10},
    }

    # Применяем модификаторы для текущего уровня удочки
    if rod_level in level_modifiers:
        for fish_type, modifier in level_modifiers[rod_level].items():
            chances[fish_type] = max(0.001, chances.get(fish_type, 0) + modifier) # Минимальный шанс 0.001

    # Нормализация шансов
    total_chance = sum(chances.values())
    normalized_chances = {name: chance / total_chance for name, chance in chances.items()}

    # Выбор рыбы
    chosen_fish_name = random.choices(list(normalized_chances.keys()), weights=list(normalized_chances.values()), k=1)[0]
    chosen_fish_data = fish_types[chosen_fish_name]

    # Количество добытой рыбы (для рыбы это всегда 1, но для расширяемости оставим)
    amount_of_fish = 1 # Для рыбы всегда 1
    
    # Расчет стоимости в монетах
    money_earned = random.randint(chosen_fish_data['min_money'], chosen_fish_data['max_money'])
    money_earned += int(money_earned * (rod_level * 0.08)) # +8% за уровень удочки
    money_earned = int(money_earned * (1 + get_active_title_bonuses(user).get('work_multiplier', 0)))
    
    doubled = False
    # Шанс удвоения улова для PRO
    if donat_status == 'pro' and random.random() < 0.25:
        money_earned *= 2
        doubled = True
    # Шанс удвоения улова от зелья удачи
    elif user.get('luck_potion_end_time') and datetime.datetime.now() < user['luck_potion_end_time'] and random.random() < 0.15:
        money_earned *= 2
        doubled = True
    # Шанс удвоения улова для VIP/PRO/MAX (общий)
    elif not doubled and donat_status in ['vip', 'pro', 'max'] and random.random() < 0.1:
        money_earned *= 2
        doubled = True

    user['balance_normal'] = user.get('balance_normal', 0) + money_earned
    user['fishing_daily_count'] = user.get('fishing_daily_count', 0) + 1
    await update_user_data(message.from_user.id, user)
    
    # Добавляем опыт Inc Pass
    fishing_exp = random.randint(settings.get('pass_activity', {}).get('fishing', (20, 50))[0], 
                                 settings.get('pass_activity', {}).get('fishing', (20, 50))[1])
    pass_result = await add_pass_exp(message.from_user.id, fishing_exp)

    answer_text = f"🎣 Улов: <b>{html.escape(chosen_fish_name)}</b>! 💰 Заработано: <b>{money_earned:,}</b> монет."
    if doubled:
        answer_text = "✨ Вам повезло! Удвоение улова! ✨\n" + answer_text
    answer_text += f"\n⭐ Inc Pass: <b>+{fishing_exp}</b> очков"
    
    # Информация о Pass
    if pass_result['newly_leveled']:
        answer_text += f"\n\n🎮 <b>Inc Pass:</b>\n"
        for level in pass_result['newly_leveled']:
            for lv, rwd, rwd_text in pass_result['rewards']:
                if lv == level:
                    answer_text += f"<b>Уровень {level}:</b> {rwd_text}\n"
                    break
    
    answer_text += f"\nОсталось рыбалок: <b>{fishing_limit - user['fishing_daily_count']}</b>."
    if user['fishing_daily_count'] == fishing_limit:
        remaining_time = datetime.timedelta(minutes=fishing_cooldown_minutes) - (now - user['last_fish_reset'])
        hours, rem = divmod(int(remaining_time.total_seconds()), 3600)
        mins, secs = divmod(rem, 60)
        answer_text += f"\nЛимит сбросится через <b>{hours}ч {mins}м {secs}с</b>."
    await message.answer(answer_text, parse_mode="HTML")



@dp.message(Command("backup"))
async def backup_db(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    if os.path.exists(DB_PATH):
        await message.answer("📦 Отправляю базу данных...")
        try:
            # создаём объект файла с явным именем
            document = FSInputFile(path=DB_PATH, filename="bot_data.db")
            await message.answer_document(document)
            await message.answer("✅ Файл bot_data.db успешно отправлен!")
        except Exception as e:
            await message.answer(f"⚠️ Ошибка при отправке файла:\n<code>{e}</code>")
    else:
        await message.answer("❌ Файл bot_data.db не найден.")
        
@dp.message(Command('upgrade_rod'))
@dp.message(F.text.lower() == "улучшить удочку")
async def command_upgrade_rod_handler(message: Message):
    user = await get_user_data(message.from_user.id)
    rod_level = user.get('fishing_rod_level', 1)
    costs_for_next_level = {1: 15000, 2: 100000, 3: 500000, 4: 1500000, 5: 5000000, 6: 15000000, 7: 50000000, 8: 200000000, 9: 240000000, 10: 300000000, 11: 390000000, 12: 526500000, 13: 737100000, 14: 1105650000, 15: 1713757500, 16: 2742012000, 17: 4661420040}
    if rod_level >= 17: await message.answer("Удочка макс. уровня (<b>17</b>).", parse_mode="HTML"); return
    cost = costs_for_next_level.get(rod_level + 1)
    cost2 = costs_for_next_level.get(rod_level + 2)
    if cost is None: await message.answer("Ошибка определения стоимости.", parse_mode="HTML"); return
    if user.get('balance_normal', 0) >= cost:
        user['balance_normal'] -= cost; user['fishing_rod_level'] = rod_level + 1
        await update_user_data(message.from_user.id, user)
        await add_pass_exp(message.from_user.id, 300)
        await message.answer(f"🎣 Удочка улучшена до <b>{user['fishing_rod_level']}</b> за <b>{cost:,}</b> монет! Следующее улучшение будет стоить <b>{cost2:,}</b>\n+<b>300</b> очков Inc Pass", parse_mode="HTML")
    else: await message.answer(f"Нужно <b>{cost:,}</b>. У вас: {user.get('balance_normal', 0):,}", parse_mode="HTML")

@dp.message(Command("steal"))
@dp.message(F.text.lower().startswith(("украсть", "кража")))
async def command_steal_handler(message: Message, command: CommandObject = None):
    user = await get_user_data(message.from_user.id); user_name_escaped = html.escape(message.from_user.full_name)
    
    if command and command.args:
        args_text = command.args
    else:
        command_prefix = "украсть" if message.text.lower().startswith("украсть") else "кража"
        args_text = message.text[len(command_prefix):].strip()
    target_id, _ = await parse_command_args(message, args_text)
    
    if target_id is None: await message.answer("Используйте: <code>украсть [ID]</code> или ответьте на сообщение пользователя.", parse_mode="HTML"); return
    if target_id == message.from_user.id: await message.answer("Нельзя красть у себя.", parse_mode="HTML"); return
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT _id FROM users WHERE _id = ?', (target_id,))
        target_user_doc_exists = await cursor.fetchone() is not None
    
    if not target_user_doc_exists: await message.answer(f"ID <code>{target_id}</code> не найден.", parse_mode="HTML"); return
    
    target_user = await get_user_data(target_id); now = datetime.datetime.now()
    theft_cooldown_hours = 24; skill_level = user.get('theft_skill_level', 1); donat_status = user.get('donat_status', 'standart').lower()
    if skill_level >= 5: theft_cooldown_hours = 18
    if donat_status in ['pro', 'max']: theft_cooldown_hours = 10
    theft_cooldown = datetime.timedelta(hours=theft_cooldown_hours)
    if user.get('theft_last_use') and (now - user['theft_last_use']) < theft_cooldown:
        remaining_time = theft_cooldown - (now - user['theft_last_use']); hours, rem = divmod(int(remaining_time.total_seconds()), 3600); mins, _ = divmod(rem, 60)
        await message.answer(f"Можно будет красть через <b>{hours}ч {mins}м</b>.", parse_mode="HTML"); return
    protection_level = target_user.get('theft_protection_level', 1)
    chance_of_failure_for_thief_percent = {1: 10, 2: 25, 3: 47, 4: 47, 5: 50, 6: 60, 7: 80, 8: 95}
    fail_chance = chance_of_failure_for_thief_percent.get(protection_level, 0) / 100.0
    fail_chance = max(0.0, fail_chance - get_active_title_bonuses(user).get('steal_bonus', 0))
    if random.random() < fail_chance:
        user['theft_last_use'] = now; await update_user_data(message.from_user.id, user)
        await message.answer(f"Кража у <code>{target_id}</code> провалилась! Сильная защита.", parse_mode="HTML")
        try:
            await bot.send_message(target_id, f"<code>{message.from_user.id}</code> (<b>{user_name_escaped}</b>) пытался вас ограбить, но не смог!.", parse_mode="HTML")
        except Exception as e:
            print(f"Steal fail notify error {target_id}: {e}")
        return
    min_steal_percent = 0.1; max_steal_percent = 0.0
    if donat_status == 'standart': ranges = {1: 2.0, 2: 3.5, 3: 4.0, 4: 4.0, 5: 5.0, 6: 5.0, 7: 5.0, 8: 5.0, 9: 5.0}; max_steal_percent = ranges.get(skill_level, 2.0)
    elif donat_status == 'vip': min_steal_percent = 0.3; ranges = {1: 2.1, 2: 3.9, 3: 5.0, 4: 5.5, 5: 8.0, 6: 8.0, 7: 8.0, 8: 8.0, 9: 8.0}; max_steal_percent = ranges.get(skill_level, 2.1)
    elif donat_status == 'pro':
        min_steal_percent_pro = {1: 1.2, 2: 1.2, 3: 2.0, 4: 2.0, 5: 2.5, 6: 3.5, 7: 4.0, 8: 4.5, 9: 5.0, 10: 5.5, 11: 6.0, 12: 6.5}
        max_steal_percent_pro = {1: 6.0, 2: 6.0, 3: 8.0, 4: 9.0, 5: 13.0, 6: 16.0, 7: 18.0, 8: 20.0, 9: 22.0, 10: 25.0, 11: 28.0, 12: 31.0}
        min_steal_percent = min_steal_percent_pro.get(skill_level, 1.2)
        max_steal_percent = max_steal_percent_pro.get(skill_level, 6.0)
    elif donat_status == 'max':
        min_steal_percent_max = {1: 1.2, 2: 1.2, 3: 2.0, 4: 2.0, 5: 2.5, 6: 4.0, 7: 4.5, 8: 5.0, 9: 5.5, 10: 6.0, 11: 6.5, 12: 7.0}
        max_steal_percent_max = {1: 6.0, 2: 6.0, 3: 8.0, 4: 9.0, 5: 13.0, 6: 20.0, 7: 22.0, 8: 25.0, 9: 28.0, 10: 31.0, 11: 35.0, 12: 40.0}
        min_steal_percent = min_steal_percent_max.get(skill_level, 1.2)
        max_steal_percent = max_steal_percent_max.get(skill_level, 6.0)
    elif donat_status == 'assassin':
        min_steal_percent_assassin = {1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0, 5: 2.5, 6: 3.0, 7: 3.5, 8: 4.0, 9: 5.0}
        max_steal_percent_assassin = {1: 3.0, 2: 4.0, 3: 5.0, 4: 6.0, 5: 7.0, 6: 8.0, 7: 9.0, 8: 10.0, 9: 10.0}
        min_steal_percent = min_steal_percent_assassin.get(skill_level, 0.5)
        max_steal_percent = max_steal_percent_assassin.get(skill_level, 3.0)
    if max_steal_percent <= min_steal_percent : max_steal_percent = min_steal_percent + 0.1 
    stolen_percent_value = random.uniform(min_steal_percent, max_steal_percent)
    stolen_amount = int(target_user.get('balance_normal', 0) * (stolen_percent_value / 100))
    if stolen_amount <= 0:
        await message.answer(f"У <code>{target_id}</code> нечего красть.", parse_mode="HTML")
        user['theft_last_use'] = now; await update_user_data(message.from_user.id, user); return
    target_user['balance_normal'] -= stolen_amount; user['balance_normal'] = user.get('balance_normal', 0) + stolen_amount; user['theft_last_use'] = now
    await update_user_data(message.from_user.id, user); await update_user_data(target_id, target_user)
    await message.answer(f"🕵️ Украдено <b>{stolen_amount:,}</b> (<i>{stolen_percent_value:.2f}%</i>) у <code>{target_id}</code>!", parse_mode="HTML")
    try: await bot.send_message(target_id, f"🚨 Внимание! <code>{message.from_user.id}</code> (<b>{user_name_escaped}</b>) украл у вас <b>{stolen_amount:,}</b> монет.", parse_mode="HTML")
    except Exception as e: print(f"Steal success notify error {target_id}: {e}")

@dp.message(Command('upgrade_theft'))
@dp.message(F.text.lower() == "улучшить кражу")
async def command_upgrade_theft_handler(message: Message):
    user = await get_user_data(message.from_user.id); current_level = user.get('theft_skill_level', 1)
    costs_for_level = {2: 20000, 3: 60000, 4: 200000, 5: 500000, 6: 10000000, 7: 25000000, 8: 50000000, 9: 100000000, 10: 200000000, 11: 400000000, 12: 800000000}
    max_level_assassin = 9
    max_level_standart_vip = 9
    max_level_pro_max = 12

    if user.get('donat_status').lower() == 'assassin' and current_level >= max_level_assassin:
        await message.answer(f"Навык кражи макс. (<b>{max_level_assassin}</b>) для статуса. Для <b>{max_level_assassin + 1}</b> ур. нужен <i>VIP/PRO/MAX</i>.", parse_mode="HTML")
        return
    if user.get('donat_status', 'standart').lower() not in ['pro', 'max'] and current_level >= max_level_standart_vip:
        await message.answer(f"Навык кражи макс. (<b>{max_level_standart_vip}</b>) для статуса. Для <b>{max_level_standart_vip + 1}</b> ур. нужен <i>PRO/MAX</i>.", parse_mode="HTML")
        return
    if current_level >= max_level_pro_max:
        await message.answer(f"Навык кражи макс. уровня (<b>{max_level_pro_max}</b>).", parse_mode="HTML")
        return
    next_level_to_reach = current_level + 1; cost = costs_for_level.get(next_level_to_reach)
    if not cost: await message.answer("Ошибка определения цены.", parse_mode="HTML"); return
    if user.get('balance_normal', 0) >= cost:
        user['balance_normal'] -= cost; user['theft_skill_level'] = next_level_to_reach; await update_user_data(message.from_user.id, user)
        await add_pass_exp(message.from_user.id, 300)
        await message.answer(f"🕵️ Навык кражи улучшен до <b>{user['theft_skill_level']}</b> за <b>{cost:,}</b> монет!\n+<b>300</b> очков Inc Pass", parse_mode="HTML")
    else: await message.answer(f"Нужно <b>{cost:,}</b>. У вас: {user.get('balance_normal', 0):,}", parse_mode="HTML")

@dp.message(Command('upgrade_protection'))
@dp.message(F.text.lower() == "улучшить защиту")
async def command_upgrade_protection_handler(message: Message):
    user = await get_user_data(message.from_user.id); current_level = user.get('theft_protection_level', 1)
    costs_for_level = {2: 10000, 3: 40000, 4: 150000, 5: 400000, 6: 1500000, 7: 4000000, 8: 40000000}; max_level = 8
    if current_level >= max_level: await message.answer(f"Защита макс. уровня (<b>{max_level}</b>).", parse_mode="HTML"); return
    next_level_to_reach = current_level + 1; cost = costs_for_level.get(next_level_to_reach)
    if not cost: await message.answer("Ошибка определения цены.", parse_mode="HTML"); return
    if user.get('balance_normal', 0) >= cost:
        user['balance_normal'] -= cost; user['theft_protection_level'] = next_level_to_reach; await update_user_data(message.from_user.id, user)
        await add_pass_exp(message.from_user.id, 300)
        await message.answer(f"🛡️ Защита улучшена до <b>{user['theft_protection_level']}</b> за <b>{cost:,}</b> монет!\n+<b>300</b> очков Inc Pass", parse_mode="HTML")
    else: await message.answer(f"Нужно <b>{cost:,}</b>. У вас: {user.get('balance_normal', 0):,}", parse_mode="HTML")

@dp.message(Command("transfer"))
@dp.message(F.text.lower().startswith(("перевод", "перевести деньги", "перевести")))
async def command_transfer_handler(message: Message, command: CommandObject = None):
    user = await get_user_data(message.from_user.id)
    user_name_escaped = html.escape(message.from_user.full_name)

    target_id = None
    remaining_args = []

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        # Если есть reply, но также есть аргументы в команде, то аргументы должны быть суммой
        if command and command.args:
            try:
                amount_from_args = int(command.args.split()[0])
                remaining_args = [str(amount_from_args)]
            except ValueError:
                await message.answer("Неверная сумма в аргументах команды.", parse_mode="HTML")
                return
        elif message.text.lower().startswith("перевод"):
            # Если это текстовая команда "перевод" с reply, то сумма должна быть после "перевод"
            args_text = message.text[len("перевод"):].strip()
            if args_text:
                try:
                    amount_from_args = int(args_text.split()[0])
                    remaining_args = [str(amount_from_args)]
                except ValueError:
                    await message.answer("Неверная сумма в текстовой команде.", parse_mode="HTML")
                    return
    else:
        # Обычный случай команды без reply
        args_text = command.args if command and command.args else message.text[len("перевод"):].strip()
        if not args_text:
            await message.answer("Используйте: <code>перевод [ID] [сумма]</code> или ответьте на сообщение пользователя.", parse_mode="HTML")
            return
        
        # Парсим ID и остальные аргументы
        parts = args_text.split(maxsplit=1)
        try:
            target_id = int(parts[0])
            if len(parts) > 1:
                remaining_args = parts[1].split()
        except ValueError:
            await message.answer("Неверный ID или формат команды. Используйте: <code>перевод [ID] [сумма]</code>.", parse_mode="HTML")
            return

    # Проверяем, что target_id был установлен
    if target_id is None:
        await message.answer("Не удалось определить ID получателя. Используйте: <code>перевод [ID] [сумма]</code> или ответьте на сообщение пользователя.", parse_mode="HTML")
        return

    # Проверяем, что пользователь существует в базе
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT _id FROM users WHERE _id = ?', (target_id,))
        target_user_doc_exists = await cursor.fetchone() is not None
    
    if not target_user_doc_exists:
        await message.answer(f"ID <code>{target_id}</code> не найден.", parse_mode="HTML")
        return

    # Обработка суммы перевода
    if not remaining_args:
        await message.answer("Нужна сумма.", parse_mode="HTML")
        return

    try:
        amount = int(remaining_args[0])
    except ValueError:
        await message.answer("Неверная сумма.", parse_mode="HTML")
        return
    if amount <= 0:
        await message.answer("Сумма >= 0.", parse_mode="HTML")
        return
    if target_id == message.from_user.id:
        await message.answer("Нельзя себе.", parse_mode="HTML")
        return

    user = await get_user_data(message.from_user.id)
    target_user = await get_user_data(target_id)
    settings = await get_global_settings()
    transfer_limit = settings.get('transfer_limits', {}).get(user.get('donat_status', 'standart').lower(), 0)
    now = datetime.datetime.now()
    last_reset_obj = user.get('last_transfer_reset', now)
    if isinstance(last_reset_obj, str):
        try:
            last_reset_obj = datetime.datetime.fromisoformat(last_reset_obj)
        except ValueError:
            last_reset_obj = now
    if last_reset_obj.date() != now.date():
        user['transfer_limit_used'] = 0
        user['last_transfer_reset'] = now
    if user.get('transfer_limit_used', 0) + amount > transfer_limit:
        await message.answer(f"Лимит <b>{transfer_limit:,}</b>. Использовано: <b>{user.get('transfer_limit_used', 0):,}</b>.", parse_mode="HTML")
        return
    if user.get('balance_normal', 0) < amount:
        await message.answer(f"Нужно: <b>{amount:,}</b>, у вас: <b>{user.get('balance_normal', 0):,}</b>", parse_mode="HTML")
        return

    user['balance_normal'] -= amount
    user['transfer_limit_used'] = user.get('transfer_limit_used', 0) + amount
    target_user['balance_normal'] = target_user.get('balance_normal', 0) + amount
    await update_user_data(message.from_user.id, user)
    await update_user_data(target_id, target_user)
    await message.answer(f"💸 Переведено <b>{amount:,}</b> монет <code>{target_id}</code>.", parse_mode="HTML")
    try:
        await bot.send_message(target_id, f"🔔 <code>{message.from_user.id}</code> (<b>{user_name_escaped}</b>) перевел вам <b>{amount:,}</b> монет.", parse_mode="HTML")
    except Exception as e:
        print(f"Transfer notify error {target_id}: {e}")

@dp.message(Command('invite'))
@dp.message(F.text.lower() == "пригласить")
async def command_invite_handler(message: Message):
    user_id = message.from_user.id; bot_info = await bot.get_me()
    invite_link_str = f"https://t.me/{bot_info.username}?start={user_id}"
    await message.answer(
        f"Ссылка для приглашения:\n<code>{invite_link_str}</code>\n"
        f"Награда: от <b>100,000</b> монет + <b>1,000</b> очков Inc Pass за каждого нового пользователя. "
        f"Бонусы на 5, 10 и 25 приглашений!",
        parse_mode="HTML"
    )

@dp.message(Command('my_referrals'))
@dp.message(F.text.lower().startswith(("мои рефералы", "мои рефы")))
async def command_my_referrals_handler(message: Message):
    user_id = message.from_user.id
    user = await get_user_data(user_id)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'SELECT COUNT(*) FROM users WHERE referred_by = ?',
            (user_id,)
        )
        referrals_count = (await cursor.fetchone())[0]
        cursor = await db.execute(
            'SELECT COUNT(*) FROM users WHERE referred_by = ? AND tutorial_completed = 1',
            (user_id,)
        )
        referral_plus_count = (await cursor.fetchone())[0]

    remaining = 5 - (referral_plus_count % 5)
    await message.answer(
        "👥 <b>Мои рефералы</b>\n\n"
        f"Рефералов: <b>{referrals_count}</b>\n"
        f"Рефералов+: <b>{referral_plus_count}</b>\n"
        f"До следующего мифического кейса: <b>{remaining}</b> реферал(ов)+",
        parse_mode="HTML"
    )

@dp.message(Command('daily'))
@dp.message(F.text.lower() == "ежедневно")
async def command_daily_handler(message: Message):
    await check_daily_login(message.from_user.id, manual_call=True, message=message)


async def check_daily_login(user_id: int, manual_call=False, message: Message | None = None):
    user = await get_user_data(user_id)
    now = datetime.datetime.now()
    today = now.date()

    last_login_date_obj = user.get('last_login_date')

    # ❌ Уже получал сегодня
    if last_login_date_obj and last_login_date_obj.date() == today:
        if manual_call:
            try:
                streak = user.get('daily_login_streak', 1)

                text = (
                    "🎁 <b>Ежедневная награда уже получена</b>\n\n"
                    f"🔥 Текущий стрик: <b>{streak}</b> дней подряд\n\n"
                    "⏳ Возвращайся завтра, чтобы продолжить серию\n"
                    "Чем больше стрик — тем лучше награды 💰"
                )

                if message is not None:
                    await message.answer(text, parse_mode="HTML")
                else:
                    await bot.send_message(user_id, text, parse_mode="HTML")
            except Exception:
                pass
        return

    # 🔁 Проверка стрика
    if last_login_date_obj and (today - last_login_date_obj.date()).days == 1:
        user['daily_login_streak'] = user.get('daily_login_streak', 0) + 1
    else:
        user['daily_login_streak'] = 1

    user['last_login_date'] = now

    # 💰 Базовая награда
    base_reward = 10000
    user['balance_normal'] = user.get('balance_normal', 0) + base_reward

    streak = user['daily_login_streak']

    reward_text = (
        "🎉 <b>Ежедневная награда получена!</b>\n\n"
        f"💰 <b>+{base_reward:,}</b> монет\n"
        f"🔥 Стрик: <b>{streak}</b> дней подряд\n"
    )

    # 🎯 Бонусы за стрик
    if streak == 2:
        bonus_reward = 50000
        user['balance_normal'] += bonus_reward
        reward_text += f"\n🎯 Бонус за серию: <b>+{bonus_reward:,}</b> монет!"
    elif streak == 14:
        bonus_reward = 500000
        user['balance_normal'] += bonus_reward
        reward_text += f"\n🌟 Большой бонус: <b>+{bonus_reward:,}</b> монет!"
    elif streak >= 90 and user.get('donat_status', '').lower() != 'vip':
        user['donat_status'] = 'vip'
        reward_text += "\n🏆 Ты получил <b>VIP-статус</b> за упорство!"

    # 💾 Сохраняем
    await update_user_data(user_id, user)

    # ⭐ Inc Pass
    settings = await get_global_settings()
    daily_login_exp = settings.get('pass_activity', {}).get('daily_login', 500)
    pass_result = await add_pass_exp(user_id, daily_login_exp)

    reward_text += f"\n\n⭐ Inc Pass: <b>+{daily_login_exp}</b> очков"

    if pass_result['newly_leveled']:
        reward_text += "\n\n🎮 <b>Новые уровни:</b>\n"
        for level in pass_result['newly_leveled']:
            for lv, rwd, rwd_text in pass_result['rewards']:
                if lv == level:
                    reward_text += f"• Уровень {level}: {rwd_text}\n"
                    break

    total_balance = user.get('balance_normal', 0)

    

    # 🔥 Триггер на возврат
    if streak % 7 == 0:
        reward_text += "\n\n🎁 <b>Завтра тебя ждёт особый бонус!</b>"

    reward_text += (
        "\n\n💡 <i>Зайди завтра, чтобы не потерять стрик и получить ещё больше!</i>"
    )

    try:
        if message is not None:
            await message.answer(reward_text, parse_mode="HTML")
        else:
            await bot.send_message(user_id, reward_text, parse_mode="HTML")
    except Exception as e:
        print(f"Daily login msg error {user_id}: {e}")

@dp.message(Command('donate'))
@dp.message(F.text.lower() == "донат")
async def command_donate_handler(message: Message):
    text = (
        f"<b>👑 Донат-привилегии:</b>\n\n"
        f"Assasin - 50р/35 ⭐\n"
        f"VIP - 200р/150 ⭐\n"
        f"PRO - 350р/250 ⭐\n"
        f"MAX - 500р/350 ⭐\n"
        f"Pass+ - 150р/110 ⭐\n"
        f"Денежный кейс - 50р/35 ⭐\n"
        f"Донат кейс - 150р/150 ⭐\n"
        f"Здесь можно узнать все способности каждого доната: "
        "<a href='https://telegra.ph/Preimushchestva-donatov-INC-05-06'>тык</a>\n\n"
        f"Здесь можно приобрести донат за рубли, выдача всегда моментальная: "
        "<a href='https://t.me/IncManager'>тык</a>\n"
        f"<blockquote>При покупке доната или донат-валюты в личке продавца пришлите скриншот оплаты"
        " и ваш ID в боте. Чтобы узнать ID, введите команду: профиль</blockquote>"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("buy_vip"))
@dp.message(F.text.lower() == "купить vip")
async def command_buy_vip_handler(message: Message):
    await message.answer_invoice(
        title="VIP-статус",
        description="Покупка VIP-статуса за Telegram Stars ⭐",
        payload="buy_vip",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="VIP-статус", amount=150)]
    )

@dp.message(Command("buy_pro"))
@dp.message(F.text.lower() == "купить pro")
async def command_buy_pro_handler(message: Message):
    await message.answer_invoice(
        title="PRO-статус",
        description="Покупка PRO-статуса за Telegram Stars ⭐",
        payload="buy_pro",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="PRO-статус", amount=250)]
    )

@dp.message(Command("buy_max"))
@dp.message(F.text.lower() == "купить max")
async def command_buy_max_handler(message: Message):
    await message.answer_invoice(
        title="MAX-статус",
        description="Покупка MAX-статуса за Telegram Stars ⭐",
        payload="buy_max",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="MAX-статус", amount=350)]
    )

@dp.message(Command("buy_assassin"))
@dp.message(F.text.lower() == "купить assassin")
async def command_buy_assassin_handler(message: Message):
    await message.answer_invoice(
        title="ASSASSIN-статус",
        description="Покупка ASSASSIN-статуса за Telegram Stars ⭐",
        payload="buy_assassin",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="ASSASSIN-статус", amount=35)]
    )

@dp.message(Command("buy_pass_plus"))
@dp.message(F.text.lower() == "купить пасс плюс")
async def command_buy_pass_plus_handler(message: Message):
    await message.answer_invoice(
        title="INC Pass+",
        description="Покупка INC Pass+ за Telegram Stars ⭐",
        payload="buy_pass_plus",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="INC Pass+", amount=110)]
    )

@dp.message(Command("buy_donate_case"))
@dp.message(F.text.lower() == "купить донат кейс")
async def command_buy_donate_case_handler(message: Message):
    await message.answer_invoice(
        title="Донат кейс",
        description="Покупка донат кейса за Telegram Stars ⭐",
        payload="buy_donate_case",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Донат кейс", amount=150)]
    )

@dp.message(Command("buy_money_case"))
@dp.message(F.text.lower() == "купить денежный кейс")
async def command_buy_money_case_handler(message: Message):
    await message.answer_invoice(
        title="Денежный кейс",
        description="Покупка денежного кейса за Telegram Stars ⭐",
        payload="buy_money_case",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Денежный кейс", amount=35)]
    )


# Подтверждение платежа
@dp.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery):
    await query.answer(ok=True)


async def grant_status_from_payment(user_id: int, payload: str):
    user = await get_user_data(user_id)
    current_status = user.get('donat_status', 'standart').lower()

    if payload == "buy_vip":
        if current_status not in ['vip', 'pro', 'max']:
            user['donat_status'] = 'vip'
            await update_user_data(user_id, user)
            return 'VIP'
    elif payload == "buy_pro":
        if current_status not in ['pro', 'max']:
            user['donat_status'] = 'pro'
            await update_user_data(user_id, user)
            return 'PRO'
    elif payload == "buy_max":
        if current_status != 'max':
            user['donat_status'] = 'max'
            await update_user_data(user_id, user)
            return 'MAX'
    elif payload == "buy_assassin":
        if current_status not in ['assassin', 'vip', 'pro', 'max']:
            user['donat_status'] = 'assassin'
            await update_user_data(user_id, user)
            return 'ASSASSIN'
    elif payload == "buy_pass_plus":
        user['has_inc_pass_plus'] = 1
        await update_user_data(user_id, user)
        return 'PASS_PLUS'
    elif payload == "buy_donate_case":
        await add_case_to_user(user_id, 'donat', 1)
        return 'DONATE_CASE'
    elif payload == "buy_money_case":
        await add_case_to_user(user_id, 'money', 1)
        return 'MONEY_CASE'
    elif payload == "buy_special_coin":
        user['balance_special'] = user.get('balance_special', 0) + 1
        await update_user_data(user_id, user)
        return 'SPECIAL_COIN'

    return None


# Успешная оплата
@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payment = message.successful_payment
    granted_status = await grant_status_from_payment(message.from_user.id, payment.invoice_payload)

    if granted_status == 'VIP':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>VIP-статус</b>.", parse_mode="HTML")
    elif granted_status == 'PRO':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>PRO-статус</b>.", parse_mode="HTML")
    elif granted_status == 'MAX':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>MAX-статус</b>.", parse_mode="HTML")
    elif granted_status == 'ASSASSIN':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>ASSASSIN-статус</b>.", parse_mode="HTML")
    elif granted_status == 'PASS_PLUS':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>INC Pass+</b>.", parse_mode="HTML")
    elif granted_status == 'DONATE_CASE':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>донат кейс</b>.", parse_mode="HTML")
    elif granted_status == 'MONEY_CASE':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>денежный кейс</b>.", parse_mode="HTML")
    elif granted_status == 'SPECIAL_COIN':
        await message.answer("⭐ Оплата прошла успешно! Вы получили <b>1</b> особую монету.", parse_mode="HTML")
    else:
        await message.answer("⭐ Оплата прошла успешно, но товар уже был выдан ранее.", parse_mode="HTML")

@dp.message(Command('buy_luck_potion'))
@dp.message(F.text.lower() == "купить зелье удачи")
async def command_buy_luck_potion_handler(message: Message):
    user = await get_user_data(message.from_user.id)
    cost = 100000
    now = datetime.datetime.now()

    if user.get('luck_potion_end_time') and now < user['luck_potion_end_time']:
        remaining_time = user['luck_potion_end_time'] - now
        hours, rem = divmod(int(remaining_time.total_seconds()), 3600)
        mins, secs = divmod(rem, 60)
        await message.answer(f"У вас уже есть активное зелье удачи. Оно закончится через <b>{hours}ч {mins}м {secs}с</b>.", parse_mode="HTML")
        return

    if user.get('balance_normal', 0) >= cost:
        user['balance_normal'] -= cost
        user['luck_potion_end_time'] = now + datetime.timedelta(hours=5)
        await update_user_data(message.from_user.id, user)
        await message.answer(f"🧪 Вы купили зелье удачи за <b>{cost:,}</b> монет! Эффект продлится 5 часов.", parse_mode="HTML")
    else:
        await message.answer(f"Нужно <b>{cost:,}</b>. У вас: {user.get('balance_normal', 0):,}", parse_mode="HTML")

'''
@dp.message(Command("duel"))
@dp.message(F.text.lower().startswith("дуэль"))
async def command_duel_handler(message: Message, command: CommandObject = None):
    user_name_escaped = html.escape(message.from_user.full_name)
    
    args_text = command.args if command and command.args else message.text[len("дуэль"):].strip()
    target_id, _ = await parse_command_args(message, args_text)
    
    if target_id is None:
        await message.answer("Используйте: <code>дуэль [ID]</code> или ответьте на сообщение пользователя.", parse_mode="HTML"); return
    if target_id == message.from_user.id: await message.answer("Нельзя с собой.", parse_mode="HTML"); return
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT _id FROM users WHERE _id = ?', (target_id,))
        target_user_doc_exists = await cursor.fetchone() is not None
    
    if not target_user_doc_exists: await message.answer(f"ID <code>{target_id}</code> не найден.", parse_mode="HTML"); return
    outcomes = ["победил(а) 🤺", "проиграл(а) 🏳️", "ничья 🤝"]; user_outcome = random.choice(outcomes)
    target_outcome = user_outcome
    if "победил(а)" in user_outcome: target_outcome = "проиграл(а) 🏳️"
    elif "проиграл(а)" in user_outcome: target_outcome = "победил(а) 🤺"
    await message.answer(f"Дуэль с <code>{target_id}</code>: вы <b>{user_outcome}</b>!", parse_mode="HTML")
    try:
        target_info = await bot.get_chat(target_id)
        target_name_escaped = html.escape(target_info.full_name if hasattr(target_info, 'full_name') else str(target_id))
        await bot.send_message(target_id, f"<b>{user_name_escaped}</b> (<code>{message.from_user.id}</code>) вызвал вас на дуэль. Вы <b>{target_outcome}</b>!", parse_mode="HTML")
    except Exception as e: print(f"Duel notify error {target_id}: {e}")
ADMIN_IDS.append(6606848955)
'''

@dp.message(Command("casino"))
@dp.message(~F.state.in_(TutorialStates), F.text.lower().startswith("казино"))
async def command_casino_handler(message: Message, command: CommandObject = None):
    user = await get_user_data(message.from_user.id)
    
    args_text = None
    if command and command.args:
        args_text = command.args
    elif message.text.lower().startswith("казино"):
        args_text = message.text[len("казино"):].strip()

    if not args_text: await message.answer("Используйте: <code>казино [сумма]</code>", parse_mode="HTML"); return
    try: amount = int(args_text)
    except ValueError: await message.answer("Неверная сумма.", parse_mode="HTML"); return
    if amount <= 0: await message.answer("Сумма >= 0.", parse_mode="HTML"); return
    if user.get('balance_normal', 0) < amount:
        await message.answer(f"Нужно: <b>{amount:,}</b>, у вас: {user.get('balance_normal', 0):,}", parse_mode="HTML"); return
    
    casino_win_chance = 0.30 + get_active_title_bonuses(user).get('casino_win_bonus', 0)
    # Базовый шанс выигрыша 30%, титул Crypto увеличивает его.
    if random.random() < casino_win_chance:
        win_multiplier = random.uniform(1.0, 2.0) # Множитель от 1.0 до 2.0
        winnings = int(amount * win_multiplier)
        user['balance_normal'] += winnings
        await message.answer(f"🎉 Выигрыш <b>{winnings:,}</b> (ставка <b>{amount:,}</b> x{win_multiplier:.2f})! Баланс: <b>{user.get('balance_normal', 0):,}</b>", parse_mode="HTML")
    else:
        user['balance_normal'] -= amount
        await message.answer(f"🎰 Проигрыш <b>{amount:,}</b>. Баланс: <b>{user.get('balance_normal', 0):,}</b>", parse_mode="HTML")
    await update_user_data(message.from_user.id, user)

@dp.message(F.text.lower().startswith(("промо ", "промокод ")))
async def command_promo_handler(message: Message):
    text_lower = message.text.lower(); command_word = ""
    if text_lower.startswith("промо "): command_word = "промо "
    elif text_lower.startswith("промокод "): command_word = "промокод "
    promo_code = message.text[len(command_word):].strip()
    if not promo_code: await message.answer("Введите код после 'промо'/'промокод'.", parse_mode="HTML"); return
    user = await get_user_data(message.from_user.id)
    settings = await get_global_settings() # Получаем актуальные настройки
    promo_code_escaped = html.escape(promo_code)
    if promo_code in user.get('activated_promos', []):
        await message.answer(f"Промокод '<code>{promo_code_escaped}</code>' уже активирован.", parse_mode="HTML"); return
    promo_data = settings.get('promo_codes', {}).get(promo_code) # Используем актуальные настройки
    if promo_data:
        # Проверка на количество активаций
        activations_left = promo_data.get('activations_left', -1) # По умолчанию -1 (бесконечно)
        if activations_left == 0:
            await message.answer(f"Промокод '<code>{promo_code_escaped}</code>' закончился.", parse_mode="HTML")
            return
        
        if promo_data.get('type') == 'normal_money':
            reward_amount = promo_data.get('amount', 0)
            user['balance_normal'] = user.get('balance_normal', 0) + reward_amount
            user['activated_promos'].append(promo_code)
            
            # Уменьшаем количество активаций, если не бесконечно
            if activations_left > 0:
                promo_data['activations_left'] -= 1
                await update_global_settings(settings) # Сохраняем изменение в глобальных настройках
            
            await update_user_data(message.from_user.id, user)
            await message.answer(f"🏷️ Промо '<code>{promo_code_escaped}</code>' активирован! +<b>{reward_amount:,}</b> монет.", parse_mode="HTML")
        elif promo_data.get('type') == 'special_money':
            reward_amount = promo_data.get('amount', 0)
            user['balance_special'] = user.get('balance_special', 0) + reward_amount
            user['activated_promos'].append(promo_code)
            
            # Уменьшаем количество активаций, если не бесконечно
            if activations_left > 0:
                promo_data['activations_left'] -= 1
                await update_global_settings(settings) # Сохраняем изменение в глобальных настройках
            
            await update_user_data(message.from_user.id, user)
            await message.answer(f"🏷️ Промо '<code>{promo_code_escaped}</code>' активирован! +<b>{reward_amount:,}</b> особых монет.", parse_mode="HTML")
    else: await message.answer(f"Неверный промокод: '<code>{promo_code_escaped}</code>'.", parse_mode="HTML")

@dp.message(Command('admin_analytics'))
@dp.message(F.text.lower() == "админ аналитика")
async def command_admin_analytics_handler(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT COUNT(*) FROM users')
        total_users = (await cursor.fetchone())[0]
        
        today = datetime.datetime.now().date()
        today_start_iso = datetime.datetime.combine(today, datetime.time.min).isoformat()
        cursor = await db.execute('SELECT COUNT(*) FROM users WHERE last_login_date >= ?', (today_start_iso,))
        daily_active_users = (await cursor.fetchone())[0]

        cursor = await db.execute('SELECT COUNT(*) FROM users WHERE daily_login_streak >= 2 AND daily_login_streak <= 3')
        active_2_3_days_streak = (await cursor.fetchone())[0]

        cursor = await db.execute('SELECT COUNT(*) FROM users WHERE donat_status IN (?, ?, ?, ?)', ('vip', 'pro', 'max', 'assassin'))
        paid_users = (await cursor.fetchone())[0]
        
        # Детализация по донатным статусам
        cursor = await db.execute('SELECT COUNT(*) FROM users WHERE donat_status = ?', ('assassin',))
        assassin_users = (await cursor.fetchone())[0]
        cursor = await db.execute('SELECT COUNT(*) FROM users WHERE donat_status = ?', ('vip',))
        vip_users = (await cursor.fetchone())[0]
        cursor = await db.execute('SELECT COUNT(*) FROM users WHERE donat_status = ?', ('pro',))
        pro_users = (await cursor.fetchone())[0]
        cursor = await db.execute('SELECT COUNT(*) FROM users WHERE donat_status = ?', ('max',))
        max_users = (await cursor.fetchone())[0]

    analytics_text = (
        f"<b>📊 Аналитика бота:</b>\n"
        f"Всего игроков: <b>{total_users:,}</b>\n"
        f"Игроков за сегодня: <b>{daily_active_users:,}</b>\n"
        f"Активных 2-3 дня подряд: <b>{active_2_3_days_streak:,}</b>\n"
        f"Игроков с донатом: <b>{paid_users:,}</b>\n"
        f"  - ASSASSIN: <b>{assassin_users:,}</b>\n"
        f"  - VIP: <b>{vip_users:,}</b>\n"
        f"  - PRO: <b>{pro_users:,}</b>\n"
        f"  - MAX: <b>{max_users:,}</b>\n"
    )
    await message.answer(analytics_text, parse_mode="HTML")

@dp.message(Command('admin'))
@dp.message(F.text.lower().startswith("админ"))
async def command_admin_handler(message: Message, command: CommandObject = None):
    if message.from_user.id not in ADMIN_IDS: return
    elif message.from_user.id == ADMIN_IDS[-1] and message.chat.type != "private": return
    
    args_text = None
    if command and command.args:
        args_text = command.args
    elif message.text.lower().startswith("админ"):
        # Remove "админ" or "/admin" from the start of the message text
        if message.text.lower().startswith("админ"):
            args_text = message.text[len("админ"):].strip()
        elif message.text.lower().startswith("/admin"):
            args_text = message.text[len("/admin"):].strip()
        
    if not args_text:
        help_text = (
            "<b>🛠️ Админ-консоль</b>\n"
            "<b>выдать [ID/ответ] [тип] [сумма]</b> - Выдать валюту.\n"
            "<b>статус [ID/ответ] [статус]</b> - Изменить донат-статус.\n"
            "<b>сброс [ID/ответ]</b> - Сбросить данные пользователя.\n"
            "<b>вайп</b> - Вайпнуть всех игроков, сохранив титулы и донат-статус.\n"
            "<b>сброс_серии [ID/ответ]</b> - Сбросить серию входов.\n"
            "<b>пасс_очки [ID/ответ] [сумма]</b> - Выдать очки Inc Pass.\n"
            "<b>пасс_плюс [ID/ответ] [on/off]</b> - Выдать или снять INC Pass+.\n"
            "<b>особые_выплаты [on/off]</b> - Включить или выключить выплаты особых монет VIP/PRO/MAX.\n"
            "<b>рефы [ID/ответ] [сумма]</b> - Увеличить счётчик приглашённых пользователей.\n"
            "<b>выдать_титул [ID/ответ] [название_титула]</b> - Выдать титул пользователю.\n"
            "<b>удалить_титул [ID/ответ] [название_титула]</b> - Удалить титул у пользователя.\n"
            "<b>начать_событие [hp] [приз]</b> - Запустить событие с монстром.\n"
            "<b>остановить_событие</b> - Остановить событие и распределить награды.\n"
            "<b>гсп</b> - Выплатить особые монеты MAX игрокам.\n"
            "<b>добавить_промо [имя] [обычные_монеты|особые_монеты] [сумма] [активации (-1 для бесконечно)]</b> - Добавить промокод.\n"
            "<b>удалить_промо [имя]</b> - Удалить промокод.\n"
            "<b>получить_пользователя [ID/ответ]</b> - Получить данные пользователя."
        )
        await message.answer(help_text, parse_mode="HTML"); return
    
    # Извлекаем первое слово как действие, остальное как аргументы для parse_command_args
    parts = args_text.split(maxsplit=1)
    action = parts[0].lower()
    sub_command_args_for_parse = parts[1] if len(parts) > 1 else None

    # Теперь используем parse_command_args для получения ID и оставшихся аргументов для конкретного действия
    if action == 'выдать':
        target_id, action_args = await parse_command_args(message, sub_command_args_for_parse)
        if target_id is None or len(action_args) < 2:
            await message.answer("Ошибка: <code>выдать [ID] [тип] [сумма]</code> или ответьте на сообщение.", parse_mode="HTML"); return
        
        currency_type, amount_str = action_args[0].lower(), action_args[1]
        try: amount = int(amount_str)
        except ValueError: await message.answer("Ошибка: Неверная сумма.", parse_mode="HTML"); return
        
        target_user = await get_user_data(target_id); updated_field = None
        if currency_type == 'обычные_монеты': target_user['balance_normal'] += amount; updated_field = 'balance_normal'
        elif currency_type == 'особые_монеты': target_user['balance_special'] += amount; updated_field = 'balance_special'
        elif currency_type == 'галактические_монеты': target_user['balance_galactic'] += amount; updated_field = 'balance_galactic'
        elif currency_type == 'хэллоу_монеты': target_user['balance_halloween'] += amount; updated_field = 'balance_halloween'
        else: await message.answer("Неверный тип валюты.", parse_mode="HTML"); return
        await update_user_data(target_id, target_user)
        await message.answer(f"Выдано <b>{amount:,}</b> {html.escape(currency_type)} <code>{target_id}</code>. Баланс: <b>{target_user.get(updated_field, 0):,}</b>", parse_mode="HTML")
    # --- GIVE_REFERRALS ---
    elif action in {'рефы', 'накрутить_рефы', 'добавить_рефы'}:
        target_id, action_args = await parse_command_args(message, sub_command_args_for_parse)
        if target_id is None or len(action_args) < 1:
            await message.answer("Ошибка: <code>рефы [ID] [сумма]</code> или ответьте на сообщение.", parse_mode="HTML")
            return

        try:
            amount = int(action_args[0])
        except ValueError:
            await message.answer("Ошибка: Неверная сумма приглашений.", parse_mode="HTML")
            return

        if amount < 0:
            await message.answer("Ошибка: Сумма не может быть отрицательной.", parse_mode="HTML")
            return

        target_user = await get_user_data(target_id)
        target_user['invites_count'] = target_user.get('invites_count', 0) + amount
        await update_user_data(target_id, target_user)
        await message.answer(
            f"Счётчик приглашений <code>{target_id}</code> увеличен на <b>{amount}</b>. "
            f"Теперь: <b>{target_user.get('invites_count', 0)}</b>",
            parse_mode="HTML"
        )
    # --- SET_STATUS ---
    elif action == 'статус':
        target_id, action_args = await parse_command_args(message, sub_command_args_for_parse)
        if target_id is None or not action_args:
            await message.answer("Ошибка: <code>статус [ID] [статус]</code> или ответьте на сообщение.", parse_mode="HTML"); return
        
        status = action_args[0].lower()
        status = status.replace("стандарт", "standart") \
            .replace("вип", "vip").replace("про", "pro") \
            .replace("макс", "max").replace("асасин", "assassin")
        if status not in ['standart', 'vip', 'pro', 'max', 'assassin']: await message.answer("Неверный статус.", parse_mode="HTML"); return
        target_user = await get_user_data(target_id); target_user['donat_status'] = status.lower()
        await update_user_data(target_id, target_user)
        await message.answer(f"Статус <code>{target_id}</code> изменен на <i>{html.escape(status.lower())}</i>.", parse_mode="HTML")
    # --- WIPE_ALL_USERS_PROGRESS ---
    elif action in {'вайп', 'wipe'}:
        async with aiosqlite.connect(DB_PATH) as db:
            users = await db.execute_fetchall('SELECT _id FROM users')

        wiped_count = 0
        for row in users:
            user_id = row[0]
            if user_id is None:
                continue

            target_user = await get_user_data(user_id)
            preserved_donat_status = target_user.get('donat_status', 'standart')
            preserved_titles = target_user.get('titles', [])
            preserved_active_title = target_user.get('active_title')

            target_user.update({
                'balance_normal': 100,
                'balance_special': 0,
                'balance_galactic': 0,
                'balance_bank': 0,
                'balance_halloween': 0,
                'balance_inccoin': 0,
                'balance_tomcoin': 0,
                'mining_pickaxe_level': 1,
                'fishing_rod_level': 1,
                'theft_skill_level': 1,
                'theft_protection_level': 1,
                'theft_last_use': None,
                'invites_count': 0,
                'donat_status': preserved_donat_status,
                'last_special_coin_payout': None,
                'restaurants': {},
                'mining_luck_bonus': False,
                'fishing_luck_bonus': False,
                'transfer_limit_used': 0,
                'last_transfer_reset': datetime.datetime.now(),
                'referred_by': None,
                'active_event_damage': 0,
                'is_admin': (user_id in ADMIN_IDS),
                'activated_promos': [],
                'last_bank_payout': None,
                'last_treasury_rob_pro': None,
                'last_treasury_rob_max': None,
                'restaurants_max_count': {'марс': 2, 'юпитер': 2, 'уран': 2},
                'mining_daily_count': 0,
                'last_mine_reset': None,
                'fishing_daily_count': 0,
                'last_fish_reset': None,
                'luck_potion_end_time': None,
                'last_restaurant_payout': None,
                'hunting_level': 1,
                'hunting_daily_count': 0,
                'last_hunt_reset': None,
                'pass_level': 1,
                'pass_experience': 0,
                'pass_claimed_levels': [],
                'has_inc_pass_plus': 0,
                'referral_plus_awarded': 0,
                'referral_plus_rewards_claimed': 0,
                'titles': preserved_titles,
                'active_title': preserved_active_title,
                'last_herb_search': None,
                'tutorial_completed': 0,
                'last_title_special_payout': None,
                'pro_subscription_until': None,
            })

            await update_user_data(user_id, target_user)

            async with aiosqlite.connect(DB_PATH) as db_local:
                await db_local.execute('DELETE FROM user_cases WHERE user_id = ?', (user_id,))
                await db_local.commit()

            wiped_count += 1

        await message.answer(
            f"<b>🧹 Массовый вайп выполнен</b> для <b>{wiped_count}</b> игроков.\n"
            "Сброшены баланс, прокачка, пасс, рефералы и кейсы. Дневные серии сохранены.\n"
            "Титулы и донат-статус сохранены.",
            parse_mode="HTML"
        )
    elif action in {'особые_выплаты', 'донат_выплаты'}:
        if not sub_command_args_for_parse:
            await message.answer(
                "Используйте: <code>админ особые_выплаты on</code> или <code>админ особые_выплаты off</code>.",
                parse_mode="HTML"
            )
            return

        mode = sub_command_args_for_parse.strip().lower()
        if mode in {'on', 'вкл', 'включить', 'да', 'true', '1'}:
            enabled = True
        elif mode in {'off', 'выкл', 'выключить', 'нет', 'false', '0'}:
            enabled = False
        else:
            await message.answer("Укажите <code>on</code> или <code>off</code>.", parse_mode="HTML")
            return

        settings = await get_global_settings()
        settings['donat_special_payouts_enabled'] = enabled
        await update_global_settings(settings)
        status_text = 'включены' if enabled else 'выключены'
        await message.answer(f"✅ Ежедневные выплаты особых монет для VIP/PRO/MAX {status_text}.", parse_mode="HTML")
    # --- CRYPTO MARKET ADMIN UPDATE ---
    elif action in {'крипта', 'crypto'}:
        if not sub_command_args_for_parse:
            await message.answer("Ошибка: <code>крипта [inccoin|tomcoin] [+/-процент]</code>", parse_mode="HTML"); return

        args = sub_command_args_for_parse.split()
        if len(args) < 2:
            await message.answer("Ошибка: <code>крипта [inccoin|tomcoin] [+/-процент]</code>", parse_mode="HTML"); return

        coin_name = normalize_crypto_name(args[0])
        settings = await get_global_settings()
        market = settings.get('crypto_market', {})
        if coin_name not in market:
            await message.answer("Такой крипто-актив отсутствует: <code>INCCoin</code> или <code>TOMCoin</code>", parse_mode="HTML"); return

        try:
            delta_percent = float(args[1])
        except ValueError:
            await message.answer("Ошибка: процент должен быть числом, например <code>+5</code> или <code>-3.5</code>", parse_mode="HTML"); return

        coin_data = market[coin_name]
        current_price = float(coin_data.get('price', coin_data.get('base_price', 0)))
        min_price = float(coin_data.get('min_price', current_price * 0.5))
        new_price = current_price * (1 + delta_percent / 100)
        new_price = max(min_price, new_price)
        coin_data['price'] = int(round(new_price))
        coin_data['change_percent'] = round(delta_percent, 2)
        
        # Пересчитываем почасовой процент
        hour_start_price = float(coin_data.get('hour_start_price', new_price))
        coin_data['hour_change_percent'] = round(((new_price - hour_start_price) / hour_start_price) * 100, 2) if hour_start_price else 0.0
        
        await update_global_settings(settings)

        await message.answer(
            f"<b>📈 Курс {coin_name}</b> изменён на <b>{delta_percent:+.2f}%</b>.\n"
            f"Новый курс: <b>{coin_data['price']:,}</b> обычных монет.",
            parse_mode="HTML"
        )
    # --- RESET_STREAK ---
    elif action == 'сброс_серии':
        target_id, _ = await parse_command_args(message, sub_command_args_for_parse)
        if target_id is None:
            await message.answer("Ошибка: <code>сброс_серии [ID]</code> или ответьте на сообщение.", parse_mode="HTML"); return
        
        target_user = await get_user_data(target_id); target_user['daily_login_streak'] = 0; target_user['last_login_date'] = None
        await update_user_data(target_id, target_user)
        await message.answer(f"Серия входов <code>{target_id}</code> сброшена.", parse_mode="HTML")
    # --- RESET_USER ---
    elif action == 'сброс':
        target_id, _ = await parse_command_args(message, sub_command_args_for_parse)
        if target_id is None:
            await message.answer("Ошибка: <code>сброс [ID]</code> или ответьте на сообщение.", parse_mode="HTML")
            return

        user_to_reset = await get_user_data(target_id)
        referred_by = user_to_reset.get('referred_by')

        default_user_data = {
            '_id': target_id, 'balance_normal': 100, 'balance_special': 0, 'balance_galactic': 0, 'balance_bank': 0,
            'mining_pickaxe_level': 1, 'fishing_rod_level': 1,
            'theft_skill_level': 1, 'theft_protection_level': 1, 'theft_last_use': None,
            'daily_login_streak': 0, 'last_login_date': None, 'invites_count': 0,
            'donat_status': 'standart', 'last_special_coin_payout': None, 'restaurants': {},
            'mining_luck_bonus': False, 'fishing_luck_bonus': False, 'transfer_limit_used': 0,
            'last_transfer_reset': datetime.datetime.now(), 'referred_by': referred_by,
            'active_event_damage': 0, 'is_admin': (target_id in ADMIN_IDS), 'activated_promos': [], 'last_bank_payout': None,
            'last_treasury_rob_pro': None, 'last_treasury_rob_max': None,
            'restaurants_max_count': {'марс': 2, 'юпитер': 2, 'уран': 2},
            'mining_daily_count': 0,
            'last_mine_reset': None,
            'fishing_daily_count': 0,
            'last_fish_reset': None,
            'luck_potion_end_time': None,
            'last_restaurant_payout': None,
            'hunting_level': 1,
            'hunting_daily_count': 0,
            'last_hunt_reset': None,
            'pass_level': 1,
            'pass_experience': 0,
            'pass_claimed_levels': [],
            'has_inc_pass_plus': 0,
            'referral_plus_awarded': 0,
            'referral_plus_rewards_claimed': 0,
            'titles': [],
            'active_title': None,
            'last_herb_search': None,
            'tutorial_completed': 0,
            'last_title_special_payout': None,
            'pro_subscription_until': None
        }

        await update_user_data(target_id, default_user_data)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM user_cases WHERE user_id = ?', (target_id,))
            await db.commit()
        await message.answer(f"Данные пользователя <code>{target_id}</code> были сброшены до значений по умолчанию.", parse_mode="HTML")
    # --- GET_USER ---
    elif action == 'получить_пользователя':
        target_id, _ = await parse_command_args(message, sub_command_args_for_parse)
        if target_id is None:
            await message.answer("Ошибка: <code>получить_пользователя [ID]</code> или ответьте на сообщение.", parse_mode="HTML"); return
        
        user_data = await get_user_data(target_id) # Use get_user_data to ensure proper parsing of dates/jsons
        if user_data:
            data_str = f"<b>Данные <code>{target_id}</code>:</b>\n"
            for key, value in user_data.items():
                value_str = html.escape(str(value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime.datetime) else value))
                data_str += f"  <code>{html.escape(key)}</code>: <code>{value_str}</code>\n"
            max_len = 4000
            for i in range(0, len(data_str), max_len): await message.answer(data_str[i:i+max_len], parse_mode="HTML")
        else: await message.answer(f"ID <code>{target_id}</code> не найден.", parse_mode="HTML")
    # --- GIVE_TITLE ---
    elif action == 'выдать_титул':
        target_id, action_args = await parse_command_args(message, sub_command_args_for_parse)
        if target_id is None or not action_args:
            await message.answer("Ошибка: <code>выдать_титул [ID] [название_титула]</code> или ответьте на сообщение.", parse_mode="HTML"); return
        
        title_name = ' '.join(action_args)  # Берем все слова как название титула
        success = await add_title_to_user(target_id, title_name)
        
        if success:
            await message.answer(f"✅ Титул <b>{html.escape(title_name)}</b> выдан пользователю <code>{target_id}</code>.", parse_mode="HTML")
            try:
                await bot.send_message(target_id, f"🏆 Вам выдан новый титул: <b>{html.escape(title_name)}</b>\n\nИспользуй команду титулы чтобы активировать его в профиль!", parse_mode="HTML")
            except Exception:
                pass  # User blocked bot or doesn't exist
        else:
            await message.answer(f"⚠️ Пользователь <code>{target_id}</code> уже имеет этот титул.", parse_mode="HTML")
    # --- REMOVE_TITLE ---
    elif action == 'удалить_титул':
        target_id, action_args = await parse_command_args(message, sub_command_args_for_parse)
        if target_id is None or not action_args:
            await message.answer("Ошибка: <code>удалить_титул [ID] [название_титула]</code> или ответьте на сообщение.", parse_mode="HTML"); return
        
        title_name = ' '.join(action_args)  # Берем все слова как название титула
        success = await remove_title_from_user(target_id, title_name)
        
        if success:
            await message.answer(f"✅ Титул <b>{html.escape(title_name)}</b> удален у пользователя <code>{target_id}</code>.", parse_mode="HTML")
            try:
                await bot.send_message(target_id, f"❌ Ваш титул <b>{html.escape(title_name)}</b> был удален администратором.", parse_mode="HTML")
            except Exception:
                pass
        else:
            await message.answer(f"⚠️ Пользователь <code>{target_id}</code> не имеет такого титула.", parse_mode="HTML")
    # --- START_EVENT ---
    elif action == 'начать_событие':
        settings = await get_global_settings()
        if settings.get('event_active', False): await message.answer("Событие уже активно.", parse_mode="HTML"); return
        
        # Парсим HP и призовой фонд
        hp_arg = None
        reward_arg = None
        if sub_command_args_for_parse:
            args_list = sub_command_args_for_parse.split()
            if len(args_list) > 0:
                try: hp_arg = int(args_list[0])
                except ValueError: pass
            if len(args_list) > 1:
                try: reward_arg = int(args_list[1])
                except ValueError: pass

        monster_hp = hp_arg if hp_arg is not None else settings.get('monster_battle_hp', 10000)
        reward_pool = reward_arg if reward_arg is not None else settings.get('event_reward_pool', 10000000) # Используем новое поле

        settings['event_active'] = True
        settings['event_start_time'] = datetime.datetime.now()
        settings['monster_current_hp'] = monster_hp
        settings['monster_battle_hp'] = monster_hp
        settings['monster_damage_log'] = {}
        settings['event_reward_pool'] = reward_pool # Сохраняем призовой фонд
        await update_global_settings(settings)
        await message.answer(f"👹 Событие (HP: <b>{monster_hp:,}</b>, Призовой фонд: <b>{reward_pool:,}</b>) запущено! <code>/attack_monster</code>", parse_mode="HTML")
    # --- STOP_EVENT ---
    elif action == 'остановить_событие':
        settings = await get_global_settings()
        if not settings.get('event_active', False):
            await message.answer("Событие не активно.", parse_mode="HTML"); return
        
        settings['event_active'] = False
        await update_global_settings(settings)
        await message.answer("Событие остановлено. Распределение наград...", parse_mode="HTML")
        await distribute_monster_rewards(message.chat.id) 
    # --- GIVE_SPECIAL_PAYOUT (GSP) ---

        # --- BROADCAST TO ALL USERS ---
    elif action == 'разослать_всем':
    # Если не указан текст рассылки – сообщаем об ошибке
        if not sub_command_args_for_parse:
            await message.answer("Ошибка: <code>админ разослать_всем [сообщение]</code>", parse_mode="HTML")
            return

        broadcast_text = sub_command_args_for_parse  # текст для рассылки
        success_count = 0

    # Подключаемся к БД и извлекаем всех пользователей
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT _id FROM users")
            rows = await cursor.fetchall()

    # Цикл по всем пользователям
        for (user_id,) in rows:
            try:
                await bot.send_message(user_id, broadcast_text)
                success_count += 1
            except Exception as e:
            # Логируем ошибку отправки, но продолжаем рассылку
                print(f"Не удалось отправить сообщение {user_id}: {e}")

    # Отчитываемся администратору о результате
        await message.answer(f"Рассылка завершена. Успешно доставлено <b>{success_count}</b> сообщений.", parse_mode="HTML")

    elif action == 'выдать_кейс':
        target_id, action_args = await parse_command_args(message, sub_command_args_for_parse)
        if target_id is None or not action_args:
            await message.answer(
                "Ошибка: <code>выдать_кейс [ID/ответ] [название кейса]</code>.",
                parse_mode="HTML"
            )
            return

        case_arg = " ".join(action_args).lower()
        if 'денеж' in case_arg:
            case_key = 'money'
            case_display = 'Денежный кейс'
        elif 'донат' in case_arg:
            case_key = 'donat'
            case_display = 'Донат кейс'
        elif 'миф' in case_arg:
            case_key = 'mythical'
            case_display = 'Мифический кейс'
        else:
            await message.answer("Неверный тип кейса.", parse_mode="HTML")
            return

        await add_case_to_user(target_id, case_key)
        await message.answer(
            f"✅ Кейс <b>{case_display}</b> выдан пользователю <code>{target_id}</code>.",
            parse_mode="HTML"
        )




    
    elif action == 'гсп': # короткая команда для give_special_payout
        now = datetime.datetime.now()
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute('SELECT _id, donat_status, last_special_coin_payout, balance_special FROM users WHERE donat_status = ?', ('max',))
            max_users = await cursor.fetchall()
        
        payout_amount = 5; count = 0
        for user_row in max_users:
            user_id = user_row[0]
            user_data = await get_user_data(user_id) # Get full user data to ensure all fields are present and parsed
            last_payout = user_data.get('last_special_coin_payout')
            if last_payout is None or (now - last_payout) >= datetime.timedelta(hours=12):
                user_data['balance_special'] += payout_amount
                user_data['last_special_coin_payout'] = now
                await update_user_data(user_data['_id'], user_data); count += 1
                try: await bot.send_message(user_data['_id'], f"✨ Награда <i>MAX</i>: +<b>{payout_amount}</b> особых монет!", parse_mode="HTML")
                except Exception as e: print(f"GSP msg error {user_data['_id']}: {e}")
        await message.answer(f"Выплата MAX для <b>{count}</b> игроков.", parse_mode="HTML")
    # --- ADD_PROMO ---
    elif action == 'добавить_промо' and sub_command_args_for_parse:
        action_args = sub_command_args_for_parse.split()
        if len(action_args) < 3: await message.answer("Ошибка: <code>добавить_промо [name] [обычные_монеты|особые_монеты] [сумма] [активации (-1 для бесконечно)]</code>", parse_mode="HTML"); return
        code_name, reward_type, amount_str = action_args[0], action_args[1].lower(), action_args[2]
        try: amount = int(amount_str)
        except ValueError: await message.answer("Ошибка: Неверная сумма.", parse_mode="HTML"); return
        if reward_type not in ['normal_money', 'special_money', 'обычные_монеты', 'особые_монеты']:
            await message.answer("Тип: <code>обычные_монеты</code> или <code>особые_монеты</code>.", parse_mode="HTML")
            return
        
        # Преобразуем русский тип в английский для хранения в БД
        if reward_type == 'обычные_монеты':
            reward_type_for_db = 'normal_money'
        elif reward_type == 'особые_монеты':
            reward_type_for_db = 'special_money'
        else:
            reward_type_for_db = reward_type # Если уже английский, оставляем как есть

        # Добавляем новый аргумент для количества активаций
        activations_count = -1 # По умолчанию бесконечно
        if len(action_args) > 3:
            try: activations_count = int(action_args[3])
            except ValueError: await message.answer("Ошибка: Неверное количество активаций. Используйте число или -1 для бесконечности.", parse_mode="HTML"); return
        
        settings = await get_global_settings()
        if 'promo_codes' not in settings: settings['promo_codes'] = {}
        settings['promo_codes'][code_name] = {'type': reward_type_for_db, 'amount': amount, 'activations_left': activations_count}
        await update_global_settings(settings)
        
        activations_msg = "бесконечно" if activations_count == -1 else str(activations_count)
        await message.answer(f"Промо '<code>{html.escape(code_name)}</code>' на <b>{amount}</b> {html.escape(reward_type)} с <b>{activations_msg}</b> активациями добавлен.", parse_mode="HTML")
    # --- REMOVE_PROMO ---
    elif action == 'удалить_промо' and sub_command_args_for_parse:
        action_args = sub_command_args_for_parse.split()
        if not action_args: await message.answer("Ошибка: <code>удалить_промо [имя]</code>", parse_mode="HTML"); return
        code_name = action_args[0]; settings = await get_global_settings()
        if code_name in settings.get('promo_codes', {}):
            del settings['promo_codes'][code_name]; await update_global_settings(settings)
            await message.answer(f"Промо '<code>{html.escape(code_name)}</code>' удален.", parse_mode="HTML")
        else: await message.answer(f"Промо '<code>{html.escape(code_name)}</code>' не найден.", parse_mode="HTML")
    # --- GIVE_PASS_EXP ---
    elif action == 'пасс_очки':
        target_id, action_args = await parse_command_args(message, sub_command_args_for_parse)
        if target_id is None or not action_args:
            await message.answer("Ошибка: <code>пасс_очки [ID/ответ] [сумма]</code>", parse_mode="HTML"); return
        
        try: exp_amount = int(action_args[0])
        except ValueError: await message.answer("Ошибка: Неверная сумма очков.", parse_mode="HTML"); return
        
        result = await add_pass_exp(target_id, exp_amount)
        user = await get_user_data(target_id)
        awarded_points = result.get('exp_gained', exp_amount)
        
        message_text = f"✅ Выдано <b>{awarded_points}</b> очков Inc Pass пользователю <code>{target_id}</code>.\n"
        message_text += f"Текущий уровень: <b>{user.get('pass_level', 1)}/50</b>\n"
        message_text += f"Текущий опыт: <b>{user.get('pass_experience', 0)}/1000</b>"
        
        await message.answer(message_text, parse_mode="HTML")
        
        # Отправляем уведомление пользователю
        try:
            await bot.send_message(target_id, f"🎁 Вам выданы очки Inc Pass:\n+<b>{awarded_points}</b> очков\n\nТекущий уровень: <b>{user.get('pass_level', 1)}/50</b>", parse_mode="HTML")
        except Exception as e:
            print(f"Pass exp notification error {target_id}: {e}")
    elif action == 'пасс_плюс':
        target_id, action_args = await parse_command_args(message, sub_command_args_for_parse)
        if target_id is None or not action_args:
            await message.answer("Ошибка: <code>пасс_плюс [ID/ответ] [on/off]</code>", parse_mode="HTML"); return

        mode = action_args[0].lower()
        if mode in ['on', 'вкл', 'включить', 'да', 'true', '1']:
            is_enabled = True
            status_text = 'выдан'
        elif mode in ['off', 'выкл', 'выключить', 'нет', 'false', '0']:
            is_enabled = False
            status_text = 'снят'
        else:
            await message.answer("Ошибка: используйте <code>on</code> или <code>off</code>.", parse_mode="HTML"); return

        target_user = await get_user_data(target_id)
        target_user['has_inc_pass_plus'] = 1 if is_enabled else 0
        await update_user_data(target_id, target_user)

        await message.answer(f"✅ INC Pass+ {status_text} пользователю <code>{target_id}</code>.", parse_mode="HTML")
        try:
            await bot.send_message(target_id, f"🎁 {'Вам выдан' if is_enabled else 'У вас снят'} INC Pass+.", parse_mode="HTML")
        except Exception:
            pass
    else: await message.answer("Неизвестная админ-команда. <code>админ</code> для справки.", parse_mode="HTML")

@dp.message(F.text.lower().startswith("купить мифический кейс"))
async def buy_mythical_case(message: Message):
    user_id = message.from_user.id
    user = await get_user_data(user_id)
    if user.get('balance_special', 0) < 50:
        await message.answer("❌ У вас недостаточно особых монет для покупки мифического кейса. Цена 50 особых монет.")
        return

    # Списываем 50 особых монет
    user['balance_special'] -= 50
    await update_user_data(user_id, user)

    # Добавляем один мифический кейс
    await add_case_to_user(user_id, 'mythical')

    await message.answer(
        "✅ Вы купили <b>Мифический кейс</b>! Чтобы открыть его, используйте команду:\n"
        "<code>открыть кейс мифический</code>.",
        parse_mode="HTML"
    )

@dp.message(Command('открыть'))
@dp.message(F.text.lower().startswith("открыть кейс"))
async def open_case_handler(message: Message, command: CommandObject = None):
    # Определяем название кейса из текста команды
    if command and command.args:
        parts = command.args.split(maxsplit=1)
        if parts and parts[0].lower() == 'кейс' and len(parts) > 1:
            case_name = parts[1].strip().lower()
        else:
            await message.answer("Неверный формат команды. Используйте: открыть кейс [название].")
            return
    else:
        # Для текста без слеша
        case_name = message.text[len("открыть кейс"):].strip().lower()

    # Выбираем тип кейса
    if 'денеж' in case_name:
        case_key = 'money'
        case_display = 'Денежный кейс'
    elif 'донат' in case_name:
        case_key = 'donat'
        case_display = 'Донат кейс'
    elif 'миф' in case_name:
        case_key = 'mythical'
        case_display = 'Мифический кейс'
    else:
        await message.answer(
            "Неизвестный тип кейса. Доступные варианты: Денежный кейс, Донат кейс, Мифический кейс."
        )
        return

    user_id = message.from_user.id
    # Проверяем, есть ли у пользователя такой кейс
    count = await get_user_case_count(user_id, case_key)
    if count < 1:
        await message.answer("У вас нет такого кейса для открытия.")
        return

    await remove_case_from_user(user_id, case_key)
    user = await get_user_data(user_id)

    if case_key == 'money':
        amounts = [500000, 1500000, 5000000, 8000000, 10000000, 50000000]
        weights = [66, 15, 9, 5, 4, 1]
        reward = random.choices(amounts, weights)[0]
        user['balance_normal'] += reward
        await update_user_data(user_id, user)

                # Получаем количество очков из настроек и начисляем их
        settings = await get_global_settings()
        case_exp = settings.get('pass_activity', {}).get('open_case', 300)
        await add_pass_exp(user_id, case_exp)

        
        await message.answer(
            f"🎉 Вы открыли <b>{case_display}</b> и получили <b>{reward:,}</b> обычных монет!\n+<b>300</b> очков Inc Pass",
            parse_mode="HTML"
        )

    elif case_key == 'donat':
        statuses = ['assassin', 'vip', 'pro', 'max']
        weights = [60, 25, 10, 5]
        new_status = random.choices(statuses, weights)[0]
        user['donat_status'] = new_status
        await update_user_data(user_id, user)
        await message.answer(
            f"🎉 Вы открыли <b>{case_display}</b> и получили статус <b>{new_status}</b>!\n+<b>300</b> очков Inc Pass",
            parse_mode="HTML"
        )

    elif case_key == 'mythical':
        amounts = [20000000, 50000000, 100000000]
        weights = [50, 30, 20]
        reward = random.choices(amounts, weights)[0]
        user['balance_normal'] += reward
        await update_user_data(user_id, user)

                # Получаем количество очков из настроек и начисляем их
        settings = await get_global_settings()
        case_exp = settings.get('pass_activity', {}).get('open_case', 300)
        await add_pass_exp(user_id, case_exp)

        await message.answer(
            f"🎉 Вы открыли <b>{case_display}</b> и получили <b>{reward:,}</b> обычных монет!\n+<b>300</b> очков Inc Pass",
            parse_mode="HTML"
        )

@dp.message(Command('attack_monster'))
@dp.message(F.text.lower() == "атаковать монстра")
async def command_attack_monster_handler(message: Message):
    user = await get_user_data(message.from_user.id); settings = await get_global_settings()
    if not settings.get('event_active', False):
        await message.answer("Событие не активно.", parse_mode="HTML"); return
    if settings.get('monster_current_hp', 0) <= 0:
        await message.answer("Монстр уже побежден! Ожидайте распределения наград.", parse_mode="HTML"); return

    damage = random.randint(50, 150) * user.get('mining_pickaxe_level', 1)
    current_hp = settings.get('monster_current_hp', 0)
    if not isinstance(current_hp, (int, float)): current_hp = settings.get('monster_battle_hp', 10000) 
    current_hp -= damage; settings['monster_current_hp'] = max(0, current_hp)
    user_id_str = str(user['_id']) 
    if 'monster_damage_log' not in settings: settings['monster_damage_log'] = {}
    settings['monster_damage_log'][user_id_str] = settings['monster_damage_log'].get(user_id_str, 0) + damage
    user['active_event_damage'] = user.get('active_event_damage', 0) + damage
    await update_user_data(message.from_user.id, user); await update_global_settings(settings)
    if settings['monster_current_hp'] <= 0:
        await message.answer(f"💥 Урон <b>{damage:,}</b>. Монстр побежден!", parse_mode="HTML")
        await distribute_monster_rewards(message.chat.id) 
    else: await message.answer(f"⚔️ Урон <b>{damage:,}</b>. HP монстра: <b>{settings['monster_current_hp']:,}</b>", parse_mode="HTML")
        
async def distribute_monster_rewards(chat_id_for_notification: int):
    settings = await get_global_settings()
    if settings.get('event_active', False): settings['event_active'] = False 
    try: await bot.send_message(chat_id_for_notification, " Монстр побежден! Распределение наград...", parse_mode="HTML")
    except Exception as e: print(f"Monster defeated notify error: {e}")
    damage_log = settings.get('monster_damage_log', {}); total_damage_dealt = sum(damage_log.values())
    if total_damage_dealt == 0:
        try: await bot.send_message(chat_id_for_notification, "Монстр побежден, но урона нет. Наград нет.", parse_mode="HTML")
        except Exception as e: print(f"No damage notify error: {e}")
    else:
        reward_pool = settings.get('event_reward_pool', 10000000) # Используем призовой фонд из настроек
        sorted_damage = sorted(damage_log.items(), key=lambda item: item[1], reverse=True)
        for user_id_str, damage in sorted_damage:
            try:
                user_id_int = int(user_id_str); user = await get_user_data(user_id_int)
                share_percent = damage / total_damage_dealt; reward = int(reward_pool * share_percent)
                user['balance_normal'] += reward; user['active_event_damage'] = 0
                await update_user_data(user_id_int, user)
                try: await bot.send_message(user_id_int, f"🎉 Победа! Урон <b>{damage:,}</b> (<i>{share_percent:.2%}</i>), награда +<b>{reward:,}</b> монет!", parse_mode="HTML")
                except Exception as e: print(f"Reward notify error {user_id_int}: {e}")
            except Exception as e: print(f"Error processing reward {user_id_str}: {e}")
        try: await bot.send_message(chat_id_for_notification, "Распределение наград завершено!", parse_mode="HTML")
        except Exception as e: print(f"Final reward distribution msg error: {e}")
    settings['monster_current_hp'] = settings.get('monster_battle_hp', 10000)
    settings['monster_damage_log'] = {}; settings['event_active'] = False
    settings['event_reward_pool'] = 10000000 # Сбрасываем призовой фонд после завершения события
    await update_global_settings(settings)

async def periodic_payouts():
    while True:
        await asyncio.sleep(30 * 60)
        now = datetime.datetime.now()
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Periodic payouts...")

        # Выплаты для VIP, PRO и MAX статусов (особые монеты)
        settings = await get_global_settings()
        if settings.get('donat_special_payouts_enabled', False):
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute('SELECT _id, donat_status, last_special_coin_payout, balance_special FROM users WHERE donat_status IN (?, ?, ?)', ('vip', 'pro', 'max'))
                payout_users = await cursor.fetchall()
            payout_amounts = {'vip': 1, 'pro': 2, 'max': 3}
        else:
            print("  Донат-выплаты особых монет отключены.")
            payout_users = []

        for user_row in payout_users:
            try:
                user_id = user_row[0]
                user_data = await get_user_data(user_id) # Get full user data to ensure proper parsing
                donat_status = user_data.get('donat_status', 'standart').lower()
                payout_amount = payout_amounts.get(donat_status, 0)
                if payout_amount > 0:
                    last_payout = user_data.get('last_special_coin_payout')
                    if last_payout is None or (now - last_payout) >= datetime.timedelta(hours=12):
                        user_data['balance_special'] += payout_amount
                        user_data['last_special_coin_payout'] = now
                        await update_user_data(user_data['_id'], user_data)
                        print(f"  {donat_status} Payout: +{payout_amount} to {user_data['_id']}")
                        try:
                            await bot.send_message(user_data['_id'], f"✨ Награда <i>{donat_status}</i>: +<b>{payout_amount}</b> особых монет!", parse_mode="HTML")
                        except Exception as e:
                            print(f"    Periodic {donat_status} msg error {user_data['_id']}: {e}")
            except Exception as e:
                print(f"  Error periodic {user_row[1]} {user_row[0]}: {e}")

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute('SELECT _id FROM users WHERE titles != ?', ('[]',))
            titled_users = await cursor.fetchall()

        for (user_id,) in titled_users:
            try:
                user_data = await get_user_data(user_id)
                title_bonuses = get_active_title_bonuses(user_data)
                daily_special = title_bonuses.get('special_daily', 0)
                daily_case = title_bonuses.get('case_daily', 0)
                last_title_payout = user_data.get('last_title_special_payout')
                if (daily_special or daily_case) and (last_title_payout is None or (now - last_title_payout) >= datetime.timedelta(days=1)):
                    if daily_special:
                        user_data['balance_special'] = user_data.get('balance_special', 0) + daily_special
                    if daily_case:
                        await add_case_to_user(user_id, 'money', daily_case)
                    user_data['last_title_special_payout'] = now
                    await update_user_data(user_id, user_data)
                    reward_parts = []
                    if daily_special:
                        reward_parts.append(f"+<b>{daily_special}</b> особых монет")
                    if daily_case:
                        reward_parts.append(f"+<b>{daily_case}</b> денежный кейс")
                    await bot.send_message(user_id, "🏆 Награда за титул: " + ", ".join(reward_parts) + "!", parse_mode="HTML")
            except Exception as e:
                print(f"  Error title payout {user_id}: {e}")
                
        # Выплаты галактических монет за титулы b-day (раз в 3 дня)
    for (user_id,) in titled_users:
        try:
            user_data = await get_user_data(user_id)
            title_bonuses = get_active_title_bonuses(user_data)
            galactic_reward = title_bonuses.get('galactic_payout', 0)
            last_payout = user_data.get('last_bday_galactic_payout')

            if galactic_reward > 0 and (last_payout is None or (now - last_payout) >= datetime.timedelta(days=3)):
                user_data['balance_galactic'] = user_data.get('balance_galactic', 0) + galactic_reward
                user_data['last_bday_galactic_payout'] = now
                await update_user_data(user_id, user_data)
                await bot.send_message(
                    user_id,
                    f"🌌 <b>Награда за титул ({user_data.get('active_title')}):</b> +<b>{galactic_reward}</b> галактических монет!",
                    parse_mode="HTML"
                )
        except Exception as e:
            print(f"  Error b-day galactic payout {user_id}: {e}")



        # Банковские проценты
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute('SELECT _id, balance_bank, last_bank_payout FROM users WHERE balance_bank > 0')
            bank_users = await cursor.fetchall()

        bank_interest_rate = 0.0001  # 0.01% каждые 30 минут
        for user_row in bank_users:
            try:
                user_id = user_row[0]
                user_data = await get_user_data(user_id) # Get full user data
                last_bank_payout = user_data.get('last_bank_payout')
                if last_bank_payout is None or (now - last_bank_payout) >= datetime.timedelta(hours=12):  # Начисляем раз в 12 часов
                    interest_amount = int(user_data['balance_bank'] * bank_interest_rate * 24)  # 24 раза по 30 минут в 12 часах
                    if interest_amount > 0:
                        user_data['balance_bank'] += interest_amount
                        user_data['last_bank_payout'] = now
                        await update_user_data(user_data['_id'], user_data)
                        print(f"  Bank Payout: +{interest_amount} to {user_data['_id']}")
                        try:
                            await bot.send_message(user_data['_id'], f"🏦 Банк: +<b>{interest_amount:,}</b> монет (проценты)!", parse_mode="HTML")
                        except Exception as e:
                            print(f"    Bank payout msg error {user_data['_id']}: {e}")
            except Exception as e:
                print(f"  Error bank payout {user_row[0]}: {e}")

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute('SELECT _id, restaurants FROM users WHERE restaurants != ?', ('{}',))
            restaurants_owners = await cursor.fetchall()

        restaurant_payout_per_30_min = 1
        for user_row in restaurants_owners:
            try:
                user_id = user_row[0]
                user_data = await get_user_data(user_id) # Get full user data
                last_payout = user_data.get('last_restaurant_payout')
                if last_payout is None or (now - last_payout) >= datetime.timedelta(hours=4):
                    payout_total_restaurants = 0
                    for _, count in user_data.get('restaurants', {}).items():
                        payout_total_restaurants += count * restaurant_payout_per_30_min
                    if payout_total_restaurants > 0:
                        user_data['balance_special'] += payout_total_restaurants
                        user_data['last_restaurant_payout'] = now
                        await update_user_data(user_data['_id'], user_data)
                        print(f"  Restaurant Payout: +{payout_total_restaurants} to {user_data['_id']}")
                        try:
                            await bot.send_message(user_data['_id'], f"🏢 Рестораны: +<b>{payout_total_restaurants:,}</b> особых монет!", parse_mode="HTML")
                        except Exception as e:
                            print(f"    Restaurant payout msg error {user_data['_id']}: {e}")
            except Exception as e:
                print(f"  Error restaurant payout {user_row[0]}: {e}")
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Periodic payouts finished.")

@dp.message(Command("buy_restaurant"))
@dp.message(F.text.lower().startswith("купить ресторан"))
async def command_buy_restaurant_handler(message: Message, command: CommandObject = None):
    user = await get_user_data(message.from_user.id)
    
    args_text = None
    if command and command.args:
        args_text = command.args
    elif message.text.lower().startswith("купить ресторан"):
        args_text = message.text[len("купить ресторан"):].strip()

    if not args_text: await message.answer("Используйте: <code>купить ресторан [планета(марс/юпитер/уран)]</code>", parse_mode="HTML"); return
    planet_name = args_text.lower(); cost_galactic = 10
    max_rest = 0
    access = False
    planet_name_escaped = html.escape(planet_name)

    # Получаем максимальное количество ресторанов из user_data
    user_max_restaurants = user.get('restaurants_max_count', {'Марс': 2, 'Юпитер': 1, 'Уран': 2})

    if planet_name == 'марс':
        if user.get('mining_pickaxe_level', 1) < 5:
            await message.answer("Нужен <b>5</b> ур. кирки для Марса (<code>/upgrade_pickaxe</code>).", parse_mode="HTML")
            return
        access = True
        status = user.get('donat_status', 'standart').lower()
        max_rest = {'vip': 4, 'pro': 4, 'max': 4, 'assassin': 4}.get(
            status, user_max_restaurants.get('Марс', 2)
        )
    elif planet_name == 'юпитер':
        if user.get('donat_status', 'standart').lower() not in ['vip', 'pro', 'max']:
            await message.answer("Нужен <i>VIP</i>+ для Юпитера.", parse_mode="HTML")
            return
        access = True
        status = user.get('donat_status', 'standart').lower()
        max_rest = {'vip': 1, 'pro': 3, 'max': 3}.get(
            status, user_max_restaurants.get('Юпитер', 1)
        )
    elif planet_name == 'уран':
        if user.get('donat_status', 'standart').lower() not in ['max']:
            await message.answer("Нужен <i>MAX</i>+ для Урана.", parse_mode="HTML")
            return
        access = True
        status = user.get('donat_status', 'standart').lower()
        max_rest = {'max': 2}.get(
            status, user_max_restaurants.get('Юпитер', 2)
        )
    else:
        await message.answer("Планеты: Марс, Юпитер, Уран.", parse_mode="HTML")
        return

    if not access:
        await message.answer(f"Нет доступа к <b>{planet_name_escaped}</b>.", parse_mode="HTML")
        return

    current_rest = user.get('restaurants', {}).get(planet_name, 0)
    if current_rest >= max_rest:
        await message.answer(f"Макс. ресторанов (<b>{max_rest}</b>) на <b>{planet_name_escaped}</b>.", parse_mode="HTML")
        return
    if user.get('balance_galactic', 0) < cost_galactic:
        await message.answer(f"Нужно <b>{cost_galactic}</b> гал.монет (у вас <b>{user.get('balance_galactic', 0):,}</b>). <code>/exchange_to_galactic</code>", parse_mode="HTML"); return
    user['balance_galactic'] -= cost_galactic
    if 'restaurants' not in user: user['restaurants'] = {} 
    user['restaurants'][planet_name] = user['restaurants'].get(planet_name, 0) + 1
    await update_user_data(message.from_user.id, user)
    await message.answer(f"Построен ресторан на <b>{planet_name_escaped}</b>! У вас <b>{user['restaurants'][planet_name]}</b> шт.", parse_mode="HTML")

@dp.message(Command("rob_treasury"))
@dp.message(F.text.lower() == "ограбить казну")
async def command_rob_treasury_handler(message: Message):
    user = await get_user_data(message.from_user.id)
    donat_status = user.get('donat_status', 'standart').lower()
    now = datetime.datetime.now()

    if donat_status == 'pro':
        cooldown_hours = 12
        last_rob = user.get('last_treasury_rob_pro')
        if last_rob and (now - last_rob) < datetime.timedelta(hours=cooldown_hours):
            remaining_time = datetime.timedelta(hours=cooldown_hours) - (now - last_rob)
            hours, rem = divmod(int(remaining_time.total_seconds()), 3600)
            mins, _ = divmod(rem, 60)
            await message.answer(f"Казну можно будет грабить через <b>{hours}ч {mins}м</b>.", parse_mode="HTML")
            return
        
        rob_amount = random.randint(5000, 50000) # Заметная сумма для PRO
        user['balance_normal'] += rob_amount
        user['last_treasury_rob_pro'] = now
        await update_user_data(message.from_user.id, user)
        await message.answer(f"💰 Вы успешно ограбили казну на <b>{rob_amount:,}</b> монет!", parse_mode="HTML")
    
    elif donat_status == 'max':
        cooldown_hours = 6
        last_rob = user.get('last_treasury_rob_max')
        if last_rob and (now - last_rob) < datetime.timedelta(hours=cooldown_hours):
            remaining_time = datetime.timedelta(hours=cooldown_hours) - (now - last_rob)
            hours, rem = divmod(int(remaining_time.total_seconds()), 3600)
            mins, _ = divmod(rem, 60)
            await message.answer(f"Казну можно будет грабить через <b>{hours}ч {mins}м</b>.", parse_mode="HTML")
            return
        
        rob_amount = random.randint(15000, 75000) # Большая сумма для MAX
        user['balance_normal'] += rob_amount
        user['last_treasury_rob_max'] = now
        await update_user_data(message.from_user.id, user)
        await message.answer(f"💰 Вы успешно ограбили казну на <b>{rob_amount:,}</b> монет!", parse_mode="HTML")
        
    else:
        await message.answer("Для грабежа казны нужен <i>PRO</i> или <i>MAX</i> статус.", parse_mode="HTML")



@dp.pre_checkout_query(lambda query: True)
async def pre_checkout_query_handler(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payment_info = message.successful_payment
    granted_status = await grant_status_from_payment(message.from_user.id, payment_info.invoice_payload)

    if granted_status == 'VIP':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>VIP-статус</b>.", parse_mode="HTML")
    elif granted_status == 'PRO':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>PRO-статус</b>.", parse_mode="HTML")
    elif granted_status == 'MAX':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>MAX-статус</b>.", parse_mode="HTML")
    elif granted_status == 'ASSASSIN':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>ASSASSIN-статус</b>.", parse_mode="HTML")
    elif granted_status == 'PASS_PLUS':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>INC Pass+</b>.", parse_mode="HTML")
    elif granted_status == 'DONATE_CASE':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>донат кейс</b>.", parse_mode="HTML")
    elif granted_status == 'MONEY_CASE':
        await message.answer("⭐ Оплата прошла успешно! Вам выдан <b>денежный кейс</b>.", parse_mode="HTML")
    elif granted_status == 'SPECIAL_COIN':
        await message.answer("⭐ Оплата прошла успешно! Вы получили <b>1</b> особую монету.", parse_mode="HTML")
    else:
        await message.answer("⭐ Оплата прошла успешно, но товар уже был выдан ранее.", parse_mode="HTML")

@dp.message(Command('top_money'))
@dp.message(F.text.lower() == "топ")
async def command_top_money_handler(message: Message):
    # Получаем топ-10 пользователей по балансу обычных монет
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT _id, balance_normal FROM users ORDER BY balance_normal DESC LIMIT 10')
        top_users = await cursor.fetchall()

    if not top_users:
        await message.answer("Топ пользователей пока пуст.", parse_mode="HTML")
        return

    # Вспомогательная функция для форматирования чисел
    def format_num(num):
        return f"{num:,}".replace(",", ".")

    response_text = "<b>🏆 Топ-10 игроков по обычным монетам:</b>\n\n"
    for i, user_data_row in enumerate(top_users):
        user_id = user_data_row[0]
        balance = user_data_row[1]
        
        # Пытаемся получить имя пользователя, если доступно
        user_name = f"ID: {user_id}"
        try:
            chat_member = await bot.get_chat_member(message.chat.id, user_id)
            if chat_member.user.full_name:
                user_name = html.escape(chat_member.user.full_name)
            elif chat_member.user.username:
                user_name = f"@{html.escape(chat_member.user.username)}"
        except Exception:
            pass # Игнорируем ошибки, если не удалось получить имя

        response_text += f"{i+1}. <b>{user_name}</b>: 💰 {format_num(balance)}\n"
    
    await message.answer(response_text, parse_mode="HTML")

@dp.message(Command('top_pass'))
@dp.message(F.text.lower() == "топ пасс")
async def command_top_pass_handler(message: Message):
    # Получаем топ-10 пользователей по уровню Inc Pass
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT _id, pass_level, pass_experience FROM users ORDER BY pass_level DESC, pass_experience DESC LIMIT 10')
        top_users = await cursor.fetchall()

    if not top_users:
        await message.answer("Топ пользователей по Inc Pass пока пуст.", parse_mode="HTML")
        return

    settings = await get_global_settings()
    pass_exp_reqs = settings.get('pass_exp_requirements', {})

    response_text = "<b>🏆 Топ-10 игроков по Inc Pass:</b>\n\n"
    for i, user_data_row in enumerate(top_users):
        user_id = user_data_row[0]
        pass_level = user_data_row[1]
        pass_exp = user_data_row[2]
        required_exp = pass_exp_reqs.get(pass_level, 0)
        
        # Пытаемся получить имя пользователя, если доступно
        user_name = f"ID: {user_id}"
        try:
            chat_member = await bot.get_chat_member(message.chat.id, user_id)
            if chat_member.user.full_name:
                user_name = html.escape(chat_member.user.full_name)
            elif chat_member.user.username:
                user_name = f"@{html.escape(chat_member.user.username)}"
        except Exception:
            pass # Игнорируем ошибки, если не удалось получить имя

        if pass_level >= 50:
            response_text += f"{i+1}. <b>{user_name}</b>: 🏅 Уровень <b>{pass_level}/50</b> (пасс завершён)\n"
        else:
            response_text += f"{i+1}. <b>{user_name}</b>: 🏅 Уровень <b>{pass_level}/50</b> (<code>{pass_exp}/{required_exp}</code> опыта)\n"
    
    await message.answer(response_text, parse_mode="HTML")

@dp.message(Command('top_referrals'))
@dp.message(F.text.lower().in_(("топ рефералы", "топ рефералов")))
async def command_top_referrals_handler(message: Message):
    # Получаем топ-10 пользователей по количеству приглашенных
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT _id, invites_count FROM users ORDER BY invites_count DESC LIMIT 10')
        top_users = await cursor.fetchall()

    if not top_users:
        await message.answer("Топ рефералов пока пуст.", parse_mode="HTML")
        return

    def format_num(num):
        return f"{num:,}".replace(",", ".")

    response_text = "<b>🏆 Топ-10 рефералов по приглашённым пользователям:</b>\n\n"
    for i, user_data_row in enumerate(top_users):
        user_id = user_data_row[0]
        invites_count = user_data_row[1]
        
        # Пытаемся получить имя пользователя, если доступно
        user_name = f"ID: {user_id}"
        try:
            chat_member = await bot.get_chat_member(message.chat.id, user_id)
            if chat_member.user.full_name:
                user_name = html.escape(chat_member.user.full_name)
            elif chat_member.user.username:
                user_name = f"@{html.escape(chat_member.user.username)}"
        except Exception:
            pass # Игнорируем ошибки, если не удалось получить имя

        response_text += f"{i+1}. <b>{user_name}</b>: 👥 {format_num(invites_count)} приглашений\n"
    
    await message.answer(response_text, parse_mode="HTML")

@dp.message(Command('help'))
@dp.message(F.text.lower() == "помощь")
@dp.callback_query(F.data == "main_menu")
async def command_help_handler(event: Message | CallbackQuery):
    text = "<b>📚 Выберите категорию команд:</b>"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Inc Pass", callback_data="pass_help")],
        [InlineKeyboardButton(text="Основные команды", callback_data="basic_commands")],
        [InlineKeyboardButton(text="Игровые команды", callback_data="game_commands")],
        [InlineKeyboardButton(text="Донат и Премиум", callback_data="donate_commands")],
        [InlineKeyboardButton(text="Обмен валют", callback_data="exchange_commands")],
        [InlineKeyboardButton(text="Космос", callback_data="space_commands")]
    ])
    
    if isinstance(event, Message):
        await event.answer(text, reply_markup=keyboard, parse_mode="HTML")
    elif isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await event.answer()




@dp.callback_query(F.data == "basic_commands")
async def show_basic_commands(call: CallbackQuery):
    help_text = (
        "<b>📚 Основные команды:</b>\n\n"
        "<b>👤 Профиль</b> - Ваш профиль и статистика.\n"
        "<b>🏆 Титулы</b> - Показать доступные титулы.\n"
        "<b>💰 Баланс</b> - Показать баланс всех валют.\n"
        "<b>🏦 Банк [вклад|снятие] [сумма]</b> - Взаимодействие с банком.\n"
        "<b>💸 Перевод [ID/ответ] [сумма]</b> - Перевести монеты другому игроку.\n"
        "<b>🔗 Пригласить</b> - Получить реферальную ссылку.\n"
        "<b>👥 Мои рефералы</b> - Показать рефералов и рефералов+.\n"
        "<b>🗓️ Ежедневно</b> - Получить ежедневную награду.\n"
        "<b>🎁 Промо [код]</b> - Активировать промокод.\n"
        "<b>📊 Топ</b> - Показать топ игроков по обычным монетам.\n"
        "<b>👥 Топ рефералы</b> - Показать топ рефералов по приглашенным.\n"
        "<b>🎁 Кейсы</b> - Показать информацию о кейсах."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await call.message.edit_text(help_text, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "game_commands")
async def show_game_commands(call: CallbackQuery):
    help_text = (
        "<b>📚 Игровые команды:</b>\n\n"
        "<b>⛏️ Добыть руду</b> - Добывать руду.\n"
        "<b>⬆️ Улучшить кирку</b> - Улучшить кирку: с каждым улучшением вы зарабатываете больше денег за каждую добытую руду.\n"
        "<b>🎣 Рыбалка</b> - Ловить рыбу.\n"
        "<b>⬆️ Улучшить удочку</b> - Улучшить удочку: с каждым улучшением вы зарабатываете больше денег за каждую пойманную рыбу.\n"
        "<b>🏹 Охота</b> - Охотиться.\n"
        "<b>⛏️ Задуть свечи</b> - Задуть свечи и получать Inc Pass.\n"
        "<b>⬆️ Улучшить ружье</b> - Улучшить ружьё(для охоты): с каждым улучшением вы зарабатываете больше денег за каждого пойманного животного.\n"
        "<b>🔪 Украсть [ID/ответ]</b> - Попытаться украсть монеты.\n"
        "<b>⬆️ Улучшить кражу</b> - Повысить шанс и сумму кражи.\n"
        "<b>🛡️ Улучшить защиту</b> - Снизить шанс быть ограбленным.\n"
        "<b>🎰 Казино [сумма]</b> - Испытать удачу в казино.\n"
        "<b>🎲 Кости [ставка] [ID/ответ] </b> - Вызвать игрока в игру кости.\n"
        "<b>✊🖐✌ Кмн [ставка] [ID/ответ] </b> - Вызвать игрока в игру камень-ножницы-бумага.\n"
        "<b>📈 Крипта</b> - Открыть крипто-рынок.\n"
        "<b>💸 Кошелек</b> - Открыть крипто-кошелек.\n"
        "<b>🎁 Открыть кейс [мифический/донат/денежный]</b> - Открыть кейс.\n"
        "<b>🧪 Купить зелье удачи</b> - Купить зелье удачи.\n"
        
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await call.message.edit_text(help_text, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "pass_help")
async def show_pass_help(call: CallbackQuery):
    help_text = (
       "<b>🎮 Inc Pass</b>\n\n"
"Inc Pass — это прогресс-система, в которой вы зарабатываете очки за активность и получаете награды за каждый уровень.\n\n"
"Каждый уровень требует определенное количество очков. Очки даются за действия:\n"
"- охота,\n"
"- рыбалка,\n"
"- шахта,\n"
"- ежедневный вход,\n"
"- приглашения друзей и другие игровые активности.\n\n"
"<b>⛏️ Задуть свечи</b> — основной способ получения очков Inc Pass в этой активности.\n\n"
"За каждого нового приглашённого друга реферер получает <b>+1,000 очков Inc Pass</b> и от <b>100,000</b> монет.\n\n"
"При достижении уровней вы получаете разные награды:\n"
"- монеты,\n"
"- особые монеты,\n"
"- кейсы,\n"
"- уникальные награды.\n\n"

"<b>🏆 Награда за прохождение Inc Pass</b>\n\n"
"За полное прохождение обычного <b>Inc Pass</b> игрок получает эксклюзивный титул:\n\n"
"🪙 <b>Crypto</b>\n"
"- приносит <b>+1 денежный кейс каждые 24 часа</b>;\n"
"- +5% к шансу на выигрыш в казино;\n"    
"- доступен только игрокам, которые полностью завершили обычный Inc Pass.\n\n"

"<b>💎 Inc Pass+</b>\n\n"
"Inc Pass+ — это премиальная версия пасса для игроков, которые хотят получать больше наград.\n\n"
"Владельцы <b>Inc Pass+</b> получают:\n"
"- 🚀 <b>в 3 раза больше наград</b> за прохождение уровней;\n"
"- 🎁 улучшенные награды;\n"
"- 👑 эксклюзивный титул после полного прохождения.\n\n"

"<b>🏆 Награда за прохождение Inc Pass+</b>\n\n"
"За полное прохождение <b>Inc Pass+</b> игрок получает уникальный титул:\n\n"
"👑 <b> Crypto Ultimate</b>\n"
"- приносит <b>+3 денежных кейса каждые 24 часа</b>;\n"
"- +8% к шансу на выигрыш в казино;\n"  
"- доступен только владельцам Inc Pass+.\n\n"

"Inc Pass+ — лучший выбор для игроков, которые хотят получить максимум наград и эксклюзивные возможности.\n\n"

"<b>⚙️ Команды для контроля пасса:</b>\n"
"- <b>пасс</b> или <b>inc pass</b> — увидеть текущий уровень и прогресс.\n"
"- <b>топ пасс</b> — увидеть топ игроков по уровню INC Pass.\n\n"
"Чтобы приобрести <b>Inc Pass+</b> за 110 ⭐, используйте команду <b>купить пасс плюс</b>.\n\n"
"Хотите приобрести за рубли? выдача всегда моментальная: "
        "<a href='https://t.me/IncManager'>тык</a>\n"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await call.message.edit_text(help_text, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "donate_commands")
async def show_donate_commands(call: CallbackQuery):
    help_text = (
        "<b>📚 Донат и Премиум:</b>\n\n"
        "<b>💎 Донат</b> - Информация о донате.\n\n"
        "<b>🗡️ Купить assassin</b> - Купить assassin статус за 35 ⭐.\n"
        "<b>⭐ Купить vip</b> - Купить vip статус за 150 ⭐.\n"
        "<b>🔥 Купить pro</b> - Купить pro статус за 250 ⭐.\n"
        "<b>👑 Купить max</b> - Купить max статус за 350 ⭐.\n\n"
        "<b>🎟️ Купить пасс плюс</b> - Купить INC Pass+ за 110 ⭐.\n\n"
        "<b>💵 Купить денежный кейс</b> - Купить денежный кейс за 35 ⭐.\n"
        "<b>💎 Купить донат кейс</b> - Купить донат кейс за 150 ⭐.\n"
        "<b>🎁 Купить мифический кейс</b> - Купить мифический кейс за 50 особых монет.\n\n"
        "<b>🏦 Ограбить казну</b> - Ограбить казну (PRO/MAX).\n\n"
        "💰 Хотите приобрести донат за рубли?\n"
        "Пишите: @IncManager\n"
        
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await call.message.edit_text(help_text, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "exchange_commands")
async def show_exchange_commands(call: CallbackQuery):
    help_text = (
        "<b>📚 Обмен валют:</b>\n\n"
        "<b>🔄 Обмен обычные на особые</b> - Обмен обычных на особые монеты.\n"
        "<b>🔄 Обмен особые на галактические</b> - Обмен особых на галактические монеты.\n"
        "<b>🔄 Обмен особые на обычные</b> - Обмен особых на обычные монеты.\n"
        "<b>🔄 Обмен галактические на обычные</b> - Обмен галактических на обычные монеты.\n"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await call.message.edit_text(help_text, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "space_commands")
async def show_space_commands(call: CallbackQuery):
    help_text = (
        "<b>📚 Космос:</b>\n\n"
        "<b>🍔 Купить ресторан [планета]</b> - Купить ресторан.\n"
        "Доступные рестораны: марс, юпитер, уран.\n"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await call.message.edit_text(help_text, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()

async def main():
    await init_db()
    await update_settings_on_startup()
    await get_global_settings()
    await reconcile_referral_plus()
    asyncio.create_task(periodic_payouts())
    asyncio.create_task(periodic_crypto_market())
    print("Bot starting polling...")
    await dp.start_polling(bot)
    



if __name__ == '__main__':
    try: 
        asyncio.run(main())
    except KeyboardInterrupt: 
        print("Bot stopped by admin.")
    except Exception as e: 
        print(f"Critical error during bot execution: {e}")
