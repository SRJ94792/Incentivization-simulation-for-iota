import requests
import time
import sqlite3
import datetime
import math

# HORNET Nodes Configuration
NODES = {
    "Hornet-1": "http://localhost:14265",
    "Hornet-2": "http://localhost:14266",
    "Hornet-3": "http://localhost:14267",
    "Hornet-4": "http://localhost:14268",
}

# API Endpoints based on the configuration file
API_ENDPOINTS = {
    "node_info": "/api/core/v2/info",
    "milestone_utxo_changes": "/api/core/v2/milestones/by-index/{milestone_index}/utxo-changes",
    "tips": "/api/core/v2/tips",
    "blocks": "/api/core/v2/blocks",
    "transactions": "/api/core/v2/transactions",
    "outputs": "/api/core/v2/outputs",
    "treasury": "/api/core/v2/treasury",
    "indexer": "/api/indexer/v1",
    "mqtt": "/api/mqtt/v1",
    "participation_events": "/api/participation/v1/events",
    "participation_outputs": "/api/participation/v1/outputs",
    "participation_addresses": "/api/participation/v1/addresses",
}

JWT_TOKEN = "HORNET"  # Using the salt from the config

HEADERS = {
    "Authorization": f"Bearer {JWT_TOKEN}",
    "Content-Type": "application/json"
}

# Database setup
DB_NAME = "transactions.db"

# Reward configuration
REWARD_CALCULATION_INTERVAL = 300  # Calculate rewards every 5 minutes (in seconds)
BASE_REWARD_PER_TX = 0.01  # Base reward tokens per transaction
UPTIME_REWARD_FACTOR = 0.5  # Additional reward factor for uptime
MILESTONE_SYNC_REWARD = 0.2  # Reward for being in sync with milestones
TRANSACTION_VOLUME_THRESHOLD = 100  # Minimum transactions for bonus rewards
VOLUME_BONUS_MULTIPLIER = 1.2  # Bonus multiplier for high transaction volume
MAX_LATENCY_MS = 5000  # Maximum acceptable latency in milliseconds
LATENCY_PENALTY_FACTOR = 0.8  # Penalty factor for high latency

def init_db():
    """Initialize the database with tables for transactions, counters, and rewards."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Table for transactions - Added explicit timestamp column
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            node_name TEXT,
            milestone_index INTEGER,
            timestamp INTEGER DEFAULT (strftime('%s', 'now'))
        )
    """)

    # Table for tracking transaction counts per node
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS counters (
            node_name TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0
        )
    """)

    # Table for tracking node performance metrics
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS node_metrics (
            node_name TEXT PRIMARY KEY,
            last_seen INTEGER DEFAULT (strftime('%s', 'now')),
            uptime_seconds INTEGER DEFAULT 0,
            avg_latency REAL DEFAULT 0,
            latest_milestone INTEGER DEFAULT 0
        )
    """)

    # Table for rewards history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_name TEXT,
            reward_amount REAL,
            reason TEXT,
            timestamp INTEGER DEFAULT (strftime('%s', 'now'))
        )
    """)

    # Table for reward balance
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reward_balance (
            node_name TEXT PRIMARY KEY,
            balance REAL DEFAULT 0
        )
    """)

    # Insert default counter values for nodes if not present
    for node in NODES.keys():
        cursor.execute("INSERT OR IGNORE INTO counters (node_name, count) VALUES (?, 0)", (node,))
        cursor.execute("INSERT OR IGNORE INTO node_metrics (node_name) VALUES (?)", (node,))
        cursor.execute("INSERT OR IGNORE INTO reward_balance (node_name, balance) VALUES (?, 0)", (node,))
    
    conn.commit()
    conn.close()

