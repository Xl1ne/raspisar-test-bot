import asyncio
import logging
import os
from datetime import date, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, ExceptionTypeFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app import adapter, config, storage, timeutil
from app.scheduler import run_backup, run_dispatch, run_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

dp = Dispatcher()

_WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_MODE_HEADER = {"today": "Сегодня", "tomorrow": "Завтра", "week": "Неделя"}
_MODE_EMPTY = {
    "today": "На сегодня занятий нет.",
    "tomorrow": "На завтра занятий нет.",
    "week": "На этой учебной неделе занятий нет.",
}


class BadChoice(Exception):
    """Кнопка с подделанными или устаревшими данными."""


_ERROR_TEXT = {
    storage.PermissionDenied: "Это действие доступно только старосте.",
    storage.LessonNotFound: "Занятие не найдено, начните заново.",
    storage.NotAMember: "Вы не состоите в группе.",
    storage.AlreadyInGroup: "Вы уже состоите в группе.",
    storage.HeadmanHasSubscribers: (
        "Вы староста. Сначала передайте роль другому подписчику, потом сможете отписаться."
    ),
    storage.AnnouncementLimit: None,
    BadChoice: "Некорректный выбор, начните заново.",
}


class NewGroup(StatesGroup):
    name = State()
    source = State()


class Subscribing(StatesGroup):
    code = State()


class ChangingSource(StatesGroup):
    source = State()


class Editing(StatesGroup):
    lesson = State()
    action = State()
    room = State()


class SettingRemind(StatesGroup):
    value = State()


class SettingQuiet(StatesGroup):
    value = State()


class Announcing(StatesGroup):
    text = State()


def _looks_like_url(text):
    return text.startswith(("http://", "https://"))


def _calendar_link(calendar_code):
    return f"{config.PUBLIC_BASE_URL}/calendar/{calendar_code}.ics"


async def _db(fn, *args):
    return await asyncio.to_thread(storage.run, fn, *args)


def _menu_state(user_id):
    with storage.session() as conn:
        group = storage.group_of(conn, user_id)
        if group is None:
            return None
        return {
            "name": group["name"],
            "invite_code": group["invite_code"],
            "calendar_code": group["calendar_code"],
            "is_headman": group["headman_id"] == user_id,
        }


def _create(user_id, name, url):
    with storage.session() as conn:
        if storage.group_of(conn, user_id) is not None:
            raise storage.AlreadyInGroup()
        occurrences = adapter.collect(url, name)
        group = storage.register_group(conn, user_id, name, url)
        storage.save_collection(conn, group["id"], occurrences)
        return group, len(occurrences)


def _change_source(user_id, url):
    with storage.session() as conn:
        group = storage.require_headman(conn, user_id)
        occurrences = adapter.collect(url, group["name"])
        storage.set_source(conn, user_id, url)
        storage.save_collection(conn, group["id"], occurrences)
        return len(occurrences)


def _schedule(user_id):
    with storage.session() as conn:
        group = storage.group_of(conn, user_id)
        return None if group is None else storage.get_schedule(conn, group["id"])


def _members(user_id):
    with storage.session() as conn:
        subs = storage.list_subscribers(conn, user_id)
        return [s["tg_user_id"] for s in subs if not s["is_headman"]]


def _tail(callback):
    return callback.data.split(":", 1)[1]


def _int_tail(callback):
    try:
        return int(_tail(callback))
    except ValueError:
        raise BadChoice from None


def _day_tail(callback):
    try:
        return date.fromisoformat(_tail(callback))
    except ValueError:
        raise BadChoice from None


def _parse_quiet(text):
    start, sep, end = text.partition("-")
    if not sep:
        return None
    try:
        return tuple(timeutil.parse_hhmm(p.strip()).strftime("%H:%M") for p in (start, end))
    except ValueError:
        return None


