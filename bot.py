# -*- coding: utf-8 -*-
# pip install aiogram aiohttp pillow pyswisseph geopy timezonefinder
# Джйотиш-бот Юли Мани: Раши D1, Навамша D9, Астро-паспорт, Банк карт, вопросы через GPTTunnel
import asyncio
import html
import io
import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
import swisseph as swe
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery,
                           InlineKeyboardButton, InlineKeyboardMarkup,
                           InputMediaPhoto, KeyboardButton, Message,
                           ReplyKeyboardMarkup)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from geopy.geocoders import Nominatim
from PIL import Image, ImageDraw, ImageFont
from timezonefinder import TimezoneFinder

# ================================================================ КОНСТАНТЫ
BOT_TOKEN = "ВАШ_ТОКЕН_СЮДА"
BOT_TOKEN = os.getenv("BOT_TOKEN", BOT_TOKEN)

PRO_LINK = "https://t.me/yulia_miou"
STONES_CHANNEL_LINK = "https://t.me/yuliamani_stones"
INSTAGRAM_LINK = "https://instagram.com/space_pill"
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

LLM_BASE = os.getenv("LLM_API_URL", "https://gpttunnel.ru")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5-mini")

# ================================================================ БАЗА ДАННЫХ
def _pick_db_path():
    try:
        os.makedirs("/app/data", exist_ok=True)
        t = "/app/data/.w"
        with open(t, "w") as f:
            f.write("1")
        os.remove(t)
        return "/app/data/charts.db"
    except Exception:
        return "./charts.db"


DB_PATH = _pick_db_path()