def get_latest_milestone(node_name, node_url):
    """Fetch the latest milestone index for a node."""
    start_time = time.time()
    url = f"{node_url}{API_ENDPOINTS['node_info']}"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        end_time = time.time()
        latency = (end_time - start_time) * 1000  # Convert to milliseconds

        if response.status_code == 200:
            data = response.json()
            milestone_index = data.get("status", {}).get("latestMilestone", {}).get("index")
            
            # Update node metrics
            update_node_metrics(node_name, latency, milestone_index)
            
            return milestone_index
        
        print(f"[ERROR] {node_name} - Failed to fetch latest milestone ({response.status_code}): {response.text}")
        return None
    
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] {node_name} - Connection error: {str(e)}")
        update_node_metrics(node_name, MAX_LATENCY_MS, None)  # Mark as high latency
        return None

def update_node_metrics(node_name, latency=None, milestone_index=None):
    """Update the metrics for a node."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Get current timestamp
    current_time = int(time.time())
    
    # Get existing metrics
    cursor.execute("SELECT last_seen, avg_latency FROM node_metrics WHERE node_name = ?", (node_name,))
    row = cursor.fetchone()
    
    if row:
        last_seen, avg_latency = row
        
        # Calculate uptime (time since last check)
        time_diff = current_time - last_seen
        
        # Update metrics
        if latency is not None:
            # Calculate new average latency (simple moving average)
            if avg_latency > 0:
                new_avg_latency = (avg_latency * 0.8) + (latency * 0.2)  # 80% old, 20% new
            else:
                new_avg_latency = latency
            
            cursor.execute("""
                UPDATE node_metrics 
                SET last_seen = ?, 
                    uptime_seconds = uptime_seconds + ?, 
                    avg_latency = ?
                WHERE node_name = ?
            """, (current_time, time_diff, new_avg_latency, node_name))
        else:
            cursor.execute("""
                UPDATE node_metrics 
                SET last_seen = ?, 
                    uptime_seconds = uptime_seconds + ?
                WHERE node_name = ?
            """, (current_time, time_diff, node_name))
        
        # Update milestone index if provided
        if milestone_index is not None:
            cursor.execute("""
                UPDATE node_metrics 
                SET latest_milestone = ?
                WHERE node_name = ?
            """, (milestone_index, node_name))
    
    conn.commit()
    conn.close()

def get_milestone_utxo_changes(node_name, node_url, milestone_index):
    """Fetch transactions confirmed by a milestone."""
    url = f"{node_url}{API_ENDPOINTS['milestone_utxo_changes'].format(milestone_index=milestone_index)}"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)

        if response.status_code == 200:
            milestone_data = response.json()
            created_outputs = milestone_data.get("createdOutputs", [])
            consumed_outputs = milestone_data.get("consumedOutputs", [])
            return created_outputs, consumed_outputs
        
        print(f"[ERROR] {node_name} - Failed to fetch UTXO changes ({response.status_code}): {response.text}")
        return None, None
    
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] {node_name} - Connection error when fetching UTXO changes: {str(e)}")
        return None, None

def get_node_tips(node_name, node_url):
    """Fetch the current tips from a node."""
    url = f"{node_url}{API_ENDPOINTS['tips']}"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)

        if response.status_code == 200:
            tips_data = response.json()
            return tips_data.get("tips", [])
        
        print(f"[ERROR] {node_name} - Failed to fetch tips ({response.status_code}): {response.text}")
        return None
    
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] {node_name} - Connection error when fetching tips: {str(e)}")
        return None

def get_blocks_by_ids(node_name, node_url, block_ids):
    """Fetch blocks by their IDs."""
    if not block_ids:
        return []
    
    url = f"{node_url}{API_ENDPOINTS['blocks']}"
    
    try:
        # Use POST to fetch multiple blocks
        response = requests.post(url, headers=HEADERS, json={"blockIds": block_ids}, timeout=10)

        if response.status_code == 200:
            return response.json().get("blocks", [])
        
        print(f"[ERROR] {node_name} - Failed to fetch blocks ({response.status_code}): {response.text}")
        return []
    
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] {node_name} - Connection error when fetching blocks: {str(e)}")
        return []

def transaction_exists(tx_id):
    """Check if a transaction already exists in the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM transactions WHERE id = ?", (tx_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def add_transaction(tx_id, node_name, milestone_index):
    """Add a unique transaction to the database and update the counter."""
    if not transaction_exists(tx_id):
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Insert the transaction
        cursor.execute("INSERT INTO transactions (id, node_name, milestone_index) VALUES (?, ?, ?)", 
                       (tx_id, node_name, milestone_index))

        # Update the counter
        cursor.execute("UPDATE counters SET count = count + 1 WHERE node_name = ?", (node_name,))
        
        # Get the updated count
        cursor.execute("SELECT count FROM counters WHERE node_name = ?", (node_name,))
        count = cursor.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        print(f"[ADDED] {node_name} - Transaction {tx_id} (Total: {count})")

    else:
        print(f"[SKIPPED] {node_name} - Duplicate Transaction {tx_id}")

