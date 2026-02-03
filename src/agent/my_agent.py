import math
import json
import random
import re
import requests
import os
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput  

load_dotenv()

# Pydantic Models (bulletproof JSON parsing)
class ParsedOrder(BaseModel):
    id: int
    prio: str
    mass: float
    dest: List[float]
    tick: int

class HighPriorityOrders(BaseModel):
    high_priority: List[ParsedOrder]

class Assignments(BaseModel):
    assignments: Dict[str, Dict[str, Any]]

class AuditResult(BaseModel):
    validations: Dict[str, Dict[str, Any]]

class FinalActions(BaseModel):
    actions: Dict[str, Dict[str, Any]]

class A2AMessage:
    def __init__(self, sender: str, receiver: str, method: str, params: Dict, result: Optional[Dict] = None):
        self.envelope = {
            "jsonrpc": "2.0", "sender": sender, "receiver": receiver,
            "method": method, "params": params, "id": random.randint(1000, 9999)
        }
        if result is not None:
            self.envelope["result"] = result
    def to_json(self): return json.dumps(self.envelope)

class KovaiMCPServer:
    @staticmethod
    def calculate_distance(pos1, pos2):
        return math.sqrt((pos1[0]-pos2[0])**2 + (pos1[1]-pos2[1])**2)
    
    @staticmethod
    def energy_to_target(drone_info: Dict, target_pos: tuple, reserve: float = 0.1) -> float:
        dist = KovaiMCPServer.calculate_distance(target_pos, (0,0))
        ticks = dist / drone_info['speed']
        return drone_info['discharge_rate'] * ticks * 1.1 + reserve

# PydanticAI Agents (JSON parsing FIXED)
order_analyst = Agent(
    "groq:llama-3.1-8b-instant",
    instructions=(
        "Return ONLY valid JSON matching HighPriorityOrders.\n"
        "Schema: {\"high_priority\": [{\"id\": int, \"prio\": str, \"mass\": float, \"dest\": [float,float], \"tick\": int}]}\n"
        "Extract tags from [TAG] in text. Sort by priority then request_tick. Return exactly 5 items if available.\n"
        "DO NOT add extra keys or text."
    ),
    output_type=PromptedOutput(HighPriorityOrders),
    output_retries=3
)

resource_allocator = Agent(
    "groq:llama-3.1-8b-instant",
    instructions=(
        "Return ONLY valid JSON matching Assignments.\n"
        "Schema: {\"assignments\": {\"Drone_000\": {\"order_id\": int, \"reason\": str}}}\n"
        "Keys MUST be drone names (e.g., Drone_000). Values MUST contain order_id and reason only.\n"
        "Match by capacity: Speedster≤2kg, Standard≤5kg, Heavy≤10kg. Minimize capacity waste.\n"
        "DO NOT add extra keys or text."
    ),
    output_type=PromptedOutput(Assignments),
    output_retries=3
)

safety_auditor = Agent(
    "groq:llama-3.1-8b-instant",
    instructions=(
        "Return ONLY valid JSON matching AuditResult.\n"
        "Schema: {\"validations\": {\"Drone_000\": {\"approved\": true/false, \"reason\": str}}}\n"
        "Validate battery: battery >= (dist/speed*discharge*1.1)+0.1.\n"
        "DO NOT add extra keys or text."
    ),
    output_type=PromptedOutput(AuditResult),
    output_retries=3
)

dispatcher = Agent(
    "groq:llama-3.1-8b-instant",
    instructions=(
        "Return ONLY valid JSON matching FinalActions.\n"
        "Schema: {\"actions\": {\"Drone_000\": {\"action\": \"WAIT|MOVE|PICKUP|DELIVER\", \"params\": {}}}}\n"
        "Use actions: IDLE→PICKUP→MOVE→DELIVER→RTB.\n"
        "DO NOT add extra keys or text."
    ),
    output_type=PromptedOutput(FinalActions),
    output_retries=3
)

class MultiAgentOrchestrator:
    def __init__(self, groq_key: str):
        self.mcp = KovaiMCPServer()
        self.api_key = groq_key
        self.state_memory = {}
    
    def orchestrate(self, state: Dict) -> Dict[str, Dict]:
        drones = state['drones']
        pending_orders = state['pending_orders']
        messages = []
        
        try:
            # 1. Order Analyst (PydanticAI auto-parses JSON)
            high_prio_raw = order_analyst.run_sync(
                f"Analyze {len(pending_orders)} orders: {json.dumps(pending_orders[:20])}"
            )
            high_prio: HighPriorityOrders = HighPriorityOrders.model_validate(high_prio_raw.output)
            msg1 = A2AMessage("Analyst", "Allocator", "high_priority_orders", high_prio.model_dump())
            messages.append(msg1)
            
            # 2. Resource Allocator
            available = [v for v in drones.values() if v['status']=='IDLE' and v['pos']==(0,0) and v['load']==0]
            assignments_raw = resource_allocator.run_sync(
                f"High prio ({len(high_prio.high_priority)}): {high_prio.model_dump_json()}\nAvailable ({len(available)}): {json.dumps(available[:10])}"
            )
            assignments: Assignments = Assignments.model_validate(assignments_raw.output)
            msg2 = A2AMessage("Allocator", "Auditor", "proposed_assignments", assignments.model_dump())
            messages.append(msg2)
            
            # 3. Safety Auditor
            naive_actions = {k: {"action": "MOVE", "params": {"target": (0,0)}} for k in list(drones)[:20]}
            audit_raw = safety_auditor.run_sync(
                f"Actions: {json.dumps(naive_actions)}\nDrones sample: {json.dumps(list(drones.values())[:10])}"
            )
            audit: AuditResult = AuditResult.model_validate(audit_raw.output)
            msg3 = A2AMessage("Auditor", "Dispatcher", "safety_validations", audit.model_dump())
            messages.append(msg3)
            
            # 4. Tactical Dispatcher (FINAL)
            actions_raw = dispatcher.run_sync(
                f"Assignments: {assignments.model_dump_json()}\nAudit: {audit.model_dump_json()}\nDrones: {json.dumps(list(drones.values())[:10])}\nMemory: {self.state_memory}"
            )
            final_actions: FinalActions = FinalActions.model_validate(actions_raw.output)
            actions = final_actions.actions

            # Ensure MOVE actions have a valid target
            for d_id, act in actions.items():
                if act.get("action") == "MOVE":
                    params = act.get("params") or {}
                    if params.get("target") is None:
                        params["target"] = [0, 0]
                        act["params"] = params
            
            # Update memory
            self.state_memory.update({k: v for k, v in actions.items() if 'order_id' in v.get('params', {})})
            
        except Exception as e:
            print(f"Agent fallback RTB: {e}")
            actions = {list(drones.keys())[i % len(drones)]: {"action": "MOVE", "params": {"target": (0,0)}} 
                      for i in range(min(10, len(drones)))}
        
        # A2A to Engine
        engine_msg = A2AMessage("Orchestrator", "Engine", "final_actions", {"actions": actions})
        print(json.dumps([m.to_json() for m in messages] + [engine_msg.to_json()], indent=2))
        
        return actions

class KovaiAgent:
    def __init__(self, groq_key: str = None):
        if groq_key is None:
            groq_key = os.getenv("GROQ_API_KEY", "")
        self.name = "KovaiAgent"
        self.orchestrator = MultiAgentOrchestrator(groq_key)
    
    def decide(self, state):
        return self.orchestrator.orchestrate(state)
