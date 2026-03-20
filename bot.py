import json
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
#  НАСТРОЙКИ — заполни перед запуском
# ============================================================
BOT_TOKEN  = "8678982386:AAFm5xGJQpgUrifplVcOyOuBbEv33e24z2g"        # Токен от @BotFather
GROUP_ID   = -1002112502375            # ID группы (отрицательное число)
ADMIN_IDS  = [535618527]               # Твой Telegram ID
BOT_USERNAME = "svob_led_bot"             # username бота без @
# ============================================================

CHANNELS_FILE = "channels.json"

# Хранилище: user_id -> {"text": ..., "photo": ..., ...}
pending_posts: dict = {}


# ─────────────────────────────────────────────────────────────
#  Работа с файлом каналов
# ─────────────────────────────────────────────────────────────

def load_channels() -> list:
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE, encoding="utf-8") as f:
            return json.load(f)
    # Значения по умолчанию
    default = [
        {"username": "@channel1", "name": "Хоккей Новости",   "url": "https://t.me/channel1"},
        {"username": "@channel2", "name": "Хоккей Барахолка", "url": "https://t.me/channel2"},
    ]
    save_channels(default)
    return default


def save_channels(channels: list) -> None:
    with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────
#  Проверка подписки на все каналы
# ─────────────────────────────────────────────────────────────

async def get_unsubscribed(bot, user_id: int, channels: list) -> list:
    """Возвращает список каналов, на которые пользователь НЕ подписан."""
    result = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["username"], user_id)
            if member.status not in ("member", "administrator", "creator"):
                result.append(ch)
        except Exception:
            result.append(ch)
    return result


# ─────────────────────────────────────────────────────────────
#  Кнопки подписки
# ─────────────────────────────────────────────────────────────

def build_keyboard(channels: list) -> InlineKeyboardMarkup:
    keyboard = []
    for ch in channels:
        keyboard.append([
            InlineKeyboardButton(f"📢 {ch['name']}", url=ch["url"])
        ])
    keyboard.append([
        InlineKeyboardButton("✅ Я выполнил", callback_data="check")
    ])
    return InlineKeyboardMarkup(keyboard)


# ─────────────────────────────────────────────────────────────
#  Обработка новых сообщений в группе
# ─────────────────────────────────────────────────────────────

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user   = msg.from_user
    channels = load_channels()

    # Администраторы проходят без проверки
    chat_member = await context.bot.get_chat_member(GROUP_ID, user.id)
    if chat_member.status in ("administrator", "creator"):
        return

    # Проверяем подписки
    not_subscribed = await get_unsubscribed(context.bot, user.id, channels)
    if not not_subscribed:
        return  # Уже подписан на всё — пост остаётся

    # ── Сохраняем пост ──────────────────────────────────────
    post_data = {
        "text":       msg.text or msg.caption or "",
        "photo":      msg.photo[-1].file_id if msg.photo else None,
        "video":      msg.video.file_id     if msg.video else None,
        "document":   msg.document.file_id  if msg.document else None,
        "caption":    msg.caption           if (msg.photo or msg.video or msg.document) else None,
        "username":   user.username or user.first_name,
    }
    pending_posts[user.id] = post_data

    # ── Удаляем исходный пост ───────────────────────────────
    try:
        await context.bot.delete_message(GROUP_ID, msg.message_id)
    except Exception as e:
        logger.warning(f"Не смог удалить сообщение: {e}")

    # ── Пишем пользователю в личку ──────────────────────────
    text = (
        "❤️ Чтобы опубликовать объявление —\n"
        "подпишись на хоккейные проекты!\n\n"
        "После подписки нажми *«✅ Я выполнил»* и объявление появится в группе 👇"
    )
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=text,
            reply_markup=build_keyboard(channels),
            parse_mode="Markdown",
        )
    except Exception:
        # Если бот ещё не начат пользователем — просим написать ему
        link = f"https://t.me/{BOT_USERNAME}?start=post"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📩 Написать боту", url=link)
        ]])
        try:
            await context.bot.send_message(
                GROUP_ID,
                f"@{user.username or user.first_name}, чтобы опубликовать объявление "
                f"— напиши боту в личку и нажми START 👇",
                reply_markup=kb,
            )
        except Exception as e:
            logger.error(f"Совсем не смог уведомить пользователя: {e}")


# ─────────────────────────────────────────────────────────────
#  Обработка кнопки «Я выполнил»
# ─────────────────────────────────────────────────────────────

