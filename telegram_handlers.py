from config import logger
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from bot import main_bot


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    await update.message.chat.send_action(action="typing")
    response = await main_bot.generate_response(chat_id, user_id, "", is_start=True)
    await update.message.reply_text(response)
    logger.info(f"/start от {user_id}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сообщений в приватных чатах И обычных сообщений в группах"""
    try:
        if not update.message or not update.message.text:
            return

        user_msg = update.message.text

        # Пропуск команд
        if user_msg.startswith('/'):
            return

        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        # Установка информации о боте
        if not main_bot.bot_id and context.bot:
            main_bot.set_bot_info(context.bot.username, context.bot.id)

        # Для групп: проверяем, должен ли бот отвечать
        if update.effective_chat.type in ['group', 'supergroup']:
            if not main_bot.should_respond_in_group(update):
                logger.debug(f"Бот не должен отвечать в группе {chat_id}")
                return

        # Генерация ответа
        await update.message.chat.send_action(action="typing")
        response = await main_bot.generate_response(chat_id, user_id, user_msg)
        await update.message.reply_text(response)

        logger.debug(f"Ответ отправлен в чат {chat_id}")

    except Exception as e:
        logger.error(f"Ошибка обработки: {e}")


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ТОЛЬКО постов канала в группах"""
    try:
        message = update.message
        if not message:
            return

        chat_id = update.effective_chat.id

        logger.debug(f"Сообщение в группе {chat_id}: text='{message.text}', caption='{message.caption}'")

        # ПРОВЕРЯЕМ, ЧТО ЭТО ПОСТ КАНАЛА
        is_channel_post = main_bot.commenting_system.is_channel_post(message)

        if is_channel_post:
            logger.info(f"Обнаружен пост канала в чате {chat_id}")

            # ПЕРЕДАЕМ В СИСТЕМУ КОММЕНТИРОВАНИЯ
            await main_bot.commenting_system.process_group_post(update, context)
            return

        # ЕСЛИ ЭТО НЕ ПОСТ КАНАЛА - ОБРАБАТЫВАЕМ КАК ОБЫЧНОЕ СООБЩЕНИЕ
        logger.debug(f"Обычное сообщение в группе {chat_id}")
        await handle_message(update, context)

    except Exception as e:
        logger.error(f"Ошибка обработки группового сообщения: {e}")


def setup_handlers(application):
    """Настройка обработчиков"""

    # Для приватных чатов (личные сообщения боту)
    private_handler = MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_message
    )

    # Для групповых чатов - ВСЕ сообщения, но логика внутри handle_group_message
    # решит, это пост канала или обычное сообщение
    group_handler = MessageHandler(
        (filters.TEXT | filters.CAPTION | filters.PHOTO) & ~filters.COMMAND &
        (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP),
        handle_group_message
    )

    # Команды работают везде
    start_handler = CommandHandler("start", start_command)

    handlers = [
        start_handler,
        private_handler,
        group_handler,
    ]

    for handler in handlers:
        application.add_handler(handler)

    logger.info("Обработчики настроены: приватные чаты + группы")