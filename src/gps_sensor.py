import time
import random
import grpc
from concurrent import futures

import drone_pb2
import drone_pb2_grpc

SIGNAL = "latitude"


class GPSSensor(drone_pb2_grpc.SensorServicer):
    def GetTelemetry(self, request, context):
        value = random.uniform(-90, 90)

        alert = False
        message = ""

        if abs(value) > 89.5:
            alert = True
            message = "GPS near boundary"

        return drone_pb2.Telemetry(
            signal=SIGNAL,
            value=value,
            alert=alert,
            message=message,
            ts_ms=int(time.time() * 1000),
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    drone_pb2_grpc.add_SensorServicer_to_server(GPSSensor(), server)
    server.add_insecure_port("[::]:50063")
    server.start()
    print("GPS sensor running...")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()