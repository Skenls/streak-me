from aiogram import Dispatcher, F
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
    WebAppInfo,
)

from .db import Database
from .rules import issue_invite, read_invite


def keyboard(label: str, **action) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, **action)]])


def invite_link(username: str, user_id: int, secret: str) -> str:
    return f"https://t.me/{username}?start=join_{issue_invite(user_id, secret)}"


def article(identifier, title, description, text, button):
    return InlineQueryResultArticle(
        id=identifier,
        title=title,
        description=description,
        input_message_content=InputTextMessageContent(message_text=text),
        reply_markup=button,
    )


def status_text(pair) -> str:
    if pair["confirmed"] and pair["friendConfirmed"]:
        return f"🔥 Дней подряд: {pair['days']}. Сегодня оба отметились!"
    if pair["confirmed"]:
        return f"🔥 Дней подряд: {pair['days']}. Ты отметился, теперь очередь друга."
    return f"🔥 Дней подряд: {pair['days']}. Отметься сегодня, чтобы поддержать огонёк."


def dispatcher(db: Database, username: str, token: str, app_url: str) -> Dispatcher:
    dp = Dispatcher()

    @dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
    async def start(message: Message, command: CommandObject):
        user = message.from_user
        if user is None:
            return
        await db.save_profile(user)
        text = "Привет! Открой StreakMe, чтобы посмотреть свои серии или пригласить друга."
        if command.args and command.args.startswith("join_"):
            invite = command.args.removeprefix("join_")
            inviter = read_invite(invite, token)
            if inviter is None:
                text = "Срок приглашения истёк или ссылка неверна. Попроси друга отправить новую."
            elif inviter == user.id:
                text = "Это твоё приглашение. Отправь его другу."
            elif await db.accept(invite, inviter, user.id):
                text = "🔥 Огонёк создан! Отметьтесь оба, чтобы засчитать первый день."
            else:
                text = "Это приглашение уже приняли. Попроси друга отправить новое."
        await message.answer(text, reply_markup=keyboard("Открыть StreakMe", web_app=WebAppInfo(url=app_url)))

    @dp.inline_query()
    async def inline(query: InlineQuery):
        user = query.from_user
        await db.save_profile(user)
        search = query.query.strip().lstrip("@").casefold()
        pairs = [
            pair for pair in await db.list(user.id)
            if search in pair["friend"]["name"].casefold()
            or search in (pair["friend"]["username"] or "").casefold()
        ]
        results = [article(
            "invite", "Пригласить друга", "Отправить одноразовое приглашение",
            "🔥 Давай зажжём общий огонёк в StreakMe!",
            keyboard("Принять приглашение", url=invite_link(username, user.id, token)),
        )]
        for pair in pairs[:24]:
            name = pair["friend"]["name"]
            pair_id = pair["id"]
            results.extend((
                article(
                    f"confirm:{pair_id}", f"Продлить серию · {name}",
                    "Отправить кнопку отметки на сегодня",
                    "🔥 Отметимся сегодня в StreakMe?",
                    keyboard("Отметиться", callback_data=f"confirm:{pair_id}"),
                ),
                article(
                    f"status:{pair_id}", f"Статус огонька · {name}",
                    f"Дней подряд: {pair['days']}",
                    f"🔥 StreakMe · дней подряд: {pair['days']}",
                    keyboard("Проверить статус", callback_data=f"status:{pair_id}"),
                ),
            ))
        if not pairs:
            bot_link = f"https://t.me/{username}"
            for identifier, title in (("confirm", "Продлить серию"), ("status", "Статус огонька")):
                results.append(article(
                    identifier, title, "Нет подходящих серий",
                    "🔥 Серии с друзьями доступны в StreakMe.",
                    keyboard("Открыть бота", url=bot_link),
                ))
        await query.answer(results, cache_time=0, is_personal=True)

    @dp.callback_query(F.data.regexp(r"^(confirm|status):[1-9][0-9]{0,17}$"))
    async def pair_action(query: CallbackQuery):
        action, pair_id = query.data.split(":", 1)
        pair = await db.get(int(pair_id), query.from_user.id, confirm=action == "confirm")
        text = status_text(pair) if pair else "Только участники огонька могут использовать эту кнопку."
        await query.answer(text, show_alert=True)

    return dp
