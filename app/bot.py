import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

from app import storage
from app.scheduler import run_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer("Расписарь на связи. Ядро подключено.")


async def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        logging.error("BOT_TOKEN не задан: впишите токен от @BotFather в .env")
        raise SystemExit(1)
    storage.ensure_schema()
    logging.info("Бот запущен")
    scheduler_task = asyncio.create_task(run_scheduler())
    try:
        await dp.start_polling(Bot(token))
    finally:
        scheduler_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
