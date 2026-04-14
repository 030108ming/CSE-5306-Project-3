import grpc
from concurrent import futures

import drone_pb2
import drone_pb2_grpc

AGG = "aggregation:50051"


class Analysis(drone_pb2_grpc.AnalysisServicer):
    def StreamAnalyzed(self, request, context):
        ch = grpc.insecure_channel(AGG)
        stub = drone_pb2_grpc.AggregationStub(ch)

        for msg in stub.StreamTelemetry(drone_pb2.Empty()):
            yield msg


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    drone_pb2_grpc.add_AnalysisServicer_to_server(Analysis(), server)
    server.add_insecure_port("[::]:50052")
    server.start()
    print("Analysis running...")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()