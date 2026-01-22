import json
import re
from typing import List, Dict, Optional
from datetime import datetime

from config import logger, LEARNED_PATTERNS_FILE


class ImprovedLearningSystem:
    """Система обучения с использованием паттернов"""

    def __init__(self, rag_system=None):
        self.patterns_file = LEARNED_PATTERNS_FILE
        self.patterns: List[Dict] = self._load_patterns()
        self.rag_system = rag_system
        self.interaction_count = 0

        logger.info(f"Загружено паттернов: {len(self.patterns)}")

    # Загрузка паттернов
    def _load_patterns(self) -> List[Dict]:
        try:
            with open(self.patterns_file, 'r', encoding='utf-8') as f:
                patterns = json.load(f)
                # Гарантируем наличие usage_count
                for pattern in patterns:
                    if 'usage_count' not in pattern:
                        pattern['usage_count'] = 0
                return patterns
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    # Сохранение паттернов
    def _save_patterns(self):
        try:
            with open(self.patterns_file, 'w', encoding='utf-8') as f:
                json.dump(self.patterns, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения паттернов: {e}")

    # Поиск похожих паттернов
    def find_similar_pattern(self, user_msg: str, similarity_threshold: float = 0.4) -> Optional[str]:
        # Если нет сохраненных паттернов, возвращаем None
        if not self.patterns:
            return None

        best_pattern = None  # Лучший найденный паттерн
        best_score = 0  # Наивысшая оценка схожести

        # Приводим сообщение пользователя к нижнему регистру и находим слова
        user_msg_lower = user_msg.lower()
        user_words = set(re.findall(r'\b[а-яё]{2,}\b', user_msg_lower))

        # Поиск лучшего совпадения
        for pattern in self.patterns:
            pattern_input = pattern.get('input', '').lower()

            # Простой расчет схожести
            score = self._calculate_similarity(user_msg_lower, pattern_input, user_words)

            # Если схожесть высокая, возвращаем
            if score > best_score and score >= similarity_threshold:
                best_score = score
                best_pattern = pattern

        # Если нашли подходящий паттерн
        if best_pattern:
            # Увеличиваем счетчик использования
            best_pattern['usage_count'] = best_pattern.get('usage_count', 0) + 1
            self._save_patterns()

            logger.info(f"Использован паттерн (схожесть: {best_score:.2f}): {pattern_input[:50]}...")
            return best_pattern['response']

        return None  # Не нашли достаточно похожий паттерн

    # Вычисляет степень похожести между двумя текстовыми сообщениями
    def _calculate_similarity(self, msg1: str, msg2: str, msg1_words: set) -> float:
        # Если сообщения пусты, возвращаем 0
        if not msg1 or not msg2:
            return 0

        # Простое текстовое совпадение
        if msg1 in msg2 or msg2 in msg1:
            return 0.8

        # Совпадение по словам
        msg2_words = set(re.findall(r'\b[а-яё]{2,}\b', msg2))

        # Если нет слов, возвращаем 0
        if not msg1_words or not msg2_words:
            return 0

        common_words = msg1_words.intersection(msg2_words)  # Общие слова

        # Вес совпадения
        if common_words:
            similarity = len(common_words) / max(len(msg1_words), len(msg2_words))

            # Усиливаем вес для важных слов
            important_words = {'зовут', 'имя', 'привет', 'дела', 'как', 'ты', 'саша', 'гриша'}
            if any(word in common_words for word in important_words):
                similarity *= 1.3

            return min(1.0, similarity)

        return 0

    # Анализ с сохранением хороших ответов
    def analyze(self, user_id: int, user_msg: str, bot_msg: str):
        self.interaction_count += 1

        # Критерии хорошего ответа
        is_good_response = (
                len(bot_msg) > 15 and
                "не знаю" not in bot_msg.lower() and
                "ошибка" not in bot_msg.lower() and
                "извини" not in bot_msg.lower() and
                "повтори" not in bot_msg.lower() and
                "не понял" not in bot_msg.lower()
        )

        # Если ответ хороший - сохраняем его
        if is_good_response:
            self._save_pattern(user_msg, bot_msg)
            logger.info(f"Сохранен новый паттерн: {user_msg[:50]}...")

    # Сохранение успешного паттерна с автоматическим экспортом в RAG
    def _save_pattern(self, user_msg: str, bot_msg: str):
        # Проверяем, нет ли уже похожего паттерна
        for pattern in self.patterns:
            if self._calculate_similarity(user_msg.lower(), pattern['input'].lower(), set()) > 0.7:
                # Обновляем существующий
                pattern['response'] = bot_msg[:200]
                pattern['learned_at'] = datetime.now().isoformat()
                pattern['usage_count'] = 0  # Сбрасываем счетчик при обновлении
                self._save_patterns()
                return

        # Создаем новый паттерн
        pattern = {
            'input': user_msg[:100],
            'response': bot_msg[:200],
            'learned_at': datetime.now().isoformat(),
            'usage_count': 0
        }

        self.patterns.append(pattern)
        self._save_patterns()

        # Автоматический экспорт в RAG
        if self.rag_system:
            dialogue = {
                "messages": [
                    {"role": "user", "content": pattern['input']},
                    {"role": "assistant", "content": pattern['response']}
                ]
            }
            self.rag_system.add_dialogue(dialogue)
            logger.info(f"Паттерн экспортирован в RAG: {pattern['input'][:50]}...")

    # Статистика
    def get_stats(self) -> Dict:
        total_used = sum(p.get('usage_count', 0) for p in self.patterns)  # Сумма использований
        most_used = max(self.patterns, key=lambda p: p.get('usage_count', 0), default=None)  # Самый используемый паттер

        return {
            'patterns': len(self.patterns),  # Сколько всего паттернов выучил бот
            'interactions': self.interaction_count,  # Всего диалогов
            'total_patterns_used': total_used,  # Сколько раз использовал сохраненные паттерны
            'most_used_pattern': most_used['input'][:50] if most_used else None,  # Самый популярный вопрос
            'most_used_count': most_used.get('usage_count', 0) if most_used else 0,  # Сколько раз на него ответили
            'patterns_with_usage': sum(1 for p in self.patterns if p.get('usage_count', 0) > 0)  # Сколько паттернов хоть раз использовались
        }

    # Извлечение имени пользователя:
    def process_introduction(self, user_id: int, message: str) -> Optional[str]:

        # Паттерны для извлечения имени
        patterns = [
            (r'меня\s+зовут\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)', 1),  # "меня зовут Саша"
            (r'^я\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)$', 1),  # "я Саша"
            (r'мо[ёе]\s+имя\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)', 1),  # "мое имя Саша"
            (r'зовут\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)', 1),  # "...зовут Саша"
            (r'привет,\s+я\s+([А-ЯЁ][а-яё]+)', 1),  # "привет, я Саша"
        ]

        # Слова, которые не являются именами
        stop_words = {'зовут', 'имя', 'это', 'вас', 'тебя', 'меня', 'мое', 'моё', 'привет', 'пока'}

        for pattern, group_num in patterns:
            if match := re.search(pattern, message, re.IGNORECASE):
                name = match.group(group_num).strip()

                # Проверяем, что это не стоп-слово и достаточно длинное
                if (name.lower() not in stop_words and
                        len(name) >= 2 and
                        not name.isdigit()):

                    # Дополнительная проверка: имя должно содержать русские буквы
                    if re.search(r'[А-ЯЁа-яё]', name):
                        logger.info(f"Извлечено имя: '{name}' из сообщения: '{message[:50]}...'")
                        return name

        logger.debug(f"Имя не найдено в сообщении: '{message[:50]}...'")
        return None
