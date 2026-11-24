# pip install aiogram pillow pyswisseph geopy timezonefinder
# -*- coding: utf-8 -*-
# Джйотиш-бот: Раши D1 (Lahiri), ретроградность, граха-дришти, чертёж Pillow
import asyncio
import html
import io
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import swisseph as swe
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, Message
from geopy.geocoders import Nominatim
from PIL import Image, ImageDraw, ImageFont
from timezonefinder import TimezoneFinder

BOT_TOKEN = "ВАШ_ТОКЕН_СЮДА"
BOT_TOKEN = os.getenv("BOT_TOKEN", BOT_TOKEN)

# ---------------------------------------------------------------- данные
SIGNS = ["Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
         "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы"]

NAKSHATRAS = ["Ашвини", "Бхарани", "Криттика", "Рохини", "Мригашира", "Ардра",
              "Пунарвасу", "Пушья", "Ашлеша", "Магха", "Пурва Пхалгуни",
              "Уттара Пхалгуни", "Хаста", "Читра", "Свати", "Вишакха", "Анурадха",
              "Джьештха", "Мула", "Пурва Ашадха", "Уттара Ашадха", "Шравана",
              "Дхаништха", "Шатабхиша", "Пурва Бхадрапада", "Уттара Бхадрапада", "Ревати"]

# код, название, id в swisseph
PLANETS = [("Su", "Солнце", swe.SUN), ("Mo", "Луна", swe.MOON),
           ("Ma", "Марс", swe.MARS), ("Me", "Меркурий", swe.MERCURY),
           ("Ju", "Юпитер", swe.JUPITER), ("Ve", "Венера", swe.VENUS),
           ("Sa", "Сатурн", swe.SATURN)]

# Граха-дришти по Парашаре: номера домов от планеты (включительно)
ASPECTS = {"Su": [7], "Mo": [7], "Me": [7], "Ve": [7],
           "Ma": [4, 7, 8], "Ju": [5, 7, 9], "Sa": [3, 7, 10],
           "Ra": [5, 7, 9], "Ke": [5, 7, 9]}

ORDER = ["As", "Su", "Mo", "Ma", "Me", "Ju", "Ve", "Sa", "Ra", "Ke"]

# ---------------------------------------------------------------- шрифты
FONT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_FILES = {
    "NotoSans-Regular.ttf": [
        "https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSans/full/ttf/NotoSans-Regular.ttf",
        "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans-Regular.ttf",
    ],
    "NotoSans-Bold.ttf": [
        "https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSans/full/ttf/NotoSans-Bold.ttf",
        "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans-Bold.ttf",
    ],
}


def ensure_fonts():
    """Скачивает Noto Sans при первом запуске. Без сети — тихий fallback."""
    for fname, urls in FONT_FILES.items():
        path = os.path.join(FONT_DIR, fname)
        if os.path.exists(path) and os.path.getsize(path) > 10000:
            continue
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=15) as r:
                    data = r.read()
                if len(data) > 10000:
                    with open(path, "wb") as f:
                        f.write(data)
                    break
            except Exception as e:
                print(f"Не удалось скачать {fname}: {e}")


_font_cache = {}


def get_font(size, bold=False):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    path = os.path.join(FONT_DIR, "NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf")
    try:
        f = ImageFont.truetype(path, size)
    except Exception:
        try:
            f = ImageFont.load_default(size)
        except Exception:
            f = ImageFont.load_default()
    _font_cache[key] = f
    return f


# ---------------------------------------------------------------- математика
def to_utc(date_str, time_str, city):
    geo = Nominatim(user_agent="jyotish_d1_bot").geocode(city, language="ru")
    if geo is None:
        raise ValueError(f"Город не найден: {city}")
    lat, lon = geo.latitude, geo.longitude
    tz_name = TimezoneFinder().timezone_at(lat=lat, lng=lon)
    if tz_name is None:
        raise ValueError("Не удалось определить часовой пояс")
    local = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
    local = local.replace(tzinfo=ZoneInfo(tz_name))
    return local.astimezone(ZoneInfo("UTC")), lat, lon, tz_name, geo.address


def fmt_deg(deg):
    d = int(deg)
    m = int((deg - d) * 60)
    return f"{d:02d}°{m:02d}'"


