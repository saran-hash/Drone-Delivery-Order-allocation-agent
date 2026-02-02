import time
import csv
import argparse
from src.simulation.kovai_engine import KovaiSim
from src.agent.my_agent import KovaiAgent

def load_fleet(path):
    fleet = []
    with open(path, mode='r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            fleet.append({
                "name": row['name'],
                "type": row['type'],
                "capacity": float(row['capacity']),
                "speed": float(row['speed']),
                "discharge_rate": float(row['discharge_rate'])
            })
    return fleet

def load_orders(path):
    orders = []
    with open(path, mode='r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            orders.append({
                "id": int(row['order_id']),
                "text": row['description'],
                "mass": float(row['mass']),
                "dest": (float(row['x']), float(row['y'])),
                "tick": int(row['request_tick'])
            })
    return orders



def main():
    parser = argparse.ArgumentParser(description="KovaiDelivery Mission Runner")
    parser.add_argument("--fleet", type=str, default="data/fleet.csv", help="Path to fleet CSV")
    parser.add_argument("--orders", type=str, default="data/orders.csv", help="Path to orders CSV")
    args = parser.parse_args()

    print(f"🚀 Initializing KovaiDelivery: Enterprise Edition...")
    
    # Load configurations
    fleet_config = load_fleet(args.fleet)
    all_orders = load_orders(args.orders)
    
    sim = KovaiSim(fleet_config=fleet_config)
    agent = KovaiAgent()

    print(f"--- Mission Started: Agent {agent.name} controlling {len(fleet_config)} drones ---")

    try:
        max_ticks = 5
        for t in range(max_ticks):
            # Inject orders scheduled for this tick
            for order in all_orders:
                if order['tick'] == t:
                    sim.inject_order(order['text'], order['mass'], order['dest'])

            state = sim.get_state()
            
            # Print periodic summary
            if t % 10 == 0:
                print(f"\n[Tick {t}] Weather: {state['weather']}")
                print(f"  Active Drones: {sum(1 for d in state['drones'].values() if d['status'] != 'CRASHED')}/{len(fleet_config)}")
                print(f"  Deliveries: {state['stats']['deliveries']}/{len(all_orders)}")
                print(f"  Stats: Dist={state['stats']['distance_traveled']} Battery={state['stats']['battery_used']}%")

            # Agent decides
            actions = agent.decide(state)
            
            # Tick the simulation
            state = sim.step(actions=actions)

            if state['stats']['deliveries'] == len(all_orders) and all(d['load'] == 0 for d in state['drones'].values()):
                print(f"\n✅ SUCCESS: All {len(all_orders)} orders fulfilled in {t} ticks!")
                break
                
            if any(d['status'] == 'CRASHED' for d in state['drones'].values()):
                # Only print crash once per drone if possible, but for simplicity:
                pass

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nSimulation terminated by user.")

    print("\n--- Final Mission Report ---")
    final_state = sim.get_state()
    print(f"Total Deliveries: {final_state['stats']['deliveries']}")
    print(f"Total Distance: {final_state['stats']['distance_traveled']}")
    print(f"Total Battery Used: {final_state['stats']['battery_used']}%")
    print(f"Efficiency Score: {round(final_state['stats']['distance_traveled'] / max(1, final_state['stats']['battery_used']), 2)} km/%")

if __name__ == "__main__":
    main()
