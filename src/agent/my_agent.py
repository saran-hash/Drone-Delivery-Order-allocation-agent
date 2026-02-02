import math
import json
import os
from typing import Dict, List, Any, Tuple
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# =========================
# MCP (TOOLS)
# =========================
class KovaiMCPServer:
    @staticmethod
    def calculate_distance(pos1: Tuple[float, float], pos2: Tuple[float, float]) -> float:
        """Calculate Euclidean distance between two positions."""
        return math.sqrt((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2)

    @staticmethod
    def estimate_battery_cost(distance: float, discharge_rate: float, load: float = 0) -> float:
        """
        Estimate battery cost for a trip.
        Formula: distance * discharge_rate * (1 + load_factor)
        """
        load_factor = 1.0 + (load * 0.1)  # 10% extra battery per kg of load
        return distance * discharge_rate * load_factor

    @staticmethod
    def is_reachable(battery: float, distance: float, discharge_rate: float, 
                     load: float = 0, safety_buffer: float = 1.2) -> bool:
        """
        Check if drone can reach destination and return to hub with safety buffer.
        Round trip = distance * 2 (to dest and back)
        """
        round_trip_cost = KovaiMCPServer.estimate_battery_cost(
            distance * 2, discharge_rate, load
        ) * safety_buffer
        return battery > round_trip_cost


# =========================
# LLM SETUP (GROQ)
# =========================
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def call_llm_for_decisions(state_summary: str) -> Dict[str, Any]:
    """
    Call LLM to make tactical decisions for drone actions.
    Returns structured JSON with action recommendations.
    """
    try:
        prompt = f"""
You are a logistics dispatcher AI. Analyze the current fleet state and recommend actions.

CONSTRAINTS AND RULES:
1. DRONE PHYSICS:
   - Each drone has a battery (0-100%)
   - Battery drains: distance * discharge_rate per unit traveled
   - discharge rate was given for each drone
   - Battery cannot go below 0 (drone crashes)
   - Charging  adds 10% battery per tick while traveling

2. DELIVERY RULES:
   - Orders can only be picked up at hub (0,0)
   - Drone must have enough capacity:  order_mass <= capacity
   - Drone must have enough battery for round trip to delivery location and back
   - PICKUP action: Drone at hub, picks up order
   - MOVE action: Drone moves toward destination
   - DELIVER action: Drone at delivery location, drops package



4. PRIORITIES:
   - Medical orders: HIGHEST priority
   - Urgent orders: HIGH priority
   - Standard orders: NORMAL priority
   - Never leave drones at 0% battery (CRASH)
   

CURRENT STATE:
{state_summary}

TASK:
For each IDLE drone with available orders:
1. Recommend ONE action: PICKUP, MOVE, CHARGE, or WAIT
2. If PICKUP: specify order_id
3. If MOVE: specify target coordinates
4. Ensure all recommendations are physically feasible

Return ONLY valid JSON:
{{
    "actions": [
        {{"drone_id": "Speedy", "action": "MOVE", "target": [5, 5]}},
        {{"drone_id": "Steady", "action": "CHARGE"}}
    ]
}}
"""
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": "You are a logistics AI. Output ONLY valid JSON. No markdown. No explanations. No code blocks."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1000,
        )
        
        response_text = completion.choices[0].message.content.strip()
        # Remove markdown code blocks if present
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        return json.loads(response_text)
    except Exception as e:
        print(f"⚠️ LLM decision call failed: {e}")
        return {"actions": []}


