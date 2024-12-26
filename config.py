# Основные настройки
SYMBOL = 'STRK/USDT'
ORDERBOOK_DEPTH = 20

# Пороговые значения
MIN_ORDER_LIFETIME = 300  # 5 минут
IMBALANCE_THRESHOLD = 50  # Увеличили порог дисбаланса
VOLUME_MULTIPLIER = 2  # Множитель для определения крупных ордеров

# Настройки логирования
LOG_FILE = 'strk_orderbook.log'
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# Путь к директории с данными
DATA_DIR = 'strk_orderbook_data'