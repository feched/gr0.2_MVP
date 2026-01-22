import torch
from telegram_handlers import setup_handlers
from telegram.ext import Application

from bot import main_bot


def main():
    """Точка входа"""
    BOT_TOKEN = "token"

    print("=" * 50)
    print("ПРОВЕРКА GPU:")
    print(f"Доступен CUDA: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU устройство: {torch.cuda.get_device_name(0)}")
        print(f"Кол-во GPU: {torch.cuda.device_count()}")
        print(f"Память GPU: {torch.cuda.get_device_properties(0).total_memory / 1024 ** 3:.1f} GB")
    else:
        print("GPU не найден! Проверь установку CUDA и PyTorch")
    print("=" * 50)

    print("Инициализация...")

    # Инициализация
    main_bot.initialize_model()

    # Статистика
    print(f"Диалогов в RAG: {len(main_bot.rag.dialogues)}")
    print(f"Пользователей: {len(main_bot.user_memory.users)}")

    # Запуск бота
    application = Application.builder().token(BOT_TOKEN).build()
    setup_handlers(application)

    print("Бот запущен!")
    print("=" * 40)
    print("Доступные команды:")
    print("/start - начать диалог")
    print("=" * 40)

    application.run_polling()


if __name__ == "__main__":
    main()