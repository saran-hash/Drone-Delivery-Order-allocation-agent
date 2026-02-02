# 🛸 KovaiDelivery: The Autonomous Logistics Multi-Agent Challenge

[![GitHub Repo](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/genorai-tech/kovai-delivery-hackathon)

Welcome to **KovaiDelivery**. This isn't just a coding task; it’s an engineering challenge to build a robust, multi-agent system capable of managing a city-scale autonomous delivery fleet.

---

## 🧠 The Engineering Challenge: "The Kovai Efficiency Crisis"
The city's logistics hub is overwhelmed. We have **200+ incoming orders** and **100 drones** of varying classes, but the operation is currently losing money due to inefficient scheduling and drone battery failures during weather spikes.

**The core problem you must solve**: 
> "If a sudden **STORMY** weather front hits the city at Tick 100, which 30% of high-priority medical deliveries can we still guarantee, and how must the remaining 70% of the fleet be re-routed to the Hub to avoid a 0% battery crash?"

Your system must solve this by implementing:
1. **Semantic Extraction**: Identify "Medical," "Urgent," or "Fragile" priorities from the unstructured text of `orders.csv`.
2. **Combinatorial Matching**: Solve the "Drone-to-Order" matching problem—never send a 30kg Titan to deliver a 0.5kg document.
3. **Predictive Energy Auditing**: Calculate the "Point of No Return" for every drone based on dynamic weather multipliers.

---

## 🏗 Multi-Agent Architecture
You are expected to design a team of specialized AI agents that collaborate using the **A2A (Agent-to-Agent)** communication pattern:

- **The Order Analyst**: Parses unstructured text orders, extracts mass/destination, and handles priority queueing.
- **The Resource Allocator**: Matches the optimal drone spec (Speedster vs. Heavy) to the order mass and distance (The "Optimizer").
- **The Tactical Dispatcher**: Manages the stateful mission lifecycle for each drone (MOVE -> PICKUP -> DELIVER).
- **The Safety Auditor**: A specialized "Energy Watchdog" that validates flight plans against real-time weather to prevent battery crashes.

---

## 🛠 Tech Stack & Protocols (Required)
Your solution must implement the following industry standards:

### 1. Model Context Protocol (MCP)
Build an **MCP Server** to expose your logistics data and the simulation engine to your agents. This allows your agents to "query" the world state and "probe" battery usage tools dynamically.

### 2. A2A Protocol
Ensure your agents communicate using a standardized JSON-RPC envelope. Every hand-off (e.g., Strategist to Dispatcher) must be a formal negotiation.

### 3. PydanticAI (Recommended)
We recommend using **PydanticAI** for building type-safe, reliable agentic flows that validate state transitions at every step.

---

## 📊 The Sandbox (Datasets)
We provide you with real-world logistics data in `data/`:
- **Fleet Matrix**: 100+ drones with specific capacity, speed, and discharge metrics.
- **Order Stream**: 200+ customer requests with varied mass and delivery coordinates.
- **Weather Logs**: Tick-by-tick environmental conditions.

## 🧭 Codebase Orientation
To succeed in this challenge, you must understand how the three core components interact:

### 1. The Engine (`src/simulation/kovai_engine.py`)
This is the **"Source of Truth."** It simulates the physics of the world, manages drone battery drain, handles package mass, and injects random weather events. 
*   **Rules**: You cannot modify this file. Your agent must interact with it by sending valid actions.
*   **Physics**: Drones consume more battery when carrying heavy loads or flying through `STORMY` weather.

### 2. The Mission Runner (`run_mission.py`)
This is the **"Clock."** It initializes the simulation, loads the CSV datasets, and runs the `tick` loop.
*   It passes the current `state` of the world to your agent every tick.
*   It collects the `actions` your agent returns and applies them to the engine.

### 3. The Agent (`src/agent/my_agent.py`)
This is the **"AI Brain"** and your primary workspace.
*   We have provided a **Heuristic Baseline**—a simple Python router that moves drones. 
*   **Your Goal**: Delete the heuristic logic and replace it with a Multi-Agent system that uses actual reasoning and standardized protocols.

---

## 🏗 What You Need to Implement
Your final submission will be evaluated on your ability to transform a simple script into an industrial-grade agentic system:

1.  **Define Agent Roles**: Implement the specialized roles (Order Analyst, Allocator, Dispatcher, Auditor) within your team.
2.  **A2A Protocol**: Implement a communication layer where agents exchange JSON-RPC messages to negotiate tasks.
3.  **MCP Integration**: (Advanced) Refactor the `KovaiMCPServer` into a formal MCP server that your agents "call" to get distance or battery estimates.
4.  **Stateful Reasoning**: Ensure your agents don't just react to the current tick but maintain a "Memory" of active plans and validations.

---

## ⚡ Quick Start: Running Your First Mission

### 1. Setup Environment
Ensure you have Python 3.8+ installed, then install the dependencies:
```bash
pip install -r requirements.txt
```

### 2. Run the Heuristic Baseline
We have provided a functional baseline so you can see the simulation in action immediately.

**To run with a small sample (3 drones, 5 orders):**
```bash
python run_mission.py --fleet data/sample/fleet_sample.csv --orders data/sample/orders_sample.csv
```

**To run the full City-Scale challenge (100 drones, 200 orders):**
```bash
python run_mission.py
```

### 3. Start Building
Open `src/agent/my_agent.py`. You will see the `orchestrate` method where the baseline logic lives. Your mission is to delete this heuristic code and implement your Multi-Agent system.

## 👨‍⚖️ Judging Criteria
- **Architecture Maturity**: How well did you use A2A and MCP?
- **Efficiency Score**: (Total Distance / Total Battery Used).
- **Service Level**: Percentage of orders fulfilled.
- **Validation**: Did your Auditor prevent any drone crashes?

---

## 🎯 Scoring & Goal
Minimize **Cost** while maximizing **Speed**.
- **Efficiency Score**: (Total Distance / Total Battery Used) - *Higher is better!*
- **Service Level**: Percentage of delivered orders.
- **Reliability**: Don't let your drones crash (0% battery)!

