from flask import Flask, render_template, jsonify
import sqlite3
import time
import datetime
import math

app = Flask(__name__)

DB_NAME = "transactions.db"

# Constants moved from ap.py for reward calculation
REWARD_CALCULATION_INTERVAL = 3600  # Calculate rewards every hour (in seconds)
BASE_REWARD_PER_TX = 0.01  # Base reward tokens per transaction
UPTIME_REWARD_FACTOR = 0.5  # Additional reward factor for uptime
MILESTONE_SYNC_REWARD = 0.2  # Reward for being in sync with milestones
TRANSACTION_VOLUME_THRESHOLD = 100  # Minimum transactions for bonus rewards
VOLUME_BONUS_MULTIPLIER = 1.2  # Bonus multiplier for high transaction volume
MAX_LATENCY_MS = 5000  # Maximum acceptable latency in milliseconds
LATENCY_PENALTY_FACTOR = 0.8  # Penalty factor for high latency

def get_node_metrics():
    """Fetch transaction counts and performance metrics for all nodes."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Fetch counters
    cursor.execute("SELECT node_name, count FROM counters")
    counter_data = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Fetch reward balances
    cursor.execute("SELECT node_name, balance FROM reward_balance")
    reward_data = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Fetch node performance metrics
    cursor.execute("""
        SELECT node_name, uptime_seconds, avg_latency, latest_milestone
        FROM node_metrics
    """)
    metrics_data = {}
    for row in cursor.fetchall():
        node_name, uptime, latency, milestone = row
        metrics_data[node_name] = {
            'uptime_seconds': uptime,
            'avg_latency': latency,
            'latest_milestone': milestone
        }
    
    # Get recent transactions (last hour)
    current_time = int(time.time())
    one_hour_ago = current_time - 3600
    
    recent_tx = {}
    cursor.execute("""
        SELECT node_name, COUNT(*) 
        FROM transactions 
        WHERE timestamp > ?
        GROUP BY node_name
    """, (one_hour_ago,))
    
    for row in cursor.fetchall():
        node_name, count = row
        recent_tx[node_name] = count
    
    # Fetch recent rewards
    cursor.execute("""
        SELECT node_name, reward_amount, reason, timestamp
        FROM rewards
        ORDER BY timestamp DESC
        LIMIT 20
    """)
    
    rewards_history = []
    for row in cursor.fetchall():
        node_name, amount, reason, timestamp = row
        rewards_history.append({
            'node_name': node_name,
            'amount': amount,
            'reason': reason,
            'timestamp': datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        })
    
    conn.close()
    
    # Combine data
    nodes_data = []
    for node_name in counter_data.keys():
        node_data = {
            'node_name': node_name,
            'total_transactions': counter_data.get(node_name, 0),
            'recent_transactions': recent_tx.get(node_name, 0),
            'reward_balance': reward_data.get(node_name, 0),
            'uptime_seconds': metrics_data.get(node_name, {}).get('uptime_seconds', 0),
            'avg_latency': metrics_data.get(node_name, {}).get('avg_latency', 0),
            'latest_milestone': metrics_data.get(node_name, {}).get('latest_milestone', 0)
        }
        nodes_data.append(node_data)
    
    return nodes_data, rewards_history

def calculate_milestone_sync_factor(node_metrics):
    """Calculate how in-sync the nodes are with milestones."""
    if not node_metrics:
        return {}
    
    # Find the highest milestone index reported by any node
    max_milestone = max(node['latest_milestone'] for node in node_metrics if node['latest_milestone'])
    
    # Calculate sync factor for each node (1.0 = fully synced, lower = less synced)
    sync_factors = {}
    for node in node_metrics:
        node_name = node['node_name']
        if max_milestone and node['latest_milestone']:
            sync_factor = node['latest_milestone'] / max_milestone
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

def calculate_reward_details(nodes_data):
    """Calculate detailed reward information based on node metrics."""
    # Calculate milestone sync factors
    sync_factors = calculate_milestone_sync_factor(nodes_data)
    
    reward_details = []
    
    # Calculate rewards for each node
    for node in nodes_data:
        node_name = node['node_name']
        metrics = node
        
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
        
        # Store reason for reward calculation
        reward_reason = (
            f"Base: {base_reward:.4f} × "
            f"Uptime({metrics['uptime_seconds']}s): {uptime_factor:.2f} × "
            f"Latency({metrics['avg_latency']:.1f}ms): {latency_factor:.2f} × "
            f"Volume({metrics['recent_transactions']}tx): {volume_bonus:.2f} + "
            f"Sync({sync_factor:.2f}): {sync_reward:.4f}"
        )
        
        reward_details.append({
            'node_name': node_name,
            'reward': reward,
            'reason': reward_reason,
            'base_reward': base_reward,
            'uptime_factor': uptime_factor,
            'latency_factor': latency_factor,
            'sync_factor': sync_factor,
            'sync_reward': sync_reward,
            'volume_bonus': volume_bonus
        })
    
    return reward_details

@app.route('/')
def index():
    """Render the front-end page with node metrics and rewards."""
    nodes_data, rewards_history = get_node_metrics()
    
    # Calculate reward details for each node
    reward_details = calculate_reward_details(nodes_data)
    
    # Calculate system stats
    total_transactions = sum(node['total_transactions'] for node in nodes_data)
    total_recent_txs = sum(node['recent_transactions'] for node in nodes_data)
    total_rewards = sum(node['reward_balance'] for node in nodes_data)
    
    # Calculate average latency of active nodes
    active_nodes = [node for node in nodes_data if node['avg_latency'] > 0]
    avg_system_latency = sum(node['avg_latency'] for node in active_nodes) / len(active_nodes) if active_nodes else 0
    
    # Calculate max milestone
    max_milestone = max([node['latest_milestone'] for node in nodes_data]) if nodes_data else 0
    
    system_stats = {
        'total_transactions': total_transactions,
        'recent_transactions': total_recent_txs,
        'total_rewards': total_rewards,
        'avg_latency': avg_system_latency,
        'max_milestone': max_milestone,
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    return render_template('index.html', 
                          nodes=nodes_data, 
                          rewards_history=rewards_history,
                          system_stats=system_stats,
                          reward_details=reward_details)

@app.route('/api/metrics')
def api_metrics():
    """JSON API endpoint for node metrics."""
    nodes_data, rewards_history = get_node_metrics()
    reward_details = calculate_reward_details(nodes_data)
    
    return jsonify({
        'nodes': nodes_data,
        'rewards': rewards_history,
        'reward_details': reward_details,
        'timestamp': int(time.time())
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)