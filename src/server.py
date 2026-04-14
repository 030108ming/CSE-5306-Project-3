import grpc
from concurrent import futures

import drone_pb2
import drone_pb2_grpc


class ServerService(drone_pb2_grpc.ServerServicer):
    def __init__(self):
        # Connect to Update service
        self.channel = grpc.insecure_channel("update:50054")
        self.stub = drone_pb2_grpc.UpdateStub(self.channel)

    def SendCommand(self, request, context):
        cmd = request.text.strip().lower()

        # Local commands handled by Server only
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

        # All other commands are forwarded to Update service
        try:
            response = self.stub.SendCommand(
                drone_pb2.Command(text=cmd)
            )
            return response
        except Exception as e:
            return drone_pb2.Reply(
                text=f"Error communicating with update service: {str(e)}"
            )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    drone_pb2_grpc.add_ServerServicer_to_server(ServerService(), server)
    server.add_insecure_port("[::]:50053")
    server.start()
    print("Server running on 50053")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()