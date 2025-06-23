# HORNET Protocol Reward System

The HORNET Protocol Reward System is a Flask-based application designed to monitor and reward nodes in a distributed network based on their performance metrics, such as transaction processing, uptime, latency, and milestone synchronization. The system tracks transactions, calculates rewards, and provides a web-based dashboard for real-time monitoring.

## Features

- **Node Monitoring**: Tracks transaction counts, uptime, latency, and milestone synchronization for multiple HORNET nodes.
- **Reward System**: Calculates rewards based on transaction volume, uptime, latency, and milestone sync status.
- **Web Dashboard**: Displays node performance, reward details, and system statistics using a responsive interface.
- **API Endpoint**: Provides JSON-based access to node metrics and rewards via `/api/metrics`.
- **Database**: Uses SQLite to store transactions, counters, node metrics, rewards history, and reward balances.
- **Continuous Processing**: Monitors nodes and processes transactions in real-time, with periodic reward calculations.

## Requirements

- Python 3.6+
- Flask (`pip install flask`)
- SQLite3 (included with Python)
- Requests (`pip install requests`)

## Installation

1. **Clone the Repository**:
   ```bash
   git clone <repository-url>
   cd hornet-reward-system
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set Up the Database**:
   The database (`transactions.db`) is automatically initialized when the application starts.

4. **Configure Nodes**:
   Update the `NODES` dictionary in `rwd.py` with the URLs of your HORNET nodes:
   ```python
   NODES = {
       "Hornet-1": "http://localhost:14265",
       "Hornet-2": "http://localhost:14266",
       # Add more nodes as needed
   }
   ```

## Usage

1. **Run the Reward Processor**:
   Start the continuous transaction processing and reward calculation script:
   ```bash
   python rwd.py
   ```
   This script initializes the database, monitors nodes for transactions, and calculates rewards every 5 minutes.

2. **Run the Web Server**:
   Start the Flask web server to access the dashboard:
   ```bash
   python a1.py
   ```
   The dashboard will be available at `http://localhost:5000`.

3. **Access the Dashboard**:
   Open a web browser and navigate to `http://localhost:5000` to view node performance, reward details, and system statistics.

4. **API Access**:
   Retrieve node metrics and rewards in JSON format via the API endpoint:
   ```
   GET http://localhost:5000/api/metrics
   ```

## Files

- **a1.py**: Flask application for the web dashboard and API endpoint. Handles rendering of the dashboard and JSON responses for metrics.
- **rwd.py**: Core logic for monitoring nodes, fetching transactions, calculating rewards, and updating the database.
- **index.html**: HTML template for the web dashboard, displaying node metrics, reward calculations, and reward history.
- **transactions.db**: SQLite database storing transactions, counters, node metrics, rewards, and balances.

## Reward Calculation

Rewards are calculated every 5 minutes (configurable via `REWARD_CALCULATION_INTERVAL`) based on the following formula:

```
Reward = (Base Reward × Uptime Factor × Latency Factor × Volume Bonus) + Sync Reward
```

Where:
- **Base Reward**: `Recent Transactions × 0.01` tokens
- **Uptime Factor**: `1.0 + (0.5 × uptimeRatio)`
- **Latency Factor**: `1.0 - ((1.0 - 0.8) × (latency / 5000))`, capped at 0.8 for high latency
- **Volume Bonus**: `1.0 + (0.2 × log10(transactions / 100 + 1))` for nodes exceeding 100 transactions
- **Sync Reward**: `0.2 × syncFactor`, where `syncFactor` is the ratio of a node's milestone index to the highest milestone index

## Database Schema

- **transactions**: Stores transaction details (id, node_name, milestone_index, timestamp).
- **counters**: Tracks total transaction count per node (node_name, count).
- **node_metrics**: Stores node performance metrics (node_name, last_seen, uptime_seconds, avg_latency, latest_milestone).
- **rewards**: Records reward history (id, node_name, reward_amount, reason, timestamp).
- **reward_balance**: Maintains current reward balance per node (node_name, balance).

## Configuration

Key configuration parameters in `rwd.py` and `a1.py`:
- `REWARD_CALCULATION_INTERVAL`: Time between reward calculations (300 seconds in `rwd.py`, 3600 seconds in `a1.py`).
- `BASE_REWARD_PER_TX`: Base reward per transaction (0.01 tokens).
- `UPTIME_REWARD_FACTOR`: Bonus for uptime (0.5).
- `MILESTONE_SYNC_REWARD`: Reward for milestone synchronization (0.2).
- `TRANSACTION_VOLUME_THRESHOLD`: Minimum transactions for volume bonus (100).
- `VOLUME_BONUS_MULTIPLIER`: Volume bonus multiplier (1.2).
- `MAX_LATENCY_MS`: Maximum acceptable latency (5000 ms).
- `LATENCY_PENALTY_FACTOR`: Penalty for high latency (0.8).

## Notes

- Ensure HORNET nodes are running and accessible at the configured URLs.
- The `JWT_TOKEN` in `rwd.py` must match the authentication token for your HORNET nodes.
- The reward calculation interval differs between `rwd.py` (300 seconds) and `a1.py` (3600 seconds). Ensure consistency if needed.
- The system assumes nodes are part of the same network. Verify protocol parameters using the `/api/core/v2/info` endpoint.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Contributing

Contributions are welcome! Please submit a pull request or open an issue for suggestions or bug reports.