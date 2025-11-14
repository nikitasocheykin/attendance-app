#!/usr/bin/env python3
import asyncio
import json
import logging
import math
import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from datetime import datetime

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ContentType, ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv

# -----------------------------
#  НАСТРОЙКИ / ENV
# -----------------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")  # URL мини-аппы на GitHub Pages
MASTER_ADMIN_IDS = {
    int(x.strip())
    for x in (os.getenv("MASTER_ADMIN_IDS") or "").replace(";", ",").split(",")
    if x.strip().isdigit()
}

DB_PATH = os.getenv("DB_PATH", "attendance.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан (env или .env).")
if not WEBAPP_URL:
    raise RuntimeError("WEBAPP_URL не задан (env или .env).")

# -----------------------------
#  ЛОГИ
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s:%(name)s: %(message)s",
)
logger = logging.getLogger("attendance_bot")

# -----------------------------
#  ГЛОБАЛЬНЫЕ ОБЪЕКТЫ
# -----------------------------
bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()
router = Router()


# -----------------------------
#  ВСПОМОГАТЕЛЬНОЕ
# -----------------------------


def build_webapp_url(base_url: str, params: dict[str, str]) -> str:
    """Добавляет или заменяет query-параметры в URL мини-аппы."""

    parsed = urlparse(base_url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is None:
            continue
        existing[key] = value

    new_query = urlencode(existing)
    return urlunparse(parsed._replace(query=new_query))


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Расстояние между двумя координатами в метрах (прибл. формула гаверсина).
    """
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(
        d_lambda / 2
    ) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS users (
                telegram_id   INTEGER PRIMARY KEY,
                first_name    TEXT,
                last_name     TEXT,
                username      TEXT,
                fio           TEXT,
                email         TEXT,
                role          TEXT DEFAULT 'student',
                created_at    TEXT DEFAULT (datetime('now')),
                updated_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS lectures (
                id           TEXT PRIMARY KEY,
                is_open      INTEGER DEFAULT 0,
                created_by   INTEGER,
                geo_lat      REAL,
                geo_lon      REAL,
                geo_radius   REAL DEFAULT 150.0, -- радиус в метрах
                opened_at    TEXT,
                closed_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS attendances (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER,
                lecture_id     TEXT,
                created_at     TEXT DEFAULT (datetime('now')),
                status         TEXT, -- pending, approved, rejected, pending_video
                geo_lat        REAL,
                geo_lon        REAL,
                geo_accuracy   REAL,
                device         TEXT,
                extra_json     TEXT,
                video_chat_id  INTEGER,
                video_message_id INTEGER,
                reviewer_id    INTEGER,
                reviewed_at    TEXT,
                FOREIGN KEY(user_id) REFERENCES users(telegram_id),
                FOREIGN KEY(lecture_id) REFERENCES lectures(id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_att_unique
                ON attendances(user_id, lecture_id);
            """
        )
        await db.commit()
    finally:
        await db.close()


async def get_setting(key: str) -> str | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else None
    finally:
        await db.close()


async def set_setting(key: str, value: str):
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        await db.commit()
    finally:
        await db.close()


