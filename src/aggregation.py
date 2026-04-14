import time
import grpc
from concurrent import futures

import drone_pb2
import drone_pb2_grpc

SENSORS = [
    "airdata:50060",
    "battery:50061",
    "engine:50062",
    "gps:50063",
    "imu:50064",
]


class Aggregation(drone_pb2_grpc.AggregationServicer):
    def StreamTelemetry(self, request, context):
        stubs = []
        for addr in SENSORS:
            ch = grpc.insecure_channel(addr)
            stubs.append(drone_pb2_grpc.SensorStub(ch))

        while context.is_active():
            for stub in stubs:
                try:
                    msg = stub.GetTelemetry(drone_pb2.Empty(), timeout=2)
                    yield msg
                except grpc.RpcError:
                    pass
            time.sleep(1)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    drone_pb2_grpc.add_AggregationServicer_to_server(Aggregation(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    print("Aggregation running...")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()