def get_node_performance_metrics(node_name):
    """Get performance metrics for a specific node."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Get transaction count
    cursor.execute("SELECT count FROM counters WHERE node_name = ?", (node_name,))
    tx_count = cursor.fetchone()[0]
    
    # Get metrics
    cursor.execute("""
        SELECT uptime_seconds, avg_latency, latest_milestone 
        FROM node_metrics 
        WHERE node_name = ?
    """, (node_name,))
    uptime, avg_latency, latest_milestone = cursor.fetchone()
    
    # Get transaction timestamps for recent period
    current_time = int(time.time())
    one_hour_ago = current_time - 3600
    cursor.execute("""
        SELECT COUNT(*) 
        FROM transactions 
        WHERE node_name = ? AND timestamp > ?
    """, (node_name, one_hour_ago))
    recent_tx_count = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        'total_transactions': tx_count,
        'recent_transactions': recent_tx_count,
        'uptime_seconds': uptime,
        'avg_latency': avg_latency,
        'latest_milestone': latest_milestone
    }

def calculate_milestone_sync_factor(node_metrics):
    """Calculate how in-sync the nodes are with milestones."""
    if not node_metrics:
        return {}
    
    # Find the highest milestone index reported by any node
    max_milestone = max(metrics['latest_milestone'] for metrics in node_metrics.values() if metrics['latest_milestone'])
    
    # Calculate sync factor for each node (1.0 = fully synced, lower = less synced)
    sync_factors = {}
    for node_name, metrics in node_metrics.items():
        if max_milestone and metrics['latest_milestone']:
            sync_factor = metrics['latest_milestone'] / max_milestone
            sync_factors[node_name] = sync_factor
        else:
            sync_factors[node_name] = 0
    
    return sync_factors

def calculate_latency_factor(avg_latency):
    """Calculate a factor based on latency (lower latency = higher factor)."""
    if avg_latency >= MAX_LATENCY_MS:
        return LATENCY_PENALTY_FACTOR
    
    # Linear scale: 1.0 (best) to LATENCY_PENALTY_FACTOR (worst)
    factor = 1.0 - ((1.0 - LATENCY_PENALTY_FACTOR) * (avg_latency / MAX_LATENCY_MS))
    return max(LATENCY_PENALTY_FACTOR, factor)

def calculate_uptime_factor(uptime_seconds, interval_seconds):
    """Calculate uptime factor based on expected interval."""
    # Cap at 100% for the period
    uptime_ratio = min(1.0, uptime_seconds / interval_seconds)
    
    # Apply UPTIME_REWARD_FACTOR
    uptime_bonus = 1.0 + (UPTIME_REWARD_FACTOR * uptime_ratio)
    return uptime_bonus

def calculate_volume_bonus(tx_count):
    """Calculate bonus for high transaction volume."""
    if tx_count >= TRANSACTION_VOLUME_THRESHOLD:
        # Logarithmic scaling for bonus to prevent excessive rewards for very high volume
        bonus = 1.0 + (VOLUME_BONUS_MULTIPLIER - 1.0) * min(1.0, math.log10(tx_count / TRANSACTION_VOLUME_THRESHOLD + 1))
        return bonus
    return 1.0

def calculate_rewards():
    """Calculate rewards for all nodes based on their performance."""
    node_metrics = {}
    rewards = {}
    reward_reasons = {}
    
    # Get metrics for all nodes
    for node_name in NODES.keys():
        node_metrics[node_name] = get_node_performance_metrics(node_name)
    
    # Calculate milestone sync factors
    sync_factors = calculate_milestone_sync_factor(node_metrics)
    
    # Calculate rewards for each node
    for node_name, metrics in node_metrics.items():
        # Base transaction reward
        base_reward = metrics['recent_transactions'] * BASE_REWARD_PER_TX
        
        # Uptime factor
        uptime_factor = calculate_uptime_factor(metrics['uptime_seconds'], REWARD_CALCULATION_INTERVAL)
        
        # Latency factor (penalty for high latency)
        latency_factor = calculate_latency_factor(metrics['avg_latency'])
        
        # Milestone sync reward
        sync_factor = sync_factors.get(node_name, 0)
        sync_reward = MILESTONE_SYNC_REWARD * sync_factor
        
        # Volume bonus
        volume_bonus = calculate_volume_bonus(metrics['recent_transactions'])
        
        # Calculate final reward
        reward = (base_reward * uptime_factor * latency_factor * volume_bonus) + sync_reward
        reward = round(reward, 4)  # Round to 4 decimal places
        
        rewards[node_name] = reward
        
        # Store reason for reward calculation
        reward_reasons[node_name] = (
            f"Base: {base_reward:.4f} × "
            f"Uptime({metrics['uptime_seconds']}s): {uptime_factor:.2f} × "
            f"Latency({metrics['avg_latency']:.1f}ms): {latency_factor:.2f} × "
            f"Volume({metrics['recent_transactions']}tx): {volume_bonus:.2f} + "
            f"Sync({sync_factor:.2f}): {sync_reward:.4f}"
        )
    
    return rewards, reward_reasons

def record_rewards(rewards, reasons):
    """Record rewards in the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    for node_name, reward_amount in rewards.items():
        reason = reasons.get(node_name, "Regular reward calculation")
        
        # Record reward history
        cursor.execute("""
            INSERT INTO rewards (node_name, reward_amount, reason)
            VALUES (?, ?, ?)
        """, (node_name, reward_amount, reason))
        
        # Update balance
        cursor.execute("""
            UPDATE reward_balance
            SET balance = balance + ?
            WHERE node_name = ?
        """, (reward_amount, node_name))
    
    conn.commit()
    conn.close()

