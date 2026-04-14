import os
import time
from concurrent import futures

import grpc

import twopc_pb2
import twopc_pb2_grpc


NODE_ID = os.environ.get("NODE_ID", "node")
ROLE = os.environ.get("ROLE", "participant")
PORT = int(os.environ.get("PORT", "51000"))
PARTICIPANTS = [
    item.strip()
    for item in os.environ.get("PARTICIPANTS", "").split(",")
    if item.strip()
]
VOTE_COMMIT = os.environ.get("VOTE_COMMIT", "true").lower() == "true"


def client_log(src_phase, src_node, rpc_name, dst_phase, dst_node):
    print(
        f"Phase {src_phase} of Node {src_node} sends RPC {rpc_name} "
        f"to Phase {dst_phase} of Node {dst_node}",
        flush=True,
    )


def server_log(dst_phase, dst_node, rpc_name, src_phase, src_node):
    print(
        f"Phase {dst_phase} of Node {dst_node} sends RPC {rpc_name} "
        f"to Phase {src_phase} of Node {src_node}",
        flush=True,
    )


class ParticipantService(twopc_pb2_grpc.TwoPCParticipantServicer):
    def __init__(self):
        self.prepared = {}
        self.decisions = {}

    def VoteRequest(self, request, context):
        server_log("voting", NODE_ID, "VoteRequest", "voting", request.coordinator_id)
        if VOTE_COMMIT:
            self.prepared[request.transaction_id] = request.operation
            return twopc_pb2.VoteReply(
                transaction_id=request.transaction_id,
                participant_id=NODE_ID,
                vote_commit=True,
                reason="prepared",
            )

        return twopc_pb2.VoteReply(
            transaction_id=request.transaction_id,
            participant_id=NODE_ID,
            vote_commit=False,
            reason="configured to abort for failure testing",
        )

    def GlobalDecision(self, request, context):
        server_log("decision", NODE_ID, "GlobalDecision", "decision", request.coordinator_id)
        operation = self.prepared.pop(request.transaction_id, "")
        phase_stub = twopc_pb2_grpc.TwoPCPhaseStub(grpc.insecure_channel(f"localhost:{PORT}"))
        client_log("decision", NODE_ID, "ApplyDecision", "decision", NODE_ID)
        return phase_stub.ApplyDecision(
            twopc_pb2.InternalApplyDecisionRequest(
                transaction_id=request.transaction_id,
                participant_id=NODE_ID,
                commit=request.commit,
                reason=request.reason,
                operation=operation,
            ),
            timeout=5,
        )


class PhaseService(twopc_pb2_grpc.TwoPCPhaseServicer):
    def __init__(self, participant_service):
        self.participant_service = participant_service

    def MakeDecision(self, request, context):
        server_log("decision", NODE_ID, "MakeDecision", "voting", request.coordinator_id)
        should_commit = bool(request.votes) and all(vote.vote_commit for vote in request.votes)
        abort_reasons = [
            f"{vote.participant_id}: {vote.reason}"
            for vote in request.votes
            if not vote.vote_commit
        ]
        reason = "all participants voted commit" if should_commit else "; ".join(abort_reasons)
        return twopc_pb2.GlobalDecisionMessage(
            transaction_id=request.transaction_id,
            coordinator_id=NODE_ID,
            commit=should_commit,
            reason=reason,
        )

    def ApplyDecision(self, request, context):
        server_log("decision", NODE_ID, "ApplyDecision", "decision", request.participant_id)
        status = "committed" if request.commit else "aborted"
        self.participant_service.decisions[request.transaction_id] = status
        if request.commit:
            print(
                f"Participant {NODE_ID} commits transaction {request.transaction_id}: {request.operation}",
                flush=True,
            )
        else:
            print(
                f"Participant {NODE_ID} aborts transaction {request.transaction_id}: {request.reason}",
                flush=True,
            )
        return twopc_pb2.DecisionAck(
            transaction_id=request.transaction_id,
            participant_id=NODE_ID,
            status=status,
        )


class CoordinatorService(twopc_pb2_grpc.TwoPCCoordinatorServicer):
    def __init__(self):
        self.participant_stubs = {}
        for item in PARTICIPANTS:
            node_id, address = item.split("=", 1)
            channel = grpc.insecure_channel(address)
            self.participant_stubs[node_id] = twopc_pb2_grpc.TwoPCParticipantStub(channel)

    def StartTransaction(self, request, context):
        server_log("voting", NODE_ID, "StartTransaction", "voting", "client")
        transaction_id = request.transaction_id or f"tx-{int(time.time() * 1000)}"
        print(
            f"Coordinator {NODE_ID} starts transaction {transaction_id}: {request.operation}",
            flush=True,
        )

        votes = []
        for participant_id, stub in self.participant_stubs.items():
            try:
                client_log("voting", NODE_ID, "VoteRequest", "voting", participant_id)
                vote = stub.VoteRequest(
                    twopc_pb2.VoteRequestMessage(
                        transaction_id=transaction_id,
                        operation=request.operation,
                        coordinator_id=NODE_ID,
                    ),
                    timeout=5,
                )
                votes.append(vote)
            except grpc.RpcError as exc:
                votes.append(
                    twopc_pb2.VoteReply(
                        transaction_id=transaction_id,
                        participant_id=participant_id,
                        vote_commit=False,
                        reason=f"RPC failure: {exc.code().name}",
                    )
                )

        phase_stub = twopc_pb2_grpc.TwoPCPhaseStub(grpc.insecure_channel(f"localhost:{PORT}"))
        client_log("voting", NODE_ID, "MakeDecision", "decision", NODE_ID)
        decision = phase_stub.MakeDecision(
            twopc_pb2.InternalDecisionRequest(
                transaction_id=transaction_id,
                coordinator_id=NODE_ID,
                votes=votes,
            ),
            timeout=5,
        )
        should_commit = decision.commit
        reason = decision.reason

        acks = []
        for participant_id, stub in self.participant_stubs.items():
            try:
                client_log("decision", NODE_ID, "GlobalDecision", "decision", participant_id)
                ack = stub.GlobalDecision(
                    decision,
                    timeout=5,
                )
                acks.append(f"{ack.participant_id}:{ack.status}")
            except grpc.RpcError as exc:
                acks.append(f"{participant_id}:ack-failed-{exc.code().name}")

        summary = (
            f"decision={'COMMIT' if should_commit else 'ABORT'}; "
            f"reason={reason}; acks={', '.join(acks)}"
        )
        print(f"Coordinator {NODE_ID} finished {transaction_id}: {summary}", flush=True)
        return twopc_pb2.TransactionResult(
            transaction_id=transaction_id,
            committed=should_commit,
            summary=summary,
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    participant_service = ParticipantService()
    twopc_pb2_grpc.add_TwoPCParticipantServicer_to_server(participant_service, server)
    twopc_pb2_grpc.add_TwoPCPhaseServicer_to_server(PhaseService(participant_service), server)
    if ROLE == "coordinator":
        twopc_pb2_grpc.add_TwoPCCoordinatorServicer_to_server(CoordinatorService(), server)
    server.add_insecure_port(f"[::]:{PORT}")
    server.start()
    print(f"2PC {ROLE} {NODE_ID} running on {PORT}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
