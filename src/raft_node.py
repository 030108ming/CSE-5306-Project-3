import os
import random
import threading
import time
from concurrent import futures

import grpc

import raft_pb2
import raft_pb2_grpc


NODE_ID = os.environ.get("NODE_ID", "raft1")
PORT = int(os.environ.get("PORT", "52001"))
CLUSTER = [
    item.strip()
    for item in os.environ.get("CLUSTER", "").split(",")
    if item.strip()
]
HEARTBEAT_INTERVAL_SECONDS = 1.0
ELECTION_TIMEOUT_MIN_SECONDS = 1.5
ELECTION_TIMEOUT_MAX_SECONDS = 3.0


def rpc_client_log(src_node, rpc_name, dst_node):
    print(f"Node {src_node} sends RPC {rpc_name} to Node {dst_node}", flush=True)


def rpc_server_log(dst_node, rpc_name, src_node):
    print(f"Node {dst_node} runs RPC {rpc_name} called by Node {src_node}", flush=True)


class RaftNode(raft_pb2_grpc.RaftServicer):
    def __init__(self):
        self.lock = threading.RLock()
        self.peers = {}
        for item in CLUSTER:
            node_id, address = item.split("=", 1)
            if node_id != NODE_ID:
                self.peers[node_id] = address

        self.stubs = {
            node_id: raft_pb2_grpc.RaftStub(grpc.insecure_channel(address))
            for node_id, address in self.peers.items()
        }
        self.majority = (len(self.peers) + 1) // 2 + 1

        self.state = "follower"
        self.current_term = 0
        self.voted_for = ""
        self.leader_id = ""
        self.log = []
        self.commit_index = 0
        self.last_applied = 0
        self.state_machine = []
        self.election_deadline = self._new_election_deadline()

    def _new_election_deadline(self):
        return time.time() + random.uniform(
            ELECTION_TIMEOUT_MIN_SECONDS, ELECTION_TIMEOUT_MAX_SECONDS
        )

    def _reset_election_timeout(self):
        self.election_deadline = self._new_election_deadline()

    def _entries_for_rpc(self):
        return [
            raft_pb2.LogEntry(
                index=entry["index"],
                term=entry["term"],
                operation=entry["operation"],
            )
            for entry in self.log
        ]

    def _copy_entries_from_rpc(self, entries):
        self.log = [
            {"index": entry.index, "term": entry.term, "operation": entry.operation}
            for entry in entries
        ]

    def _apply_committed_entries(self):
        while self.last_applied < self.commit_index and self.last_applied < len(self.log):
            entry = self.log[self.last_applied]
            self.state_machine.append(
                f"applied index={entry['index']} term={entry['term']} op={entry['operation']}"
            )
            self.last_applied += 1

    def _become_follower(self, term, leader_id=""):
        old_state = self.state
        if term > self.current_term:
            self.current_term = term
            self.voted_for = ""
            self.leader_id = leader_id
        self.state = "follower"
        if leader_id:
            self.leader_id = leader_id
        elif old_state in ("leader", "candidate") and self.leader_id == NODE_ID:
            self.leader_id = ""
        self._reset_election_timeout()

    def RequestVote(self, request, context):
        rpc_server_log(NODE_ID, "RequestVote", request.candidate_id)
        with self.lock:
            if request.term < self.current_term:
                return raft_pb2.RequestVoteReply(
                    term=self.current_term, vote_granted=False, voter_id=NODE_ID
                )

            if request.term > self.current_term:
                self._become_follower(request.term)

            vote_available = self.voted_for in ("", request.candidate_id)
            vote_granted = vote_available and request.term == self.current_term
            if vote_granted:
                self.voted_for = request.candidate_id
                self._reset_election_timeout()

            return raft_pb2.RequestVoteReply(
                term=self.current_term,
                vote_granted=vote_granted,
                voter_id=NODE_ID,
            )

    def AppendEntries(self, request, context):
        rpc_server_log(NODE_ID, "AppendEntries", request.leader_id)
        with self.lock:
            if request.term < self.current_term:
                return raft_pb2.AppendEntriesReply(
                    term=self.current_term,
                    success=False,
                    follower_id=NODE_ID,
                    match_index=len(self.log),
                )

            self._become_follower(request.term, request.leader_id)
            self._copy_entries_from_rpc(request.entries)
            self.commit_index = min(request.commit_index, len(self.log))
            self._apply_committed_entries()

            return raft_pb2.AppendEntriesReply(
                term=self.current_term,
                success=True,
                follower_id=NODE_ID,
                match_index=len(self.log),
            )

    def ClientCommand(self, request, context):
        caller = "client"
        rpc_server_log(NODE_ID, "ClientCommand", caller)

        with self.lock:
            if self.state != "leader":
                leader_id = self.leader_id
                leader_stub = self.stubs.get(leader_id)
                if not leader_id or not leader_stub:
                    return raft_pb2.ClientCommandReply(
                        success=False,
                        leader_id=leader_id,
                        result=f"Node {NODE_ID} is {self.state}; leader unknown",
                    )

        if self.state != "leader":
            try:
                rpc_client_log(NODE_ID, "ClientCommand", leader_id)
                return leader_stub.ClientCommand(request, timeout=10)
            except grpc.RpcError as exc:
                return raft_pb2.ClientCommandReply(
                    success=False,
                    leader_id=leader_id,
                    result=f"forward to leader failed: {exc.code().name}",
                )

        with self.lock:
            entry = {
                "index": len(self.log) + 1,
                "term": self.current_term,
                "operation": request.operation,
            }
            self.log.append(entry)
            print(f"Leader {NODE_ID} appended {entry}", flush=True)

        ack_count = 1
        for peer_id in self.stubs:
            if self._replicate_to_peer(peer_id):
                ack_count += 1

        if ack_count >= self.majority:
            with self.lock:
                self.commit_index = len(self.log)
                self._apply_committed_entries()
                result = self.state_machine[-1] if self.state_machine else "no-op"
            print(
                f"Leader {NODE_ID} committed index {self.commit_index} with {ack_count} ACKs",
                flush=True,
            )
            for peer_id in self.stubs:
                self._replicate_to_peer(peer_id)
            return raft_pb2.ClientCommandReply(
                success=True,
                leader_id=NODE_ID,
                result=result,
            )

        return raft_pb2.ClientCommandReply(
            success=False,
            leader_id=NODE_ID,
            result=f"not enough ACKs: {ack_count}/{self.majority}",
        )

    def GetStatus(self, request, context):
        rpc_server_log(NODE_ID, "GetStatus", "client")
        with self.lock:
            return raft_pb2.StatusReply(
                node_id=NODE_ID,
                state=self.state,
                term=self.current_term,
                leader_id=self.leader_id,
                log_length=len(self.log),
                commit_index=self.commit_index,
                state_machine=list(self.state_machine),
            )

    def _replicate_to_peer(self, peer_id):
        with self.lock:
            term = self.current_term
            leader_id = NODE_ID
            entries = self._entries_for_rpc()
            commit_index = self.commit_index
        try:
            rpc_client_log(NODE_ID, "AppendEntries", peer_id)
            reply = self.stubs[peer_id].AppendEntries(
                raft_pb2.AppendEntriesRequest(
                    term=term,
                    leader_id=leader_id,
                    entries=entries,
                    commit_index=commit_index,
                ),
                timeout=2,
            )
        except grpc.RpcError:
            return False

        with self.lock:
            if reply.term > self.current_term:
                self._become_follower(reply.term)
                return False
        return reply.success

    def election_loop(self):
        while True:
            time.sleep(0.05)
            with self.lock:
                should_start = self.state != "leader" and time.time() >= self.election_deadline
            if should_start:
                self.start_election()

    def start_election(self):
        with self.lock:
            self.state = "candidate"
            self.current_term += 1
            term = self.current_term
            self.voted_for = NODE_ID
            self.leader_id = ""
            self._reset_election_timeout()
            print(f"Node {NODE_ID} starts election for term {term}", flush=True)

        votes = 1
        for peer_id, stub in self.stubs.items():
            try:
                rpc_client_log(NODE_ID, "RequestVote", peer_id)
                reply = stub.RequestVote(
                    raft_pb2.RequestVoteRequest(term=term, candidate_id=NODE_ID),
                    timeout=2,
                )
            except grpc.RpcError:
                continue

            with self.lock:
                if reply.term > self.current_term:
                    self._become_follower(reply.term)
                    return
            if reply.vote_granted:
                votes += 1

        with self.lock:
            if self.state == "candidate" and self.current_term == term and votes >= self.majority:
                self.state = "leader"
                self.leader_id = NODE_ID
                print(
                    f"Node {NODE_ID} becomes leader for term {term} with {votes} votes",
                    flush=True,
                )
            elif self.state == "candidate" and self.current_term == term:
                print(
                    f"Node {NODE_ID} election failed for term {term}: {votes} votes",
                    flush=True,
                )
                self.state = "follower"
                self.leader_id = ""
                self._reset_election_timeout()

    def heartbeat_loop(self):
        while True:
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)
            with self.lock:
                is_leader = self.state == "leader"
            if is_leader:
                for peer_id in self.stubs:
                    self._replicate_to_peer(peer_id)


def serve():
    node = RaftNode()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=32))
    raft_pb2_grpc.add_RaftServicer_to_server(node, server)
    server.add_insecure_port(f"[::]:{PORT}")
    server.start()
    print(f"Raft node {NODE_ID} running on {PORT}", flush=True)

    threading.Thread(target=node.election_loop, daemon=True).start()
    threading.Thread(target=node.heartbeat_loop, daemon=True).start()

    server.wait_for_termination()


if __name__ == "__main__":
    serve()
