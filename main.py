import websockets
import json
import logging
import asyncio
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from config import *
import sys

# Настройка логирования в консоль и файл
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Установим уровень DEBUG для большей информации

# Создаем обработчик для вывода в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Создаем обработчик для записи в файл
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

class OrderBookMonitor:
    def __init__(self):
        # Основной стакан
        self.current_orderbook = {
            'bids': {},  # price -> quantity
            'asks': {}   # price -> quantity
        }
        
        # Базовые метрики
        self.current_metrics = {
            'bid_volume': 0,
            'ask_volume': 0,
            'imbalance': 0,
            'current_price': 0
        }
        
        # История для разных таймфреймов
        self.history = {
            '1m': {'time': None, 'imbalance': [], 'bid_volume': [], 'ask_volume': []},
            '5m': {'time': None, 'imbalance': [], 'bid_volume': [], 'ask_volume': []},
            '15m': {'time': None, 'imbalance': [], 'bid_volume': [], 'ask_volume': []}
        }
        
        # Добавляем параметры для анализа
        self.analysis_params = {
            'volume_threshold': 100000,  # Порог для определения крупного объема
            'imbalance_threshold': 40,   # Порог для сильного дисбаланса
            'trend_periods': {           # Периоды для определения тренда
                '1m': 10,  # последние 10 обновлений
                '5m': 6,   # последние 6 обновлений
                '15m': 4   # последние 4 обновления
            }
        }
        
        # Настройка логирования
        self._setup_logging()
        self.ws_connections = {}  # Добавляем хранение WebSocket соединений
        
        # Добавим накопление данных внутри текущей минуты
        self.current_minute_data = {
            'imbalances': [],
            'bid_volumes': [],
            'ask_volumes': [],
            'minute': None
        }

    def _setup_logging(self):
        """Настройка логгера с сохранением в файл"""
        if not os.path.exists('logs'):
            os.makedirs('logs')
        
        # Очищаем существующие обработчики
        logger.handlers.clear()
        
        # Создаем форматтеры
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        
        # Файловый handler для подробного лога
        detailed_handler = logging.FileHandler(
            f'logs/detailed_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
            encoding='utf-8'
        )
        detailed_handler.setFormatter(detailed_formatter)
        detailed_handler.setLevel(logging.DEBUG)
        
        # Файловый handler для сигналов
        signals_handler = logging.FileHandler(
            f'logs/signals_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
            encoding='utf-8'
        )
        signals_handler.setFormatter(detailed_formatter)
        signals_handler.setLevel(logging.INFO)
        
        # Консольный handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO)
        
        # Добавляем handlers
        logger.addHandler(detailed_handler)
        logger.addHandler(signals_handler)
        logger.addHandler(console_handler)
        logger.setLevel(logging.DEBUG)

    def analyze_timeframe(self, timeframe: str, min_history: int = 3) -> Optional[Dict]:
        """Анализ данных по таймфрейму"""
        try:
            if len(self.history[timeframe]['imbalance']) < min_history:
                logger.debug(f"Недостаточно данных для {timeframe} (нужно {min_history}, есть {len(self.history[timeframe]['imbalance'])})")
                return {
                    'trend_ascii': '-',
                    'current_imbalance': self.history[timeframe]['imbalance'][-1],
                    'volume_ratio': self.history[timeframe]['bid_volume'][-1] / self.history[timeframe]['ask_volume'][-1]
                }
            
            logger.debug(f"Анализ {timeframe}: длина истории = {len(self.history[timeframe]['imbalance'])}")
            
            if len(self.history[timeframe]['imbalance']) < 2:
                logger.debug(f"Недостаточно данных для {timeframe}")
                return None
            
            imbalances = self.history[timeframe]['imbalance'][-10:]
            volumes_bid = self.history[timeframe]['bid_volume'][-10:]
            volumes_ask = self.history[timeframe]['ask_volume'][-10:]
            
            logger.debug(f"Данные {timeframe}: imbalances={imbalances}")
            
            # Определяем тренд по последним значениям
            if imbalances[-1] > imbalances[0] + 5:
                trend = 'up'
                trend_ascii = 'UP'
            elif imbalances[-1] < imbalances[0] - 5:
                trend = 'down'
                trend_ascii = 'DOWN'
            else:
                trend = 'neutral'
                trend_ascii = '-'
            
            result = {
                'trend_ascii': trend_ascii,
                'current_imbalance': imbalances[-1],
                'volume_ratio': volumes_bid[-1] / volumes_ask[-1] if volumes_ask[-1] > 0 else 1
            }
            
            logger.debug(f"Результат анализа {timeframe}: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка анализа {timeframe}: {str(e)}")
            return None

    def analyze_signals(self, imbalance: float, imbalance_speed: float, 
                       large_bids: list, large_asks: list, 
                       analysis_5m: dict, analysis_15m: dict,
                       volume_ratio: float) -> list:
        """Анализ и формирование торговых сигналов"""
        signals = []
        
        # Анализ накопления
        stable_orders = sum(1 for k, v in self.order_behavior.items() 
                          if len(v) > 5 and self.analyze_order_behavior(k, 0, 0) == "Стабильный")
        if stable_orders > 3 and abs(imbalance_speed) < 5:
            signals.append("🔵 НАКОПЛЕНИЕ: Обнаружено несколько стабильных ордеров")
        
        # Анализ разворота вверх
        if (imbalance < -40 and  # Сильный негативный дисбаланс
            analysis_5m and analysis_5m['trend'] == '↗️' and  # Разворот на 5M
            any(order[1] > self.average_volume * 2 for order in large_bids)):  # Крупные покупки
            signals.append("🟢 РАЗВОРОТ ВВЕРХ: Сильный негативный дисбаланс + крупные покупки")
        
        # Анализ разворота вниз
        if (imbalance > 40 and  # Сильный позитивный дисбаланс
            analysis_5m and analysis_5m['trend'] == '↘️' and  # Разворот на 5M
            any(order[1] > self.average_volume * 2 for order in large_asks)):  # Крупные продажи
            signals.append("🔴 РАЗВОРОТ ВНИЗ: Сильный позитивный дисбаланс + крупные продажи")
        
        # Анализ ложного движения
        flashing_orders = sum(1 for k, v in self.order_behavior.items() 
                            if self.analyze_order_behavior(k, 0, 0) == "Мерцает")
        if flashing_orders > 3 and abs(imbalance_speed) > 20:
            signals.append("⚠️ ЛОЖНОЕ ДВИЖЕНИЕ: Много мерцающих ордеров + высокая скорость")
        
        # Анализ сильного импульса
        if (abs(imbalance_speed) > 15 and 
            volume_ratio > 1.5 and 
            analysis_5m and analysis_15m and 
            analysis_5m['trend'] == analysis_15m['trend']):
            direction = "ВВЕРХ 🚀" if imbalance > 0 else "ВНИЗ 🔻"
            signals.append(f"⚡ СИЛЬНЫЙ ИМПУЛЬС {direction}: Высокая скорость + объем + подтверждение трендов")
        
        return signals

    async def process_depth_message(self, symbol: str, message: dict):
        """Обработка сообщения стакана"""
        try:
            # Обновляем стакан
            self._update_orderbook(message)
            
            # Рассчитываем метрики
            self._calculate_metrics()
            
            # Получаем текущее время
            current_time = datetime.now()
            
            # Обновляем историю
            self._update_history(current_time)
            
            # Выводим отладочную информацию
            self._print_debug_info(current_time)
            
        except Exception as e:
            logger.error(f"Error processing depth message: {e}")
    
    def _update_orderbook(self, message: Dict):
        """Обновление стакана"""
        try:
            # Обновляем биды
            for price, qty in message['b']:
                price_float = float(price)
                qty_float = float(qty)
                if qty_float > 0:
                    self.current_orderbook['bids'][price_float] = qty_float
                else:
                    self.current_orderbook['bids'].pop(price_float, None)
            
            # Обновляем аски
            for price, qty in message['a']:
                price_float = float(price)
                qty_float = float(qty)
                if qty_float > 0:
                    self.current_orderbook['asks'][price_float] = qty_float
                else:
                    self.current_orderbook['asks'].pop(price_float, None)
                    
        except Exception as e:
            logger.error(f"Ошибка обновления стакана: {str(e)}")
            
    def _calculate_metrics(self):
        """Расчет текущих метрик"""
        try:
            # Получаем отсортированные списки
            bids = sorted(self.current_orderbook['bids'].items(), reverse=True)[:10]  # Топ 10 ордеров
            asks = sorted(self.current_orderbook['asks'].items())[:10]  # Топ 10 ордеров
            
            if bids and asks:
                # Текущая цена как среднее между лучшим бидом и аском
                self.current_metrics['current_price'] = (bids[0][0] + asks[0][0]) / 2
                
                # Расчет объемов в USD (только топ-10)
                self.current_metrics['bid_volume'] = sum(
                    qty * self.current_metrics['current_price'] 
                    for _, qty in bids
                )
                self.current_metrics['ask_volume'] = sum(
                    qty * self.current_metrics['current_price'] 
                    for _, qty in asks
                )
                
                # Расчет дисбаланса
                total_volume = self.current_metrics['bid_volume'] + self.current_metrics['ask_volume']
                if total_volume > 0:
                    self.current_metrics['imbalance'] = (
                        (self.current_metrics['bid_volume'] - self.current_metrics['ask_volume']) 
                        / total_volume * 100
                    )
                else:
                    self.current_metrics['imbalance'] = 0
                    
        except Exception as e:
            logger.error(f"Ошибка расчета метрик: {str(e)}")

    def calculate_imbalance_speed(self, timeframe='1m') -> float:
        """Расчет скорости изменения имбаланса"""
        try:
            history = self.history[timeframe]['imbalance']
            if len(history) < 2:
                return 0.0
            
            # Берем последние два значения
            prev_imbalance = history[-2]
            curr_imbalance = history[-1]
            
            # Рассчитываем изменение в минуту
            return curr_imbalance - prev_imbalance
            
        except Exception as e:
            logger.error(f"Ошибка расчета скорости имбаланса: {str(e)}")
            return 0.0

    def detect_anomaly(self, volume_deviation: float, imbalance_speed: float) -> str:
        """Определение уровня аномальности"""
        if abs(volume_deviation) > 200 or abs(imbalance_speed) > 30:
            return "Высокая ⚠️"
        elif abs(volume_deviation) > 100 or abs(imbalance_speed) > 15:
            return "Средняя ⚡"
        return "Низкая ✓"

    def generate_warnings(self, volume_deviation: float, imbalance_speed: float,
                         large_bids: List, large_asks: List) -> List[str]:
        """Генерация контекстных предупреждений"""
        warnings = []
        
        if volume_deviation > 150:
            warnings.append("Аномально высокий объем")
        
        stable_orders = sum(1 for k, v in self.order_behavior.items() 
                          if len(v) > 5 and self.analyze_order_behavior(k, 0, 0) == "Стабильный")
        if stable_orders > 3:
            warnings.append("Обнаружен паттерн накопления")
        
        if imbalance_speed > 20:
            direction = "вверх" if imbalance_speed > 0 else "вниз"
            warnings.append(f"Возможна подготовка движения {direction}")
        
        return warnings

    async def connect_to_binance(self, symbol: str):
        """Подключение к WebSocket Binance для получения данных стакана"""
        ws_url = f"wss://fstream.binance.com/ws/{symbol.lower()}@depth@100ms"
        logger.debug(f"Attempting to connect to: {ws_url}")
        
        try:
            async with websockets.connect(ws_url) as websocket:
                logger.info(f"Connected to Binance Futures WebSocket for {symbol}")
                self.ws_connections[symbol] = websocket
                
                while True:
                    try:
                        message = await websocket.recv()
                        await self.process_depth_message(symbol, json.loads(message))
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
                        await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            await asyncio.sleep(5)

    async def run(self):
        """Запуск мониторинга"""
        logger.info("Starting order monitoring system")
        symbol = SYMBOL.replace('/', '').lower()
        
        while True:
            try:
                await self.connect_to_binance(symbol)
            except Exception as e:
                logger.error(f"Connection error: {e}")
                await asyncio.sleep(5)

    async def calculate_average_volume(self, current_volume: float) -> float:
        """Расчет среднего объема"""
        if not hasattr(self, '_volume_samples'):
            self._volume_samples = []
        
        self._volume_samples.append(current_volume)
        # Храним только последние 100 значений
        if len(self._volume_samples) > 100:
            self._volume_samples.pop(0)
        
        return sum(self._volume_samples) / len(self._volume_samples)

    def _update_history(self, current_time: datetime):
        """Обновление исторических данных"""
        try:
            # Собираем данные в текущий минутный буфер
            if self.current_minute_data['minute'] != current_time.minute:
                # Если началась новая минута, сохраняем предыдущие данные
                if self.current_minute_data['minute'] is not None and self.current_minute_data['imbalances']:
                    avg_imbalance = sum(self.current_minute_data['imbalances']) / len(self.current_minute_data['imbalances'])
                    avg_bid_vol = sum(self.current_minute_data['bid_volumes']) / len(self.current_minute_data['bid_volumes'])
                    avg_ask_vol = sum(self.current_minute_data['ask_volumes']) / len(self.current_minute_data['ask_volumes'])

                    logger.debug(f"Минутная статистика: "
                            f"Avg Imb: {avg_imbalance:.2f}% "
                            f"(min: {min(self.current_minute_data['imbalances']):.2f}%, "
                            f"max: {max(self.current_minute_data['imbalances']):.2f}%), "
                            f"Avg Bid Vol: {avg_bid_vol:.0f}, "
                            f"Avg Ask Vol: {avg_ask_vol:.0f}")

                    # Обновляем историю средними значениями
                    self.history['1m']['imbalance'].append(avg_imbalance)
                    self.history['1m']['bid_volume'].append(avg_bid_vol)
                    self.history['1m']['ask_volume'].append(avg_ask_vol)
                    self.history['1m']['time'] = current_time

                    # Выводим минутную сводку
                    analysis = self.analyze_timeframe('1m', min_history=1)
                    if analysis:
                        logger.info("\n".join([
                            "=== СТАТИСТИКА 1M ===",
                            f"1m  | Trend: {analysis['trend_ascii']:4} | "
                            f"Imb: {analysis['current_imbalance']:+6.1f}% | "
                            f"Vol Ratio: {analysis['volume_ratio']:4.1f}",
                            "==================\n"
                        ]))

                    # Обновляем и выводим 5m и 15m статистику только в начале минуты
                    if current_time.second == 0 and current_time.microsecond < 100000:
                        if current_time.minute % 5 == 0:
                            self._update_higher_timeframe('5m', current_time, 5)
                            analysis_5m = self.analyze_timeframe('5m', min_history=1)
                            if analysis_5m:
                                logger.info("\n".join([
                                    "=== СТАТИСТИКА 5M ===",
                                    f"5m  | Trend: {analysis_5m['trend_ascii']:4} | "
                                    f"Imb: {analysis_5m['current_imbalance']:+6.1f}% | "
                                    f"Vol Ratio: {analysis_5m['volume_ratio']:4.1f}",
                                    "==================\n"
                                ]))

                            # Проверяем и обновляем 15m статистику
                            if current_time.minute % 15 == 0:
                                self._update_higher_timeframe('15m', current_time, 15)
                                analysis_15m = self.analyze_timeframe('15m', min_history=1)
                                if analysis_15m:
                                    logger.info("\n".join([
                                        "=== СТАТИСТИКА 15M ===",
                                        f"15m | Trend: {analysis_15m['trend_ascii']:4} | "
                                        f"Imb: {analysis_15m['current_imbalance']:+6.1f}% | "
                                        f"Vol Ratio: {analysis_15m['volume_ratio']:4.1f}",
                                        "==================\n"
                                    ]))
                
                # Очищаем буфер для новой минуты
                self.current_minute_data = {
                    'imbalances': [],
                    'bid_volumes': [],
                    'ask_volumes': [],
                    'minute': current_time.minute
                }
            
            # Добавляем текущие данные в буфер
            self.current_minute_data['imbalances'].append(self.current_metrics['imbalance'])
            self.current_minute_data['bid_volumes'].append(self.current_metrics['bid_volume'])
            self.current_minute_data['ask_volumes'].append(self.current_metrics['ask_volume'])

        except Exception as e:
            logger.error(f"Ошибка обновления истории: {str(e)}")
            logger.exception(e)
        
    def _update_higher_timeframe(self, timeframe: str, current_time: datetime, n_minutes: int):
        """Обновление статистики старших таймфреймов на основе минутных данных"""
        try:
            imb = sum(self.history['1m']['imbalance'][-n_minutes:]) / n_minutes
            bid = sum(self.history['1m']['bid_volume'][-n_minutes:]) / n_minutes
            ask = sum(self.history['1m']['ask_volume'][-n_minutes:]) / n_minutes
            
            self.history[timeframe]['imbalance'].append(imb)
            self.history[timeframe]['bid_volume'].append(bid)
            self.history[timeframe]['ask_volume'].append(ask)
            self.history[timeframe]['time'] = current_time
            
            logger.debug(f"Обновлена {timeframe} статистика: Imb={imb:.2f}%, Bid Vol={bid:.0f}, Ask Vol={ask:.0f}")
            
        except Exception as e:
            logger.error(f"Ошибка обновления {timeframe}: {str(e)}")
    
    def _cleanup_history(self):
        """Очистка устаревших данных"""
        max_items = {
            '1m': 60,  # Храним час истории для 1m
            '5m': 12,  # Храним час истории для 5m
            '15m': 4   # Храним час истории для 15m
        }
        for tf in self.history:
            while len(self.history[tf]['imbalance']) > max_items[tf]:
                self.history[tf]['imbalance'].pop(0)
                self.history[tf]['bid_volume'].pop(0)
                self.history[tf]['ask_volume'].pop(0)
    
    def _print_debug_info(self, current_time: datetime):
        """Вывод отладочной информации"""
        # Базовая информация в начале каждой секунды
        if current_time.microsecond < 100000:
            metrics_info = (
                f"Price: {self.current_metrics['current_price']:.2f} | "
                f"Bid Vol: {self.current_metrics['bid_volume']:,.0f} | "
                f"Ask Vol: {self.current_metrics['ask_volume']:,.0f} | "
                f"Imb: {self.current_metrics['imbalance']:+.2f}%"
            )
            logger.debug(metrics_info)
            
            # Статистика по таймфреймам только в 0 секунду каждой минуты
            # и только при первом вызове (microsecond < 1000)
            if current_time.second == 0 and current_time.microsecond < 1000:
                timeframe_stats = []
                
                # 1m статистика каждую минуту
                analysis_1m = self.analyze_timeframe('1m')
                if analysis_1m:
                    timeframe_stats.append("=== СТАТИСТИКА 1M ===")
                    timeframe_stats.append(
                        f"1m  | Trend: {analysis_1m['trend_ascii']:4} | "
                        f"Imb: {analysis_1m['current_imbalance']:+6.1f}% | "
                        f"Vol Ratio: {analysis_1m['volume_ratio']:4.1f}"
                    )
                    timeframe_stats.append("==================\n")
                
                # 5m статистика каждые 5 минут
                if current_time.minute % 5 == 0:
                    analysis_5m = self.analyze_timeframe('5m')
                    if analysis_5m:
                        timeframe_stats.append("=== СТАТИСТИКА 5M ===")
                        timeframe_stats.append(
                            f"5m  | Trend: {analysis_5m['trend_ascii']:4} | "
                            f"Imb: {analysis_5m['current_imbalance']:+6.1f}% | "
                            f"Vol Ratio: {analysis_5m['volume_ratio']:4.1f}"
                        )
                        timeframe_stats.append("==================\n")
                
                if timeframe_stats:
                    logger.info("\n".join(timeframe_stats))

    def generate_signals(self) -> List[str]:
        """Генерация торговых сигналов"""
        signals = []
        
        # Получаем анализ по всем таймфреймам
        analysis = {
            tf: self.analyze_timeframe(tf) 
            for tf in ['1m', '5m', '15m']
        }
        
        # Проверяем наличие данных
        if not all(analysis.values()):
            return signals
        
        # 1. Базовые сигналы (существующие)
        if abs(self.current_metrics['imbalance']) > self.analysis_params['imbalance_threshold']:
            direction = "покупки" if self.current_metrics['imbalance'] > 0 else "продажи"
            signals.append(f"⚠️ Сильный дисбаланс в сторону {direction} "
                         f"({self.current_metrics['imbalance']:.1f}%)")
        
        if all(a['trend'] == "↗️" for a in analysis.values()):
            signals.append("🟢 Восходящий тренд по всем таймфреймам")
        elif all(a['trend'] == "↘️" for a in analysis.values()):
            signals.append("🔴 Нисходящий тренд по всем таймфреймам")
        
        # 2. Анализ скорости изменения имбаланса
        imbalance_speed = self.calculate_imbalance_speed('1m')
        if abs(imbalance_speed) > 15:  # Быстрое изменение
            direction = "роста" if imbalance_speed > 0 else "падения"
            signals.append(f"⚡ Высокая скорость {direction} имбаланса: {imbalance_speed:.1f}/мин")
        
        # 3. Анализ крупных ордеров
        large_orders = self.detect_large_orders()
        if large_orders['bids']:
            signals.append(f"💫 Крупные ордера на покупку: {len(large_orders['bids'])} шт")
        if large_orders['asks']:
            signals.append(f"💫 Крупные ордера на продажу: {len(large_orders['asks'])} шт")
        
        # 4. Паттерны накопления
        accumulation = self.detect_accumulation()
        if accumulation:
            signals.append(f"🔵 {accumulation}")
        
        return signals

    def detect_large_orders(self) -> Dict[str, List]:
        """Определение крупных ордеров"""
        try:
            result = {'bids': [], 'asks': []}
            
            # Берем только топ-20 ордеров для анализа
            bids = sorted(self.current_orderbook['bids'].items(), reverse=True)[:20]
            asks = sorted(self.current_orderbook['asks'].items())[:20]
            
            # Рассчитываем средний объем
            all_volumes = [qty for _, qty in bids]
            all_volumes.extend([qty for _, qty in asks])
            if not all_volumes:
                return result
            
            avg_volume = sum(all_volumes) / len(all_volumes)
            threshold = avg_volume * 5  # Увеличиваем порог до 5x от среднего
            
            # Ищем крупные ордера
            for price, qty in bids:
                if qty > threshold:
                    result['bids'].append((price, qty))
                
            for price, qty in asks:
                if qty > threshold:
                    result['asks'].append((price, qty))
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка определения крупных ордеров: {str(e)}")
            return {'bids': [], 'asks': []}

    def detect_accumulation(self) -> Optional[str]:
        """Определение паттернов накопления"""
        try:
            # Анализируем последние 5 минут данных
            if len(self.history['1m']['imbalance']) < 5:
                return None
            
            imbalances = self.history['1m']['imbalance'][-5:]
            volumes = self.history['1m']['bid_volume'][-5:]
            
            # Признаки накопления:
            # 1. Стабильный имбаланс (малая волатильность)
            imb_volatility = max(imbalances) - min(imbalances)
            
            # 2. Растущий объем
            volume_trend = volumes[-1] > volumes[0] * 1.2  # Рост на 20%
            
            # 3. Преимущественно положительный имбаланс
            positive_imb = sum(1 for i in imbalances if i > 0) >= 3
            
            if imb_volatility < 10 and volume_trend and positive_imb:
                return "Обнаружено накопление: стабильный имбаланс + растущий объем"
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка определения накопления: {str(e)}")
            return None

if __name__ == "__main__":
    print("Starting program...")  # Добавим прямой вывод
    monitor = OrderBookMonitor()
    asyncio.run(monitor.run())