async def check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user  = query.from_user
    channels = load_channels()

    not_subscribed = await get_unsubscribed(context.bot, user.id, channels)

    if not_subscribed:
        names = ", ".join(ch["name"] for ch in not_subscribed)
        await query.answer(f"❌ Ещё не подписан на: {names}", show_alert=True)
        return

    # ── Публикуем сохранённый пост ──────────────────────────
    post = pending_posts.pop(user.id, None)
    if not post:
        await query.answer("⚠️ Объявление не найдено. Отправь его снова в группу.", show_alert=True)
        return

    try:
        tag = f"@{post['username']}" if post["username"] else "Участник"

        if post["photo"]:
            await context.bot.send_photo(
                GROUP_ID,
                photo=post["photo"],
                caption=f"📌 Объявление от {tag}:\n\n{post['caption'] or ''}",
            )
        elif post["video"]:
            await context.bot.send_video(
                GROUP_ID,
                video=post["video"],
                caption=f"📌 Объявление от {tag}:\n\n{post['caption'] or ''}",
            )
        elif post["document"]:
            await context.bot.send_document(
                GROUP_ID,
                document=post["document"],
                caption=f"📌 Объявление от {tag}:\n\n{post['caption'] or ''}",
            )
        else:
            await context.bot.send_message(
                GROUP_ID,
                f"📌 Объявление от {tag}:\n\n{post['text']}",
            )

        await query.edit_message_text("✅ Готово! Твоё объявление опубликовано в группе.")

    except Exception as e:
        logger.error(f"Ошибка публикации: {e}")
        await query.answer("⚠️ Не удалось опубликовать. Попробуй снова.", show_alert=True)


# ─────────────────────────────────────────────────────────────
#  /start — личка бота
# ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот барахолки 🏒\n\n"
        "Отправь объявление в группу, и я помогу его опубликовать."
    )


# ─────────────────────────────────────────────────────────────
#  Админ-команды
# ─────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def cmd_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить канал. Формат: /addchannel @username Название https://t.me/username"""
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Формат:\n/addchannel @username Название https://t.me/username\n\n"
            "Пример:\n/addchannel @hockey_ru Хоккей РФ https://t.me/hockey_ru"
        )
        return

    username, name, url = args[0], args[1], args[2]
    if not username.startswith("@"):
        username = "@" + username

    channels = load_channels()
    if any(c["username"] == username for c in channels):
        await update.message.reply_text(f"⚠️ Канал {username} уже есть в списке.")
        return

    channels.append({"username": username, "name": name, "url": url})
    save_channels(channels)
    await update.message.reply_text(f"✅ Канал *{name}* добавлен!", parse_mode="Markdown")


async def cmd_remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить канал. Формат: /removechannel @username"""
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Формат: /removechannel @username")
        return

    username = args[0] if args[0].startswith("@") else "@" + args[0]
    channels = load_channels()
    new_channels = [c for c in channels if c["username"] != username]

    if len(new_channels) == len(channels):
        await update.message.reply_text(f"⚠️ Канал {username} не найден.")
        return

    save_channels(new_channels)
    await update.message.reply_text(f"✅ Канал {username} удалён.")


async def cmd_list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список каналов: /listchannels"""
    if not is_admin(update.effective_user.id):
        return

    channels = load_channels()
    if not channels:
        await update.message.reply_text("Список каналов пуст.")
        return

    lines = ["📋 *Каналы для подписки:*\n"]
    for i, ch in enumerate(channels, 1):
        lines.append(f"{i}. *{ch['name']}* — {ch['username']}\n   {ch['url']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика ожидающих постов: /stats"""
    if not is_admin(update.effective_user.id):
        return
    count = len(pending_posts)
    await update.message.reply_text(f"📊 Сейчас ожидают публикации: *{count}* объявлений.", parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────
#  Запуск
# ─────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("addchannel",    cmd_add_channel))
    app.add_handler(CommandHandler("removechannel", cmd_remove_channel))
    app.add_handler(CommandHandler("listchannels",  cmd_list_channels))
    app.add_handler(CommandHandler("stats",         cmd_stats))

    # Сообщения в группе
    app.add_handler(MessageHandler(
        filters.Chat(GROUP_ID) & ~filters.COMMAND,
        handle_group_message
    ))

    # Кнопка «Я выполнил»
    app.add_handler(CallbackQueryHandler(check_callback, pattern="^check$"))

    logger.info("Бот запущен ✅")
    app.run_polling()


if __name__ == "__main__":
    main()
