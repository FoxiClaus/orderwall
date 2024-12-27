# Project Structure

## main.py
### Class: OrderBookMonitor
- **Data Buffers**
  - current_minute_data: Real-time tick data within current minute
    - imbalances[] - all tick imbalances
    - bid_volumes[] - all tick bid volumes
    - ask_volumes[] - all tick ask volumes
  
  - history: Timeframe historical data
    - 1m: {time, imbalance[], bid_volume[], ask_volume[]}
    - 5m: {time, imbalance[], bid_volume[], ask_volume[]}
    - 15m: {time, imbalance[], bid_volume[], ask_volume[]}

- **Data Flow**
  1. Collect all ticks in current_minute_data
  2. At minute end: calculate averages and add to history
  3. Use history for trend analysis
  
- **Initialization**
  - Logger setup
  - Variables and buffers initialization
  - History data structures

- **Main Loop**
  - WebSocket connection
  - Order book data processing
  - Real-time metrics calculation

- **Data Management**
  - _update_history(): Updates historical data
  - _append_history(): Adds data points
  - _cleanup_history(): Cleans old data

- **Analysis**
  - analyze_timeframe(): Analyzes specific timeframe
  - _update_higher_timeframe(): Updates higher timeframes
  - detect_accumulation(): Detects accumulation patterns

## config.py
- WebSocket settings
- Timeframe configurations
- Logging settings

## logs/
- detailed_YYYYMMDD_HHMMSS.log: Detailed debug logs
- signals_YYYYMMDD_HHMMSS.log: Trading signals and statistics 