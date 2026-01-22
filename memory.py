import json
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, List, Optional
import threading
import os
from config import logger, MAX_CONTEXT_MESSAGES


class UserMemory:
    """Память пользователей с потокобезопасностью"""

    def __init__(self, users_file: str = "grisha_users.json"):
        self.users_file = users_file
        self._lock = threading.Lock()
        self.users: Dict[str, Dict] = {}
        self._load_users()
        logger.info(f"Загружено пользователей: {len(self.users)}")

    def _load_users(self):
        """Загрузка с обработкой ошибок"""
        try:
            # Если файл есть - загружаем
            if os.path.exists(self.users_file):
                with open(self.users_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # ВАЖНО: конвертируем chat_ids обратно в set,
                    for user_id, user_data in data.items():
                        if 'chat_ids' in user_data and isinstance(user_data['chat_ids'], list):
                            user_data['chat_ids'] = set(user_data['chat_ids'])
                    self.users = data
            # Файла нет - создаем пустой
            else:
                self.users = {}
                logger.info(f"Файл {self.users_file} не найден, создаем новый")
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Ошибка загрузки пользователей: {e}")
            self.users = {}

    def _save_users(self):
        """Сохранение с потокобезопасностью"""
        with self._lock:
            try:
                users_to_save = {}
                for user_id, user_data in self.users.items():
                    # Создаем копию для сохранения
                    user_copy = user_data.copy()
                    # Конвертируем set в list для JSON
                    if 'chat_ids' in user_copy and isinstance(user_copy['chat_ids'], set):
                        user_copy['chat_ids'] = list(user_copy['chat_ids'])
                    users_to_save[user_id] = user_copy

                with open(self.users_file, 'w', encoding='utf-8') as f:
                    json.dump(users_to_save, f, ensure_ascii=False, indent=2)

                logger.debug(f"Пользователи сохранены: {len(users_to_save)} записей")
            except Exception as e:
                logger.error(f"Ошибка сохранения пользователей: {e}")

    def get_user(self, user_id: int) -> Optional[Dict]:
        """Получение данных пользователя"""
        return self.users.get(str(user_id))

    def get_user_name(self, user_id: int) -> Optional[str]:
        """Имя пользователя"""
        if user := self.get_user(user_id):
            name = user.get('name')
            logger.debug(f"get_user_name({user_id}) -> '{name}'")
            return name
        return None

    def set_user_name(self, user_id: int, name: str):
        """Установка имени пользователя"""
        user_id_str = str(user_id)  #  айди пользователя в Telegram

        logger.info(f"СОХРАНЕНИЕ ИМЕНИ для {user_id}: '{name}'")

        # Если пользователя нет - создаем
        if user_id_str not in self.users:
            self.users[user_id_str] = {
                'name': name,                    # Основное имя
                'chat_ids': set(),               # Множество чатов, где пользователь общался
                'learned_names': {},             # Словарь для альтернативных имен/никнеймов
                'trust_score': 0.5,              # Начальный уровень доверия (50%)
                'created_at': datetime.now().isoformat(),  # Время создания записи
                'last_seen': datetime.now().isoformat()    # Время последней активности
            }
            logger.info(f"Создан новый пользователь {user_id} с именем '{name}'")
        # Если есть - добавляем
        else:
            old_name = self.users[user_id_str].get('name')                      # Сохраняем старое имя для логов (важно для отслеживания изменений)
            self.users[user_id_str]['name'] = name                              # Обновляем имя в словаре пользователя
            self.users[user_id_str]['last_seen'] = datetime.now().isoformat()   # Обновляем last_seen - пользователь активен сейчас
            logger.info(f"Имя изменено с '{old_name}' на '{name}'")

        # Немедленное сохранение
        self._save_users()

        # Финальная проверка (самодиагностика)
        saved = self.get_user_name(user_id)
        logger.info(f"Проверка сохранения: get_user_name({user_id}) = '{saved}'")


    def add_user_chat(self, user_id: int, chat_id: int):
        """Отслеживать, в каких чатах пользователь общается с ботом"""
        user_id_str = str(user_id)

        # Если пользователя нет - создаем
        if user_id_str not in self.users:
            self.users[user_id_str] = {
                'name': None,                    # Имя пока неизвестно
                'chat_ids': {chat_id},           # Первый чат пользователя
                'learned_names': {},             # Пока пусто
                'trust_score': 0.5,              # Стартовый уровень доверия
                'created_at': datetime.now().isoformat(),  # Когда впервые увидели
                'last_seen': datetime.now().isoformat()    # Когда в последний раз видели
            }
        # Если есть - добавляем
        else:
            if 'chat_ids' not in self.users[user_id_str]:
                self.users[user_id_str]['chat_ids'] = {chat_id}
            else:
                self.users[user_id_str]['chat_ids'].add(chat_id)

            self.users[user_id_str]['last_seen'] = datetime.now().isoformat()

        self._save_users()
        logger.debug(f"Пользователю {user_id} добавлен чат {chat_id}")


class ConversationMemory:
    """Краткосрочная память диалогов"""

    def __init__(self, max_messages: int = MAX_CONTEXT_MESSAGES):
        self.max_messages = max_messages
        self.conversations: Dict[int, deque] = defaultdict(
            lambda: deque(maxlen=max_messages)
        )

    def get_last_messages(self, chat_id: int, limit: int = 10) -> List[Dict]:
        """Получение последних N сообщений"""
        if chat_id in self.conversations:
            # Возвращаем последние limit сообщений
            return list(self.conversations[chat_id])[-limit:]
        return []

    def add_message(self, chat_id: int, role: str, content: str):
        """Добавление сообщения"""
        self.conversations[chat_id].append({
            "role": role,  # Кто отправил
            "content": content,  # Текст сообщения
            "timestamp": datetime.now()  # Когда отправлено
        })

    def get_history(self, chat_id: int) -> List[Dict]:
        """История диалога"""
        # Возвращает ВСЕ сообщения из истории указанного чата
        return list(self.conversations.get(chat_id, deque()))

    def clear(self, chat_id: int):
        """Очистка истории"""
        # Полностью удаляет все сообщения из истории указанного чата
        # Чат остается в памяти, но становится пустым
        if chat_id in self.conversations:
            self.conversations[chat_id].clear()
            logger.debug(f"Очищена история для чата {chat_id}")