# =========================
# AGENT LOGIC
# =========================
class KovaiOrchestrator:
    def __init__(self):
        self.mcp = KovaiMCPServer()
        self.drone_targets: Dict[str, Dict] = {}  # Track active delivery targets
        self.memory: Dict[str, Any] = {}  # Persistent memory across ticks

    def orchestrate(self, state: Dict[str, Any]) -> Dict[str, Dict]:
        """
        Main orchestration logic. Returns actions for each drone.
        """
        actions = {}
        
        try:
            # Extract state
            drones = state.get('drones', {})
            pending_orders = state.get('pending_orders', [])
            weather = state.get('weather', 'CLEAR')
            tick = state.get('tick', 0)
            
            # Get weather multiplier for battery calculations
            weather_mult = {
                'CLEAR': 1.0,
                'WINDY': 1.2,
                'STORMY': 1.5
            }.get(weather, 1.0)
            
            # ========== PHASE 1: HANDLE MOVING DRONES ==========
            for drone_id, drone_info in drones.items():
                status = drone_info.get('status', 'IDLE')
                
                if status == 'IN_TRANSIT':
                    # Continue to current target
                    target = self.drone_targets.get(drone_id)
                    if target:
                        dest = target.get('dest') or target.get('destination')
                        if dest:
                            actions[drone_id] = {
                                "action": "MOVE",
                                "params": {"target": list(dest)}
                            }
            
            # ========== PHASE 2: HANDLE DELIVERY COMPLETION & MOVEMENT WITH CARGO ==========
            for drone_id, drone_info in drones.items():
                status = drone_info.get('status', 'IDLE')
                
                if status == 'IDLE' and drone_info.get('load', 0) > 0:
                    # Drone has cargo - either move to delivery or deliver if arrived
                    target = self.drone_targets.get(drone_id)
                    if target:
                        dest = target.get('dest') or target.get('destination')
                        if dest:
                            dist = self.mcp.calculate_distance(drone_info['pos'], dest)
                            if dist < 1.0:
                                # Arrived at delivery location - DELIVER
                                actions[drone_id] = {
                                    "action": "DELIVER",
                                    "params": {}
                                }
                                self.drone_targets.pop(drone_id, None)
                            else:
                                # Not yet arrived - MOVE to delivery location
                                actions[drone_id] = {
                                    "action": "MOVE",
                                    "params": {"target": list(dest)}
                                }
            
            # ========== PHASE 3: ASSIGN NEW ORDERS TO IDLE DRONES ==========
            idle_drones = [
                (d_id, d_info) 
                for d_id, d_info in drones.items() 
                if d_info.get('status') == 'IDLE' and d_info.get('load', 0) == 0
            ]
            
            if idle_drones and pending_orders:
                # Build state summary for LLM (limited size)
                summary = self._build_state_summary(
                    idle_drones[:],  # Only top 5 idle drones
                    pending_orders[:],  # Only top 5 pending orders
                    weather,
                    tick
                )
                
                # Get LLM recommendations
                llm_response = call_llm_for_decisions(summary)
                llm_actions = llm_response.get('actions', [])
                
                # Apply LLM recommendations
                for llm_action in llm_actions:
                    drone_id = llm_action.get('drone_id')
                    action = llm_action.get('action', '').upper()
                    
                    if drone_id not in drones:
                        continue
                    
                    if action == 'PICKUP':
                        order_id = llm_action.get('order_id')
                        order = next(
                            (o for o in pending_orders if o.get('id') == order_id),
                            None
                        )
                        if order:
                            # Verify constraints
                            drone = drones[drone_id]
                            if order.get('mass', 0) <= drone.get('capacity', 0):
                                actions[drone_id] = {
                                    "action": "PICKUP",
                                    "params": {"order_id": order_id}
                                }
                                # Remember target for later
                                self.drone_targets[drone_id] = order
                    
                    elif action == 'MOVE':
                        target = llm_action.get('target', [0, 0])
                        actions[drone_id] = {
                            "action": "MOVE",
                            "params": {"target": target}
                        }
                    
                    elif action == 'CHARGE':
                        actions[drone_id] = {
                            "action": "MOVE",
                            "params": {"target": [0, 0]}
                        }
            
            # ========== PHASE 4: DEFAULT ACTIONS FOR UNHANDLED DRONES ==========
            for drone_id, drone_info in drones.items():
                if drone_id not in actions:
                    status = drone_info.get('status', 'IDLE')
                    battery = drone_info.get('bat', 0)
                    
                    if status == 'CRASHED':
                        pass  # No action for crashed drones
                    elif battery < 20:
                        # Low battery - go to hub and charge
                        actions[drone_id] = {
                            "action": "MOVE",
                            "params": {"target": [0, 0]}
                        }
                    elif status == 'IDLE':
                        # WAIT at current position
                        actions[drone_id] = {
                            "action": "WAIT",
                            "params": {}
                        }
            
            return actions
            
        except Exception as e:
            print(f"⚠️ Orchestrator error: {e}")
            return {}

    def _build_state_summary(self, idle_drones: List, pending_orders: List, 
                            weather: str, tick: int) -> str:
        """Build a concise summary of state for LLM."""
        drone_list = []
        for drone_id, drone_info in idle_drones:
            drone_list.append({
                "id": drone_id,
                "battery": round(drone_info.get('bat', 0), 1),
                "capacity": drone_info.get('capacity', 0),
                "speed": drone_info.get('speed', 0),
                "pos": list(drone_info.get('pos', [0, 0]))
            })
        
        order_list = []
        for order in pending_orders[:5]:
            dest = order.get('dest') or order.get('destination')
            order_list.append({
                "id": order.get('id'),
                "mass": order.get('mass', 0),
                "dest": list(dest) if dest else [0, 0],
                "priority": "MEDICAL" if "Medical" in order.get('text', '') else "STANDARD"
            })
        
        return json.dumps({
            "tick": tick,
            "weather": weather,
            "available_drones": drone_list,
            "available_orders": order_list
        }, indent=2)


class KovaiAgent:
    def __init__(self):
        self.orchestrator = KovaiOrchestrator()
        self.name = "AI_Agent"

    def decide(self, state: Dict[str, Any]) -> Dict[str, Dict]:
        """Main entry point for agent decision-making."""
        return self.orchestrator.orchestrate(state)
