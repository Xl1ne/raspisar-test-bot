import asyncio
from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app import bot as botmod, config, storage

OUTSIDER = 5


class _StubSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, SendMessage):
            self.sent.append(method.text)
            return Message(
                message_id=len(self.sent) + 1, date=datetime.now(timezone.utc),
                chat=Chat(id=OUTSIDER, type="private"), text=method.text,
            )
        if isinstance(method, AnswerCallbackQuery):
            return True
        raise AssertionError(f"неожиданный вызов Telegram: {type(method).__name__}")


def _press(data, update_id):
    user = User(id=OUTSIDER, is_bot=False, first_name="x")
    message = Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=OUTSIDER, type="private"))
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id), from_user=user, chat_instance="c", data=data, message=message
        ),
    )


@pytest.fixture
def tg(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "bot.db"))
    storage.ensure_schema()
    session = _StubSession()
    return Bot("42:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN", session=session), session


def test_domain_errors_become_user_messages(tg):
    bot, session = tg

    async def scenario():
        await botmod.dp.feed_update(bot, _press("subs", 1))
        await botmod.dp.feed_update(bot, _press("editday:не-дата", 2))
        await botmod.dp.feed_update(bot, _press("today", 3))

    asyncio.run(scenario())
    assert session.sent == [
        "Это действие доступно только старосте.",
        "Некорректный выбор, начните заново.",
        "Вы не состоите в группе.",
    ]