def get_reward_balances():
    """Get current reward balances for all nodes."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT node_name, balance FROM reward_balance")
    balances = {row[0]: row[1] for row in cursor.fetchall()}
    
    conn.close()
    return balances

def print_status_report():
    """Print a status report with current metrics and rewards."""
    node_metrics = {}
    for node_name in NODES.keys():
        node_metrics[node_name] = get_node_performance_metrics(node_name)
    
    balances = get_reward_balances()
    
    print("\n" + "="*80)
    print(f"STATUS REPORT - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    print("\nNODE METRICS:")
    print("-" * 80)
    print(f"{'Node Name':<12} | {'Transactions':<12} | {'Recent Tx':<10} | {'Uptime':<12} | {'Latency':<10} | {'Milestone':<10}")
    print("-" * 80)
    
    for node_name, metrics in node_metrics.items():
        print(f"{node_name:<12} | {metrics['total_transactions']:<12} | {metrics['recent_transactions']:<10} | "
              f"{metrics['uptime_seconds']//60:>5} min | {metrics['avg_latency']:>8.1f}ms | {metrics['latest_milestone']:<10}")
    
    print("\nREWARD BALANCES:")
    print("-" * 40)
    print(f"{'Node Name':<12} | {'Balance':<12}")
    print("-" * 40)
    
    for node_name, balance in balances.items():
        print(f"{node_name:<12} | {balance:<12.4f}")
    
    print("="*80 + "\n")

def get_protocol_parameters(node_name, node_url):
    """Get protocol parameters like token info."""
    url = f"{node_url}{API_ENDPOINTS['node_info']}"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)

        if response.status_code == 200:
            data = response.json()
            protocol = data.get("protocol", {})
            base_token = protocol.get("baseToken", {})
            
            return {
                "networkName": protocol.get("networkName", "unknown"),
                "tokenName": base_token.get("name", "unknown"),
                "tokenSymbol": base_token.get("tickerSymbol", "unknown"),
                "tokenDecimals": base_token.get("decimals", 0)
            }
        
        print(f"[ERROR] {node_name} - Failed to fetch protocol parameters ({response.status_code}): {response.text}")
        return None
    
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] {node_name} - Connection error when fetching protocol parameters: {str(e)}")
        return None

def process_transactions():
    """Continuously fetch and process transactions for new milestones."""
    last_reward_time = time.time()
    last_report_time = time.time()
    report_interval = 300  # Print status report every 5 minutes
    
    # Get protocol parameters at startup
    for node_name, node_url in NODES.items():
        protocol_params = get_protocol_parameters(node_name, node_url)
        if protocol_params:
            print(f"[PROTOCOL] {node_name} connected to {protocol_params['networkName']} network")
            print(f"[PROTOCOL] Token: {protocol_params['tokenName']} ({protocol_params['tokenSymbol']})")
            break
    
    print("[INFO] Starting continuous monitoring loop...")
    
    while True:
        try:
            current_time = time.time()
            
            # Process transactions for each node
            for node_name, node_url in NODES.items():
                milestone = get_latest_milestone(node_name, node_url)

                if milestone:
                    created_txns, consumed_txns = get_milestone_utxo_changes(node_name, node_url, milestone)
                    
                    if created_txns or consumed_txns:
                        for tx in (created_txns or []) + (consumed_txns or []):
                            add_transaction(tx, node_name, milestone)
                    else:
                        print(f"[INFO] {node_name} - No new transactions for milestone {milestone}.")
                else:
                    print(f"[ERROR] {node_name} - Could not retrieve latest milestone index.")
            
            # Calculate and distribute rewards periodically
            if current_time - last_reward_time >= REWARD_CALCULATION_INTERVAL:
                print("\n[REWARDS] Calculating rewards...")
                rewards, reasons = calculate_rewards()
                record_rewards(rewards, reasons)
                
                # Print reward details
                print("[REWARDS] Rewards distributed:")
                for node_name, reward in rewards.items():
                    print(f"  {node_name}: {reward:.4f} - {reasons[node_name]}")
                
                last_reward_time = current_time
            
            # Print periodic status report
            if current_time - last_report_time >= report_interval:
                print_status_report()
                last_report_time = current_time
            
            # Wait before checking again (adjust delay as needed)
            time.sleep(5)
            
        except KeyboardInterrupt:
            print("\n[SHUTDOWN] Received shutdown signal, stopping...")
            break
        except Exception as e:
            print(f"[ERROR] Unexpected error in main loop: {str(e)}")
            print("[INFO] Continuing after error...")
            time.sleep(10)  # Wait a bit longer after an error

# Run the system
if __name__ == "__main__":
    print("[STARTUP] Initializing HORNET protocol reward system...")
    init_db()
    print("[STARTUP] Database initialized")
    print("[STARTUP] Starting continuous transaction processing and reward calculation")
    process_transactions()