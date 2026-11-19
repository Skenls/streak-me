from aiogram import Dispatcher, F
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
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
from .rules import STATIC_INVITE, issue_chat_key, read_chat_key, read_invite


def open_app(app_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть StreakMe", web_app=WebAppInfo(url=app_url))
    ]])


def invite_link(username: str, code: str) -> str:
    return f"https://t.me/{username}?start=join_{code}"


def status_text(pair) -> str:
    if pair["status"] == "lost":
        return f"Огонёк погас после {pair['days']} дн. Восстановить его можно в StreakMe."
    if pair["status"] == "active":
        return f"🔥 Дней подряд: {pair['days']}. Сегодня оба отметились!"
    if pair["confirmed"]:
        return f"🧊 Дней подряд: {pair['days']}. Ты отметился, теперь очередь друга."
    return f"🧊 Дней подряд: {pair['days']}. Отметься сегодня, чтобы поддержать огонёк."


def dispatcher(db: Database, username: str, token: str, app_url: str) -> Dispatcher:
    dp = Dispatcher(disable_fsm=True)

    @dp.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
    async def start(message: Message, command: CommandObject):
        user = message.from_user
        if user is None:
            return
        await db.save_profile(user)
        text = "Привет! Открой StreakMe, чтобы посмотреть свои серии или пригласить друга."
        if command.args and command.args.startswith("join_"):
            invite = command.args.removeprefix("join_")
            if STATIC_INVITE.fullmatch(invite):
                result = await db.accept_invite(invite, user.id)
            else:
                inviter = read_invite(invite, token)
                result = await db.accept_invite(invite, user.id, legacy_inviter=inviter) if inviter else "invalid"
            text = {
                "ok": "🔥 Огонёк готов! Отметьтесь оба, чтобы засчитать день.",
                "own": "Это твоё приглашение. Отправь его другу.",
                "invalid": "Ссылка недействительна. Попроси друга прислать актуальную.",
                "claimed": "Это старое приглашение уже использовано. Попроси друга прислать актуальную ссылку.",
            }[result]
        await message.answer(text, reply_markup=open_app(app_url))

    @dp.message(Command("reset"), F.chat.type == ChatType.PRIVATE)
    async def reset(message: Message):
        user = message.from_user
        if user is None:
            return
        await db.save_profile(user)
        link = invite_link(username, await db.invite_code(user.id, reset=True))
        await message.answer(f"Ссылка обновлена. Предыдущая больше не действует.\n{link}")

    @dp.inline_query()
    async def inline(query: InlineQuery):
        user = query.from_user
        await db.save_profile(user)
        link = invite_link(username, await db.invite_code(user.id))
        buttons = [[InlineKeyboardButton(text="Принять приглашение", url=link)]]
        if query.chat_type == ChatType.PRIVATE:
            key = issue_chat_key(user.id, token)
            buttons.append([
                InlineKeyboardButton(text="Статус огонька", callback_data=f"chat:status:{key}"),
                InlineKeyboardButton(text="Продлить", callback_data=f"chat:confirm:{key}"),
            ])
        result = InlineQueryResultArticle(
            id="invite", title="Пригласить друга", description="Отправить ссылку на общий огонёк",
            input_message_content=InputTextMessageContent(message_text="🔥 Давай зажжём общий огонёк в StreakMe!"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        await query.answer([result], cache_time=0, is_personal=True)

    @dp.callback_query(F.data.regexp(r"^chat:(confirm|status):[A-Za-z0-9_-]{38}$"))
    async def pair_action(query: CallbackQuery):
        _, action, key = query.data.split(":", 2)
        owner = read_chat_key(key, token)
        if owner is None or not query.inline_message_id:
            await query.answer("Эта кнопка доступна в карточке личного чата.", show_alert=True)
            return
        user = query.from_user.id
        pair_id = await db.inline_pair(query.chat_instance, owner, user)
        pair = await db.get(pair_id, user, action="confirm" if action == "confirm" else None) if pair_id else None
        if pair:
            text = status_text(pair)
        elif owner == user and pair_id is None:
            text = "Пусть друг первым нажмёт кнопку на этой карточке, чтобы бот нашёл вашу серию."
        else:
            text = "В этом личном чате нет общей серии. Воспользуйтесь приглашением."
        await query.answer(text, show_alert=True)

    @dp.callback_query(F.data.regexp(r"^(confirm|status):[1-9][0-9]{0,17}$"))
    async def old_pair_action(query: CallbackQuery):
        await query.answer("Отправьте новую карточку StreakMe в личный чат.", show_alert=True)

    return dp
