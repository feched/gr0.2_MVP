import json
import re
from typing import List, Dict
from collections import defaultdict, Counter
from datetime import datetime

from config import logger, RAG_DATASET_PATH, LEARNED_PATTERNS_FILE


class RAGSystem:
    """Объединенная RAG система с паттернами"""

    def __init__(self):
        self.dialogues: List[Dict] = []
        self.keyword_index: Dict[str, List[int]] = defaultdict(list)
        self.patterns_file = LEARNED_PATTERNS_FILE

        self._load_dataset()
        self._load_patterns()
        self._build_index()

        logger.info(f"RAG: {len(self.dialogues)} диалогов (датасет + паттерны)")

    # Загрузка основного датасета
    def _load_dataset(self):
        try:
            with open(RAG_DATASET_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        dialogue = json.loads(line.strip())
                        self.dialogues.append(dialogue)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            logger.warning(f"Файл датасета не найден: {RAG_DATASET_PATH}")

    # Загрузка паттернов как диалогов
    def _load_patterns(self):
        try:
            with open(self.patterns_file, 'r', encoding='utf-8') as f:
                patterns = json.load(f)

                for pattern in patterns:
                    # Преобразуем паттерн в формат диалога
                    dialogue = {
                        "messages": [
                            {"role": "user", "content": pattern['input']},
                            {"role": "assistant", "content": pattern['response']}
                        ],
                        "source": "pattern",  # Помечаем как паттерн
                        "usage_count": pattern.get('usage_count', 0),
                        "learned_at": pattern.get('learned_at')
                    }
                    self.dialogues.append(dialogue)

                    logger.debug(f"Паттерн добавлен в RAG: {pattern['input'][:50]}...")

        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("Файл паттернов не найден или пуст")

    def _build_index(self):
        """Построение общего индекса"""
        for idx, dialogue in enumerate(self.dialogues):
            text = self._get_dialog_text(dialogue).lower()
            keywords = self._extract_keywords(text)

            for keyword in keywords:
                self.keyword_index[keyword].append(idx)

    def _get_dialog_text(self, dialogue: Dict) -> str:
        """Текст диалога для индексации"""
        return " ".join(
            msg.get("content", "")
            for msg in dialogue.get("messages", [])
        )

    def _extract_keywords(self, text: str) -> List[str]:
        """Извлечение ключевых слов (улучшенная версия)"""
        stop_words = {
            'как', 'что', 'где', 'когда', 'почему', 'зачем', 'кто', 'чей',
            'привет', 'пока', 'спасибо', 'пожалуйста', 'это', 'вот', 'ну'
        }

        words = re.findall(r'\b[а-яё]{3,}\b', text.lower())
        keywords = [word for word in words if word not in stop_words]

        counter = Counter(keywords)
        return [word for word, _ in counter.most_common(10)]

    # Поиск похожих диалогов
    def find_similar(self, query: str, top_k: int = 3) -> List[Dict]:
        if not self.dialogues:
            return []

        # Фильтруем короткие/бессмысленные запросы
        if self._should_skip_query(query):
            logger.debug(f"Пропускаем RAG для: '{query}'")
            return []

        logger.info(f"Unified RAG поиск: '{query[:50]}...'")

        # Извлекаем ключевые слова
        query_keywords = self._extract_keywords(query.lower())
        logger.debug(f"Ключевые слова: {query_keywords}")

        # Подсчет релевантности
        dialogue_scores = defaultdict(int)
        for keyword in query_keywords:
            for idx in self.keyword_index.get(keyword, []):
                dialogue_scores[idx] += 1

        # Сортировка с приоритетом паттернов
        sorted_indices = sorted(
            dialogue_scores.items(),
            key=lambda x: (
                # 1. Приоритет: паттерны
                10 if self.dialogues[x[0]].get('source') == 'pattern' else 0,
                # 2. Приоритет: количество использований паттерна
                self.dialogues[x[0]].get('usage_count', 0),
                # 3. Приоритет: релевантность
                x[1]
            ),
            reverse=True
        )[:top_k]

        results = [
            self.dialogues[idx]
            for idx, score in sorted_indices
            if score > 0
        ]

        if results:
            source_types = [d.get('source', 'dataset') for d in results]
            logger.info(f"Найдено: {len(results)} (источники: {source_types})")

        return results[:top_k]  # Ограничиваем количество

   # Определяет, стоит ли пропускать этот запрос
    def _should_skip_query(self, query: str) -> bool:

        query = query.strip().lower()

        # Слишком короткие запросы
        if len(query) < 4:
            return True

        # Одно слово (кроме вопросов)
        if len(query.split()) == 1 and not query.endswith('?'):
            return True

        # Бессмысленные/случайные запросы
        meaningless = ['давай', 'ок', 'ага', 'угу', 'хм', 'ээ', 'ну', 'вот']
        if query in meaningless:
            return True

        # Слишком общие запросы без контекста
        if query in ['привет', 'пока', 'спасибо', 'хорошо']:
            return True

        return False

    # Сохранение паттерна в файл
    def add_pattern(self, user_msg: str, bot_msg: str):

        # Сохраняем в файл паттернов
        self._save_pattern_to_file(user_msg, bot_msg)

        # Немедленно добавляем в RAG
        dialogue = {
            "messages": [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": bot_msg}
            ],
            "source": "pattern",
            "usage_count": 0,
            "learned_at": datetime.now().isoformat()
        }

        idx = len(self.dialogues)
        self.dialogues.append(dialogue)

        # Индексируем
        text = self._get_dialog_text(dialogue).lower()
        keywords = self._extract_keywords(text)

        for keyword in keywords:
            self.keyword_index[keyword].append(idx)

        logger.info(f"Новый паттерн добавлен в Unified RAG: {user_msg[:50]}...")

        return dialogue

    # Сохраняет паттерн в файл
    def _save_pattern_to_file(self, user_msg: str, bot_msg: str):
        try:
            # Загружаем существующие паттерны
            try:
                with open(self.patterns_file, 'r', encoding='utf-8') as f:
                    patterns = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                patterns = []

            # Добавляем новый
            new_pattern = {
                'input': user_msg[:100],
                'response': bot_msg[:200],
                'learned_at': datetime.now().isoformat(),
                'usage_count': 0
            }

            # Проверяем на дубликаты
            if not any(p['input'] == new_pattern['input'] for p in patterns):
                patterns.append(new_pattern)

                # Сохраняем
                with open(self.patterns_file, 'w', encoding='utf-8') as f:
                    json.dump(patterns, f, ensure_ascii=False, indent=2)

                logger.info(f"Паттерн сохранен в файл: {user_msg[:50]}...")

        except Exception as e:
            logger.error(f"Ошибка сохранения паттерна: {e}")

    # Увеличивает счетчик использования для паттерна
    def increment_usage(self, dialogue_idx: int):

        if dialogue_idx < len(self.dialogues):
            dialogue = self.dialogues[dialogue_idx]

            if dialogue.get('source') == 'pattern':
                dialogue['usage_count'] = dialogue.get('usage_count', 0) + 1
                logger.debug(f"Увеличено использование паттерна: {dialogue['usage_count']}")

                # Также обновляем в файле
                self._update_pattern_file(dialogue)

    # Обновляет счетчик использования в файле
    def _update_pattern_file(self, updated_dialogue: Dict):
        try:
            with open(self.patterns_file, 'r', encoding='utf-8') as f:
                patterns = json.load(f)

            # Находим и обновляем
            for pattern in patterns:
                if pattern['input'] == updated_dialogue['messages'][0]['content']:
                    pattern['usage_count'] = updated_dialogue.get('usage_count', 0)
                    break

            with open(self.patterns_file, 'w', encoding='utf-8') as f:
                json.dump(patterns, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Ошибка обновления файла паттернов: {e}")

    # Статистика Unified RAG
    def get_stats(self) -> Dict:

        pattern_count = sum(1 for d in self.dialogues if d.get('source') == 'pattern')
        dataset_count = len(self.dialogues) - pattern_count

        # Статистика использования паттернов
        pattern_usage = sum(
            d.get('usage_count', 0)
            for d in self.dialogues
            if d.get('source') == 'pattern'
        )

        return {
            'total_dialogues': len(self.dialogues),
            'from_dataset': dataset_count,
            'from_patterns': pattern_count,
            'pattern_usage_total': pattern_usage,
            'keywords_indexed': len(self.keyword_index)
        }