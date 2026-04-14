import time
import random
import grpc
from concurrent import futures

import drone_pb2
import drone_pb2_grpc

SIGNAL = "vibration"


class IMUSensor(drone_pb2_grpc.SensorServicer):
    def GetTelemetry(self, request, context):
        value = random.uniform(0, 10)

        alert = False
        message = ""

        if value > 7.5:
            alert = True
            message = "Vibration high"

        if value > 9:
            alert = True
            message = "Vibration severe"

        return drone_pb2.Telemetry(
            signal=SIGNAL,
            value=value,
            alert=alert,
            message=message,
            ts_ms=int(time.time() * 1000),
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    drone_pb2_grpc.add_SensorServicer_to_server(IMUSensor(), server)
    server.add_insecure_port("[::]:50064")
    server.start()
    print("IMU sensor running...")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()