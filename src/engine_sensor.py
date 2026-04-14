import time
import random
import grpc
from concurrent import futures

import drone_pb2
import drone_pb2_grpc

SIGNAL = "egt"


class EngineSensor(drone_pb2_grpc.SensorServicer):
    def GetTelemetry(self, request, context):
        value = random.uniform(400, 950)

        alert = False
        message = ""

        if value > 850:
            alert = True
            message = "EGT high"

        if value > 900:
            alert = True
            message = "EGT over-temp"

        return drone_pb2.Telemetry(
            signal=SIGNAL,
            value=value,
            alert=alert,
            message=message,
            ts_ms=int(time.time() * 1000),
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    drone_pb2_grpc.add_SensorServicer_to_server(EngineSensor(), server)
    server.add_insecure_port("[::]:50062")
    server.start()
    print("Engine sensor running...")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()