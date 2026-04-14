import time
import random
import grpc
from concurrent import futures

import drone_pb2
import drone_pb2_grpc


SIGNAL = "altitude"


class AirdataSensor(drone_pb2_grpc.SensorServicer):
    def GetTelemetry(self, request, context):
        # Simulated altitude in feet
        value = random.uniform(0.0, 12000.0)

        alert = False
        message = ""

        # Example alert condition
        if value < 50.0:
            alert = True
            message = "Altitude critically low"

        return drone_pb2.Telemetry(
            signal=SIGNAL,
            value=value,
            alert=alert,
            message=message,
            ts_ms=int(time.time() * 1000),
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    drone_pb2_grpc.add_SensorServicer_to_server(AirdataSensor(), server)
    server.add_insecure_port("[::]:50060")
    server.start()
    print("Airdata sensor running on port 50060")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()