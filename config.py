import logging


# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
MAX_CONTEXT_MESSAGES = 20
RAG_DATASET_PATH = "data/full_dataset.jsonl"
MODEL_NAME = "Qwen/Qwen2-1.5B-Instruct"
USERS_FILE = "grisha_users.json"
LEARNED_PATTERNS_FILE = "grisha_learned_patterns.json"
COMMENT_HISTORY_FILE = "comment_history.json"

# Системный промпт
SYSTEM_PROMPT = """
Здесь нужен новый системный промпт
"""