import math
import json
import random
from groq import Groq
from dotenv import load_dotenv
import os

from groq import Groq
load_dotenv() 
class A2AMessage:
    """Standardized JSON-RPC 2.0 envelope for Agent-to-Agent communication."""
    def __init__(self, sender, receiver, method, params):
        self.envelope = {
            "jsonrpc": "2.0",
            "sender": sender,
            "receiver": receiver,
            "method": method,
            "params": params,
            "id": random.randint(1000, 9999) # Unique session ID
        }

class KovaiMCPServer:
    """
    Mock MCP Server exposing simulation tools.
    In a real solution, this would be a separate process communicating via JSON-RPC.
    """
    @staticmethod
    def calculate_distance(pos1, pos2):
        return math.sqrt((pos1[0]-pos2[0])**2 + (pos1[1]-pos2[1])**2)
    

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def call_llm(prompt: str) -> str | None:
    """
    Single LLM call using Groq.
    MUST be called only once (planner stage).
    """
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise AI planner. Return ONLY valid JSON. No explanations."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2,
        )

        return completion.choices[0].message.content

    except Exception as e:
        print("⚠️ Groq LLM call failed:", e)
        return None
    
def safe_json_loads(text, fallback):
    if not text:
        return fallback

    text = text.strip()

    # Case 1: markdown ```json ... ```
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("{") or part.startswith("["):
                try:
                    return json.loads(part)
                except Exception:
                    pass

    # Case 2: find first JSON object manually
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass

    print("⚠️ JSON parse failed completely, using fallback")
    return fallback

    
class OrderAnalystAgent:
    def handle(self, orders):
        prompt = f"""
You are an Order Analyst AI Agent.

Task:
- Read orders
- Detect urgency from description
Rules:
- medical → urgency 3
- express / urgent → urgency 2
- otherwise → urgency 1

Return ONLY JSON:
{{
  "orders": [
    {{"order_id": int, "urgency": int}}
  ]
}}

Orders:
{json.dumps(orders)}
"""
        result = safe_json_loads(call_llm(prompt), fallback={"orders": []})
        return A2AMessage("order_analyst", "allocator", "rank_orders", result)


class ResourceAllocatorAgent:
    def handle(self, ranked_orders, drones):
        prompt = f"""
You are a Resource Allocator AI Agent.

Task:
- Assign best idle drone to each order
Rules:
- Drone must have enough capacity
- Prefer smallest suitable drone
- One drone per order

Return ONLY JSON:
{{
  "assignments": [
    {{"drone_id": str, "order_id": int}}
  ]
}}

Orders:
{json.dumps(ranked_orders)}

Drones:
{json.dumps(drones)}
"""
        result = safe_json_loads(call_llm(prompt), fallback={"assignments": []})
        return A2AMessage("allocator", "auditor", "propose_assignments", result)


class SafetyAuditorAgent:
    def handle(self, assignments, drones, orders, mcp):
        safe = []

        for a in assignments:
            drone = drones[a["drone_id"]]
            order = next(o for o in orders if o["id"] == a["order_id"])

            to_dest = mcp.calculate_distance((0, 0), order["destination"])
            to_hub = mcp.calculate_distance(order["destination"], (0, 0))
            total_dist = to_dest + to_hub

            ticks = max(1, int(total_dist / drone["speed"]))
            net_gain = 10 - drone["discharge"]
            final_battery = 100 + net_gain * ticks

            if final_battery > 0:
                safe.append(a)

        return A2AMessage("auditor", "dispatcher", "approved", {"assignments": safe})


class TacticalDispatcherAgent:
    def handle(self, state, approved, memory, mcp):
        actions = {}

        for drone_id, info in state["drones"].items():
            if info["status"] == "CRASHED":
                continue

            # Find approved assignment for this drone (if any)
            approved_order = next(
                (a for a in approved if a["drone_id"] == drone_id),
                None
            )

            
            if approved_order and info["status"] == "IDLE" and info["load"] == 0:
                order = next(
                    (o for o in state["pending_orders"]
                     if o["id"] == approved_order["order_id"]),
                    None
                )

                if not order:
                    continue  # already taken by another drone

                memory["targets"][drone_id] = order

                actions[drone_id] = {
                    "action": "PICKUP",
                    "params": {"order_id": order["id"]}
                }
                continue

            
            if info["load"] > 0:
                order = memory["targets"].get(drone_id)
                if not order:
                    continue  # safety guard

                dist = mcp.calculate_distance(info["pos"], order["destination"])

                if dist < 0.1:
                    actions[drone_id] = {"action": "DELIVER", "params": {}}
                    memory["targets"].pop(drone_id, None)
                else:
                    actions[drone_id] = {
                        "action": "MOVE",
                        "params": {"target": order["destination"]}
                    }
                continue

            if info["status"] == "IDLE" and info["load"] == 0 and info["pos"] != (0, 0):
                actions[drone_id] = {
                    "action": "MOVE",
                    "params": {"target": (0, 0)}
                }

        return actions



class KovaiOrchestrator:
    """
    AI-Agentic Orchestrator using LLM + MCP + A2A
    """
    def __init__(self):
        self.name = "Senior Controller"

        # MCP
        self.mcp = KovaiMCPServer()

        # Shared memory
        self.memory = {
            "targets": {}  # drone_id -> order_id
        }

        # Initialize agents (THIS WAS MISSING)
        self.order_analyst = OrderAnalystAgent()
        self.allocator = ResourceAllocatorAgent()
        self.auditor = SafetyAuditorAgent()
        self.dispatcher = TacticalDispatcherAgent()

    def orchestrate(self, state):
        # 1️⃣ Order Analyst
        msg1 = self.order_analyst.handle(state["pending_orders"])

        # 2️⃣ Resource Allocator
        msg2 = self.allocator.handle(
            msg1.envelope["params"]["orders"],
            state["drones"]
        )

        # 3️⃣ Safety Auditor
        msg3 = self.auditor.handle(
            msg2.envelope["params"]["assignments"],
            state["drones"],
            state["pending_orders"],
            self.mcp
        )

        # 4️⃣ Tactical Dispatcher
        actions = self.dispatcher.handle(
            state,
            msg3.envelope["params"]["assignments"],
            self.memory,
            self.mcp
        )

        return actions


class KovaiAgent:
    def __init__(self):
        self.orchestrator = KovaiOrchestrator()
        self.name = self.orchestrator.name

    def decide(self, state):
        return self.orchestrator.orchestrate(state)
