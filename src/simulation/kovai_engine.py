import math
import random

class Drone:
    def __init__(self, name, capacity, battery, speed, discharge_rate):
        self.name = name
        self.capacity = capacity # kg
        self.current_load = 0 # kg
        self.battery = battery # 0 to 100%
        self.position = (0, 0) # Start at Hub
        self.speed = speed # grid units per tick
        self.discharge_rate = discharge_rate # battery % per grid unit
        self.status = "IDLE" # IDLE, IN_TRANSIT, CHARGING, CRASHED
        self.target_order = None

    def move_towards(self, target):
        if self.battery <= 0:
            self.status = "CRASHED"
            return "CRASHED"
        
        x1, y1 = self.position
        x2, y2 = target
        dx, dy = x2 - x1, y2 - y1
        distance = math.sqrt(dx**2 + dy**2)
        
        if distance <= self.speed:
            self.position = target
            self.battery -= distance * self.discharge_rate
            return "ARRIVED"
        else:
            move_x = (dx / distance) * self.speed
            move_y = (dy / distance) * self.speed
            self.position = (x1 + move_x, y1 + move_y)
            self.battery -= self.speed * self.discharge_rate
            return "IN_TRANSIT"

    def charge(self):
        if self.position == (0, 0):
            self.battery = min(100, self.battery + 10) # Charge 10% per tick
            self.status = "CHARGING" if self.battery < 100 else "IDLE"
            return True
        return False

class KovaiSim:
    def __init__(self, fleet_config=None):
        self.drones = {}
        if fleet_config:
            for d in fleet_config:
                self.drones[d['name']] = Drone(
                    d['name'], d['capacity'], 100, d['speed'], d['discharge_rate']
                )
        else:
            # Default fallback
            self.drones = {
                "Speedster": Drone("Speedster", 2, 100, 3, 2),
                "Heavy": Drone("Heavy", 10, 100, 1, 5),
                "Standard": Drone("Standard", 5, 100, 2, 3)
            }
        
        self.orders = []
        self.completed_orders = []
        self.time_step = 0
        self.weather = "CLEAR"
        self.total_battery_used = 0
        self.total_distance = 0

    def get_state(self):
        return {
            "time": self.time_step,
            "weather": self.weather,
            "drones": {name: {
                "pos": d.position, 
                "bat": round(d.battery, 1), 
                "load": d.current_load,
                "capacity": d.capacity,
                "status": d.status,
                "speed": d.speed,
                "discharge": d.discharge_rate
            } for name, d in self.drones.items()},
            "pending_orders": [o for o in self.orders if o["status"] == "PENDING"],
            "stats": {
                "battery_used": round(self.total_battery_used, 2),
                "distance_traveled": round(self.total_distance, 2),
                "deliveries": len(self.completed_orders)
            }
        }

    def inject_order(self, order_text, mass, destination):
        self.orders.append({
            "id": random.randint(1000, 9999), 
            "text": order_text, 
            "mass": mass,
            "destination": destination,
            "status": "PENDING"
        })

    def process_action(self, drone_id, action, params):
        drone = self.drones.get(drone_id)
        if not drone or drone.status == "CRASHED": return
        
        if action == "MOVE":
            target = params.get("target") # (x, y)
            old_pos = drone.position
            old_bat = drone.battery
            res = drone.move_towards(target)
            
            # Update stats
            self.total_distance += math.dist(old_pos, drone.position)
            self.total_battery_used += (old_bat - drone.battery)
            
            drone.status = "IN_TRANSIT" if res == "IN_TRANSIT" else "IDLE"
        elif action == "CHARGE":
            drone.charge()
        elif action == "PICKUP":
            order_id = params.get("order_id")
            order = next((o for o in self.orders if o["id"] == order_id), None)
            if order and order["status"] == "PENDING" and drone.position == (0, 0) and (drone.current_load + order["mass"] <= drone.capacity):
                drone.current_load += order["mass"]
                order["status"] = "PICKED_UP"
                order["drone"] = drone_id
                print(f"📦 [Engine] {drone_id} picked up order {order_id} ({order['mass']}kg)")
        elif action == "DELIVER":
            # Check if drone is at delivery location of its orders
            for order in self.orders:
                if order["status"] == "PICKED_UP" and order["drone"] == drone_id:
                    if math.dist(drone.position, order["destination"]) < 0.1:
                        drone.current_load -= order["mass"]
                        order["status"] = "DELIVERED"
                        self.completed_orders.append(order)

    def step(self, actions=None):
        self.time_step += 1
        
        # Apply actions
        if actions:
            for drone_id, act_data in actions.items():
                self.process_action(drone_id, act_data["action"], act_data.get("params", {}))
        
        # Random weather changes
        if random.random() < 0.1:
            self.weather = random.choice(["CLEAR", "WINDY", "STORMY"])
            
        return self.get_state()
