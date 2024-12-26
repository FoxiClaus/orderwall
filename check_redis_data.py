import json
import os
from datetime import datetime
from config import *

class OrderBookAnalyzer:
    def __init__(self):
        self.data_dir = DATA_DIR

    def analyze_historical_data(self, hours: int = 24):
        """Анализ исторических данных за указанное количество часов"""
        current_time = datetime.now()
        start_time = current_time.timestamp() - (hours * 3600)
        
        data = []
        
        # Читаем все файлы из директории
        for filename in os.listdir(self.data_dir):
            if filename.endswith('.json'):
                file_path = os.path.join(self.data_dir, filename)
                try:
                    with open(file_path, 'r') as f:
                        entry = json.load(f)
                        if entry['timestamp'] >= start_time:
                            data.append(entry)
                except Exception as e:
                    print(f"Ошибка чтения файла {filename}: {e}")
        
        if data:
            # Анализ данных
            total_entries = len(data)
            total_large_bids = sum(len(entry['large_bids']) for entry in data)
            total_large_asks = sum(len(entry['large_asks']) for entry in data)
            
            print(f"\nСтатистика за последние {hours} часов:")
            print(f"Всего записей: {total_entries}")
            print(f"Всего крупных ордеров на покупку: {total_large_bids}")
            print(f"Всего крупных ордеров на продажу: {total_large_asks}")
            
            # Анализ объемов
            if total_large_bids > 0:
                avg_bid_volume = sum(sum(order[1] for order in entry['large_bids']) 
                                   for entry in data) / total_large_bids
                print(f"Средний объем крупного ордера на покупку: {avg_bid_volume:.2f} BTC")
            
            if total_large_asks > 0:
                avg_ask_volume = sum(sum(order[1] for order in entry['large_asks']) 
                                   for entry in data) / total_large_asks
                print(f"Средний объем крупного ордера на продажу: {avg_ask_volume:.2f} BTC")
        else:
            print("Данные за указанный период не найдены")

if __name__ == "__main__":
    analyzer = OrderBookAnalyzer()
    analyzer.analyze_historical_data() 