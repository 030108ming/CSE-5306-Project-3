import os
import sys
import time

import grpc

import twopc_pb2
import twopc_pb2_grpc


TARGET = os.environ.get("TARGET", "twopc-coordinator:51000")
COORDINATOR_ID = os.environ.get("COORDINATOR_ID", "coordinator")


def client_log(src_phase, src_node, rpc_name, dst_phase, dst_node):
    print(
        f"Phase {src_phase} of Node {src_node} sends RPC {rpc_name} "
        f"to Phase {dst_phase} of Node {dst_node}",
        flush=True,
    )


def main():
    operation = " ".join(sys.argv[1:]) or "set drone_mode=stable"
    tx_id = f"tx-{int(time.time() * 1000)}"
    channel = grpc.insecure_channel(TARGET)
    stub = twopc_pb2_grpc.TwoPCCoordinatorStub(channel)
    client_log("voting", "client", "StartTransaction", "voting", COORDINATOR_ID)
    response = stub.StartTransaction(
        twopc_pb2.TransactionRequest(transaction_id=tx_id, operation=operation),
        timeout=15,
    )
    print(f"transaction_id: {response.transaction_id}")
    print(f"committed: {response.committed}")
    print(response.summary)


if __name__ == "__main__":
    main()