async def ensure_user(message: Message) -> None:
    """
    Создаёт/обновляет пользователя в БД.
    """
    db = await get_db()
    try:
        u = message.from_user
        await db.execute(
            """
            INSERT INTO users (telegram_id, first_name, last_name, username, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name  = excluded.last_name,
                username   = excluded.username,
                updated_at = excluded.updated_at
            """,
            (
                u.id,
                u.first_name,
                u.last_name,
                u.username,
                now_iso(),
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def set_user_profile(telegram_id: int, fio: str | None, email: str | None):
    db = await get_db()
    try:
        await db.execute(
            """
            UPDATE users
               SET fio = COALESCE(?, fio),
                   email = COALESCE(?, email),
                   updated_at = ?
             WHERE telegram_id = ?
            """,
            (fio, email, now_iso(), telegram_id),
        )
        await db.commit()
    finally:
        await db.close()


async def set_user_role(telegram_id: int, role: str):
    db = await get_db()
    try:
        await db.execute(
            """
            UPDATE users
               SET role = ?,
                   updated_at = ?
             WHERE telegram_id = ?
            """,
            (role, now_iso(), telegram_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_user_role(telegram_id: int) -> str:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT role FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cur.fetchone()
        return row["role"] if row and row["role"] else "student"
    finally:
        await db.close()


# -----------------------------
#  КОМАНДЫ
# -----------------------------


@router.message(CommandStart())
async def cmd_start(message: Message):
    await ensure_user(message)

    role = await get_user_role(message.from_user.id)
    role = role or "student"

    role_map = {
        "student": ("student", ["student"]),
        "speaker": ("speaker", ["student", "speaker"]),
        "admin": ("admin", ["student", "speaker", "admin"]),
        "rating": ("rating", ["student"]),
    }

    role_param, allowed_panels = role_map.get(role, role_map["student"])
    webapp_url = build_webapp_url(
        WEBAPP_URL,
        {
            "role": role_param,
            "panels": ",".join(allowed_panels),
        },
    )

    kb = ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[
            [
                KeyboardButton(
                    text="Открыть мини-аппу",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ]
        ],
    )

    await message.answer(
        (
            "Привет! Это бот для отметки посещаемости.\n\n"
            "Нажми кнопку <b>«Открыть мини-аппу»</b>, чтобы запустить интерфейс,"
            " который покажет разделы согласно твоей роли."
        ),
        reply_markup=kb,
    )


@router.message(Command("set_rating_chat"))
async def cmd_set_rating_chat(message: Message):
    """
    Выполняется в чате команды рейтинга.
    Только мастер-админ.
    """
    if message.from_user.id not in MASTER_ADMIN_IDS:
        await message.reply("Команда только для мастер-админов.")
        return

    chat_id = message.chat.id
    await set_setting("rating_chat_id", str(chat_id))
    await message.reply(
        f"Чат рейтинга установлен: <code>{chat_id}</code>\n"
        "Сюда будут отправляться кружки на проверку."
    )


@router.message(Command("whoami"))
async def cmd_whoami(message: Message):
    await ensure_user(message)
    role = await get_user_role(message.from_user.id)
    await message.reply(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n"
        f"Текущая роль в системе: <b>{role}</b>"
    )


# -----------------------------
#  ОБРАБОТКА WEB_APP_DATA
# -----------------------------


@router.message(F.web_app_data)
async def webapp_data_handler(message: Message):
    """
    Сюда прилетают данные из мини-аппы через Telegram.WebApp.sendData().
    """
    await ensure_user(message)

    raw = message.web_app_data.data
    try:
        payload = json.loads(raw)
    except Exception as e:
        logger.exception("Bad WebApp payload: %s", raw)
        await message.answer("⚠ Не удалось разобрать данные из мини-аппы.")
        return

    actual_role = await get_user_role(message.from_user.id)
    declared_role = (payload.get("role") or "").lower() or None
    logger.info(
        "WebApp payload from %s (role=%s, declared=%s): %s",
        message.from_user.id,
        actual_role,
        declared_role,
        payload,
    )

    p_type = payload.get("type")

    # Дальше диспатчим по типу события
    if p_type == "register":
        await handle_register(message, payload)
    elif p_type == "qr_scan":
        await handle_qr_scan(message, payload)
    elif p_type == "geo_stream":
        await handle_geo_stream(message, payload)
    elif p_type == "checkin":
        await handle_checkin(message, payload)
    elif p_type == "speaker_open_lecture":
        await handle_speaker_open_lecture(message, payload)
    elif p_type == "speaker_close_lecture":
        await handle_speaker_close_lecture(message, payload)
    elif p_type == "speaker_set_geo":
        await handle_speaker_set_geo(message, payload)
    elif p_type == "admin_set_role":
        await handle_admin_set_role(message, payload)
    elif p_type == "admin_request_stats":
        await handle_admin_request_stats(message, payload)
    else:
        await message.answer(f"⚠ Неизвестный тип события: <code>{p_type}</code>.")


# -----------------------------
#  ХЕНДЛЕРЫ ДЛЯ ТИПОВ PAYLOAD
# -----------------------------


async def handle_register(message: Message, payload: dict):
    fio = payload.get("fio") or None
    email = payload.get("email") or None

    await set_user_profile(message.from_user.id, fio, email)
    await message.answer("✅ Профиль обновлён.\nФИО и почта сохранены в системе.")


async def handle_qr_scan(message: Message, payload: dict):
    qr = str(payload.get("qr") or "").strip()
    if not qr:
        await message.answer("⚠ Пустой QR.")
        return

    # В простейшем варианте считаем, что qr = ID лекции.
    lecture_id = qr

    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO lectures (id, is_open, created_by, opened_at)
            VALUES (?, 0, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (lecture_id, message.from_user.id, now_iso()),
        )
        await db.commit()
    finally:
        await db.close()

    await message.answer(
        f"📎 Лекция <code>{lecture_id}</code> привязана к вашему сеансу.\n"
        "Итоговое решение, засчитывать ли отметку, принимает сервер."
    )


async def handle_geo_stream(message: Message, payload: dict):
    """
    Live-трансляция геопозиции через watchPosition.
    Сейчас мы просто логируем входящие координаты для диагностики.
    """
    lat = payload.get("lat")
    lon = payload.get("lon")
    acc = payload.get("accuracy")
    ts = payload.get("timestamp")

    if lat is None or lon is None:
        # тихо логируем, не спамим пользователя
        logger.warning(
            "geo_stream без координат от %s: %s", message.from_user.id, payload
        )
        return

    # Можно сохранять последнюю geo в отдельную таблицу, но для простоты логируем:
    logger.info(
        "Geo stream from %s: lat=%s lon=%s acc=%s ts=%s",
        message.from_user.id,
        lat,
        lon,
        acc,
        ts,
    )
    # Пользователю не обязательно отвечать каждый раз.


async def handle_checkin(message: Message, payload: dict):
    """
    Отметка студента:
    - проверяем, есть ли лекция
    - проверяем геозону (если задана)
    - обеспечиваем "один пользователь = одна отметка на лекцию"
    - при подозрительной геопозиции ставим статус pending_video и просим кружок
    """
    user_id = message.from_user.id
    fio = payload.get("fio")
    email = payload.get("email")
    last_geo = payload.get("lastGeo") or {}
    lecture_id = payload.get("lectureId")

    await set_user_profile(user_id, fio or None, email or None)

    if not lecture_id:
        await message.answer(
            "⚠ Лекция не выбрана.\nОтсканируйте QR-код лекции в мини-аппе."
        )
        return

    lat = last_geo.get("latitude")
    lon = last_geo.get("longitude")
    acc = last_geo.get("accuracy")

    db = await get_db()
    try:
        # Проверим существование лекции и её геозону
        cur = await db.execute(
            "SELECT id, is_open, geo_lat, geo_lon, geo_radius FROM lectures WHERE id = ?",
            (lecture_id,),
        )
        lec = await cur.fetchone()

        if not lec:
            await message.answer(
                f"⚠ Лекция <code>{lecture_id}</code> не зарегистрирована.\n"
                "Попросите спикера открыть лекцию в своей панели."
            )
            return

        if not lec["is_open"]:
            await message.answer(
                f"🚫 Лекция <code>{lecture_id}</code> сейчас закрыта для отметок."
            )
            return

        # Проверка "один пользователь = одна отметка на лекцию"
        cur = await db.execute(
            """
            SELECT id, status
              FROM attendances
             WHERE user_id = ? AND lecture_id = ?
            """,
            (user_id, lecture_id),
        )
        existing = await cur.fetchone()
        if existing and existing["status"] in ("approved", "pending_video", "pending"):
            await message.answer(
                "ℹ Отметка по этой лекции уже существует.\n"
                "Дублирующие отметки не засчитываются."
            )
            return

        geo_ok = True
        distance = None

        if lec["geo_lat"] is not None and lec["geo_lon"] is not None:
            if lat is None or lon is None:
                geo_ok = False
            else:
                distance = haversine_m(lat, lon, lec["geo_lat"], lec["geo_lon"])
                if distance is None:
                    geo_ok = False
                else:
                    # если дальше радиуса, считаем подозрительным
                    radius = lec["geo_radius"] or 150.0
                    geo_ok = distance <= radius

        status = "approved" if geo_ok else "pending_video"

        try:
            await db.execute(
                """
                INSERT INTO attendances (
                    user_id, lecture_id, status,
                    geo_lat, geo_lon, geo_accuracy,
                    device, extra_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    lecture_id,
                    status,
                    lat,
                    lon,
                    acc,
                    payload.get("device") or None,
                    json.dumps({"raw": payload}, ensure_ascii=False),
                ),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            # уникальный индекс user_id+lecture_id
            await message.answer(
                "ℹ Отметка по этой лекции уже существует.\n"
                "Дублирующие отметки не засчитываются."
            )
            return

        if status == "approved":
            text = (
                "✅ Отметка предварительно засчитана.\n"
                f"Лекция: <code>{lecture_id}</code>\n"
            )
            if distance is not None:
                text += f"Расстояние до аудитории ≈ <b>{int(distance)} м</b>."
            await message.answer(text)
        else:
            text = (
                "⚠ Ваша геопозиция не совпала с геозоной лекции.\n"
                "Пожалуйста, запишите <b>кружок (video note)</b> и отправьте его боту.\n"
                "Команда рейтинга проверит и вручную засчитает/отклонит посещение."
            )
            await message.answer(text)

    finally:
        await db.close()


async def handle_speaker_open_lecture(message: Message, payload: dict):
    user_id = message.from_user.id
    role = await get_user_role(user_id)
    if role != "speaker" and user_id not in MASTER_ADMIN_IDS:
        logger.warning(
            "Access denied for speaker_open_lecture: user=%s role=%s payload=%s",
            user_id,
            role,
            payload,
        )
        await message.answer(
            "🚫 У вас нет прав для открытия лекции."
            " Доступ разрешён только спикерам или мастер-админам."
        )
        return

    lecture_id = payload.get("lectureId") or payload.get("lecture_id")
    if not lecture_id:
        await message.answer("⚠ Не указан ID лекции.")
        return

    user_role = await get_user_role(user_id)
    if user_id not in MASTER_ADMIN_IDS and user_role not in ("speaker", "admin"):
        await message.answer("🚫 Только спикер или мастер-админ может открывать лекцию.")
        return

    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO lectures (id, is_open, created_by, opened_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                is_open = 1,
                opened_at = excluded.opened_at
            """,
            (lecture_id, user_id, now_iso()),
        )
        await db.commit()
    finally:
        await db.close()

    await message.answer(
        f"🔓 Лекция <code>{lecture_id}</code> открыта для отметок.\n"
        "Студенты могут отмечаться через мини-аппу."
    )


async def handle_speaker_close_lecture(message: Message, payload: dict):
    user_id = message.from_user.id
    role = await get_user_role(user_id)
    if role != "speaker" and user_id not in MASTER_ADMIN_IDS:
        logger.warning(
            "Access denied for speaker_close_lecture: user=%s role=%s payload=%s",
            user_id,
            role,
            payload,
        )
        await message.answer(
            "🚫 У вас нет прав для закрытия лекции."
            " Доступ разрешён только спикерам или мастер-админам."
        )
        return

    lecture_id = payload.get("lectureId") or payload.get("lecture_id")
    if not lecture_id:
        await message.answer("⚠ Не указан ID лекции.")
        return

    db = await get_db()
    try:
        await db.execute(
            """
            UPDATE lectures
               SET is_open = 0,
                   closed_at = ?
             WHERE id = ?
            """,
            (now_iso(), lecture_id),
        )
        await db.commit()
    finally:
        await db.close()

    await message.answer(
        f"🔒 Лекция <code>{lecture_id}</code> закрыта для новых отметок."
    )


async def handle_speaker_set_geo(message: Message, payload: dict):
    user_id = message.from_user.id
    role = await get_user_role(user_id)
    if role != "speaker" and user_id not in MASTER_ADMIN_IDS:
        logger.warning(
            "Access denied for speaker_set_geo: user=%s role=%s payload=%s",
            user_id,
            role,
            payload,
        )
        await message.answer(
            "🚫 У вас нет прав для изменения геозоны лекции."
            " Доступ разрешён только спикерам или мастер-админам."
        )
        return

    lecture_id = payload.get("lectureId") or payload.get("lecture_id")
    lat = payload.get("lat")
    lon = payload.get("lon")
    acc = payload.get("accuracy")

    if not lecture_id:
        await message.answer(
            "⚠ Не указан ID лекции.\nВ мини-аппе заполните поле ID лекции."
        )
        return
    if lat is None or lon is None:
        await message.answer("⚠ Не удалось получить координаты для геозоны.")
        return

    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO lectures (id, is_open, created_by, geo_lat, geo_lon, geo_radius, opened_at)
            VALUES (?, 0, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                geo_lat = excluded.geo_lat,
                geo_lon = excluded.geo_lon,
                geo_radius = excluded.geo_radius
            """,
            (
                lecture_id,
                message.from_user.id,
                lat,
                lon,
                150.0,  # базовый радиус, можно вынести в настройку
                now_iso(),
            ),
        )
        await db.commit()
    finally:
        await db.close()

    await message.answer(
        f"📍 Геозона для лекции <code>{lecture_id}</code> установлена.\n"
        f"lat={lat:.5f}, lon={lon:.5f}, точность ≈ {acc!r}."
    )


async def handle_admin_set_role(message: Message, payload: dict):
    if message.from_user.id not in MASTER_ADMIN_IDS:
        role = await get_user_role(message.from_user.id)
        logger.warning(
            "Access denied for admin_set_role: user=%s role=%s payload=%s",
            message.from_user.id,
            role,
            payload,
        )
        await message.answer("🚫 Только мастер-админ может менять роли.")
        return

    target_id = payload.get("targetUserId")
    new_role = (payload.get("newRole") or "").strip().lower()

    if not target_id or not str(target_id).isdigit():
        await message.answer("⚠ Некорректный Telegram user_id.")
        return

    if new_role not in ("student", "speaker", "rating", "admin"):
        await message.answer("⚠ Некорректная роль.")
        return

    target_id = int(target_id)
    await set_user_role(target_id, new_role)
    await message.answer(
        f"✅ Роль пользователя <code>{target_id}</code> изменена на <b>{new_role}</b>."
    )


async def handle_admin_request_stats(message: Message, payload: dict):
    if message.from_user.id not in MASTER_ADMIN_IDS:
        role = await get_user_role(message.from_user.id)
        logger.warning(
            "Access denied for admin_request_stats: user=%s role=%s payload=%s",
            message.from_user.id,
            role,
            payload,
        )
        await message.answer("🚫 Только мастер-админ может запрашивать статистику.")
        return

    lecture_id = payload.get("lectureId") or payload.get("lecture_id")
    if not lecture_id:
        await message.answer("⚠ Не указан ID лекции.")
        return

    db = await get_db()
    try:
        cur = await db.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS ok,
                SUM(CASE WHEN status='pending_video' THEN 1 ELSE 0 END) AS pending_vid,
                SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected
            FROM attendances
            WHERE lecture_id = ?
            """,
            (lecture_id,),
        )
        row = await cur.fetchone()
    finally:
        await db.close()

    if not row or row["total"] == 0:
        await message.answer(
            f"ℹ По лекции <code>{lecture_id}</code> пока нет отметок."
        )
        return

    await message.answer(
        f"📊 Статистика по лекции <code>{lecture_id}</code>:\n"
        f"Всего записей: <b>{row['total']}</b>\n"
        f"Засчитано: <b>{row['ok'] or 0}</b>\n"
        f"Ожидают видео/проверки: <b>{row['pending_vid'] or 0}</b>\n"
        f"Отклонено: <b>{row['rejected'] or 0}</b>"
    )


# -----------------------------
#  ВИДЕО-КРУЖКИ / РЕЙТИНГ
# -----------------------------


@router.message(F.content_type == ContentType.VIDEO_NOTE)
async def handle_video_note(message: Message):
    """
    Пользователь присылает кружок после "pending_video".
    Бот пересылает кружок в чат рейтинга, прикрепляет inline-кнопки
    "Верифицировать / Отклонить" и сохраняет привязку.
    """
    user_id = message.from_user.id
    rating_chat = await get_setting("rating_chat_id")
    if not rating_chat:
        await message.reply(
            "⚠ Чат рейтинга не настроен. Попросите мастер-админа выполнить /set_rating_chat в нужном чате."
        )
        return

    rating_chat_id = int(rating_chat)

    db = await get_db()
    try:
        # Находим последнюю pending_video отметку для этого пользователя
        cur = await db.execute(
            """
            SELECT id, lecture_id
              FROM attendances
             WHERE user_id = ?
               AND status = 'pending_video'
          ORDER BY created_at DESC
             LIMIT 1
            """,
            (user_id,),
        )
        att = await cur.fetchone()
        if not att:
            await message.reply(
                "ℹ Нет отметки, ожидающей видеоподтверждения.\n"
                "Сначала попробуйте отметиться через мини-аппу."
            )
            return

        attendance_id = att["id"]
        lecture_id = att["lecture_id"]

        # Пересылаем кружок в чат рейтинга с inline-кнопками
        fwd = await bot.send_video_note(
            chat_id=rating_chat_id,
            video_note=message.video_note.file_id,
            caption=(
                f"Кружок от пользователя <code>{user_id}</code>\n"
                f"Лекция: <code>{lecture_id}</code>\n"
                f"ID отметки: <code>{attendance_id}</code>"
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Верифицировать",
                            callback_data=f"verify_att:{attendance_id}:ok",
                        ),
                        InlineKeyboardButton(
                            text="❌ Отклонить",
                            callback_data=f"verify_att:{attendance_id}:reject",
                        ),
                    ]
                ]
            ),
        )

        # Сохраняем, где лежит видео
        await db.execute(
            """
            UPDATE attendances
               SET video_chat_id = ?, video_message_id = ?, status = 'pending'
             WHERE id = ?
            """,
            (fwd.chat.id, fwd.message_id, attendance_id),
        )
        await db.commit()

        await message.reply(
            "✅ Кружок отправлен в команду рейтинга.\n"
            "После проверки вы получите решение."
        )
    finally:
        await db.close()


@router.callback_query(F.data.startswith("verify_att:"))
async def callback_verify_attendance(call: CallbackQuery):
    """
    Обработка решения команды рейтинга:
    - verify_att:<attendance_id>:ok
    - verify_att:<attendance_id>:reject
    """
    data = call.data or ""
    try:
        _, att_id_str, decision = data.split(":")
        attendance_id = int(att_id_str)
    except Exception:
        await call.answer("Ошибка формата callback.", show_alert=True)
        return

    decision = decision.lower()
    if decision not in ("ok", "reject"):
        await call.answer("Неверное действие.", show_alert=True)
        return

    # Проверим, что нажимающий действительно в "rating" или мастер-админ
    user_id = call.from_user.id
    user_role = await get_user_role(user_id)
    if user_role not in ("rating", "admin") and user_id not in MASTER_ADMIN_IDS:
        await call.answer("У вас нет прав оценивать кружки.", show_alert=True)
        return

    db = await get_db()
    try:
        cur = await db.execute(
            """
            SELECT user_id, lecture_id, video_chat_id, video_message_id
              FROM attendances
             WHERE id = ?
            """,
            (attendance_id,),
        )
        att = await cur.fetchone()
        if not att:
            await call.answer("Отметка не найдена.", show_alert=True)
            return

        new_status = "approved" if decision == "ok" else "rejected"

        await db.execute(
            """
            UPDATE attendances
               SET status = ?,
                   reviewer_id = ?,
                   reviewed_at = ?
             WHERE id = ?
            """,
            (new_status, user_id, now_iso(), attendance_id),
        )
        await db.commit()

        # Удаляем кружок из чата рейтинга, если можем
        if att["video_chat_id"] and att["video_message_id"]:
            try:
                await bot.delete_message(
                    chat_id=att["video_chat_id"],
                    message_id=att["video_message_id"],
                )
            except Exception as e:
                logger.warning("Не удалось удалить сообщение с кружком: %s", e)

        # Сообщаем студенту
        student_id = att["user_id"]
        if decision == "ok":
            text = (
                "✅ Ваша отметка по лекции "
                f"<code>{att['lecture_id']}</code> подтверждена командой рейтинга."
            )
        else:
            text = (
                "❌ Ваша отметка по лекции "
                f"<code>{att['lecture_id']}</code> отклонена командой рейтинга."
            )

        try:
            await bot.send_message(student_id, text)
        except Exception as e:
            logger.warning("Не удалось отправить сообщение студенту: %s", e)

        await call.answer(
            "Решение применено.",
            show_alert=False,
        )
        # Можно также изменить подпись/кнопки у самого callback-сообщения:
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    finally:
        await db.close()


# -----------------------------
#  ЗАПУСК
# -----------------------------


async def main():
    await init_db()
    dp.include_router(router)
    logger.info("Starting bot polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
