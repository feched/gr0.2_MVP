from config import logger
import json
from datetime import datetime
import re

import torch
from telegram import Update, Message
from telegram.ext import ContextTypes


class CommentingConfig:
    """Конфигурация для системы комментирования"""

    def __init__(self, config_file: str = "commenting_config.json"):
        self.config_file = config_file
        self.config = self._load_config()

    def _load_config(self):
        """Загружает конфигурацию"""
        default_config = {
            "enabled_groups": [-1003284056823],
            "min_post_length": 3,  # ЕЩЕ МЕНЬШЕ для коротких подписей
            "max_comments_per_hour": 20,
            "comment_media_posts": True,
            "debug": True
        }

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                default_config.update(loaded)
                return default_config
        except:
            return default_config

    def can_comment_in_group(self, group_id: int) -> bool:
        """Проверяет, можно ли комментировать в группе"""
        return group_id in self.config["enabled_groups"]


class AutoCommentingSystem:
    """Система автоматического комментирования постов в каналах"""

    def __init__(self, grisha_bot):
        self.grisha_bot = grisha_bot
        self.config = CommentingConfig()
        self.comment_history_file = "comment_history.json"
        self.comment_history = self._load_history()

        logger.info("Система комментирования инициализирована")

    def _load_history(self):
        """Загружает историю комментариев"""
        try:
            with open(self.comment_history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    def _save_history(self):
        """Сохраняет историю комментариев"""
        try:
            with open(self.comment_history_file, 'w', encoding='utf-8') as f:
                json.dump(self.comment_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения истории: {e}")

    def has_commented(self, group_id: int, post_id: int) -> bool:
        """Проверяем, комментировали ли уже этот пост"""
        key = f"{group_id}_{post_id}"
        return key in self.comment_history

    def add_to_history(self, group_id: int, post_id: int, comment_text: str):
        """Добавляет комментарий в историю"""
        key = f"{group_id}_{post_id}"
        self.comment_history[key] = {
            "group_id": group_id,
            "post_id": post_id,
            "comment_text": comment_text[:100],
            "timestamp": datetime.now().isoformat()
        }

        if len(self.comment_history) > 500:
            oldest_keys = sorted(self.comment_history.keys())[:100]
            for key_to_remove in oldest_keys:
                del self.comment_history[key_to_remove]

        self._save_history()

    def is_channel_post(self, message: Message) -> bool:
        """СУПЕР-ПРОСТАЯ ПРОВЕРКА С ПРИНТАМИ"""
        print(f"\n=== is_channel_post ДЛЯ СООБЩЕНИЯ {message.message_id} ===")
        print(f"text: '{message.text}'")
        print(f"caption: '{message.caption}'")
        print(f"photo: {bool(message.photo)}")

        # Признак 1: sender_chat есть и это канал
        if message.sender_chat:
            print(f"sender_chat.type: '{message.sender_chat.type}'")
            if message.sender_chat.type == 'channel':
                print("ПРИЗНАК 1: sender_chat.type == 'channel' - ЭТО ПОСТ КАНАЛА!")
                return True

        # Признак 2: forward_origin есть и это канал
        if hasattr(message, 'forward_origin') and message.forward_origin:
            print(f"forward_origin.type: '{message.forward_origin.type}'")
            if message.forward_origin.type == 'channel':
                print("ПРИЗНАК 2: forward_origin.type == 'channel' - ЭТО ПЕРЕСЛАННЫЙ ПОСТ КАНАЛА!")
                return True

        print("НИ ОДИН ПРИЗНАК НЕ СРАБОТАЛ - ЭТО НЕ ПОСТ КАНАЛА")
        print("==================================================")
        return False

    def _should_skip_post(self, text: str, message: Message) -> bool:
        """Определяет, нужно ли пропустить этот пост"""
        # Если есть текст или подпись - обрабатываем
        if text and len(text.strip()) > 0:
            text_lower = text.lower().strip()

            # Пропускаем команды
            if text_lower.startswith('/'):
                logger.info(f"Пропускаем команду: {text}")
                return True

            # Пропускаем слишком короткие сообщения
            min_length = self.config.config.get("min_post_length", 3)
            if len(text.strip()) < min_length:
                logger.info(f"Слишком короткий текст: '{text}' ({len(text.strip())} chars)")
                return True

            # Пропускаем определенные паттерны
            skip_patterns = [
                r'^\.\.\.+$',
                r'^---+$',
                r'^\[.*\]$',
            ]

            for pattern in skip_patterns:
                if re.match(pattern, text.strip()):
                    logger.info(f"Пропускаем по паттерну: '{text}'")
                    return True

            return False

        # Если текста нет совсем (только медиа без подписи)
        logger.info(f"Нет текста для комментария")
        return True

    def _get_post_text(self, message: Message) -> str:
        """
        Получает текст поста - ПРОСТАЯ ВЕРСИЯ
        """
        # Обычный текст
        if message.text:
            return message.text

        # Подпись к медиа (ФОТО/ВИДЕО)
        if message.caption:
            return message.caption

        # Имя документа
        if message.document and message.document.file_name:
            return message.document.file_name

        return ""

    def _has_media(self, message: Message) -> bool:
        """Проверяет, содержит ли сообщение медиа"""
        return bool(
            message.photo or
            message.video or
            message.document or
            message.audio or
            message.voice or
            message.video_note or
            message.sticker or
            message.animation
        )

    async def generate_comment(self, post_text: str, has_media: bool = False) -> str:
        """
        Генерирует комментарий на пост - УПРОЩЕННЫЙ ПРОМПТ
        """
        try:
            # СУПЕР-ПРОСТОЙ ПРОМПТ
            prompt = f"""<|im_start|>system
Ты — Гриша, чат-бот. Ты видишь пост в канале.
Отвечай коротко и естественно, как в обычном диалоге.
<|im_end|>

<|im_start|>user
{post_text}
<|im_end|>

<|im_start|>assistant
"""

            logger.info(f"Генерируем комментарий для: '{post_text[:50]}...'")

            if not self.grisha_bot.model_loaded:
                logger.warning("Модель не загружена, используем fallback")
                return self._get_fallback_comment(has_media)

            # Генерация через модель
            try:
                inputs = self.grisha_bot.tokenizer(
                    prompt,
                    return_tensors="pt",
                    truncation=True,
                    max_length=512
                )

                device = self.grisha_bot.model.device
                inputs = {k: v.to(device) for k, v in inputs.items()}

                with torch.no_grad():
                    outputs = self.grisha_bot.model.generate(
                        **inputs,
                        max_new_tokens=100,
                        temperature=0.8,
                        do_sample=True,
                        top_p=0.9,
                        repetition_penalty=1.1,
                        pad_token_id=self.grisha_bot.tokenizer.eos_token_id
                    )

                response_length = inputs['input_ids'].shape[1]
                comment = self.grisha_bot.tokenizer.decode(
                    outputs[0][response_length:],
                    skip_special_tokens=True
                )

                # Очищаем ответ
                comment = self._clean_comment(comment)

                if comment and len(comment.strip()) > 3:
                    logger.info(f"Сгенерирован комментарий: {comment[:50]}...")
                    return comment[:250]

                logger.warning("Сгенерирован пустой комментарий")
                return self._get_fallback_comment(has_media)

            except Exception as e:
                logger.error(f"Ошибка генерации LLM: {e}")
                return self._get_fallback_comment(has_media)

        except Exception as e:
            logger.error(f"Общая ошибка генерации комментария: {e}")
            return "👍"

    def _get_fallback_comment(self, has_media: bool = False) -> str:
        """Запасные варианты комментариев"""
        import random

        if has_media:
            fallback_comments = [
                "Отличное фото!",
                "Хорошая картинка!",
                "Интересно!",
                "Класс!",
                "👍",
                "👌",
                "😊",
                "Интересный визуал!",
                "Спасибо за пост!",
            ]
        else:
            fallback_comments = [
                "Интересная мысль!",
                "Спасибо за пост!",
                "Хороший материал!",
                "Полезная информация!",
                "Заставляет задуматься!",
                "Согласен!",
                "Интересно!",
                "Хорошо сказано!",
            ]

        return random.choice(fallback_comments)

    def _clean_comment(self, comment: str) -> str:
        """Очищает комментарий"""
        if not comment:
            return ""

        # Убираем специальные токены
        comment = re.sub(r'<\|[^>]+\|>', '', comment)

        # Убираем лишние пробелы
        comment = re.sub(r'\s+', ' ', comment)

        # Убираем кавычки в начале/конце
        comment = comment.strip('"\'').strip()

        return comment

    async def process_group_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        УПРОЩЕННЫЙ обработчик постов - ПРИНУДИТЕЛЬНАЯ ОБРАБОТКА
        """
        try:
            message = update.message
            if not message:
                print("Нет сообщения")
                return

            chat_id = update.effective_chat.id
            message_id = message.message_id

            # ПРИНУДИТЕЛЬНЫЙ ВЫВОД
            print(f"\nПРОЦЕССИНГ ПОСТА {message_id}:")
            print(f"   Чат: {chat_id}")
            print(f"   Текст: '{message.text}'")
            print(f"   Caption: '{message.caption}'")
            print(f"   Фото: {bool(message.photo)}")
            print(f"   Sender Chat тип: {getattr(message.sender_chat, 'type', 'Нет')}")

            # ПРИНУДИТЕЛЬНО: если есть caption и фото - обрабатываем
            if message.caption and (message.photo or message.video):
                print(f"ПРИНУДИТЕЛЬНАЯ ОБРАБОТКА МЕДИА-ПОСТА!")

                # Получаем текст
                post_text = message.caption
                has_media = True

                print(f"Текст для комментария: '{post_text}'")

                # Генерируем комментарий
                comment_text = await self.generate_comment(post_text, has_media)

                if comment_text and len(comment_text.strip()) > 2:
                    print(f"Сгенерирован комментарий: {comment_text[:50]}...")

                    # Отправляем
                    await message.reply_text(comment_text)
                    print(f"Комментарий отправлен!")
                    return
                else:
                    print(f"Не удалось сгенерировать комментарий")
                    return

            chat_id = update.effective_chat.id
            message_id = message.message_id

            # 1. Проверяем, что группа разрешена
            if not self.config.can_comment_in_group(chat_id):
                logger.debug(f"Группа {chat_id} не в списке")
                return

            # 2. Проверяем, что это пост канала
            if not self.is_channel_post(message):
                logger.debug(f"Не пост канала")
                return

            # 3. Получаем текст
            post_text = self._get_post_text(message)
            has_media = self._has_media(message)

            # Логируем что получили
            logger.info(
                f"Пост {message_id}: text='{message.text}', caption='{message.caption}', has_media={has_media}")

            # 4. Проверяем, нужно ли пропустить
            if self._should_skip_post(post_text, message):
                return

            # 5. Проверяем, не комментировали ли уже
            if self.has_commented(chat_id, message_id):
                logger.debug(f"Уже комментировали пост {message_id}")
                return

            logger.info(f"Начинаем обработку поста {message_id}: '{post_text[:50]}...'")

            # 6. Генерируем комментарий
            comment_text = await self.generate_comment(post_text, has_media)

            if not comment_text or len(comment_text.strip()) < 2:
                logger.warning(f"Не удалось сгенерировать комментарий для поста {message_id}")
                return

            # 7. Отправляем комментарий
            try:
                await message.reply_text(comment_text)

                # 8. Сохраняем в историю
                self.add_to_history(chat_id, message_id, comment_text)

                logger.info(f"Отправлен комментарий к посту {message_id}: {comment_text[:50]}...")

            except Exception as e:
                logger.error(f"Ошибка отправки комментария: {e}")

        except Exception as e:
            logger.error(f"Ошибка обработки поста: {e}")
