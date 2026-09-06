import asyncio
import logging

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


def _collect_all_fresh():
    conn = storage.connect()
    try:
        collect_all(conn)
    finally:
        conn.close()


async def run_scheduler():
    while True:
        await asyncio.sleep(timeutil.seconds_until_hour(config.COLLECT_HOUR))
        try:
            await asyncio.to_thread(_collect_all_fresh)
        except Exception:
            log.exception("Ошибка суточного сбора")
