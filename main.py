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

    def _setup_logging(self):
        """Настройка логгера с корректной обработкой Unicode"""
        if not os.path.exists('logs'):
            os.makedirs('logs')
        
        # Очищаем существующие обработчики
        logger.handlers.clear()
        
        # Файловый handler с UTF-8
        file_handler = logging.FileHandler('logs/orderbook.log', encoding='utf-8')
        file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        
        # Консольный handler с ASCII-символами
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.setLevel(logging.DEBUG)

    def analyze_timeframe(self, timeframe: str) -> Dict:
        """Анализ данных по таймфрейму"""
        try:
            if len(self.history[timeframe]['imbalance']) < 2:
                return None
            
            imbalances = self.history[timeframe]['imbalance'][-10:]  # Берем последние 10 значений
            volumes_bid = self.history[timeframe]['bid_volume'][-10:]
            volumes_ask = self.history[timeframe]['ask_volume'][-10:]
            
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
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка в analyze_timeframe для {timeframe}: {str(e)}")
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

    async def process_depth_message(self, symbol: str, message: Dict):
        try:
            current_time = datetime.now()
            
            if 'b' in message and 'a' in message:
                # 1. Обновляем стакан
                self._update_orderbook(message)
                
                # 2. Рассчитываем текущие метрики
                self._calculate_metrics()
                
                # 3. Обновляем историю если нужно
                self._update_history(current_time)
                
                # 4. Выводим отладочную информацию
                self._print_debug_info(current_time)
                
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {str(e)}")
    
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
            bids = sorted(self.current_orderbook['bids'].items(), reverse=True)  # По убыванию
            asks = sorted(self.current_orderbook['asks'].items())  # По возрастанию
            
            if bids and asks:
                # Текущая цена как среднее между лучшим бидом и аском
                self.current_metrics['current_price'] = (bids[0][0] + asks[0][0]) / 2
                
                # Расчет объемов в USD
                self.current_metrics['bid_volume'] = sum(
                    qty * self.current_metrics['current_price'] 
                    for _, qty in bids
                )
                self.current_metrics['ask_volume'] = sum(
                    qty * self.current_metrics['current_price'] 
                    for _, qty in asks
                )
                
                # Расчет дисбаланса
                if self.current_metrics['ask_volume'] > 0:
                    self.current_metrics['imbalance'] = (
                        (self.current_metrics['bid_volume'] - self.current_metrics['ask_volume']) 
                        / self.current_metrics['ask_volume'] * 100
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
            # Обновляем историю только раз в секунду
            if current_time.microsecond < 100000:  # Первые 100мс каждой секунды
                logger.debug(f"Проверка обновления истории в {current_time}")
                
                # Обновляем 1m
                if (self.history['1m']['time'] is None or 
                    current_time.minute != self.history['1m']['time'].minute):
                    logger.debug("Обновление 1m данных")
                    self._append_history('1m', current_time)
                
                # Обновляем 5m
                if (self.history['5m']['time'] is None or 
                    current_time.minute // 5 != self.history['5m']['time'].minute // 5):
                    logger.debug("Обновление 5m данных")
                    self._append_history('5m', current_time)
                
                # Обновляем 15m
                if (self.history['15m']['time'] is None or 
                    current_time.minute // 15 != self.history['15m']['time'].minute // 15):
                    logger.debug("Обновление 15m данных")
                    self._append_history('15m', current_time)
                    
                # Очищаем старые данные
                self._cleanup_history()
                
        except Exception as e:
            logger.error(f"Ошибка обновления истории: {str(e)}")
    
    def _append_history(self, timeframe: str, current_time: datetime):
        """Добавление текущих метрик в историю"""
        try:
            self.history[timeframe]['time'] = current_time
            self.history[timeframe]['imbalance'].append(self.current_metrics['imbalance'])
            self.history[timeframe]['bid_volume'].append(self.current_metrics['bid_volume'])
            self.history[timeframe]['ask_volume'].append(self.current_metrics['ask_volume'])
            
            logger.debug(f"Добавлены данные для {timeframe}: "
                        f"imbalance={self.current_metrics['imbalance']:.2f}, "
                        f"bid_vol={self.current_metrics['bid_volume']:.0f}, "
                        f"ask_vol={self.current_metrics['ask_volume']:.0f}")
                    
        except Exception as e:
            logger.error(f"Ошибка добавления в историю для {timeframe}: {str(e)}")
    
    def _cleanup_history(self):
        """Очистка устаревших данных"""
        max_items = {'1m': 60, '5m': 12, '15m': 4}  # Храним час истории
        for tf in self.history:
            while len(self.history[tf]['imbalance']) > max_items[tf]:
                self.history[tf]['imbalance'].pop(0)
                self.history[tf]['bid_volume'].pop(0)
                self.history[tf]['ask_volume'].pop(0)
    
    def _print_debug_info(self, current_time: datetime):
        """Вывод отладочной информации"""
        # Базовая информация каждую секунду
        if current_time.microsecond < 100000:  # Только в начале каждой секунды
            logger.debug(
                f"[{current_time.strftime('%H:%M:%S')}] "
                f"Price: {self.current_metrics['current_price']:.2f} | "
                f"Bid Vol: {self.current_metrics['bid_volume']:,.0f} | "
                f"Ask Vol: {self.current_metrics['ask_volume']:,.0f} | "
                f"Imb: {self.current_metrics['imbalance']:+.2f}%"
            )
        
        # Расширенная статистика каждую минуту
        if current_time.second == 0 and current_time.microsecond < 100000:
            for tf in ['1m', '5m', '15m']:
                analysis = self.analyze_timeframe(tf)
                if analysis:
                    logger.info(
                        f"{tf} Stats | "
                        f"Trend: {analysis['trend_ascii']} | "
                        f"Curr Imb: {analysis['current_imbalance']:+.2f}% | "
                        f"Vol Ratio: {analysis['volume_ratio']:.2f}"
                    )

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
            
            # Рассчитываем средний объем
            all_volumes = [qty for _, qty in self.current_orderbook['bids'].items()]
            all_volumes.extend([qty for _, qty in self.current_orderbook['asks'].items()])
            if not all_volumes:
                return result
            
            avg_volume = sum(all_volumes) / len(all_volumes)
            threshold = avg_volume * 3  # Ордер в 3 раза больше среднего считаем крупным
            
            # Ищем крупные ордера
            for price, qty in self.current_orderbook['bids'].items():
                if qty > threshold:
                    result['bids'].append((price, qty))
            
            for price, qty in self.current_orderbook['asks'].items():
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