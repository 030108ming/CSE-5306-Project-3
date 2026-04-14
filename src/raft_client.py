import os
import sys
import time

import grpc

import raft_pb2
import raft_pb2_grpc


def parse_cluster(raw_cluster):
    cluster = {}
    for item in raw_cluster.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            node_id, address = item.split("=", 1)
        else:
            node_id, address = item.split(":", 1)
            address = f"{node_id}:{address}"
        cluster[node_id] = address
    return cluster


CLUSTER = parse_cluster(
    os.environ.get(
        "CLUSTER",
        "raft1=raft1:52001,raft2=raft2:52002,raft3=raft3:52003,raft4=raft4:52004,raft5=raft5:52005",
    )
)


def stub_for(address):
    return raft_pb2_grpc.RaftStub(grpc.insecure_channel(address))


def rpc_client_log(src_node, rpc_name, dst_node):
    print(f"Node {src_node} sends RPC {rpc_name} to Node {dst_node}", flush=True)


def status():
    for node_id, address in sorted(CLUSTER.items()):
        try:
            rpc_client_log("client", "GetStatus", node_id)
            reply = stub_for(address).GetStatus(raft_pb2.StatusRequest(), timeout=2)
            print(
                f"{reply.node_id}: state={reply.state} term={reply.term} "
                f"leader={reply.leader_id or '-'} log={reply.log_length} "
                f"commit={reply.commit_index}"
            )
            for applied in reply.state_machine:
                print(f"  {applied}")
        except grpc.RpcError as exc:
            print(f"{node_id}: unavailable ({exc.code().name})")


def command(operation):
    last_result = "no response"
    for attempt in range(1, 6):
        tried = set()
        preferred = []
        for node_id, address in sorted(CLUSTER.items()):
            if node_id in tried:
                continue
            tried.add(node_id)
            try:
                rpc_client_log("client", "ClientCommand", node_id)
                reply = stub_for(address).ClientCommand(
                    raft_pb2.ClientCommandRequest(operation=operation),
                    timeout=15,
                )
                print(
                    f"attempt={attempt} sent_to={node_id} success={reply.success} "
                    f"leader={reply.leader_id or '-'} result={reply.result}"
                )
                last_result = reply.result
                if reply.success:
                    return
                if reply.leader_id and reply.leader_id in CLUSTER and reply.leader_id not in tried:
                    preferred.append(reply.leader_id)
            except grpc.RpcError as exc:
                last_result = exc.code().name
                continue

            for leader_id in preferred:
                tried.add(leader_id)
                try:
                    rpc_client_log("client", "ClientCommand", leader_id)
                    leader_reply = stub_for(CLUSTER[leader_id]).ClientCommand(
                        raft_pb2.ClientCommandRequest(operation=operation),
                        timeout=15,
                    )
                    print(
                        f"attempt={attempt} sent_to={leader_id} success={leader_reply.success} "
                        f"leader={leader_reply.leader_id or '-'} result={leader_reply.result}"
                    )
                    last_result = leader_reply.result
                    if leader_reply.success:
                        return
                except grpc.RpcError as exc:
                    last_result = exc.code().name
                    continue

        time.sleep(2)

    print(f"No reachable Raft node accepted the command. Last result: {last_result}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "status":
        status()
        return

    if sys.argv[1] == "cmd":
        operation = " ".join(sys.argv[2:]) or "set drone_mode=stable"
        command(operation)
        return

    print("Usage:")
    print("  python raft_client.py status")
    print("  python raft_client.py cmd <operation>")


if __name__ == "__main__":
    main()
