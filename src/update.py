import grpc
from concurrent import futures
import time

import drone_pb2
import drone_pb2_grpc

ANALYSIS = "analysis:50052"


class Update(drone_pb2_grpc.UpdateServicer):
    def __init__(self):
        self.analysis_channel = grpc.insecure_channel(ANALYSIS)
        self.analysis_stub = drone_pb2_grpc.AnalysisStub(self.analysis_channel)

    # Keep streaming support
    def StreamUpdate(self, request, context):
        for msg in self.analysis_stub.StreamAnalyzed(drone_pb2.Empty()):
            yield msg

    # Add command handling RPC
    def SendCommand(self, request, context):
        cmd = request.text.strip().lower()

        # Collect one batch of telemetry
        telemetry = []
        for msg in self.analysis_stub.StreamAnalyzed(drone_pb2.Empty()):
            telemetry.append(msg)
            if len(telemetry) >= 10:
                break

        if cmd == "status":
            return drone_pb2.Reply(text="System online.")

        if cmd == "health":
            alerts = [m for m in telemetry if m.alert]
            if alerts:
                return drone_pb2.Reply(text="⚠ Alerts present.")
            return drone_pb2.Reply(text="All systems nominal.")

        if cmd == "list":
            names = sorted(set(m.signal for m in telemetry))
            return drone_pb2.Reply(text="\n".join(names))

        if cmd.startswith("sensor "):
            parts = cmd.split()
            if len(parts) != 2:
                return drone_pb2.Reply(text="Usage: sensor <name>")

            name = parts[1]
            for m in telemetry:
                if m.signal == name:
                    return drone_pb2.Reply(text=f"{name}: {m.value:.2f}")

            return drone_pb2.Reply(text=f"Sensor '{name}' not found.")

        if cmd == "alerts":
            alerts = [f"{m.signal}: {m.message}" for m in telemetry if m.alert]
            if alerts:
                return drone_pb2.Reply(text="\n".join(alerts))
            return drone_pb2.Reply(text="No active alerts.")

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

        return drone_pb2.Reply(text="Unknown command.")


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    drone_pb2_grpc.add_UpdateServicer_to_server(Update(), server)
    server.add_insecure_port("[::]:50054")
    server.start()
    print("Update running...")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()