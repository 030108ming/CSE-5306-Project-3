import time
import random
import threading
from concurrent import futures

import grpc
import drone_pb2
import drone_pb2_grpc


# ==============================
# MONOLITH INTERNAL STATE
# ==============================

SENSOR_NAMES = [
    "altitude",
    "airspeed",
    "voltage",
    "egt",
    "latitude",
    "longitude",
    "vibration",
]

THRESHOLDS = {
    "altitude": 50.0,
    "airspeed": 10.0,
    "voltage": 20.0,
    "egt": 720.0,
    "vibration": 8.0,
}


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.values = {name: 0.0 for name in SENSOR_NAMES}
        self.alerts = {}
        self.start_time = time.time()


STATE = State()


# ==============================
# TELEMETRY GENERATOR
# ==============================

def rand_value(name):
    if name == "altitude":
        return random.uniform(0.0, 300.0)
    if name == "airspeed":
        return random.uniform(0.0, 120.0)
    if name == "voltage":
        return random.uniform(16.0, 28.0)
    if name == "egt":
        return random.uniform(600.0, 800.0)
    if name == "latitude":
        return random.uniform(-90.0, 90.0)
    if name == "longitude":
        return random.uniform(-180.0, 180.0)
    if name == "vibration":
        return random.uniform(0.0, 10.0)
    return 0.0


def telemetry_loop():
    while True:
        with STATE.lock:
            for name in SENSOR_NAMES:
                val = rand_value(name)
                STATE.values[name] = val

                if name in THRESHOLDS:
                    thr = THRESHOLDS[name]

                    if name in ("altitude", "airspeed", "voltage"):
                        # low threshold
                        if val < thr:
                            STATE.alerts[name] = f"{name}: LOW ({val:.2f})"
                        else:
                            STATE.alerts.pop(name, None)
                    else:
                        # high threshold
                        if val > thr:
                            STATE.alerts[name] = f"{name}: HIGH ({val:.2f})"
                        else:
                            STATE.alerts.pop(name, None)

        time.sleep(0.05)


# ==============================
# gRPC SERVICE (MATCHES server.py)
# ==============================

class ServerService(drone_pb2_grpc.ServerServicer):

    def SendCommand(self, request, context):
        cmd = request.text.strip().lower()

        if cmd == "help":
            return drone_pb2.Reply(text=
                "Available commands:\n"
                "  help\n"
                "  status\n"
                "  health\n"
                "  list\n"
                "  sensor <name>\n"
                "  alerts\n"
                "  quit"
            )

        if cmd == "quit":
            return drone_pb2.Reply(text="Exiting client.")

        if cmd == "status":
            with STATE.lock:
                uptime = time.time() - STATE.start_time
            return drone_pb2.Reply(text=f"Operational (uptime {uptime:.1f}s)")

        if cmd == "health":
            with STATE.lock:
                if not STATE.alerts:
                    return drone_pb2.Reply(text="Health: OK")
                return drone_pb2.Reply(text=f"Health: DEGRADED ({len(STATE.alerts)} alerts)")

        if cmd == "list":
            return drone_pb2.Reply(text="\n".join(SENSOR_NAMES))

        if cmd.startswith("sensor "):
            name = cmd.split(" ", 1)[1].strip()
            with STATE.lock:
                if name not in STATE.values:
                    return drone_pb2.Reply(text=f"Unknown sensor: {name}")
                value = STATE.values[name]
                alert = STATE.alerts.get(name)

            if alert:
                return drone_pb2.Reply(text=f"{name}: {value:.2f} (ALERT)")
            return drone_pb2.Reply(text=f"{name}: {value:.2f}")

        if cmd == "alerts":
            with STATE.lock:
                if not STATE.alerts:
                    return drone_pb2.Reply(text="No active alerts.")
                return drone_pb2.Reply(text="\n".join(STATE.alerts.values()))

        return drone_pb2.Reply(text=f"Unknown command: {cmd}")


# ==============================
# SERVER BOOTSTRAP
# ==============================

def serve():
    t = threading.Thread(target=telemetry_loop, daemon=True)
    t.start()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    drone_pb2_grpc.add_ServerServicer_to_server(ServerService(), server)

    server.add_insecure_port("[::]:50053")
    server.start()

    print("Monolith running on port 50053")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()