def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            questions_balance INTEGER DEFAULT 1,
            max_charts INTEGER DEFAULT 3,
            active_chart INTEGER DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS charts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, name TEXT, gender TEXT, date TEXT, time TEXT,
            city TEXT, style TEXT, json_data TEXT)""")


def get_user(uid):
    with db() as c:
        r = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if r is None:
            c.execute("INSERT INTO users(user_id) VALUES(?)", (uid,))
            r = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        return dict(r)


def charts_of(uid):
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT id,name,date,time,city FROM charts WHERE user_id=? ORDER BY id", (uid,))]


def save_chart(uid, d):
    with db() as c:
        cur = c.execute(
            "INSERT INTO charts(user_id,name,gender,date,time,city,style,json_data) VALUES(?,?,?,?,?,?,?,?)",
            (uid, d["name"], d["gender"], d["date"], d["time"], d["city"], d["style"],
             json.dumps(d, ensure_ascii=False)))
        cid = cur.lastrowid
        c.execute("UPDATE users SET active_chart=? WHERE user_id=?", (cid, uid))
        return cid


def load_chart(cid, uid):
    with db() as c:
        r = c.execute("SELECT json_data FROM charts WHERE id=? AND user_id=?", (cid, uid)).fetchone()
    return json.loads(r["json_data"]) if r else None


def active_chart(uid):
    u = get_user(uid)
    d = load_chart(u["active_chart"], uid) if u["active_chart"] else None
    return (u["active_chart"], d) if d else (None, None)


def set_active(uid, cid):
    with db() as c:
        c.execute("UPDATE users SET active_chart=? WHERE user_id=?", (cid, uid))


def delete_chart(uid, cid):
    with db() as c:
        c.execute("DELETE FROM charts WHERE id=? AND user_id=?", (cid, uid))
        c.execute("UPDATE users SET active_chart=0 WHERE user_id=? AND active_chart=?", (uid, cid))


def spend_question(uid):
    get_user(uid)
    with db() as c:
        cur = c.execute("UPDATE users SET questions_balance=questions_balance-1 "
                        "WHERE user_id=? AND questions_balance>0", (uid,))
        return cur.rowcount > 0


def add_questions(uid, n):
    get_user(uid)
    with db() as c:
        c.execute("UPDATE users SET questions_balance=questions_balance+? WHERE user_id=?", (n, uid))


def add_slots(uid, n):
    get_user(uid)
    with db() as c:
        c.execute("UPDATE users SET max_charts=max_charts+? WHERE user_id=?", (n, uid))


# ================================================================ АСТРО-ДАННЫЕ
SIGNS = ["Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
         "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы"]
SYM = [chr(0x2648 + i) for i in range(12)]

NAKSHATRAS = ["Ашвини", "Бхарани", "Криттика", "Рохини", "Мригашира", "Ардра",
              "Пунарвасу", "Пушья", "Ашлеша", "Магха", "Пурва Пхалгуни",
              "Уттара Пхалгуни", "Хаста", "Читра", "Свати", "Вишакха", "Анурадха",
              "Джьештха", "Мула", "Пурва Ашадха", "Уттара Ашадха", "Шравана",
              "Дхаништха", "Шатабхиша", "Пурва Бхадрапада", "Уттара Бхадрапада", "Ревати"]

PLANETS = [("Su", "Солнце", swe.SUN), ("Mo", "Луна", swe.MOON),
           ("Ma", "Марс", swe.MARS), ("Me", "Меркурий", swe.MERCURY),
           ("Ju", "Юпитер", swe.JUPITER), ("Ve", "Венера", swe.VENUS),
           ("Sa", "Сатурн", swe.SATURN)]
NAMES = {"As": "Лагна", "Su": "Солнце", "Mo": "Луна", "Ma": "Марс", "Me": "Меркурий",
         "Ju": "Юпитер", "Ve": "Венера", "Sa": "Сатурн", "Ra": "Раху", "Ke": "Кету"}
ORDER = ["As", "Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "Ra", "Ke"]
NINE = ["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "Ra", "Ke"]

SIGN_LORDS = ["Ma", "Ve", "Me", "Mo", "Su", "Me", "Ve", "Ma", "Ju", "Sa", "Sa", "Ju"]
EXALT = {"Su": 0, "Mo": 1, "Ma": 9, "Me": 5, "Ju": 3, "Ve": 11, "Sa": 6}
MOOL = {"Su": 4, "Mo": 1, "Ma": 0, "Me": 5, "Ju": 8, "Ve": 6, "Sa": 10}
FRIENDS = {"Su": "Mo Ma Ju", "Mo": "Su Me", "Ma": "Su Mo Ju", "Me": "Su Ve",
           "Ju": "Su Mo Ma", "Ve": "Me Sa", "Sa": "Me Ve"}
ENEMIES = {"Su": "Ve Sa", "Mo": "", "Ma": "Me", "Me": "Mo", "Ju": "Me Ve",
           "Ve": "Su Mo", "Sa": "Su Mo Ma"}

# Граха-дришти (Парашара), номера домов от планеты включительно
ASPECTS = {"Su": [7], "Mo": [7], "Me": [7], "Ve": [7], "Ma": [4, 7, 8],
           "Ju": [5, 7, 9], "Sa": [3, 7, 10], "Ra": [5, 7, 9], "Ke": [5, 7, 9]}

KARAKA_NAMES = ["АК", "АмК", "БК", "МК", "ПК", "ГК", "ДК"]
COMBUST_ORB = {"Mo": 12, "Ma": 17, "Me": 14, "Ju": 11, "Ve": 10, "Sa": 15}

# Бхиннаштакаварга: BAV[планета][вкладчик] = дома от вкладчика
def _p(s):
    return {k: [int(x) for x in v.split()] for k, v in s.items()}


BAV_TABLE = {
    "Su": _p({"Su": "1 2 4 7 8 9 10 11", "Mo": "3 6 10 11", "Ma": "1 2 4 7 8 9 10 11",
              "Me": "3 5 6 9 10 11 12", "Ju": "5 6 9 11", "Ve": "6 7 12",
              "Sa": "1 2 4 7 8 9 10 11", "As": "3 4 6 10 11 12"}),
    "Mo": _p({"Su": "3 6 7 8 10 11", "Mo": "1 3 6 7 10 11", "Ma": "2 3 5 6 9 10 11",
              "Me": "1 3 4 5 7 8 10 11", "Ju": "1 4 7 8 10 11 12", "Ve": "3 4 5 7 9 10 11",
              "Sa": "3 5 6 11", "As": "3 6 10 11"}),
    "Ma": _p({"Su": "3 5 6 10 11", "Mo": "3 6 11", "Ma": "1 2 4 7 8 10 11",
              "Me": "3 5 6 11", "Ju": "6 10 11 12", "Ve": "6 8 11 12",
              "Sa": "1 4 7 8 9 10 11", "As": "1 3 6 10 11"}),
    "Me": _p({"Su": "5 6 9 11 12", "Mo": "2 4 6 8 10 11", "Ma": "1 2 4 7 8 9 10 11",
              "Me": "1 3 5 6 9 10 11 12", "Ju": "6 8 11 12", "Ve": "1 2 3 4 5 8 9 11",
              "Sa": "1 2 4 7 8 9 10 11", "As": "1 2 4 6 8 10 11"}),
    "Ju": _p({"Su": "1 2 3 4 7 8 9 10 11", "Mo": "2 5 7 9 11", "Ma": "1 2 4 7 8 10 11",
              "Me": "1 2 4 5 6 9 10 11", "Ju": "1 2 3 4 7 8 10 11", "Ve": "2 5 6 9 10 11",
              "Sa": "3 5 6 12", "As": "1 2 4 5 6 7 9 10 11"}),
    "Ve": _p({"Su": "8 11 12", "Mo": "1 2 3 4 5 8 9 11 12", "Ma": "3 4 6 9 11 12",
              "Me": "3 5 6 9 11", "Ju": "5 8 9 10 11", "Ve": "1 2 3 4 5 8 9 10 11",
              "Sa": "3 4 5 8 9 10 11", "As": "1 2 3 4 5 8 9 11"}),
    "Sa": _p({"Su": "1 2 4 7 8 10 11", "Mo": "3 6 11", "Ma": "3 5 6 10 11 12",
              "Me": "6 8 9 10 11 12", "Ju": "5 6 11 12", "Ve": "6 11 12",
              "Sa": "3 5 6 11", "As": "1 3 4 6 10 11"}),
}

# Вимшоттари
DORDER = ["Ke", "Ve", "Su", "Mo", "Ma", "Ra", "Ju", "Sa", "Me"]
DYEARS = {"Ke": 7, "Ve": 20, "Su": 6, "Mo": 10, "Ma": 7, "Ra": 18, "Ju": 16, "Sa": 19, "Me": 17}
YEAR_DAYS = 365.25

TITHI_NAMES = ["Пратипада", "Двития", "Тритья", "Чатуртхи", "Панчами", "Шашти", "Саптами",
               "Аштами", "Навами", "Дашами", "Экадаши", "Двадаши", "Трайодаши", "Чатурдаши"]

HOUSE_KEY = ["личность и тело", "ресурсы и речь", "усилия и таланты", "дом и покой",
             "творчество и дети", "здоровье и преодоление", "отношения и брак",
             "трансформации и кризисы", "удача и дхарма", "карьера и статус",
             "доходы и желания", "траты и духовность"]
HOUSE_TITLES = ["Личность, тело", "Ресурсы, речь", "Усилия, таланты", "Дом, мама",
                "Творчество, дети", "Здоровье, рутина", "Отношения, брак", "Трансформации",
                "Удача, дхарма", "Карьера, статус", "Доходы, желания", "Траты, духовность"]
HOUSE_KARAKA = ["Солнце", "Юпитер", "Марс", "Луна", "Юпитер", "Сатурн / Марс", "Венера / Юпитер",
                "Сатурн", "Юпитер", "Меркурий / Солнце / Сатурн", "Юпитер", "Сатурн / Кету"]

SIGN_TRAITS = [
    "энергия, инициатива, прямота", "устойчивость, чувственность, практичность",
    "любознательность, гибкость, общительность", "чувствительность, забота, привязанность к дому",
    "лидерство, творческая сила, достоинство", "анализ, порядок, служение",
    "гармония, дипломатия, эстетика", "глубина, интенсивность, воля к трансформации",
    "поиск смысла, оптимизм, свобода", "дисциплина, ответственность, терпение",
    "независимость, идеи, дружба", "интуиция, сострадание, уход в тонкое"]

STATUS_PHRASE = {
    "exalt": "планета в высшей силе, результаты проявляются ярко и естественно",
    "own": "планета в родной стихии, ведет себя уверенно и устойчиво",
    "friend": "знак дружественный, планета получает поддержку и действует мягко",
    "neutral": "знак нейтральный, результат зависит от аспектов и периодов",
    "enemy": "знак напряженный для планеты, нужны осознанность и компенсация",
}

# ================================================================ ВОПРОСЫ (Часть 2 ТЗ)
# (им., род., вин., "моего/моей"+род., "мой/моя"+им., "мой/мою"+вин., он/она, его/её)
PL_FORMS = {
    "Su": ("Солнце", "Солнца", "Солнце", "моего Солнца", "моё Солнце", "моё Солнце", "оно", "его"),
    "Mo": ("Луна", "Луны", "Луну", "моей Луны", "моя Луна", "мою Луну", "она", "её"),
    "Ma": ("Марс", "Марса", "Марс", "моего Марса", "мой Марс", "мой Марс", "он", "его"),
    "Me": ("Меркурий", "Меркурия", "Меркурий", "моего Меркурия", "мой Меркурий", "мой Меркурий", "он", "его"),
    "Ju": ("Юпитер", "Юпитера", "Юпитер", "моего Юпитера", "мой Юпитер", "мой Юпитер", "он", "его"),
    "Ve": ("Венера", "Венеры", "Венеру", "моей Венеры", "моя Венера", "мою Венеру", "она", "её"),
    "Sa": ("Сатурн", "Сатурна", "Сатурн", "моего Сатурна", "мой Сатурн", "мой Сатурн", "он", "его"),
    "Ra": ("Раху", "Раху", "Раху", "моего Раху", "мой Раху", "мой Раху", "он", "его"),
    "Ke": ("Кету", "Кету", "Кету", "моего Кету", "мой Кету", "мой Кету", "он", "его"),
}
PLANET_Q = [
    "В чем главная сила и уникальные таланты {mg} в этой карте?",
    "Какие скрытые блоки, страхи или искажения дает {mn}?",
    "Как {n} влияет на сферы домов, которыми {pr} управляет?",
    "Как проявляет себя {n} в доме, где {pr} расположен(а) в D1?",
    "Как раскрывается энергия {mg} в Навамше (D9) и во второй половине жизни?",
    "Как на {ma} влияют соединения и аспекты (дришти) других планет?",
    "Какой кармический урок и задачу души несет {n} (с учетом {pos} Чара-караки и накшатры)?",
    "Как {n} проявит себя в свой период или подпериод (Вимшоттари Даша)?",
    "Какие практические действия и упайи помогут мне гармонизировать и усилить {n}?",
]

BHAVA_Q = {
    1: [
        "Какое первое впечатление я произвожу на людей и в чем моя природная харизма?",
        "В чем моя главная жизненная сила и источник внутренней опоры?",
        "Какие черты характера мне важно развивать, а какие мешают двигаться вперед?",
        "На что обратить внимание в вопросах здоровья, внешности и физического тонуса?",
        "Как положение моего Лагнеша в D1 определяет главный вектор моей жизни?",
        "Как меняется моя личность и самоощущение во второй половине жизни (по Навамше D9)?",
        "Какие планеты аспектируют мой 1-й дом и как они корректируют мой характер?",
        "В какой среде и при каких условиях я чувствую себя максимально «на своем месте»?",
        "В чем мой главный внутренний конфликт между «хочу» и «надо»?",
        "Как моя Джанма-накшатра (Луна) дополняет характер восходящего знака?",
        "Какие периоды жизни принесут мне самый мощный личностный рост?",
        "Главная рекомендация (упайя) для укрепления Лагны и жизненной энергии.",
    ],
    2: [
        "Через какие источники и таланты ко мне легче всего приходят деньги и накопления?",
        "Умею ли я сохранять и приумножать капитал или склонен(на) к импульсивным тратам?",
        "Какова сила моей речи, голоса и убеждения — как использовать это в жизни и работе?",
        "Какие установки и программы я унаследовал(а) от своей родительской семьи (рода)?",
        "Как выстраиваются мои отношения с близкими родственниками?",
        "Какой тип питания и режима дня лучше всего поддерживает мою энергию (по 2-му дому)?",
        "В чем главная финансовая ловушка моей карты и как её обойти?",
        "Как положение управителя 2-го дома в D1 и D9 влияет на рост благосостояния?",
        "Насколько силен мой 2-й дом по Аштакаварге (САВ) и что это дает на практике?",
        "Какие периоды Даша наиболее благоприятны для крупных покупок и накоплений?",
        "Могу ли я зарабатывать через семейное дело, консультации, обучение или голос?",
        "Практическая рекомендация (упайя) для расширения денежного потока.",
    ],
    3: [
        "В чем мои главные прикладные таланты, навыки и творческие способности (работа руками, слово, медиа)?",
        "Насколько мне легко начинать новые проекты и проявлять инициативу?",
        "Как устроена моя сила воли: я спринтер на рывках или марафонец в долгую?",
        "Как складываются отношения с младшими братьями, сестрами и ближайшим окружением?",
        "Подходит ли мне работа в продажах, маркетинге, блогинге, текстах или коммуникациях?",
        "Как частые поездки, перемещения и смена обстановки влияют на мою продуктивность?",
        "Где я трачу слишком много усилий впустую и как оптимизировать свою энергию?",
        "Как Марс (карака 3-го дома) и управитель 3-го дома влияют на мою решительность?",
        "Какие хобби и увлечения могут перерасти для меня в полноценный источник дохода?",
        "Как проявляется мой 3-й дом в Навамше D9 (умение сотрудничать и договариваться)?",
        "Какие периоды требуют от меня максимальной смелости и самостоятельных шагов?",
        "Практическая рекомендация (упайя) для раскрытия талантов и уверенности в действиях.",
    ],
    4: [
        "Что для меня означает истинное внутреннее спокойствие и эмоциональный комфорт?",
        "Какой дом, интерьер и формат жилья подходят мне лучше всего по карте?",
        "Есть ли в карте показатели на покупку собственной недвижимости, земли или автомобиля?",
        "Насколько благоприятна для меня жизнь в родном городе или лучше переехать?",
        "Как складываются мои отношения с мамой и какое влияние она оказала на мою психику?",
        "Умею ли я по-настоящему отдыхать и восстанавливать внутренний ресурс?",
        "Какие эмоциональные травмы или тревоги скрыты в глубине подсознания (по Луне и 4-му дому)?",
        "Как положение управителя 4-го дома в D1 и D9 влияет на стабильность в жизни?",
        "Насколько силен мой 4-й дом по Аштакаварге (САВ) — легко ли мне дается бытовой комфорт?",
        "Подходит ли мне удаленная работа из дома или свой уютный офис/студия?",
        "В какие периоды Даша вероятны покупка жилья, ремонт или переезд?",
        "Практическая рекомендация (упайя) для гармонии в душе и в доме.",
    ],
    5: [
        "В чем проявляется мой творческий потенциал и способность создавать что-то уникальное?",
        "Каков склад моего ума, интуиции и способности к обучению и аналитике?",
        "Как складывается тема детей в моей карте: отношения с детьми и родительский опыт?",
        "Как я проявляю себя в романтических отношениях и влюбленности (до брака)?",
        "Есть ли у меня склонность к инвестициям, бирже, стартапам или разумному риску?",
        "Какие благие заслуги прошлого воплощения (Пурва-пунья) поддерживают меня в этой жизни?",
        "Подходит ли мне роль наставника, учителя, автора курсов или руководителя проектов?",
        "Как Юпитер (карака 5-го дома) и управитель 5-го дома проявляются в D1 и D9?",
        "Что блокирует мою спонтанность, радость жизни и вдохновение?",
        "Какие периоды жизни наиболее благоприятны для рождения детей или запуска творческого проекта?",
        "Насколько силен 5-й дом по Аштакаварге (САВ) и как это влияет на удачу?",
        "Практическая рекомендация (упайя) для раскрытия творчества и радости.",
    ],
    6: [
        "В чем моя главная суперсила в преодолении кризисов, конкуренции и сложных задач?",
        "Какие зоны организма требуют особого внимания и профилактики (по 6-му дому и его управителю)?",
        "Как мне правильно выстроить режим дня, питание и физическую нагрузку, чтобы не выгорать?",
        "Как я отношусь к кредитам, долгам и финансовым обязательствам — стоит ли их брать?",
        "Как складываются отношения с коллегами, подчиненными и наемными сотрудниками?",
        "Подходит ли мне работа в медицине, психологии, юриспруденции, сервисе или антикризисном управлении?",
        "Почему в моей жизни возникают конфликты или недоброжелатели и как мне экологично побеждать?",
        "Насколько силен мой 6-й дом по Аштакаварге (САВ) — побеждаю ли я трудности или они давят?",
        "Как положение управителя 6-го дома в D1 и D9 влияет на здоровье и работу?",
        "Какие привычки в повседневной рутине разрушают мою энергию, а какие усиливают?",
        "В какие периоды Даша нужно особенно беречь здоровье и избегать судебных/финансовых споров?",
        "Практическая рекомендация (упайя) для крепкого здоровья и защиты от проблем.",
    ],
    7: [
        "Какой партнер (по характеру, ценностям и внешнему типажу) мне действительно подходит?",
        "Где и при каких обстоятельствах наиболее вероятна судьбоносная встреча?",
        "В чем мой главный кармический урок и зона роста в близких отношениях?",
        "Что укрепляет мой брак, а какие сценарии поведения приводят к охлаждению или кризисам?",
        "Как раскрывается тема брака и супруга(и) во второй половине жизни (по Навамше D9)?",
        "В чем сила и уязвимость моей караки брака (Венеры для мужчин / Юпитера для женщин)?",
        "Есть ли в карте показатели на поздний брак, нестандартный союз или разницу в возрасте/культуре?",
        "Благоприятно ли для меня деловое партнерство и совместный бизнес или лучше работать одному(ой)?",
        "Как ось Раху/Кету и аспекты на 7-й дом влияют на ожидания от партнера?",
        "Насколько силен мой 7-й дом по Аштакаварге (САВ) и как распределяются роли в семье?",
        "Какие периоды Вимшоттари Даша наиболее благоприятны для брака и обновления отношений?",
        "Практическая рекомендация (упайя) для гармонии в любви и партнерстве.",
    ],
    8: [
        "Как я прохожу через жизненные кризисы и в чем мой ресурс возрождения после перемен?",
        "Есть ли в моей карте способности к эзотерике, астрологии, психологии и работе с подсознанием?",
        "Как складывается тема чужих денег: наследство, гранты, инвестиции партнеров, пассивный доход?",
        "Какую роль играет финансовая поддержка супруга(и) или бизнес-партнеров в моей жизни?",
        "Какие скрытые страхи, тревоги или привязанности мешают мне доверять миру?",
        "На что обратить внимание в вопросах безопасности, экстремальных ситуаций и хронических состояний?",
        "В чем сила и глубина моей сексуальной и эмоциональной энергии?",
        "Как положение управителя 8-го дома в D1 и D9 влияет на продолжительность и качество трансформаций?",
        "Насколько силен 8-й дом по Аштакаварге (САВ) — помогают ли мне перемены расти?",
        "Подходит ли мне работа в исследованиях, аналитике, страховании, кризис-менеджменте или психотерапии?",
        "Какие периоды Даша принесут глубокую внутреннюю перестройку и обновление жизни?",
        "Практическая рекомендация (упайя) для мягкого прохождения трансформаций.",
    ],
    9: [
        "В чем заключается моя Дхарма — главный жизненный вектор, приносящий удачу и поддержку мира?",
        "Насколько сильна моя природная удача (Бхагья) и через какие действия она активируется?",
        "Какую роль в моей жизни играют наставники, учителя, духовные знания и высшее образование?",
        "Как складываются отношения с отцом и какие родовые программы идут по отцовской линии?",
        "Благоприятны ли для меня дальние путешествия, изучение иностранных языков и других культур?",
        "Подходит ли мне деятельность в преподавании, науке, издательстве, праве или духовном наставничестве?",
        "Какие убеждения и принципы помогают мне расти, а какие превращаются в жесткий догматизм?",
        "Как Юпитер и управитель 9-го дома проявляются в D1 и в Навамше D9?",
        "Насколько силен мой 9-й дом по Аштакаварге (САВ) — легко ли мне дается признание и покровительство?",
        "Как сочетаются в моей карте материальные цели и духовный поиск?",
        "Какие периоды Даша откроют для меня новые горизонты, обучение или дальние поездки?",
        "Практическая рекомендация (упайя) для активации удачи и поддержки Высших сил.",
    ],
    10: [
        "В каких профессиях и сферах деятельности я смогу достичь максимального успеха и признания?",
        "Что мне подходит больше: работа в найме, руководящая должность, фриланс или собственный бизнес?",
        "Какие мои сильные качества больше всего ценят руководители, клиенты и общество?",
        "Насколько важны для меня социальный статус, репутация и карьерные амбиции?",
        "В чем главная причина карьерного потолка или выгорания в моей карте и как это преодолеть?",
        "Как положение управителя 10-го дома в D1 и Навамше D9 определяет мой профессиональный путь?",
        "Насколько силен мой 10-й дом по Аштакаварге (САВ) — легко ли мне даются карьерные взлеты?",
        "Могу ли я реализовать себя в управлении, госслужбе, публичности или экспертной деятельности?",
        "Как баланс между работой (10 дом) и семьей (4 дом) выстроен в моей карте?",
        "Какие планеты влияют на мой 10-й дом и какой стиль работы они диктуют?",
        "Какие периоды Вимшоттари Даша принесут смену работы, повышение или прорыв в карьере?",
        "Практическая рекомендация (упайя) для профессионального роста и успеха.",
    ],
    11: [
        "Через какие проекты, сообщества и масштабные идеи ко мне приходят большие деньги (прибыль)?",
        "Умею ли я ставить амбициозные цели и доводить их до материального результата?",
        "Какую роль в моем успехе играют друзья, нетворкинг, соцсети и работа с аудиторией?",
        "Каких людей я притягиваю в круг друзей и единомышленников — кто меня усиливает?",
        "Есть ли в карте показатели на множественные источники дохода или онлайн-бизнес?",
        "Как складываются отношения со старшими братьями, сестрами или влиятельными покровителями?",
        "Насколько силен мой 11-й дом по Аштакаварге (САВ) — легко ли исполняются мои желания?",
        "Как положение управителя 11-го дома в D1 и D9 влияет на финансовый масштаб?",
        "В чем разница между моими текущими заработками (2 дом) и сверхприбылью (11 дом)?",
        "Какие иллюзии или лишние амбиции (если в 11 доме есть Раху/другие влияния) требуют трезвого взгляда?",
        "Какие периоды Даша наиболее денежные и результативные для запуска проектов?",
        "Практическая рекомендация (упайя) для роста доходов и реализации целей.",
    ],
    12: [
        "Есть ли в моей карте сильные показатели на эмиграцию, жизнь у моря или работу с заграницей?",
        "Насколько мне необходимо регулярное уединение и тишина для восстановления сил?",
        "Куда утекают мои деньги и энергия — как превратить вынужденные траты в осознанные инвестиции?",
        "Как устроен мой сон, подсознание, интуиция и способность отпускать прошлое?",
        "Подходит ли мне работа в закрытых учреждениях, ретритах, благотворительности, IT или международных компаниях?",
        "Какие духовные практики, медитации или паломничества дают мне самую глубокую перезагрузку?",
        "Что мешает мне расслабиться и отпустить гиперконтроль (по 12-му дому)?",
        "Как положение управителя 12-го дома в D1 и Навамше D9 влияет на внутреннюю свободу?",
        "Насколько силен мой 12-й дом по Аштакаварге (САВ) — умею ли я грамотно распоряжаться ресурсами?",
        "Как ось 6–12 домов балансирует в моей карте между повседневной суетой и покоем?",
        "Какие периоды Даша благоприятны для переезда за рубеж, духовного роста или завершения старых циклов?",
        "Практическая рекомендация (упайя) для гармонии подсознания и защиты от потерь.",
    ],
}

DASHA_Q = [
    "Каков главный вектор и главная задача моего текущего большого периода (Махадаши)?",
    "Какие конкретные события и перемены несет текущий подпериод (Антардаша)?",
    "На что обратить особое внимание в ближайшие месяцы по Пратьянтардаше?",
    "Насколько гармонично сочетаются между собой управители моей Махадаши и Антардаши?",
    "Какие сферы жизни (дома) сейчас максимально активированы текущим периодом?",
    "Где в текущем периоде скрыты главные риски, задержки или эмоциональные проверки?",
    "Какие возможности в карьере, деньгах или отношениях открывает текущий период?",
    "Чего ждать от следующего периода (Антардаши / Махадаши) и как к нему подготовиться заранее?",
    "Какие упайи и действия лучше всего делать именно сейчас, чтобы прожить текущий период на максимуме?",
]

ASHTAKA_Q = [
    "Какие сферы жизни (дома с баллом САВ 30+) являются моим главным природным ресурсом и опорой?",
    "Какие сферы жизни (дома с баллом САВ ниже 25) требуют от меня осознанной проработки и терпения?",
    "Как распределен баланс сил между кендрами (1, 4, 7, 10) и триконами (1, 5, 9) в моей Аштакаварге?",
    "Насколько силен мой финансовый контур по Аштакаварге (сравнение 2-го, 10-го и 11-го домов и правила прибыли 11 > 10 > 12)?",
    "Что говорит Аштакаварга о сфере отношений и брака (баллы 7-го дома и Бхиннаштакаварга Венеры/Юпитера)?",
    "Какие планеты в моей карте имеют самый высокий личный балл БАВ (5–8 баллов) и в чем их суперсила?",
    "Какие планеты имеют низкий балл БАВ (0–3 балла) и как компенсировать их слабость?",
    "Как транзиты Сатурна и Юпитера по знакам с высоким и низким САВ влияют на мою удачу?",
    "Главный стратегический вывод по распределению энергии в моей карте согласно Аштакаварге.",
]


def get_questions(kind, arg):
    if kind == "pl":
        f = PL_FORMS[arg]
        m = dict(n=f[0], g=f[1], a=f[2], mg=f[3], mn=f[4], ma=f[5], pr=f[6], pos=f[7])
        return [q.format(**m) for q in PLANET_Q]
    if kind == "bh":
        return BHAVA_Q[int(arg)]
    if kind == "da":
        return DASHA_Q
    return ASHTAKA_Q


# ================================================================ ШРИФТЫ
FONT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_FILES = {
    "NotoSans-Regular.ttf": [
        "https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSans/full/ttf/NotoSans-Regular.ttf",
        "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans-Regular.ttf"],
    "NotoSans-Bold.ttf": [
        "https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSans/full/ttf/NotoSans-Bold.ttf",
        "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans-Bold.ttf"],
    "NotoSansSymbols2-Regular.ttf": [
        "https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansSymbols2/full/ttf/NotoSansSymbols2-Regular.ttf",
        "https://github.com/google/fonts/raw/main/ofl/notosanssymbols2/NotoSansSymbols2-Regular.ttf"],
}


def ensure_fonts():
    for fname, urls in FONT_FILES.items():
        path = os.path.join(FONT_DIR, fname)
        if os.path.exists(path) and os.path.getsize(path) > 10000:
            continue
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=20) as r:
                    data = r.read()
                if len(data) > 10000:
                    with open(path, "wb") as f:
                        f.write(data)
                    break
            except Exception as e:
                print(f"Не удалось скачать {fname}: {e}", flush=True)


_fc = {}


def _font(fname, size):
    k = (fname, size)
    if k not in _fc:
        try:
            _fc[k] = ImageFont.truetype(os.path.join(FONT_DIR, fname), size)
        except Exception:
            try:
                _fc[k] = ImageFont.load_default(size)
            except Exception:
                _fc[k] = ImageFont.load_default()
    return _fc[k]


def get_font(size, bold=False):
    return _font("NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf", size)


def get_sym(size):
    return _font("NotoSansSymbols2-Regular.ttf", size)


# ================================================================ РАСЧЕТЫ
def fd(deg):
    d = int(deg)
    return f"{d:02d}°{int((deg - d) * 60):02d}'"


def nak_of(lon):
    span = 360 / 27
    return NAKSHATRAS[int(lon // span) % 27], int((lon % span) // (span / 4)) + 1


def calc(jd, pid, flags):
    res = swe.calc_ut(jd, pid, flags)
    xx = res[0] if isinstance(res[0], (tuple, list)) else res
    return xx[0] % 360, xx[3]


def dignity(code, sign, signs):
    if code not in EXALT:
        return "Нейтральный", "neutral"
    if sign == EXALT[code]:
        return "Экзальтация", "exalt"
    if sign == (EXALT[code] + 6) % 12:
        return "Падение", "enemy"
    if sign == MOOL[code]:
        return "Мулатрикона", "own"
    lord = SIGN_LORDS[sign]
    if lord == code:
        return "Свой знак", "own"
    nat = 1 if lord in FRIENDS[code].split() else (-1 if lord in ENEMIES[code].split() else 0)
    house_of_lord = (signs[lord] - sign) % 12 + 1
    temp = 1 if house_of_lord in (2, 3, 4, 10, 11, 12) else -1
    s = nat + temp
    return {2: ("Большой друг", "friend"), 1: ("Друг", "friend"), 0: ("Нейтральный", "neutral"),
            -1: ("Враг", "enemy"), -2: ("Большой враг", "enemy")}[s]


def tithi_of(sun, moon):
    n = int(((moon - sun) % 360) // 12) + 1
    paksha = "Шукла" if n <= 15 else "Кришна"
    if n == 15:
        nm = "Пурнима"
    elif n == 30:
        nm = "Амавасья"
    else:
        nm = TITHI_NAMES[(n - 1) % 15]
    return {"num": n, "paksha": paksha, "name": nm}


def build_chart(name, gender, date_s, time_s, city, style, lat, lon, address):
    tz_name = TimezoneFinder().timezone_at(lat=lat, lng=lon)
    if not tz_name:
        raise ValueError("Не удалось определить часовой пояс")
    local = datetime.strptime(f"{date_s} {time_s}", "%d.%m.%Y %H:%M").replace(tzinfo=ZoneInfo(tz_name))
    utc = local.astimezone(timezone.utc)
    swe.set_sid_mode(swe.SIDM_TRUE_CITRA)
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED
    jd = swe.julday(utc.year, utc.month, utc.day, utc.hour + utc.minute / 60 + utc.second / 3600)
    _, ascmc = swe.houses_ex(jd, lat, lon, b"P", flags)
    asc = ascmc[0] % 360

    pts = {"As": (asc, False)}
    for code, _, pid in PLANETS:
        L, sp = calc(jd, pid, flags)
        pts[code] = (L, sp < 0)
    rahu, rsp = calc(jd, swe.TRUE_NODE, flags)
    pts["Ra"] = (rahu, rsp < 0)
    pts["Ke"] = ((rahu + 180) % 360, rsp < 0)

    lagna = int(asc // 30)
    nav_of = lambda L: int(L / (30 / 9)) % 12
    nlagna = nav_of(asc)
    signs = {c: int(pts[c][0] // 30) for c in pts}
    sun = pts["Su"][0]

    # Чара-караки
    seven = sorted(["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa"], key=lambda c: -(pts[c][0] % 30))
    kar = {c: KARAKA_NAMES[i] for i, c in enumerate(seven)}

    # Аштакаварга
    pos = {c: signs[c] for c in ["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "As"]}
    bav = {}
    for p, tbl in BAV_TABLE.items():
        arr = [0] * 12
        for s in range(12):
            for contrib, hs in tbl.items():
                if ((s - pos[contrib]) % 12) + 1 in hs:
                    arr[s] += 1
        bav[p] = arr
    sav_sign = [sum(bav[p][s] for p in bav) for s in range(12)]
    sav_house = [sav_sign[(lagna + h) % 12] for h in range(12)]

    rows = []
    for c in ORDER:
        L, retro = pts[c]
        s = signs[c]
        nk, pada = nak_of(L)
        st, key = ("Лагна", "lagna") if c == "As" else dignity(c, s, signs)
        ns = nav_of(L)
        row = {
            "code": c, "name": NAMES[c], "lon": L, "sign": s, "sign_name": SIGNS[s],
            "deg": L % 30, "retro": retro, "house": (s - lagna) % 12 + 1,
            "nak": nk, "pada": pada, "status": st, "key": key,
            "nav_sign": ns, "nav_house": (ns - nlagna) % 12 + 1,
            "varg": ns == s, "combust": False, "gandanta": False,
            "karaka": kar.get(c, ""), "bav": bav[c][s] if c in bav else None,
            "rules": [(i - lagna) % 12 + 1 for i in range(12) if SIGN_LORDS[i] == c],
        }
        if c in COMBUST_ORB:
            diff = abs(L - sun)
            diff = min(diff, 360 - diff)
            orb = COMBUST_ORB[c]
            if c == "Me" and retro:
                orb = 12
            if c == "Ve" and retro:
                orb = 8
            row["combust"] = diff < orb
        dist = min(min(abs(L - b), 360 - abs(L - b)) for b in (0, 120, 240))
        row["gandanta"] = dist <= 3 + 20 / 60
        rows.append(row)

    aspects = [[] for _ in range(12)]
    for r in rows:
        if r["code"] == "As":
            continue
        for k in ASPECTS[r["code"]]:
            t = (r["house"] - 1 + k - 1) % 12
            if t != r["house"] - 1 and r["code"] not in aspects[t]:
                aspects[t].append(r["code"])
    for a in aspects:
        a.sort(key=ORDER.index)

    return {
        "name": name, "gender": gender, "date": date_s, "time": time_s, "city": city,
        "style": style, "address": address, "lat": lat, "lon": lon, "tz": tz_name,
        "utc_str": utc.strftime("%d.%m.%Y %H:%M"),
        "utc_iso": utc.replace(tzinfo=None).isoformat(),
        "lagna": lagna, "nav_lagna": nlagna, "rows": rows, "aspects": aspects,
        "sav": sav_house, "sav_sign": sav_sign, "bav": bav,
        "tithi": tithi_of(pts["Su"][0], pts["Mo"][0]),
        "moon_lon": pts["Mo"][0], "rectify": asc % 30 < 1.5 or asc % 30 > 28.5,
    }


def R(data, code):
    return next(r for r in data["rows"] if r["code"] == code)


def lbl(r):
    return f"({r['code']})" if r["retro"] else r["code"]


def sub_periods(lord, start, end):
    i = DORDER.index(lord)
    total = end - start
    res, s = [], start
    for k in range(9):
        l = DORDER[(i + k) % 9]
        e = s + total * DYEARS[l] / 120
        res.append((l, s, e))
        s = e
    return res


def dasha_tree(data):
    birth = datetime.fromisoformat(data["utc_iso"])
    moon = data["moon_lon"]
    span = 360 / 27
    i0 = int(moon // span) % 9
    frac = (moon % span) / span
    start = birth - timedelta(days=DYEARS[DORDER[i0]] * frac * YEAR_DAYS)
    mds = []
    for k in range(9):
        l = DORDER[(i0 + k) % 9]
        end = start + timedelta(days=DYEARS[l] * YEAR_DAYS)
        mds.append((l, start, end))
        start = end
    return mds


def periods(data, now=None):
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    mds = dasha_tree(data)
    md = next((m for m in mds if m[1] <= now < m[2]), mds[-1])
    ads = sub_periods(*md)
    ad = next((a for a in ads if a[1] <= now < a[2]), ads[-1])
    pds = sub_periods(*ad)
    pd = next((p for p in pds if p[1] <= now < p[2]), pds[-1])
    i = ads.index(ad)
    nxt = ads[i + 1] if i + 1 < len(ads) else None
    return mds, md, ad, pd, nxt


def dd(dt):
    return dt.strftime("%d.%m.%Y")


# ================================================================ ЧЕРТЕЖИ
PAPER, PENCIL, PEN, GRAY, ACCENT = "#FCFCFA", "#4A4A4A", "#141414", "#7A7A7A", "#D95D39"
STYLE = {  # key -> (bold, color)
    "lagna": (True, ACCENT), "exalt": (True, "#1B5E20"), "own": (False, "#1B5E20"),
    "friend": (True, "#1E88E5"), "neutral": (False, PEN), "enemy": (True, "#8E2424"),
}


def sheet(w, h):
    img = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([12, 12, w - 13, h - 13], outline=PENCIL, width=2)
    return img, d


def house_polys(ox, oy, s):
    P = lambda x, y: (ox + x, oy + y)
    A, B, C, D = P(0, 0), P(s, 0), P(s, s), P(0, s)
    T, Rr, Bm, L = P(s / 2, 0), P(s, s / 2), P(s / 2, s), P(0, s / 2)
    O = P(s / 2, s / 2)
    p1, p2, p3, p4 = P(s / 4, s / 4), P(3 * s / 4, s / 4), P(3 * s / 4, 3 * s / 4), P(s / 4, 3 * s / 4)
    return {
        1: ([T, p1, O, p2], O), 2: ([A, T, p1], p1), 3: ([A, p1, L], p1),
        4: ([L, p1, O, p4], O), 5: ([L, p4, D], p4), 6: ([D, p4, Bm], p4),
        7: ([Bm, p4, O, p3], O), 8: ([Bm, p3, C], p3), 9: ([C, p3, Rr], p3),
        10: ([Rr, p3, O, p2], O), 11: ([Rr, p2, B], p2), 12: ([B, p2, T], p2),
    }


def chunks(seq, n):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def draw_grid(d, polys, ox, oy, s):
    for pts, _ in polys.values():
        d.line(pts + [pts[0]], fill=PENCIL, width=2)
    d.rectangle([ox, oy, ox + s, oy + s], outline=PENCIL, width=2)


def fill_houses(d, polys, lagna_sign, items, asps):
    f_num, f_sym, f_asp = get_font(12), get_sym(18), get_font(18)
    for h, (pts, ref) in polys.items():
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        diamond = len(pts) == 4
        nx = ref[0] + (cx - ref[0]) * 0.25
        ny = ref[1] + (cy - ref[1]) * 0.25
        d.text((nx - 10, ny), str(h), font=f_num, fill=GRAY, anchor="mm")
        d.text((nx + 10, ny), SYM[(lagna_sign + h - 1) % 12], font=f_sym, fill=PENCIL, anchor="mm")
        prow = chunks(items.get(h, []), 3 if diamond else 2)
        arow = chunks(asps.get(h, []), 4 if diamond else 3)
        p_step, a_step, gap = 34, 30, 10
        total = len(prow) * p_step + ((gap + len(arow) * a_step) if arow else 0)
        y = cy - total / 2 + p_step / 2
        for row in prow:
            n = len(row)
            for i, (txt, font, col) in enumerate(row):
                d.text((cx + (i - (n - 1) / 2) * 66, y), txt, font=font, fill=col, anchor="mm")
            y += p_step
        if arow:
            y += gap - p_step / 2 + a_step / 2
            for row in arow:
                n = len(row)
                for i, c in enumerate(row):
                    x = cx + (i - (n - 1) / 2) * 32
                    d.ellipse([x - 13, y - 13, x + 13, y + 13], outline=GRAY, width=1)
                    d.text((x, y), c, font=f_asp, fill=GRAY, anchor="mm")
                y += a_step


def short(s, n):
    return s if len(s) <= n else s[:n - 1] + "…"


def draw_d1(data):
    img, d = sheet(900, 980)
    title = f"РАШИ (D1) • {short(data['name'], 16)} • {short(data['city'], 18)}, {data['date']} {data['time']}"
    d.text((450, 45), title, font=get_font(20, True), fill=PEN, anchor="mm")
    ox, oy, s = 40, 80, 820
    polys = house_polys(ox, oy, s)
    draw_grid(d, polys, ox, oy, s)
    items = {}
    for r in data["rows"]:
        bold, col = STYLE[r["key"]]
        items.setdefault(r["house"], []).append((lbl(r), get_font(26, bold), col))
    asps = {}
    for h in range(1, 13):
        here = [r["code"] for r in data["rows"] if r["house"] == h]
        asps[h] = [c for c in data["aspects"][h - 1] if c not in here]
    # порядок планет в доме
    for h in items:
        items[h].sort(key=lambda t: ORDER.index(t[0].strip("()")))
    fill_houses(d, polys, data["lagna"], items, asps)

    # легенда
    legend = [("Лагна", "lagna"), ("Экзальтация", "exalt"), ("Свой знак", "own"), ("Друг", "friend"),
              ("Нейтральный", "neutral"), ("Враг / падение", "enemy")]
    fonts = [get_font(15, STYLE[k][0]) for _, k in legend]
    widths = [d.textlength(t, font=f) for (t, _), f in zip(legend, fonts)]
    total = sum(widths) + 22 * (len(legend) - 1)
    x = 450 - total / 2
    for (t, k), f, w in zip(legend, fonts, widths):
        d.text((x, 925), t, font=f, fill=STYLE[k][1], anchor="lm")
        x += w + 22
    d.text((450, 955), "Карта Раши (D1) • Юля Мани • True Chitrapaksha",
           font=get_font(14), fill=GRAY, anchor="mm")
    return img


def draw_d9(data):
    img, d = sheet(900, 960)
    d.text((450, 42), f"НАВАМША (D9) • {short(data['name'], 28)}", font=get_font(22, True),
           fill=PEN, anchor="mm")
    ox, oy, s = 40, 90, 820
    polys = house_polys(ox, oy, s)
    draw_grid(d, polys, ox, oy, s)
    items = {}
    for r in data["rows"]:
        items.setdefault(r["nav_house"], []).append((lbl(r), get_font(26), PEN))
    for h in items:
        items[h].sort(key=lambda t: ORDER.index(t[0].strip("()")))
    fill_houses(d, polys, data["nav_lagna"], items, {})
    return img


def wrap_text(d, text, font, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def passport_items(data):
    lag = R(data, "As")
    lord = R(data, SIGN_LORDS[data["lagna"]])
    ak = next((r for r in data["rows"] if r["karaka"] == "АК"), None)
    mo, su, ra, ke = R(data, "Mo"), R(data, "Su"), R(data, "Ra"), R(data, "Ke")
    _, md, ad, pd, _ = periods(data)
    t = data["tithi"]
    nk = lambda r: f"{r['nak']}, пада {r['pada']}"
    return [
        ("1. Дата, местное время (UTC), город",
         f"{data['date']}, {data['time']} (UTC {data['utc_str']}), {data['city']}"),
        ("2. Лагна", f"{lag['sign_name']} {fd(lag['deg'])} • {nk(lag)}"),
        ("3. Лагнеш", f"{lord['name']} в знаке {lord['sign_name']}, {lord['house']} дом • {nk(lord)}"),
        ("4. Атмакарака (АК)", f"{ak['name']} • {ak['sign_name']} • {nk(ak)}" if ak else "—"),
        ("5. Луна", f"{mo['sign_name']} • {nk(mo)}"),
        ("6. Солнце", f"{su['sign_name']} • {nk(su)}"),
        ("7. Ось Раху / Кету",
         f"Раху: {ra['sign_name']}, {ra['house']} дом • Кету: {ke['sign_name']}, {ke['house']} дом"),
        ("8. Лунные сутки (Титхи)", f"{t['num']} • {t['paksha']} • {t['name']}"),
        ("9. Текущий период Вимшоттари Даша",
         f"МД {NAMES[md[0]]} / АД {NAMES[ad[0]]} / ПД {NAMES[pd[0]]}; АД до {dd(ad[2])}"),
    ]


def draw_passport(data):
    img, d = sheet(900, 960)
    d.text((450, 60), f"АСТРО-ПАСПОРТ • {short(data['name'], 26)}", font=get_font(26, True),
           fill=PEN, anchor="mm")
    d.line([(40, 95), (860, 95)], fill=PENCIL, width=2)
    y = 120
    for key, val in passport_items(data):
        d.text((50, y), key.upper(), font=get_font(13), fill=GRAY, anchor="lm")
        lines = wrap_text(d, val, get_font(20, True), 800)[:2]
        for i, ln in enumerate(lines):
            d.text((50, y + 26 + i * 26), ln, font=get_font(20, True), fill=PEN, anchor="lm")
        y += 84
        d.line([(40, y - 10), (860, y - 10)], fill=PENCIL, width=1)
    return img


def render_all(data):
    out = []
    for fn, name in ((draw_d1, "d1.png"), (draw_d9, "d9.png"), (draw_passport, "passport.png")):
        buf = io.BytesIO()
        fn(data).save(buf, format="PNG")
        out.append((name, buf.getvalue()))
    return out


# ================================================================ ТЕКСТЫ
def specials(r):
    s = []
    if r["varg"]:
        s.append("Варготтама (знак D1 = знак D9)")
    if r["combust"]:
        s.append("Сожжение / Аста (близость к Солнцу)")
    if r["gandanta"]:
        s.append("Гандантa (стык водных и огненных знаков)")
    if r["retro"] and r["code"] in ("Ma", "Me", "Ju", "Ve", "Sa"):
        s.append("Ретроградность: высокая внутренняя сила (Чешта-бала)")
    elif r["retro"]:
        s.append("Ретроградность")
    return s


def table_text(data):
    head = f"{'Тчк':<5}{'Знак':<9}{'Град':<8}{'Дом':<4}{'D9':<4}{'БАВ':<4}Кар"
    lines = [head, "-" * 40]
    for r in data["rows"]:
        bv = "-" if r["bav"] is None else str(r["bav"])
        lines.append(f"{lbl(r):<5}{r['sign_name'][:8]:<9}{fd(r['deg']):<8}{r['house']:<4}"
                     f"{r['nav_house']:<4}{bv:<4}{r['karaka'] or '-'}")
    lines.append("")
    lines.append("САВ по домам: " + " ".join(f"{i + 1}:{v}" for i, v in enumerate(data["sav"])))
    lines.append("")
    for r in data["rows"][1:]:
        if r["code"] in ("Ra", "Ke"):
            lines.append(f"{lbl(r)}: {r['nak']} ({r['pada']})")
        else:
            lines.append(f"{lbl(r)}: {r['status']}; {r['nak']} ({r['pada']})")
    return "<pre>" + html.escape("\n".join(lines)) + "</pre>"


def lagna_text(data):
    lag = R(data, "As")
    ls = data["lagna"]
    lord = R(data, SIGN_LORDS[ls])
    nl = data["nav_lagna"]
    t = [f"<b>Лагна D1:</b> {SIGNS[ls]} {fd(lag['deg'])} — {SIGN_TRAITS[ls]}.",
         f"<b>Лагнеш:</b> {lord['name']} в знаке {lord['sign_name']}, {lord['house']} доме "
         f"({HOUSE_KEY[lord['house'] - 1]}); статус: {lord['status']}.",
         f"<b>Лагна D9:</b> {SIGNS[nl]} — {SIGN_TRAITS[nl]}. Лагнеш в D9: {lord['nav_house']} дом.",
         f"<b>Титхи:</b> {data['tithi']['num']} ({data['tithi']['paksha']}, {data['tithi']['name']})."]
    if data["rectify"]:
        t.append("⚠️ Градус Лагны пограничный (менее 1,5° или более 28,5°): небольшая неточность времени "
                 "может сменить знак. Рекомендуется ректификация времени рождения.")
    return "\n".join(t)


def planet_overview(data, code):
    r = R(data, code)
    ruled = ", ".join(map(str, r["rules"])) if r["rules"] else "— (узел не управляет знаками)"
    out = [f"<b>🪐 {r['name']} ({lbl(r)})</b> — бесплатный базовый обзор", "",
           f"Знак: {r['sign_name']}, {fd(r['deg'])}, {r['house']} дом ({HOUSE_KEY[r['house'] - 1]})",
           f"Накшатра: {r['nak']}, пада {r['pada']}",
           f"Управляет домами: {ruled}",
           f"Чара-карака: {r['karaka'] or '—'}",
           f"Самбандха в знаке D1: {r['status']}"]
    if r["bav"] is not None:
        out.append(f"БАВ в своем знаке: {r['bav']} • САВ {r['house']} дома: {data['sav'][r['house'] - 1]}")
    else:
        out.append(f"САВ {r['house']} дома: {data['sav'][r['house'] - 1]}")
    sp = specials(r)
    out.append("Особые состояния: " + ("; ".join(sp) if sp else "нет"))
    out.append(f"Навамша D9: {SIGNS[r['nav_sign']]}, {r['nav_house']} дом от Лагны D9")
    asp = [NAMES[c] for c in data["aspects"][r["house"] - 1] if c != code]
    out.append("Аспекты на дом планеты: " + (", ".join(asp) if asp else "нет"))
    out.append("")
    out.append(f"<b>Синтез:</b> {STATUS_PHRASE.get(r['key'], 'опорная точка карты')}. "
               f"Тема проявления — {HOUSE_KEY[r['house'] - 1]}.")
    return "\n".join(out)


def house_overview(data, h):
    s = (data["lagna"] + h - 1) % 12
    lord = R(data, SIGN_LORDS[s])
    here = [lbl(r) + " " + r["name"] for r in data["rows"] if r["house"] == h and r["code"] != "As"]
    if h == 1:
        here.insert(0, "Лагна")
    asp = [NAMES[c] for c in data["aspects"][h - 1]]
    kar = HOUSE_KARAKA[h - 1]
    if h == 7:
        kar = "Юпитер" if data["gender"] == "f" else "Венера"
    v = data["sav"][h - 1]
    lvl = "высокий" if v >= 30 else ("низкий" if v < 25 else "средний")
    return "\n".join([
        f"<b>🏛 {h} дом — {HOUSE_KEY[h - 1]}</b> — бесплатный базовый обзор", "",
        f"Знак: {SIGNS[s]} {SYM[s]}", f"САВ: {v} ({lvl} уровень)",
        "Планеты в доме: " + (", ".join(here) if here else "пусто"),
        "Аспекты (дришти): " + (", ".join(asp) if asp else "нет"),
        f"Управитель: {lord['name']} — в D1 {lord['sign_name']}, {lord['house']} дом; "
        f"в D9 {lord['nav_house']} дом",
        f"Карака дома: {kar}", "",
        f"<b>Синтез:</b> тема дома раскрывается через {lord['name']} "
        f"({lord['status']}) и поддерживается баллом САВ {v}."])


def dasha_overview(data):
    mds, md, ad, pd, nxt = periods(data)
    out = ["<b>⏳ Вимшоттари Даша</b> — бесплатный базовый обзор", "",
           f"Махадаша: {NAMES[md[0]]} ({dd(md[1])} – {dd(md[2])})",
           f"Антардаша: {NAMES[ad[0]]} (до {dd(ad[2])})",
           f"Пратьянтардаша: {NAMES[pd[0]]} (до {dd(pd[2])})"]
    if nxt:
        out.append(f"Следующая антардаша: {NAMES[nxt[0]]} с {dd(nxt[1])}")
    out.append("")
    out.append("<b>Все Махадаши:</b>")
    for l, s, e in mds:
        mark = " ◀ сейчас" if l == md[0] else ""
        out.append(f"{NAMES[l]}: {dd(s)} – {dd(e)}{mark}")
    return "\n".join(out)


def ashtaka_overview(data):
    sav = data["sav"]
    out = ["<b>📊 Аштакаварга</b> — бесплатный базовый обзор", "", "<b>САВ по домам:</b>"]
    for i, v in enumerate(sav):
        mark = " ▲" if v >= 30 else (" ▼" if v < 25 else "")
        out.append(f"{i + 1} дом ({HOUSE_KEY[i]}): {v}{mark}")
    out.append(f"Сумма: {sum(sav)} (канон 337)")
    out.append("")
    out.append("<b>БАВ планет в их знаках:</b>")
    for c in ["Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa"]:
        r = R(data, c)
        out.append(f"{r['name']}: {r['bav']}")
    out.append("")
    out.append("▲ — 30 и выше (опора), ▼ — ниже 25 (зона проработки).")
    return "\n".join(out)


def chart_summary(data):
    L = [f"Пол: {'Ж' if data['gender'] == 'f' else 'М'}. Стиль: "
         f"{'с астро-терминами' if data['style'] == 'term' else 'простым языком'}.",
         f"Лагна: {SIGNS[data['lagna']]} {fd(R(data, 'As')['deg'])}; Лагна D9: {SIGNS[data['nav_lagna']]}."]
    for r in data["rows"][1:]:
        sp = "; ".join(specials(r))
        L.append(f"{r['name']}{'(R)' if r['retro'] else ''}: {r['sign_name']} {fd(r['deg'])}, {r['house']} дом, "
                 f"{r['status']}, {r['nak']}-{r['pada']}, D9 дом {r['nav_house']}, "
                 f"управляет {r['rules'] or '-'}, карака {r['karaka'] or '-'}, БАВ {r['bav']}"
                 + (f", {sp}" if sp else ""))
    L.append("САВ домов: " + ", ".join(f"{i + 1}:{v}" for i, v in enumerate(data["sav"])))
    _, md, ad, pd, _ = periods(data)
    L.append(f"Даша: МД {NAMES[md[0]]}, АД {NAMES[ad[0]]} до {dd(ad[2])}, ПД {NAMES[pd[0]]}")
    return "\n".join(L)


# ================================================================ LLM
async def ask_llm(data, question):
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY не задан")
    style = ("Используй санскритские термины с краткими пояснениями." if data["style"] == "term"
             else "Пиши простым языком без сложных терминов.")
    system = ("Ты — практикующий астролог Джйотиш (школа Юли Мани). Отвечай по-русски, тепло и конкретно, "
              "строго опираясь на данные карты. Обращайся с учетом пола. " + style +
              " Без запугивания и медицинских диагнозов. Объем до 1800 знаков.")
    payload = {"model": LLM_MODEL, "max_tokens": 900, "temperature": 0.7,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": f"Данные карты:\n{chart_summary(data)}\n\nВопрос: {question}"}]}
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    url = LLM_BASE.rstrip("/") + "/v1/chat/completions"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
        async with s.post(url, json=payload, headers=headers) as r:
            js = await r.json(content_type=None)
            if r.status != 200:
                raise RuntimeError(str(js)[:300])
            return js["choices"][0]["message"]["content"].strip()


# ================================================================ БОТ
router = Router()

MAIN_KB = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🗺 Новая карта"), KeyboardButton(text="🗂 Банк карт")],
    [KeyboardButton(text="🎯 Разбор и вопросы")]], resize_keyboard=True)

WELCOME = ("Добро пожаловать в пространство ведической астрологии Джйотиш от Юли Мани ✨\n"
           "Я помогу построить вашу карту Раши (D1), дробную карту Навамша (D9) и персональный "
           "Астро-паспорт на эстетичном чертеже, а также глубже понять ваши таланты, отношения и "
           "текущие периоды жизни.\n"
           "Для начала давайте создадим запись в вашей картотеке. Как подписать эту карту? "
           "(Например: Юлия, Муж, Мама)")
GENDER_TXT = ("Приятно познакомиться! Укажите, пожалуйста, пол для этой карты — в Джйотиш это важно для "
              "точного анализа показателей брака и выбора правильных обращений в разборе:")
DATE_TXT = "Теперь напишите дату рождения в формате ДД.ММ.ГГГГ (например: 27.02.1988):"
TIME_TXT = ("Укажите точное местное время рождения в формате ЧЧ:ММ (например: 16:35).\n"
            "🕰 Важно: в ведической астрологии восходящий знак (Лагна) и дробная карта D9 меняются каждые "
            "1,5–2 часа, а иногда и за считанные минуты. Лучше всего указать время строго по бирке из "
            "роддома. Если точное время пока неизвестно — напишите примерное (например, 12:00), но "
            "учитывайте, что для глубинного анализа потребуется ректификация.")
CITY_TXT = ("Напишите населенный пункт фактического рождения (город, поселок или село). Если рядом с местом "
            "рождения не было роддома, укажите именно тот город, где человек фактически появился на свет:")
STYLE_TXT = "Почти готово! В каком стиле вам комфортнее получать расшифровки?"


class Form(StatesGroup):
    name = State()
    gender = State()
    date = State()
    time = State()
    city = State()
    pick = State()
    style = State()
    confirm = State()


class Misc(StatesGroup):
    search = State()
    ask = State()
    ask_confirm = State()


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(**b) for b in row] for row in rows])


def btn(text, cb=None, url=None):
    return {"text": text, **({"callback_data": cb} if cb else {"url": url})}


async def begin_form(message, state, uid):
    await state.clear()
    u = get_user(uid)
    if len(charts_of(uid)) >= u["max_charts"]:
        await message.answer(
            f"Картотека заполнена: занято {len(charts_of(uid))} из {u['max_charts']} слотов.\n"
            "Удалите одну из карт или расширьте лимит.",
            reply_markup=kb([[btn("🗂 Перейти в Банк карт", "bank")],
                             [btn("✨ Расширить лимит слотов", "tariff")]]))
        return
    await state.set_state(Form.name)
    await message.answer(WELCOME, reply_markup=MAIN_KB)


@router.message(CommandStart())
@router.message(F.text == "🗺 Новая карта")
async def cmd_start(message: Message, state: FSMContext):
    await begin_form(message, state, message.from_user.id)


@router.callback_query(F.data == "newchart")
async def cb_new(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await begin_form(cb.message, state, cb.from_user.id)


@router.message(Form.name, F.text)
async def f_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip()[:40])
    await state.set_state(Form.gender)
    await message.answer(GENDER_TXT, reply_markup=kb([[btn("♂ Мужской", "g:m"), btn("♀ Женский", "g:f")]]))


@router.callback_query(Form.gender, F.data.startswith("g:"))
async def f_gender(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(gender=cb.data[2:])
    await state.set_state(Form.date)
    await cb.message.answer(DATE_TXT)


@router.message(Form.date, F.text)
async def f_date(message: Message, state: FSMContext):
    try:
        datetime.strptime(message.text.strip(), "%d.%m.%Y")
    except ValueError:
        await message.answer("Неверный формат. Пример: 27.02.1988")
        return
    await state.update_data(date=message.text.strip())
    await state.set_state(Form.time)
    await message.answer(TIME_TXT)


@router.message(Form.time, F.text)
async def f_time(message: Message, state: FSMContext):
    try:
        datetime.strptime(message.text.strip(), "%H:%M")
    except ValueError:
        await message.answer("Неверный формат. Пример: 16:35")
        return
    await state.update_data(time=message.text.strip())
    await state.set_state(Form.city)
    await message.answer(CITY_TXT)


def geocode_many(q):
    res = Nominatim(user_agent="jyotish_yulia_bot").geocode(q, exactly_one=False, limit=4, language="ru")
    return [{"addr": g.address, "lat": g.latitude, "lon": g.longitude} for g in (res or [])]


@router.message(Form.city, F.text)
async def f_city(message: Message, state: FSMContext):
    wait = await message.answer("Ищу место...")
    try:
        cands = await asyncio.to_thread(geocode_many, message.text.strip())
    except Exception as e:
        await wait.edit_text(f"Ошибка геокодера: {e}\nПопробуйте еще раз.")
        return
    if not cands:
        await wait.edit_text("Место не найдено. Уточните название и отправьте снова:")
        return
    await state.update_data(cands=cands)
    await state.set_state(Form.pick)
    b = InlineKeyboardBuilder()
    for i, c in enumerate(cands):
        b.button(text=short(c["addr"], 60), callback_data=f"city:{i}")
    b.adjust(1)
    await wait.edit_text("Выберите нужный вариант:", reply_markup=b.as_markup())


@router.callback_query(Form.pick, F.data.startswith("city:"))
async def f_pick(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    c = data["cands"][int(cb.data.split(":")[1])]
    await state.update_data(lat=c["lat"], lon=c["lon"], address=c["addr"], city=c["addr"].split(",")[0])
    await state.set_state(Form.style)
    await cb.message.answer(STYLE_TXT, reply_markup=kb([
        [btn("📚 С астро-терминами", "st:term")], [btn("📕 Простым языком (без сложных слов)", "st:simple")]]))


@router.callback_query(Form.style, F.data.startswith("st:"))
async def f_style(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(style=cb.data[3:])
    d = await state.get_data()
    await state.set_state(Form.confirm)
    await cb.message.answer(
        "<b>Проверьте анкету:</b>\n"
        f"Имя карты: {html.escape(d['name'])}\n"
        f"Пол: {'женский' if d['gender'] == 'f' else 'мужской'}\n"
        f"Дата: {d['date']}\nВремя: {d['time']}\n"
        f"Место: {html.escape(d['address'])}\n"
        f"Стиль: {'с астро-терминами' if d['style'] == 'term' else 'простым языком'}",
        parse_mode="HTML",
        reply_markup=kb([[btn("✅ Да, построить карту", "go:yes")], [btn("🔄 Начать сначала", "go:no")]]))


@router.callback_query(Form.confirm, F.data.startswith("go:"))
async def f_go(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    uid = cb.from_user.id
    if cb.data == "go:no":
        await begin_form(cb.message, state, uid)
        return
    d = await state.get_data()
    u = get_user(uid)
    if len(charts_of(uid)) >= u["max_charts"]:
        await state.clear()
        await cb.message.answer("Лимит слотов исчерпан.", reply_markup=kb([[btn("🗂 Перейти в Банк карт", "bank")]]))
        return
    wait = await cb.message.answer("Считаю карту и рисую чертежи...")
    try:
        chart = await asyncio.to_thread(build_chart, d["name"], d["gender"], d["date"], d["time"],
                                        d["city"], d["style"], d["lat"], d["lon"], d["address"])
        imgs = await asyncio.to_thread(render_all, chart)
    except Exception as e:
        await wait.edit_text(f"Ошибка расчета: {e}\nНачните заново: /start")
        await state.clear()
        return
    await state.clear()
    cid = save_chart(uid, chart)
    await wait.delete()
    await deliver(cb.message, chart, imgs)


async def deliver(message, chart, imgs=None):
    if imgs is None:
        imgs = await asyncio.to_thread(render_all, chart)
    media = [InputMediaPhoto(media=BufferedInputFile(b, filename=n)) for n, b in imgs]
    await message.answer_media_group(media=media)
    await message.answer(
        f"<b>{html.escape(chart['name'])}</b> • {chart['date']} {chart['time']} • {html.escape(chart['city'])}\n"
        f"UTC {chart['utc_str']} • {chart['tz']}\nTrue Chitrapaksha, True Node. (X) — ретроградность.\n\n"
        + table_text(chart) + "\n" + lagna_text(chart),
        parse_mode="HTML",
        reply_markup=kb([[btn("🎯 Разбор и вопросы по карте", "menu")]]))


# ---------------------------------------------------------------- Банк карт
async def show_bank(message, uid, query=None, edit=False):
    u = get_user(uid)
    ch = charts_of(uid)
    if query:
        ch = [c for c in ch if query.lower() in c["name"].lower()]
    b = InlineKeyboardBuilder()
    for c in ch:
        b.row(InlineKeyboardButton(text=short(f"📂 {c['name']} • {c['date']}", 40), callback_data=f"sel:{c['id']}"),
              InlineKeyboardButton(text="🗑", callback_data=f"del:{c['id']}"))
    b.row(InlineKeyboardButton(text="🔍 Поиск", callback_data="srch"),
          InlineKeyboardButton(text="🗺 Новая карта", callback_data="newchart"))
    text = (f"<b>🗂 Банк карт</b>\nСлоты: {len(charts_of(uid))} из {u['max_charts']}"
            + ("" if ch else "\nКарты не найдены."))
    if edit:
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())
            return
        except Exception:
            pass
    await message.answer(text, parse_mode="HTML", reply_markup=b.as_markup())


@router.message(Command("bank"))
@router.message(F.text == "🗂 Банк карт")
async def cmd_bank(message: Message, state: FSMContext):
    await state.clear()
    await show_bank(message, message.from_user.id)


@router.callback_query(F.data == "bank")
async def cb_bank(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    await show_bank(cb.message, cb.from_user.id)


@router.callback_query(F.data == "srch")
async def cb_search(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(Misc.search)
    await cb.message.answer("Введите имя (или часть имени) карты для поиска:")


@router.message(Misc.search, F.text)
async def do_search(message: Message, state: FSMContext):
    await state.clear()
    await show_bank(message, message.from_user.id, query=message.text.strip())


@router.callback_query(F.data.startswith("sel:"))
async def cb_sel(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    cid = int(cb.data[4:])
    chart = load_chart(cid, uid)
    if not chart:
        await cb.message.answer("Карта не найдена.")
        return
    set_active(uid, cid)
    await deliver(cb.message, chart)


@router.callback_query(F.data.startswith("del:"))
async def cb_del(cb: CallbackQuery):
    await cb.answer()
    cid = cb.data[4:]
    await cb.message.edit_text(
        "Удалить эту карту? Купленные слоты сохранятся.",
        reply_markup=kb([[btn("✅ Да, удалить", f"dely:{cid}"), btn("❌ Отмена", "bank")]]))


@router.callback_query(F.data.startswith("dely:"))
async def cb_dely(cb: CallbackQuery):
    await cb.answer("Удалено")
    delete_chart(cb.from_user.id, int(cb.data[5:]))
    await show_bank(cb.message, cb.from_user.id, edit=True)


# ---------------------------------------------------------------- Меню разбора
def menu_kb():
    return kb([[btn("🪐 9 Планет (Грахи)", "sec:pl")], [btn("🏛 12 Сфер жизни (Бхавы)", "sec:bh")],
               [btn("⏳ Периоды (Вимшоттари Даша)", "sec:da")], [btn("📊 Сила карты (Аштакаварга)", "sec:av")]])


async def need_chart(message, uid):
    cid, data = active_chart(uid)
    if not data:
        await message.answer("Сначала постройте или выберите карту.",
                             reply_markup=kb([[btn("🗺 Новая карта", "newchart")], [btn("🗂 Банк карт", "bank")]]))
    return data


@router.message(Command("menu"))
@router.message(F.text == "🎯 Разбор и вопросы")
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    data = await need_chart(message, message.from_user.id)
    if data:
        await message.answer(f"<b>🎯 Разбор карты «{html.escape(data['name'])}»</b>\nВыберите раздел:",
                             parse_mode="HTML", reply_markup=menu_kb())


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    data = await need_chart(cb.message, cb.from_user.id)
    if data:
        await cb.message.answer(f"<b>🎯 Разбор карты «{html.escape(data['name'])}»</b>\nВыберите раздел:",
                                parse_mode="HTML", reply_markup=menu_kb())


@router.callback_query(F.data.startswith("sec:"))
async def cb_section(cb: CallbackQuery):
    await cb.answer()
    data = await need_chart(cb.message, cb.from_user.id)
    if not data:
        return
    sec = cb.data[4:]
    b = InlineKeyboardBuilder()
    if sec == "pl":
        for c in NINE:
            b.button(text=NAMES[c], callback_data=f"pl:{c}")
        b.adjust(3)
        await cb.message.answer("Выберите планету:", reply_markup=b.as_markup())
    elif sec == "bh":
        for i in range(12):
            b.button(text=f"{i + 1} • {HOUSE_TITLES[i]}", callback_data=f"bh:{i + 1}")
        b.adjust(2)
        await cb.message.answer("Выберите сферу жизни:", reply_markup=b.as_markup())
    elif sec == "da":
        await send_topic(cb.message, data, "da", "0")
    else:
        await send_topic(cb.message, data, "av", "0")


@router.callback_query(F.data.regexp(r"^(pl|bh):"))
async def cb_topic(cb: CallbackQuery):
    await cb.answer()
    data = await need_chart(cb.message, cb.from_user.id)
    if data:
        kind, arg = cb.data.split(":")
        await send_topic(cb.message, data, kind, arg)


async def send_topic(message, data, kind, arg):
    if kind == "pl":
        txt = planet_overview(data, arg)
    elif kind == "bh":
        txt = house_overview(data, int(arg))
    elif kind == "da":
        txt = dasha_overview(data)
    else:
        txt = ashtaka_overview(data)
    await message.answer(txt, parse_mode="HTML")
    await show_questions(message, kind, arg)


async def show_questions(message, kind, arg, edit=False):
    qs = get_questions(kind, arg)
    text = ("<b>Дополнительные вопросы</b> (1 вопрос = 1 списание с баланса)\n\n"
            + "\n".join(f"{i + 1}. {html.escape(q)}" for i, q in enumerate(qs)))
    b = InlineKeyboardBuilder()
    for i in range(len(qs)):
        b.button(text=str(i + 1), callback_data=f"q:{kind}:{arg}:{i + 1}")
    b.adjust(6 if len(qs) > 9 else 5)
    b.row(InlineKeyboardButton(text="✍️ Задать свой вопрос", callback_data=f"qa:{kind}:{arg}"))
    if edit:
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=b.as_markup())
            return
        except Exception:
            pass
    await message.answer(text, parse_mode="HTML", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("qb:"))
async def cb_qback(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    _, kind, arg = cb.data.split(":")
    await show_questions(cb.message, kind, arg, edit=True)


@router.callback_query(F.data.regexp(r"^q:"))
async def cb_qconfirm(cb: CallbackQuery):
    await cb.answer()
    _, kind, arg, n = cb.data.split(":")
    q = get_questions(kind, arg)[int(n) - 1]
    u = get_user(cb.from_user.id)
    await cb.message.edit_text(
        f"<b>Вопрос {n}:</b>\n{html.escape(q)}\n\nСтоимость: 1 вопрос\nВаш баланс: {u['questions_balance']}",
        parse_mode="HTML",
        reply_markup=kb([[btn("✅ Да, получить ответ", f"qy:{kind}:{arg}:{n}")],
                         [btn("⬅️ Назад к списку вопросов", f"qb:{kind}:{arg}")]]))


async def run_question(message, uid, data, question):
    if not spend_question(uid):
        await message.answer("Баланс вопросов — 0. Пополните его, чтобы получить ответ.",
                             reply_markup=kb([[btn("✨ Тарифы", "tariff")]]))
        return
    wait = await message.answer("✨ Готовлю ответ...")
    try:
        ans = await ask_llm(data, question)
    except Exception as e:
        add_questions(uid, 1)
        await wait.edit_text(f"Не удалось получить ответ ({str(e)[:150]}). Вопрос возвращен на баланс.")
        return
    await wait.delete()
    for i in range(0, len(ans), 4000):
        await message.answer(ans[i:i + 4000])
    u = get_user(uid)
    await message.answer(f"Осталось вопросов: {u['questions_balance']}",
                         reply_markup=kb([[btn("🎯 Разбор и вопросы", "menu")]]))


@router.callback_query(F.data.startswith("qy:"))
async def cb_qyes(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    data = await need_chart(cb.message, uid)
    if not data:
        return
    _, kind, arg, n = cb.data.split(":")
    await run_question(cb.message, uid, data, get_questions(kind, arg)[int(n) - 1])


@router.callback_query(F.data.startswith("qa:"))
async def cb_qask(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(Misc.ask)
    await cb.message.answer("Напишите свой вопрос по активной карте одним сообщением:")


@router.message(Misc.ask, F.text)
async def f_ask(message: Message, state: FSMContext):
    await state.update_data(question=message.text.strip()[:600])
    await state.set_state(Misc.ask_confirm)
    u = get_user(message.from_user.id)
    await message.answer(
        f"<b>Ваш вопрос:</b>\n{html.escape(message.text.strip()[:600])}\n\n"
        f"Стоимость: 1 вопрос\nВаш баланс: {u['questions_balance']}", parse_mode="HTML",
        reply_markup=kb([[btn("✅ Да, получить ответ", "cy")], [btn("❌ Отмена", "cn")]]))


@router.callback_query(Misc.ask_confirm, F.data.in_({"cy", "cn"}))
async def f_ask_ok(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    d = await state.get_data()
    await state.clear()
    if cb.data == "cn":
        await cb.message.answer("Отменено.")
        return
    data = await need_chart(cb.message, cb.from_user.id)
    if data:
        await run_question(cb.message, cb.from_user.id, data, d["question"])


# ---------------------------------------------------------------- Профиль, тарифы, о проекте
@router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    u = get_user(uid)
    cid, data = active_chart(uid)
    await message.answer(
        f"<b>👤 Мой профиль</b>\nID: <code>{uid}</code>\n"
        f"Активная карта: {html.escape(data['name']) if data else 'не выбрана'}\n"
        f"Слоты: {len(charts_of(uid))} из {u['max_charts']}\n"
        f"Баланс вопросов: {u['questions_balance']}",
        parse_mode="HTML", reply_markup=kb([[btn("✨ Тарифы", "tariff")]]))


TARIFF_TXT = ("<b>✨ Тарифы</b>\n\n"
              "🔥 1 вопрос (Число Марса) — 9 ₽\n"
              "🌿 5 вопросов — 39 ₽\n"
              "🌙 21 вопрос (Полный разбор карты) — 149 ₽\n"
              "🪐 108 вопросов (Пакет Астролог) — 499 ₽\n\n"
              "🗂 +1 слот в Банке карт (навсегда) — 49 ₽\n"
              "📚 +10 слотов в Банке карт (Картотека) — 149 ₽\n\n"
              "Оформление и подбор камней — у Юли Мани.")
TARIFF_KB = kb([[btn("✉️ Оформить у Юли Мани", url=PRO_LINK)],
                [btn("💎 Подобрать камень по карте", url=STONES_CHANNEL_LINK)]])


@router.message(Command("tariff"))
async def cmd_tariff(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(TARIFF_TXT, parse_mode="HTML", reply_markup=TARIFF_KB)


@router.callback_query(F.data == "tariff")
async def cb_tariff(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer(TARIFF_TXT, parse_mode="HTML", reply_markup=TARIFF_KB)


@router.message(Command("about"))
async def cmd_about(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "<b>О проекте</b>\nДжйотиш-бот Юли Мани: карта Раши (D1), Навамша (D9) и Астро-паспорт на "
        "чертеже белого ватмана. Айанамша — True Chitrapaksha, узлы — истинные.\n\n"
        "<b>Как читать чертеж:</b>\n"
        "• Дома неподвижны: верхний ромб — 1 дом (Лагна), дальше против часовой стрелки.\n"
        "• Маленькая цифра — номер дома, рядом символ знака зодиака.\n"
        "• As — Лагна. (Ra) / (Ke) и другие в скобках — ретроградные.\n"
        "• Цвет планеты — её состояние в знаке: зеленый — экзальтация/свой знак, синий — друг, "
        "черный — нейтральный, красно-бордовый — враг/падение.\n"
        "• Серые кружки — аспекты (граха-дришти) на дом.",
        parse_mode="HTML",
        reply_markup=kb([[btn("💎 Браслеты-резонаторы (Telegram)", url=STONES_CHANNEL_LINK)],
                         [btn("📸 Instagram @space_pill", url=INSTAGRAM_LINK)],
                         [btn("✉️ Написать Юле Мани", url=PRO_LINK)]]))


# ---------------------------------------------------------------- Админ
@router.message(Command("add_q"))
async def cmd_add_q(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        uid, n = map(int, command.args.split())
    except Exception:
        await message.answer("Формат: /add_q <user_id> <кол-во>")
        return
    add_questions(uid, n)
    await message.answer(f"Пользователю {uid} добавлено вопросов: {n}")


@router.message(Command("add_slot"))
async def cmd_add_slot(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        uid, n = map(int, command.args.split())
    except Exception:
        await message.answer("Формат: /add_slot <user_id> <кол-во>")
        return
    add_slots(uid, n)
    await message.answer(f"Пользователю {uid} добавлено слотов: {n}")


@router.message()
async def fallback(message: Message):
    await message.answer("Выберите действие в меню или нажмите /start.", reply_markup=MAIN_KB)


# ================================================================ ЗАПУСК (Webhook)
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

WEBHOOK_HOST = "https://spacepill.bothost.tech"
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"


async def on_startup(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Построить новую карту"),
        BotCommand(command="bank", description="Банк карт"),
        BotCommand(command="menu", description="Разбор и вопросы по карте"),
        BotCommand(command="profile", description="Мой профиль"),
        BotCommand(command="tariff", description="Тарифы"),
        BotCommand(command="about", description="О проекте и соцсети"),
    ])
    await bot.set_webhook(WEBHOOK_URL)
    print(f"Webhook успешно установлен на {WEBHOOK_URL}", flush=True)


async def main():
    init_db()
    ensure_fonts()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)

    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    port = int(os.getenv("PORT", 3000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Сервер Webhook запущен на порту {port}", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