def _kb(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def _main_kb(state):
    if state is None:
        return _kb(
            [
                [("Создать группу (я староста)", "create")],
                [("Подписаться по коду", "subscribe")],
            ]
        )
    rows = [[("Сегодня", "today"), ("Завтра", "tomorrow"), ("Неделя", "week")]]
    if state["is_headman"]:
        rows.append([("Изменить занятие", "edit"), ("Объявление", "announce")])
        rows.append([("Список подписчиков", "subs"), ("Передать роль", "transfer")])
        rows.append([("Изменить адрес источника", "chsrc")])
    rows.append([("Напоминание", "remind"), ("Тихие часы", "quiet")])
    rows.append([("Отписаться", "unsub")])
    return _kb(rows)


def _menu_text(state):
    if state is None:
        return (
            "Расписарь. Вы пока не состоите в группе.\n\n"
            "Староста — создайте группу. Студент — подпишитесь по коду приглашения."
        )
    link = _calendar_link(state["calendar_code"])
    if state["is_headman"]:
        return (
            f"Группа {state['name']}. Вы староста.\n\n"
            f"Код приглашения (раздайте однокурсникам): {state['invite_code']}\n"
            f"Ссылка для календаря: {link}"
        )
    return f"Группа {state['name']}. Вы подписаны.\n\nСсылка для календаря: {link}"


def _filter_sort(rows, mode, today):
    if mode == "today":
        low = high = today
    elif mode == "tomorrow":
        low = high = today + timedelta(days=1)
    else:
        low, high = timeutil.week_bounds(today)
    picked = [r for r in rows if low <= timeutil.to_display(r["time_start"]).date() <= high]
    return sorted(picked, key=lambda r: r["time_start"])


def _format_lesson(row):
    start = timeutil.to_display(row["time_start"])
    end = timeutil.to_display(row["time_end"])
    parts = [
        f"{_WD[start.weekday()]} {start:%d.%m}",
        f"{start:%H:%M}–{end:%H:%M}",
        storage.lesson_title(row),
    ]
    if row["room"]:
        parts.append(f"ауд. {row['room']}")
    if row["teacher"]:
        parts.append(row["teacher"])
    line = " · ".join(parts)
    if row["cancelled"]:
        line = "❌ Отменено: " + line
    return line


def _render_schedule(rows, mode, today):
    picked = _filter_sort(rows, mode, today)
    if not picked:
        return _MODE_EMPTY[mode]
    return _MODE_HEADER[mode] + ":\n" + "\n".join(_format_lesson(r) for r in picked)


async def _reshow(message, user_id):
    state = await asyncio.to_thread(_menu_state, user_id)
    await message.answer("Меню:", reply_markup=_main_kb(state))


async def _notify_edit(bot, group_id, editor_id, text):
    for uid in await _db(storage.other_subscriber_ids, group_id, editor_id):
        try:
            await bot.send_message(uid, text)
        except Exception:
            log.warning("Не удалось доставить уведомление о правке подписчику")


@dp.errors(ExceptionTypeFilter(*_ERROR_TEXT))
async def on_domain_error(event: ErrorEvent, state: FSMContext) -> None:
    text = _ERROR_TEXT[type(event.exception)] or str(event.exception)
    await state.clear()
    update = event.update
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if message:
        await message.answer(text)


@dp.message(CommandStart())
async def start(message: Message) -> None:
    state = await asyncio.to_thread(_menu_state, message.from_user.id)
    await message.answer(_menu_text(state), reply_markup=_main_kb(state))


@dp.callback_query(F.data == "create")
async def create_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if await asyncio.to_thread(_menu_state, callback.from_user.id) is not None:
        raise storage.AlreadyInGroup()
    await state.set_state(NewGroup.name)
    await callback.message.answer(
        "Введите наименование группы — код её колонки в источнике, "
        "например ОБ-09.03.03.02-41."
    )


@dp.message(NewGroup.name)
async def create_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Пришлите наименование группы текстом.")
        return
    await state.update_data(name=name)
    await state.set_state(NewGroup.source)
    await message.answer("Теперь пришлите адрес страницы расписания (http:// или https://).")


@dp.message(NewGroup.source)
async def create_source(message: Message, state: FSMContext) -> None:
    url = (message.text or "").strip()
    if not _looks_like_url(url):
        await message.answer("Адрес должен начинаться с http:// или https://. Пришлите ещё раз.")
        return
    data = await state.get_data()
    await message.answer("Проверяю источник…")
    try:
        group, count = await asyncio.to_thread(_create, message.from_user.id, data["name"], url)
    except adapter.CollectError as exc:
        await message.answer(
            f"Не удалось разобрать расписание по этому адресу: {exc}\n"
            "Проверьте адрес и наименование группы, затем пришлите адрес ещё раз."
        )
        return
    await state.clear()
    await message.answer(
        f"Группа {group['name']} создана. Загружено занятий: {count}.\n\n"
        f"Код приглашения: {group['invite_code']}\n"
        f"Ссылка для календаря: {_calendar_link(group['calendar_code'])}"
    )
    await _reshow(message, message.from_user.id)


@dp.callback_query(F.data == "subscribe")
async def subscribe_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if await asyncio.to_thread(_menu_state, callback.from_user.id) is not None:
        raise storage.AlreadyInGroup()
    await state.set_state(Subscribing.code)
    await callback.message.answer("Пришлите код приглашения от старосты.")


@dp.message(Subscribing.code)
async def subscribe_code(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip()
    try:
        group = await _db(storage.subscribe, message.from_user.id, code)
    except LookupError:
        await message.answer("Такого кода приглашения нет. Проверьте и пришлите ещё раз.")
        return
    await state.clear()
    await message.answer(f"Вы подписаны на группу {group['name']}.")
    await _reshow(message, message.from_user.id)


@dp.callback_query(F.data == "chsrc")
async def change_source_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _db(storage.require_headman, callback.from_user.id)
    await state.set_state(ChangingSource.source)
    await callback.message.answer("Пришлите новый адрес страницы расписания (http:// или https://).")


@dp.message(ChangingSource.source)
async def change_source_set(message: Message, state: FSMContext) -> None:
    url = (message.text or "").strip()
    if not _looks_like_url(url):
        await message.answer("Адрес должен начинаться с http:// или https://. Пришлите ещё раз.")
        return
    await message.answer("Проверяю источник…")
    try:
        count = await asyncio.to_thread(_change_source, message.from_user.id, url)
    except adapter.CollectError as exc:
        await message.answer(
            f"Не удалось разобрать расписание по этому адресу: {exc}\nПришлите адрес ещё раз."
        )
        return
    await state.clear()
    await message.answer(f"Адрес источника обновлён. Загружено занятий: {count}.")
    await _reshow(message, message.from_user.id)


@dp.callback_query(F.data.in_({"today", "tomorrow", "week"}))
async def view_schedule(callback: CallbackQuery) -> None:
    await callback.answer()
    rows = await asyncio.to_thread(_schedule, callback.from_user.id)
    if rows is None:
        raise storage.NotAMember()
    await callback.message.answer(_render_schedule(rows, callback.data, timeutil.today_msk()))


@dp.callback_query(F.data == "subs")
async def view_subscribers(callback: CallbackQuery) -> None:
    await callback.answer()
    people = await _db(storage.list_subscribers, callback.from_user.id)
    lines = [
        f"{p['tg_user_id']}" + (" — староста" if p["is_headman"] else "") for p in people
    ]
    await callback.message.answer(f"Подписчиков: {len(people)}\n" + "\n".join(lines))


@dp.callback_query(F.data == "edit")
async def edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _db(storage.require_headman, callback.from_user.id)
    await state.clear()
    sched = await asyncio.to_thread(_schedule, callback.from_user.id)
    today = timeutil.today_msk()
    horizon = today + timedelta(days=config.EDIT_HORIZON_DAYS)
    days = sorted({r["date"] for r in sched if today <= r["date"] <= horizon})
    if not days:
        await callback.message.answer(
            f"В ближайшие {config.EDIT_HORIZON_DAYS} дней занятий нет."
        )
        return
    buttons = [(f"{_WD[d.weekday()]} {d:%d.%m}", f"editday:{d.isoformat()}") for d in days]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    await callback.message.answer("Какой день изменить?", reply_markup=_kb(rows))


@dp.callback_query(F.data.startswith("editday:"))
async def edit_day(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    day = _day_tail(callback)
    sched = await asyncio.to_thread(_schedule, callback.from_user.id)
    if sched is None:
        raise storage.NotAMember()
    lessons = [r for r in sched if r["date"] == day]
    if not lessons:
        await callback.message.answer("На этот день занятий нет.")
        return
    await state.set_state(Editing.lesson)
    await state.update_data(
        day=day.isoformat(),
        lessons=[{"subject": r["subject"], "kind": r["kind"]} for r in lessons],
    )
    rows = []
    for i, r in enumerate(lessons):
        moment = timeutil.to_display(r["time_start"])
        mark = "❌ " if r["cancelled"] else ""
        rows.append([(f"{mark}{moment:%H:%M} {storage.lesson_title(r)}", f"editles:{i}")])
    await callback.message.answer("Какое занятие изменить?", reply_markup=_kb(rows))


@dp.callback_query(Editing.lesson, F.data.startswith("editles:"))
async def edit_pick(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    idx = _int_tail(callback)
    lessons = (await state.get_data()).get("lessons", [])
    if not 0 <= idx < len(lessons):
        raise BadChoice()
    chosen = lessons[idx]
    await state.update_data(subject=chosen["subject"], kind=chosen["kind"])
    await state.set_state(Editing.action)
    await callback.message.answer(
        f"{chosen['subject']} ({chosen['kind']}). Что сделать?",
        reply_markup=_kb(
            [
                [("Отменить занятие", "editact:cancel")],
                [("Перенести время", "editact:move")],
                [("Сменить аудиторию", "editact:room")],
            ]
        ),
    )


@dp.callback_query(Editing.action, F.data == "editact:cancel")
async def edit_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    day = date.fromisoformat(data["day"])
    gid = await _db(storage.cancel_lesson, callback.from_user.id, day, data["subject"], data["kind"])
    await state.clear()
    await callback.message.answer(f"{data['subject']} ({data['kind']}) на {day:%d.%m} отменено.")
    await _notify_edit(
        callback.bot, gid, callback.from_user.id,
        f"❗ Изменение расписания: {day:%d.%m} {data['subject']} ({data['kind']}) — занятие отменено.",
    )
    await _reshow(callback.message, callback.from_user.id)


@dp.callback_query(Editing.action, F.data == "editact:move")
async def edit_move(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    buttons = [
        (f"{start}–{end}", f"editpair:{pair}")
        for pair, (start, end) in sorted(config.BELL.items())
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    await callback.message.answer("На какую пару перенести?", reply_markup=_kb(rows))


@dp.callback_query(Editing.action, F.data.startswith("editpair:"))
async def edit_pair(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    pair = _int_tail(callback)
    if pair not in config.BELL:
        raise BadChoice()
    start_hhmm, end_hhmm = config.BELL[pair]
    data = await state.get_data()
    day = date.fromisoformat(data["day"])
    gid = await _db(
        storage.reschedule_lesson, callback.from_user.id, day, data["subject"], data["kind"],
        timeutil.to_utc(day, start_hhmm), timeutil.to_utc(day, end_hhmm),
    )
    await state.clear()
    await callback.message.answer(
        f"{data['subject']} ({data['kind']}) на {day:%d.%m} перенесено на {start_hhmm}."
    )
    await _notify_edit(
        callback.bot, gid, callback.from_user.id,
        f"❗ Изменение расписания: {day:%d.%m} {data['subject']} ({data['kind']})"
        f" — перенесено на {start_hhmm}.",
    )
    await _reshow(callback.message, callback.from_user.id)


@dp.callback_query(Editing.action, F.data == "editact:room")
async def edit_room_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(Editing.room)
    await callback.message.answer("Пришлите новую аудиторию.")


@dp.message(Editing.room)
async def edit_room_set(message: Message, state: FSMContext) -> None:
    room = (message.text or "").strip()
    if not room:
        await message.answer("Пришлите аудиторию текстом.")
        return
    data = await state.get_data()
    day = date.fromisoformat(data["day"])
    gid = await _db(
        storage.change_room, message.from_user.id, day, data["subject"], data["kind"], room
    )
    await state.clear()
    await message.answer(f"{data['subject']} ({data['kind']}) на {day:%d.%m}: аудитория {room}.")
    await _notify_edit(
        message.bot, gid, message.from_user.id,
        f"❗ Изменение расписания: {day:%d.%m} {data['subject']} ({data['kind']})"
        f" — новая аудитория {room}.",
    )
    await _reshow(message, message.from_user.id)


@dp.callback_query(F.data == "remind")
async def remind_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if await asyncio.to_thread(_menu_state, callback.from_user.id) is None:
        raise storage.NotAMember()
    await state.set_state(SettingRemind.value)
    await callback.message.answer(
        f"За сколько минут до занятия напоминать? Число от {config.REMIND_MIN_MINUTES} "
        f"до {config.REMIND_MAX_MINUTES}."
    )


@dp.message(SettingRemind.value)
async def remind_set(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Пришлите число минут.")
        return
    try:
        await _db(storage.set_remind_minutes, message.from_user.id, int(text))
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(f"Напоминание будет приходить за {int(text)} мин до занятия.")
    await _reshow(message, message.from_user.id)


@dp.callback_query(F.data == "quiet")
async def quiet_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if await asyncio.to_thread(_menu_state, callback.from_user.id) is None:
        raise storage.NotAMember()
    await state.set_state(SettingQuiet.value)
    await callback.message.answer(
        "Тихие часы в формате ЧЧ:ММ-ЧЧ:ММ, например 22:00-08:00. "
        "Чтобы выключить, пришлите «выкл»."
    )


@dp.message(SettingQuiet.value)
async def quiet_set(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().lower()
    if text in ("выкл", "off"):
        await _db(storage.set_quiet_hours, message.from_user.id, None, None)
        await state.clear()
        await message.answer("Тихие часы выключены.")
        await _reshow(message, message.from_user.id)
        return
    parsed = _parse_quiet(text)
    if parsed is None:
        await message.answer("Не понял формат. Пример: 22:00-08:00 или «выкл».")
        return
    start, end = parsed
    await _db(storage.set_quiet_hours, message.from_user.id, start, end)
    await state.clear()
    await message.answer(
        f"Тихие часы: с {start} до {end}. Уведомления о правках расписания приходят всегда."
    )
    await _reshow(message, message.from_user.id)


@dp.callback_query(F.data == "unsub")
async def unsubscribe(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    group = await _db(storage.unsubscribe, callback.from_user.id)
    await callback.message.answer(
        f"Вы отписались от группы {group['name']}. Сообщения больше не будут приходить."
    )
    await _reshow(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "announce")
async def announce_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _db(storage.require_headman, callback.from_user.id)
    await state.set_state(Announcing.text)
    await callback.message.answer("Пришлите текст объявления для всех подписчиков.")


@dp.message(Announcing.text)
async def announce_send(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пришлите текст объявления.")
        return
    await _db(storage.post_announcement, message.from_user.id, text)
    await state.clear()
    await message.answer(
        "Объявление принято. Подписчики получат его в ближайшие минуты "
        "(в тихие часы — после их окончания)."
    )
    await _reshow(message, message.from_user.id)


@dp.callback_query(F.data == "transfer")
async def transfer_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    people = await asyncio.to_thread(_members, callback.from_user.id)
    if not people:
        await callback.message.answer("В группе нет других подписчиков — некому передать роль.")
        return
    rows = [[(str(uid), f"trto:{uid}")] for uid in people]
    await callback.message.answer(
        "Кому передать роль старосты? Подписчики показаны по Telegram ID.",
        reply_markup=_kb(rows),
    )


@dp.callback_query(F.data.startswith("trto:"))
async def transfer_to(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    new_id = _int_tail(callback)
    await _db(storage.transfer_role, callback.from_user.id, new_id)
    await callback.message.answer(
        f"Роль старосты передана пользователю {new_id}. Теперь вы обычный подписчик."
    )
    try:
        await callback.bot.send_message(
            new_id,
            "Вам передали роль старосты группы: теперь вы можете править расписание "
            "и рассылать объявления.",
        )
    except Exception:
        log.warning("Не удалось уведомить нового старосту")
    await _reshow(callback.message, callback.from_user.id)


async def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        log.error("BOT_TOKEN не задан: впишите токен от @BotFather в .env")
        raise SystemExit(1)
    storage.ensure_schema()
    log.info("Бот запущен")
    bot = Bot(token)
    tasks = [asyncio.create_task(t) for t in (run_scheduler(), run_dispatch(bot), run_backup())]
    try:
        await dp.start_polling(bot)
    finally:
        for task in tasks:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
