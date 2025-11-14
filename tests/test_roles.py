import uuid
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import types as pytypes

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("WEBAPP_URL", "https://example.com")

if "dotenv" not in sys.modules:
    dotenv_stub = pytypes.ModuleType("dotenv")

    def _load_dotenv(*args, **kwargs):
        return None

    dotenv_stub.load_dotenv = _load_dotenv
    sys.modules["dotenv"] = dotenv_stub

if "aiogram" not in sys.modules:
    aiogram_stub = pytypes.ModuleType("aiogram")

    class _Dummy:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, *args, **kwargs):
            return self

    class _Router:
        def message(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def callback_query(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class _Filter:
        def __getattr__(self, item):
            return self

        def __eq__(self, other):
            return self

        def startswith(self, *args, **kwargs):
            return self

    aiogram_stub.Bot = _Dummy
    aiogram_stub.Dispatcher = _Dummy
    aiogram_stub.Router = _Router
    aiogram_stub.types = pytypes.ModuleType("aiogram.types")

    for attr in [
        "Message",
        "CallbackQuery",
        "ReplyKeyboardMarkup",
        "KeyboardButton",
        "WebAppInfo",
        "InlineKeyboardMarkup",
        "InlineKeyboardButton",
    ]:
        setattr(aiogram_stub.types, attr, _Dummy)

    aiogram_stub.enums = pytypes.ModuleType("aiogram.enums")

    class _ContentType:
        VIDEO_NOTE = "video_note"

    class _ParseMode:
        HTML = "HTML"

    aiogram_stub.enums.ContentType = _ContentType
    aiogram_stub.enums.ParseMode = _ParseMode

    aiogram_stub.client = pytypes.ModuleType("aiogram.client")
    aiogram_stub.client.default = pytypes.ModuleType("aiogram.client.default")
    aiogram_stub.client.default.DefaultBotProperties = _Dummy

    aiogram_stub.filters = pytypes.ModuleType("aiogram.filters")
    aiogram_stub.filters.CommandStart = _Dummy
    aiogram_stub.filters.Command = _Dummy

    aiogram_stub.F = _Filter()

    sys.modules["aiogram"] = aiogram_stub
    sys.modules["aiogram.types"] = aiogram_stub.types
    sys.modules["aiogram.enums"] = aiogram_stub.enums
    sys.modules["aiogram.client"] = aiogram_stub.client
    sys.modules["aiogram.client.default"] = aiogram_stub.client.default
    sys.modules["aiogram.filters"] = aiogram_stub.filters

import bot.bot as bot_module


class DummyMessage:
    def __init__(self, user_id):
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text, *args, **kwargs):
        self.answers.append(text)

    async def reply(self, text, *args, **kwargs):
        self.answers.append(text)


@pytest.fixture
def memory_db(monkeypatch):
    db_path = f"file:{uuid.uuid4().hex}?mode=memory&cache=shared"
    bot_module.DB_PATH = db_path

    original_connect = bot_module.aiosqlite.connect

    async def connect_override(path, *args, **kwargs):
        if path == db_path:
            kwargs.setdefault("uri", True)
        return await original_connect(path, *args, **kwargs)

    monkeypatch.setattr(bot_module.aiosqlite, "connect", connect_override)

    keeper_conn = asyncio.run(original_connect(db_path, uri=True))
    asyncio.run(bot_module.init_db())
    yield
    asyncio.run(keeper_conn.close())


async def insert_user(user_id: int, role: str):
    db = await bot_module.get_db()
    try:
        await db.execute(
            "INSERT INTO users (telegram_id, role, updated_at) VALUES (?, ?, datetime('now'))",
            (user_id, role),
        )
        await db.commit()
    finally:
        await db.close()


def test_student_cannot_open_lecture(memory_db):
    async def run():
        student_id = 1001
        await insert_user(student_id, "student")

        message = DummyMessage(student_id)
        payload = {"lectureId": "math101"}

        await bot_module.handle_speaker_open_lecture(message, payload)

        assert message.answers == ["🚫 Только спикер или мастер-админ может открывать лекцию."]

        db = await bot_module.get_db()
        try:
            cur = await db.execute("SELECT COUNT(*) FROM lectures")
            (count,) = await cur.fetchone()
        finally:
            await db.close()

        assert count == 0

    asyncio.run(run())


def test_speaker_opens_lecture_successfully(memory_db):
    async def run():
        speaker_id = 2002
        await insert_user(speaker_id, "speaker")

        message = DummyMessage(speaker_id)
        payload = {"lectureId": "math102"}

        await bot_module.handle_speaker_open_lecture(message, payload)

        assert len(message.answers) == 1
        assert "🔓 Лекция <code>math102</code> открыта" in message.answers[0]

        db = await bot_module.get_db()
        try:
            cur = await db.execute(
                "SELECT is_open, created_by FROM lectures WHERE id = ?", ("math102",)
            )
            row = await cur.fetchone()
        finally:
            await db.close()

        assert row is not None
        assert row["is_open"] == 1
        assert row["created_by"] == speaker_id

    asyncio.run(run())


def test_master_admin_can_open_lecture(memory_db, monkeypatch):
    async def run():
        admin_id = 3003
        await insert_user(admin_id, "student")

        message = DummyMessage(admin_id)
        payload = {"lectureId": "math103"}

        monkeypatch.setattr(bot_module, "MASTER_ADMIN_IDS", {admin_id})

        await bot_module.handle_speaker_open_lecture(message, payload)

        assert len(message.answers) == 1
        assert "🔓 Лекция <code>math103</code> открыта" in message.answers[0]

        db = await bot_module.get_db()
        try:
            cur = await db.execute(
                "SELECT is_open, created_by FROM lectures WHERE id = ?", ("math103",)
            )
            row = await cur.fetchone()
        finally:
            await db.close()

        assert row is not None
        assert row["is_open"] == 1
        assert row["created_by"] == admin_id

    asyncio.run(run())
