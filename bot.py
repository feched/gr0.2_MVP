import re
import torch
import transformers
import telegram
from datetime import datetime

from config import logger, SYSTEM_PROMPT, MODEL_NAME
from memory import UserMemory, ConversationMemory
from commenting import AutoCommentingSystem
from rag import RAGSystem
from learning import ImprovedLearningSystem


class MainBot:
    """ Основной класс для чат-бота """
    def __init__(self):
        # Модули
        self.memory = ConversationMemory()
        self.rag = RAGSystem()
        self.learning = ImprovedLearningSystem()
        self.user_memory = UserMemory()

        # Модель
        self.tokenizer = None
        self.model = None
        self.model_loaded = False

        # Информация бота
        self.bot_username = None
        self.bot_id = None

        # Кэш быстрых ответов
        self.response_cache = {}

        # Система автокомментирования
        self.commenting_system = AutoCommentingSystem(self)

        logger.info("Бот инициализирован")

    # метод сохраняет информацию о самом боте в Telegram для правильной работы в групповых чатах.
    def set_bot_info(self, username: str, bot_id: int):
        self.bot_username = username.lower().replace('@', '') if username else None
        self.bot_id = bot_id
        logger.info(f"Бот: @{self.bot_username} (ID: {bot_id})")

    # метод загружает модель LLM в память.
    def initialize_model(self):
        try:
            logger.info("Загрузка модели...")

            # Загрузка токенизатора
            self.tokenizer = transformers.AutoTokenizer.from_pretrained(
                MODEL_NAME,
                trust_remote_code=True
            )

            # Сама загрузка модели
            self.model = transformers.AutoModelForCausalLM.from_pretrained(
                MODEL_NAME,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else "cpu",
                trust_remote_code=True
            )

            # Настройка pad токена
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token

            # Установка флага и логирование
            # Флаг model_loaded используется для проверки
            self.model_loaded = True
            logger.info("Модель загружена успешно")

        except Exception as e:
            logger.error(f"Ошибка загрузки модели: {e}")
            self.model_loaded = False

    # Определение необходимости ответа в группе
    def should_respond_in_group(self, update: telegram.Update) -> bool:
        """Определение необходимости ответа в группе"""
        # В личных сообщениях бот всегда отвечает на всё
        if update.effective_chat.type == 'private':
            return True

        # Если сообщение пустое или не текстовое (фото, стикер и т.д.) то не отвечать
        message = update.message
        if not message or not message.text:
            return False

        text = message.text

        # Команды
        if text.startswith('/'):
            return True

        # Упоминания
        if self.bot_username:
            mentions = re.findall(r'@(\w+)', text)
            if mentions and self.bot_username in [m.lower() for m in mentions]:
                return True

        # Ответы на сообщения бота
        if (message.reply_to_message and
                message.reply_to_message.from_user and
                message.reply_to_message.from_user.id == self.bot_id):
            return True

        return False

    # Формирование промпта. Собирает все данные (личность бота, историю диалога, контекст, имя пользователя)
    # в единый структурированный текст, который понимает модель Qwen.
    def format_prompt(self, chat_id: int, user_id: int, user_msg: str, is_start: bool = False) -> str:
        # Системный промпт (из config.py)
        prompt_parts = [f"<|im_start|>system\n{SYSTEM_PROMPT}\n<|im_end|>\n"]

        # Контекст времени и даты
        current_time = datetime.now()
        prompt_parts.append(f"<|im_start|>context\nСейчас: {current_time.strftime('%d.%m.%Y %H:%M')}\n<|im_end|>\n")

        #  Информация о пользователе (имя)
        user_name = self.user_memory.get_user_name(user_id)
        if user_name:
            prompt_parts.append(f"<|im_start|>context\nТекущий пользователь: {user_name}\n<|im_end|>\n")
            logger.info(f"В промпт добавлено имя: {user_name}")
        else:
            logger.info(f"Имя пользователя {user_id} не найдено в памяти")

        # История диалога (контекст)
        history = self.memory.get_history(chat_id)
        if history:
            prompt_parts.append("<|im_start|>history\nИстория диалога:\n")
            for msg in history[-6:]:  # Последние 6 сообщений (3 обмена)
                role = msg['role']
                content = msg['content'][:120]  # Обрезаем
                prompt_parts.append(f"{role}: {content}\n")
            prompt_parts.append("<|im_end|>\n")

        # RAG-контекст (при ниобходимости)
        similar = self.rag.find_similar(user_msg, top_k=2)

        # Проверяем, что нашли что-то РЕЛЕВАНТНОЕ
        if similar and len(similar) > 0:
            prompt_parts.append("<|im_start|>examples\nПример ответа:\n")
            for dialogue in similar:
                for msg in dialogue.get("messages", []):
                    if msg.get("role") == "assistant":
                        content = msg.get("content", "")[:150]
                        # УБИРАЕМ теги из контента
                        content = content.replace('<|im_start|>', '').replace('<|im_end|>', '')
                        prompt_parts.append(f"{content}")
                        break
            prompt_parts.append("<|im_end|>\n")

        # Текущее сообщение пользователя
        if is_start:
            current_msg = "Привет! Расскажи о себе."
        else:
            current_msg = user_msg

        prompt_parts.append(f"<|im_start|>user\n{current_msg}\n<|im_end|>\n")

        # Инструкция для вопросов об имени
        if any(word in user_msg.lower() for word in ['зовут', 'имя', 'как меня', 'мое имя']):
            if user_name:
                # ЕСЛИ ИМЯ ИЗВЕСТНО - СКАЖИ ЕГО!
                prompt_parts.append(
                    f"<|im_start|>instruction\nОтвечая, обязательно используй имя пользователя: {user_name}\n<|im_end|>\n")
            else:
                prompt_parts.append(
                    "<|im_start|>instruction\nЕсли не знаешь имя пользователя, спроси его или признайся, что не помнишь.\n<|im_end|>\n")

        # Маркер для ответа
        prompt_parts.append("<|im_start|>assistant\n")

        full_prompt = "".join(prompt_parts)

        # Логируем промпт
        logger.info(f"Промпт для user_id={user_id} (name={user_name}) ===")
        logger.info(f"Последние 500 символов:\n{full_prompt[-500:]}")
        logger.info("Конец промпта")

        return full_prompt


    def clean_response(self, response: str) -> str:
        """Очистка ответа"""
        # Убираем повторения
        response = re.sub(r'(\b\w+\b)(?:\s+\1)+', r'\1', response, flags=re.IGNORECASE)

        # Убираем артефакты токенизации
        artifacts = [
            (r'<\|im_end\|>', ''),
            (r'<\|im_start\|>', ''),
            (r'\[ИМЯ\]', ''),
            (r'\s+', ' '),
        ]

        for pattern, replacement in artifacts:
            response = re.sub(pattern, replacement, response)

        return response.strip() or "Я подумаю над этим..."

    # Обработка сообщений
    async def generate_response(self, chat_id: int, user_id: int, user_msg: str, is_start: bool = False) -> str:
        try:
            logger.debug(f"Входящий: user={user_id}, msg='{user_msg[:50]}...', is_start={is_start}")

            #  Сохраняет связь пользователь ту чат в UserMemory
            self.user_memory.add_user_chat(user_id, chat_id)

            # Извлекаем имя (если есть в сообщении)
            if name := self.learning.process_introduction(user_id, user_msg):
                logger.info(f" Извлечено имя: {name} (user_id={user_id})")
                self.user_memory.set_user_name(user_id, name)

                # Если это сообщение с именем - отвечаем сразу
                if any(word in user_msg.lower() for word in ['зовут', 'имя', 'я ', 'меня']):
                    return f"Привет, {name}! Рад познакомиться. Я Гриша, чат-бот с ИИ."

            # Формируем промпт (используем старый проверенный метод)
            prompt = self.format_prompt(chat_id, user_id, user_msg, is_start)

            # Токенизация промпта
            inputs = self.tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=2048
            ).to(self.model.device)

            # Генерация ответа
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=100,
                    temperature=0.8,
                    do_sample=True,
                    top_p=0.9,
                    repetition_penalty=1.1,
                    pad_token_id=self.tokenizer.eos_token_id
                )

            # Декодируем ответ
            response = self.tokenizer.decode(
                outputs[0][inputs['input_ids'].shape[1]:],
                skip_special_tokens=True
            )

            # Очищаем ответ
            response = self.clean_response(response)

            # Сохраняем в историю
            if not is_start:
                self.memory.add_message(chat_id, "user", user_msg)
            self.memory.add_message(chat_id, "assistant", response)

            # Обучение
            if not is_start:
                self.learning.analyze(user_id, user_msg, response)

            return response

        except Exception as e:
            logger.error(f"Ошибка генерации: {e}")
            return "Извини, произошла ошибка. Попробуй еще раз."


# Глобальный экземпляр
main_bot = MainBot()