def nakshatra(lon):
    span = 360 / 27
    idx = int(lon // span)
    pada = int((lon % span) // (span / 4)) + 1
    return NAKSHATRAS[idx], pada


def calc(jd, pid, flags):
    """Возвращает (долгота, скорость по долготе)."""
    res = swe.calc_ut(jd, pid, flags)
    xx = res[0] if isinstance(res[0], (tuple, list)) else res
    return xx[0] % 360, xx[3]


def build_d1(date_str, time_str, city):
    utc, lat, lon, tz_name, address = to_utc(date_str, time_str, city)
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED

    hour = utc.hour + utc.minute / 60 + utc.second / 3600
    jd = swe.julday(utc.year, utc.month, utc.day, hour)

    _, ascmc = swe.houses_ex(jd, lat, lon, b"P", flags)
    asc = ascmc[0] % 360

    points = [("As", "Лагна (Asc)", asc, False)]
    for code, name, pid in PLANETS:
        L, speed = calc(jd, pid, flags)
        points.append((code, name, L, speed < 0))
    rahu, _ = calc(jd, swe.TRUE_NODE, flags)
    points.append(("Ra", "Раху (True Node)", rahu, False))
    points.append(("Ke", "Кету", (rahu + 180) % 360, False))

    lagna_sign = int(asc // 30)
    rows = []
    for code, name, L, retro in points:
        sign = int(L // 30)
        nak, pada = nakshatra(L)
        rows.append({
            "code": code, "name": name, "lon": L, "sign": sign,
            "sign_name": SIGNS[sign], "deg": L % 30, "retro": retro,
            "house": (sign - lagna_sign) % 12 + 1, "nak": nak, "pada": pada,
        })

    # Граха-дришти: для каждого из 12 домов — кто его аспектирует
    aspects = {h: [] for h in range(1, 13)}
    for r in rows:
        if r["code"] == "As":
            continue
        for k in ASPECTS[r["code"]]:
            target = (r["house"] - 1 + k - 1) % 12 + 1
            if target != r["house"] and r["code"] not in aspects[target]:
                aspects[target].append(r["code"])
    for h in aspects:
        aspects[h].sort(key=ORDER.index)

    return {
        "rows": rows, "aspects": aspects, "lagna_sign": lagna_sign,
        "utc": utc, "lat": lat, "lon": lon, "tz": tz_name, "address": address,
        "date": date_str, "time": time_str, "city": city,
    }


def label(r):
    return f"({r['code']})" if r["retro"] else r["code"]


# ---------------------------------------------------------------- чертёж
W, H = 1200, 850
INK = "#2B2B2B"
PAPER = "#F7F4EB"
GRID = "#E8E2D5"
ACCENT = "#D95D39"
GRAY = "#7A7A7A"
PINK, MINT, BLUE = "#F9ECEC", "#EDF5EE", "#EDF3F8"
S = 740
OX, OY = 40, 55


def house_polys():
    P = lambda x, y: (OX + x, OY + y)
    A, B, C, D = P(0, 0), P(S, 0), P(S, S), P(0, S)
    T, R, Bm, L = P(S / 2, 0), P(S, S / 2), P(S / 2, S), P(0, S / 2)
    O = P(S / 2, S / 2)
    p1, p2 = P(S / 4, S / 4), P(3 * S / 4, S / 4)
    p3, p4 = P(3 * S / 4, 3 * S / 4), P(S / 4, 3 * S / 4)
    # (вершины, опорная вершина для номера знака)
    return {
        1: ([T, p1, O, p2], O), 2: ([A, T, p1], p1), 3: ([A, p1, L], p1),
        4: ([L, p1, O, p4], O), 5: ([L, p4, D], p4), 6: ([D, p4, Bm], p4),
        7: ([Bm, p4, O, p3], O), 8: ([Bm, p3, C], p3), 9: ([C, p3, R], p3),
        10: ([R, p3, O, p2], O), 11: ([R, p2, B], p2), 12: ([B, p2, T], p2),
    }


def chunks(seq, n):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def draw_chart(data):
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    # тетрадная сетка
    for x in range(0, W, 25):
        d.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, 25):
        d.line([(0, y), (W, y)], fill=GRID, width=1)

    # двойная рамка
    d.rectangle([8, 8, W - 9, H - 9], outline=INK, width=2)
    d.rectangle([16, 16, W - 17, H - 17], outline=INK, width=1)

    polys = house_polys()
    kendra = {1, 4, 7, 10}
    others = [2, 3, 5, 6, 8, 9, 11, 12]
    fills = {}
    for i, h in enumerate(others):
        fills[h] = MINT if i % 2 == 0 else BLUE
    for h in kendra:
        fills[h] = PINK

    for h, (pts, _) in polys.items():
        d.polygon(pts, fill=fills[h])
    for h, (pts, _) in polys.items():
        d.line(pts + [pts[0]], fill=INK, width=2)
    d.rectangle([OX, OY, OX + S, OY + S], outline=INK, width=2)

    by_house = {h: [] for h in range(1, 13)}
    for r in data["rows"]:
        by_house[r["house"]].append(r)

    f_num = get_font(16)
    f_pl = get_font(21, True)
    f_asp = get_font(12)

    for h, (pts, ref) in polys.items():
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        diamond = len(pts) == 4

        # номер знака у вершины
        sign_no = (data["lagna_sign"] + h - 1) % 12 + 1
        nx = ref[0] + (cx - ref[0]) * 0.28
        ny = ref[1] + (cy - ref[1]) * 0.28
        d.text((nx, ny), str(sign_no), font=f_num, fill=GRAY, anchor="mm")

        planets = sorted(by_house[h], key=lambda r: ORDER.index(r["code"]))
        p_rows = chunks(planets, 3 if diamond else 2)
        asp_list = [c for c in data["aspects"][h]
                    if c not in [r["code"] for r in planets]]
        a_rows = chunks(asp_list, 4 if diamond else 3)

        p_step, a_step, gap = 28, 30, 10
        total = len(p_rows) * p_step + (gap + len(a_rows) * a_step if a_rows else 0)
        y = cy - total / 2 + p_step / 2
        for row in p_rows:
            n = len(row)
            for i, r in enumerate(row):
                x = cx + (i - (n - 1) / 2) * 54
                col = ACCENT if r["code"] == "As" else INK
                d.text((x, y), label(r), font=f_pl, fill=col, anchor="mm")
            y += p_step
        if a_rows:
            y += gap - p_step / 2 + a_step / 2
            for row in a_rows:
                n = len(row)
                for i, c in enumerate(row):
                    x = cx + (i - (n - 1) / 2) * 30
                    d.ellipse([x - 12, y - 12, x + 12, y + 12], outline=GRAY, width=1)
                    d.text((x, y), c, font=f_asp, fill=GRAY, anchor="mm")
                y += a_step

    # ---- правая карточка-заметка
    cx0, cy0, cx1, cy1 = 810, OY, W - 40, OY + S
    d.rectangle([cx0, cy0, cx1, cy1], fill="#FFFDF7", outline=INK, width=2)
    for yy in range(cy0 + 75, cy1 - 10, 32):
        d.line([(cx0 + 16, yy), (cx1 - 16, yy)], fill="#CFC8B8", width=1)
    d.line([(cx0 + 40, cy0 + 4), (cx0 + 40, cy1 - 4)], fill="#E7B8B0", width=1)

    d.text((cx0 + 56, cy0 + 40), "RASHI D1 • LAHIRI", font=get_font(24, True),
           fill=INK, anchor="lm")

    rows = data["rows"]
    asc = rows[0]
    moon = next(r for r in rows if r["code"] == "Mo")
    f_k = get_font(13)
    f_v = get_font(18, True)

    def note(line_no, key, val, color=INK):
        yy = cy0 + 75 + line_no * 32
        d.text((cx0 + 56, yy - 24), key.upper(), font=f_k, fill=GRAY, anchor="lm")
        d.text((cx0 + 56, yy - 8), val, font=f_v, fill=color, anchor="lm")

    city = data["city"] if len(data["city"]) <= 24 else data["city"][:23] + "…"
    note(1, "Дата рождения", data["date"])
    note(3, "Местное время", data["time"])
    note(5, "Город", city)
    note(7, "Лагна (восходящий знак)",
         f"{asc['sign_name']}  {fmt_deg(asc['deg'])}", ACCENT)
    note(9, "Луна — знак", moon["sign_name"])
    note(11, "Джанма накшатра", f"{moon['nak']} ({moon['pada']})")
    note(13, "Часовой пояс", data["tz"])

    # легенда
    ly = cy1 - 70
    d.line([(cx0 + 16, ly - 18), (cx1 - 16, ly - 18)], fill=INK, width=1)
    f_l = get_font(14)
    d.text((cx0 + 56, ly), "( )", font=get_font(16, True), fill=INK, anchor="lm")
    d.text((cx0 + 100, ly), "— ретроградность", font=f_l, fill=INK, anchor="lm")
    d.ellipse([cx0 + 50, ly + 26 - 9, cx0 + 68, ly + 26 + 9], outline=GRAY, width=1)
    d.text((cx0 + 100, ly + 26), "— аспекты на дом (дришти)", font=f_l, fill=INK, anchor="lm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def table_text(data):
    lines = [
        f"{'Точка':<10}{'Знак':<10}{'Градусы':<8}{'Дом':<4}Накшатра",
        "-" * 50,
    ]
    for r in data["rows"]:
        lines.append(
            f"{label(r):<10}{r['sign_name']:<10}{fmt_deg(r['deg']):<8}"
            f"{r['house']:<4}{r['nak']} ({r['pada']})"
        )
    lines.append("")
    lines.append("Дришти на дома:")
    for h in range(1, 13):
        a = ", ".join(data["aspects"][h]) or "—"
        lines.append(f"Дом {h:<3}← {a}")
    head = (
        f"<b>Место:</b> {html.escape(data['address'])}\n"
        f"<b>UTC:</b> {data['utc']:%d.%m.%Y %H:%M} | <b>TZ:</b> {data['tz']}\n"
        f"<i>Lahiri, True Node, дома: знак = дом. (X) — ретроградная</i>\n\n"
    )
    return head + "<pre>" + html.escape("\n".join(lines)) + "</pre>"


# ---------------------------------------------------------------- бот
router = Router()


class Form(StatesGroup):
    date = State()
    time = State()
    city = State()


@router.message(CommandStart())
@router.message(Command("new"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Form.date)
    await message.answer("Построим карту Раши D1.\nВведите дату рождения (ДД.ММ.ГГГГ):")


@router.message(Form.date, F.text)
async def got_date(message: Message, state: FSMContext):
    try:
        datetime.strptime(message.text.strip(), "%d.%m.%Y")
    except ValueError:
        await message.answer("Неверный формат. Пример: 27.02.1988")
        return
    await state.update_data(date=message.text.strip())
    await state.set_state(Form.time)
    await message.answer("Введите время рождения (ЧЧ:ММ):")


@router.message(Form.time, F.text)
async def got_time(message: Message, state: FSMContext):
    try:
        datetime.strptime(message.text.strip(), "%H:%M")
    except ValueError:
        await message.answer("Неверный формат. Пример: 16:35")
        return
    await state.update_data(time=message.text.strip())
    await state.set_state(Form.city)
    await message.answer("Введите город рождения:")


@router.message(Form.city, F.text)
async def got_city(message: Message, state: FSMContext):
    data = await state.get_data()
    city = message.text.strip()
    wait = await message.answer("Считаю карту...")
    try:
        result = await asyncio.to_thread(build_d1, data["date"], data["time"], city)
        png = await asyncio.to_thread(draw_chart, result)
    except Exception as e:
        await wait.edit_text(f"Ошибка: {e}\nПопробуйте другой город или начните заново: /start")
        return
    await state.clear()
    await wait.delete()
    await message.answer_photo(
        BufferedInputFile(png.getvalue(), filename="rashi_d1.png"),
        caption=f"Раши D1 — {city}, {data['date']} {data['time']}",
    )
    await message.answer(table_text(result), parse_mode="HTML")
    await message.answer("Новая карта: /start")


@router.message()
async def fallback(message: Message):
    await message.answer("Нажмите /start, чтобы построить карту D1.")


@router.message()
async def fallback(message: Message):
    await message.answer("Нажмите /start, чтобы построить карту D1.")


import socket
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import User


class IPv4Session(AiohttpSession):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._connector_init["family"] = socket.AF_INET


async def main():
    ensure_fonts()
    session = IPv4Session(timeout=60)
    bot = Bot(token=BOT_TOKEN, session=session)

    bot_id = int(BOT_TOKEN.split(":")[0])
    bot._me = User(id=bot_id, is_bot=True, first_name="JyotishBot", username="jyotish_bot")

    dp = Dispatcher()
    dp.include_router(router)
    while True:
        try:
            print("Запускаю polling по IPv4...", flush=True)
            await dp.start_polling(bot, handle_as_tasks=True)
            break
        except Exception as e:
            print(f"Ошибка сети, повтор через 10 сек: {e}", flush=True)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
