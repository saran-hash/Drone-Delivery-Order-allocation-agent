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

# -------------------- DATA MODELS --------------------

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


# -------------------- A2A MESSAGE --------------------

class A2AMessage:
    def __init__(self, sender: str, receiver: str, method: str, params: Dict, result: Optional[Dict] = None):
        self.envelope = {
            "jsonrpc": "2.0",
            "sender": sender,
            "receiver": receiver,
            "method": method,
            "params": params,
            "id": random.randint(1000, 9999)
        }
        if result is not None:
            self.envelope["result"] = result

    def to_json(self):
        return json.dumps(self.envelope)


# -------------------- MCP SERVER --------------------

class KovaiMCPServer:

    @staticmethod
    def calculate_distance(pos1, pos2):
        return math.sqrt((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2)

    @staticmethod
    def energy_to_target(drone_info: Dict, target_pos: tuple, reserve: float = 0.1) -> float:
        dist = KovaiMCPServer.calculate_distance(target_pos, (0, 0))
        ticks = dist / drone_info['speed']
        return drone_info['discharge_rate'] * ticks * 1.1 + reserve


# -------------------- AI AGENTS --------------------

order_analyst = Agent(
    "groq:llama-3.1-8b-instant",
    instructions=(
        "You are an ORDER PRIORITY ANALYSIS AGENT.\n"
        "Your job:\n"
        "- Read incoming order list\n"
        "- Identify HIGH PRIORITY orders\n"
        "- Sort by priority level and earliest tick\n"
        "- Select only the TOP 5 orders\n\n"
        "Output RULES:\n"
        "- Return ONLY valid JSON\n"
        "- Follow this schema strictly:\n"
        "{\"high_priority\": [{\"id\": int, \"prio\": str, \"mass\": float, \"dest\": [float,float], \"tick\": int}]}\n"
        "- Do NOT explain\n"
        "- Do NOT add comments\n"
        "- Do NOT add extra fields\n"
        "- Ensure numeric types remain numeric\n"
    ),
    output_type=PromptedOutput(HighPriorityOrders),
    output_retries=3
)


resource_allocator = Agent(
    "groq:llama-3.1-8b-instant",
    instructions=(
        "You are a DRONE RESOURCE ALLOCATION AGENT.\n"
        "Your job:\n"
        "- Assign drones to orders\n"
        "- Match drone capacity with package mass\n"
        "- Avoid over-allocating large drones for small packages\n\n"
        "Capacity Rules:\n"
        "Speedster \n"
        "Standard \n"
        "Heavy \n\n"
        "Optimization Goals:\n"
        "- Minimize unused capacity\n"
        "- Assign only IDLE drones\n"
        "- Each drone gets only ONE order\n\n"
        "Output RULES:\n"
        "- Return ONLY valid JSON\n"
        "- Follow schema:\n"
        "{\"assignments\": {\"Drone_000\": {\"order_id\": int, \"reason\": str}}}\n"
        "- Do NOT add extra keys\n"
        "- Do NOT include explanation outside JSON\n"
    ),
    output_type=PromptedOutput(Assignments),
    output_retries=3
)


safety_auditor = Agent(
    "groq:llama-3.1-8b-instant",
    instructions=(
        "You are a FLIGHT SAFETY VALIDATION AGENT.\n"
        "Your job:\n"
        "- Validate drone battery safety\n"
        "- Ensure drone can complete trip and return\n\n"
        "Battery Formula:\n"
        "Required = (distance / speed * discharge_rate * 1.1) + 0.1\n\n"
        "Approval Rules:\n"
        "- If battery >= required → approved = true\n"
        "- Else → approved = false\n\n"
        "Output RULES:\n"
        "- Return ONLY valid JSON\n"
        "- Follow schema:\n"
        "{\"validations\": {\"Drone_000\": {\"approved\": true/false, \"reason\": str}}}\n"
        "- Do NOT add extra text\n"
    ),
    output_type=PromptedOutput(AuditResult),
    output_retries=3
)


dispatcher = Agent(
    "groq:llama-3.1-8b-instant",
    instructions=(
        "You are a DRONE ACTION DISPATCH AGENT.\n"
        "Your job:\n"
        "- Convert assignments + safety results into real drone commands\n"
        "- Only dispatch approved drones\n\n"
        "Valid Actions:\n"
        "WAIT\n"
        "PICKUP\n"
        "MOVE\n"
        "DELIVER\n"
        "RTB\n\n"
        "Flow Rule:\n"
        "IDLE → PICKUP → MOVE → DELIVER → RTB\n\n"
        "Output RULES:\n"
        "- Return ONLY valid JSON\n"
        "- Follow schema:\n"
        "{\"actions\": {\"Drone_000\": {\"action\": \"WAIT|MOVE|PICKUP|DELIVER\", \"params\": {}}}}\n"
        "- Do NOT add explanations\n"
        "- Do NOT change action names\n"
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

            high_prio_raw = order_analyst.run_sync(
                f"Analyze {len(pending_orders)} orders: {json.dumps(pending_orders[:20])}"
            )

            high_prio = HighPriorityOrders.model_validate(high_prio_raw.output)

            msg1 = A2AMessage("Analyst", "Allocator", "high_priority_orders", high_prio.model_dump())
            messages.append(msg1)

            available = [
                v for v in drones.values()
                if v['status'] == 'IDLE' and v['pos'] == (0, 0) and v['load'] == 0
            ]

            assignments_raw = resource_allocator.run_sync(
                f"Orders: {high_prio.model_dump_json()} Available: {json.dumps(available[:10])}"
            )

            assignments = Assignments.model_validate(assignments_raw.output)

            msg2 = A2AMessage("Allocator", "Auditor", "proposed_assignments", assignments.model_dump())
            messages.append(msg2)

            naive_actions = {
                k: {"action": "MOVE", "params": {"target": (0, 0)}}
                for k in list(drones)[:20]
            }

            audit_raw = safety_auditor.run_sync(
                f"Actions: {json.dumps(naive_actions)} Drones: {json.dumps(list(drones.values())[:10])}"
            )

            audit = AuditResult.model_validate(audit_raw.output)

            msg3 = A2AMessage("Auditor", "Dispatcher", "safety_validations", audit.model_dump())
            messages.append(msg3)

            actions_raw = dispatcher.run_sync(
                f"Assignments: {assignments.model_dump_json()} "
                f"Audit: {audit.model_dump_json()} "
                f"Drones: {json.dumps(list(drones.values())[:10])} "
                f"Memory: {self.state_memory}"
            )

            final_actions = FinalActions.model_validate(actions_raw.output)
            actions = final_actions.actions

            for d_id, act in actions.items():
                if act.get("action") == "MOVE":
                    params = act.get("params") or {}
                    if params.get("target") is None:
                        params["target"] = [0, 0]
                        act["params"] = params

            self.state_memory.update({
                k: v for k, v in actions.items()
                if 'order_id' in v.get('params', {})
            })

        except Exception as e:
            print(f"Agent fallback RTB: {e}")

            actions = {
                list(drones.keys())[i % len(drones)]: {
                    "action": "MOVE",
                    "params": {"target": (0, 0)}
                }
                for i in range(min(10, len(drones)))
            }

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
