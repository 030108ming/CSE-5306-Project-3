import time
import random
import grpc
from concurrent import futures

import drone_pb2
import drone_pb2_grpc


SIGNAL = "voltage"


class BatterySensor(drone_pb2_grpc.SensorServicer):
    def GetTelemetry(self, request, context):
        value = random.uniform(18.0, 25.2)

        alert = False
        message = ""

        if value < 20:
            alert = True
            message = "Battery low"

        if value < 19:
            alert = True
            message = "Battery critical"

        return drone_pb2.Telemetry(
            signal=SIGNAL,
            value=value,
            alert=alert,
            message=message,
            ts_ms=int(time.time() * 1000),
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    drone_pb2_grpc.add_SensorServicer_to_server(BatterySensor(), server)
    server.add_insecure_port("[::]:50061")
    server.start()
    print("Battery sensor running on 50061")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()