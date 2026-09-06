import asyncio
import logging
import os
import sqlite3

from app import adapter, config, storage, timeutil

log = logging.getLogger(__name__)


def collect_group(conn, group, collector=adapter.collect):
    try:
        occurrences = collector(group["source_url"], group["name"])
    except adapter.CollectError as exc:
        log.warning("Сбор для группы %s не удался: %s. Прошлая версия сохранена.",
                    group["id"], exc)
        return False
    except Exception:
        log.exception("Сбор для группы %s упал с непредвиденной ошибкой. Прошлая версия сохранена.",
                      group["id"])
        return False
    storage.save_collection(conn, group["id"], occurrences)
    log.info("Сбор для группы %s: сохранено занятий: %d", group["id"], len(occurrences))
    return True


def collect_all(conn, collector=adapter.collect):
    groups = storage.list_groups(conn)
    for group in groups:
        collect_group(conn, group, collector)
    return len(groups)


async def run_scheduler():
    while True:
        await asyncio.sleep(timeutil.seconds_until_hour(config.COLLECT_HOUR))
        try:
            await asyncio.to_thread(storage.run, collect_all)
        except Exception:
            log.exception("Ошибка суточного сбора")


def _reminder_text(lesson):
    start = timeutil.to_display(lesson["time_start"])
    parts = [f"🔔 Скоро занятие: {storage.lesson_title(lesson)}", f"начало в {start:%H:%M}"]
    if lesson["room"]:
        parts.append(f"ауд. {lesson['room']}")
    return ", ".join(parts)


async def _send(bot, chat_id, text):
    try:
        await bot.send_message(chat_id, text)
    except Exception:
        log.warning("Не удалось доставить сообщение подписчику")


async def run_dispatch(bot):
    while True:
        await asyncio.sleep(config.DISPATCH_INTERVAL_SECONDS)
        try:
            now = timeutil.now_utc()
            for item in await asyncio.to_thread(storage.run, storage.pop_due_reminders, now):
                await _send(bot, item["tg_user_id"], _reminder_text(item["lesson"]))
            for item in await asyncio.to_thread(
                storage.run, storage.pop_deliverable_announcements, now
            ):
                await _send(bot, item["tg_user_id"], "📢 Объявление: " + item["text"])
        except Exception:
            log.exception("Ошибка рассылки")


def backup_once():
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    stamp = timeutil.to_display(timeutil.now_utc()).strftime("%Y%m%d")
    target = os.path.join(config.BACKUP_DIR, f"raspisar-{stamp}.db")
    copy = sqlite3.connect(target)
    try:
        with storage.session() as live:
            live.backup(copy)
    finally:
        copy.close()
    copies = sorted(
        name for name in os.listdir(config.BACKUP_DIR)
        if name.startswith("raspisar-") and name.endswith(".db")
    )
    for old in copies[: -config.BACKUP_KEEP]:
        os.remove(os.path.join(config.BACKUP_DIR, old))
    log.info("Резервная копия сохранена: %s", target)
    return target


async def run_backup():
    while True:
        await asyncio.sleep(timeutil.seconds_until_hour(config.BACKUP_HOUR))
        try:
            await asyncio.to_thread(backup_once)
        except Exception:
            log.exception("Ошибка резервного копирования")
