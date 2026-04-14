# CSE 5306 Project 3 Report — Consensus Algorithms: 2PC and Raft

**Course:** CSE 5306 — Distributed Systems  
**GitHub:** *([insert your GitHub link here](https://github.com/030108ming/CSE-5306-Project-3))*

---

## Team Members

| Name | Student ID | Contribution |
|------|-----------|--------------|
| Shaoming Pan | 1002340635 | Raft implementation (Q3, Q4, Q5), Docker setup, test scripts |
| Chenchuhui Hu | 1002341126 | 2PC implementation (Q1, Q2), proto file design, Docker setup |

---

## Base Implementation

We extended Project 2 implementation: a distributed drone telemetry system (Python + gRPC + Docker Compose). The consensus modules (2PC and Raft) are added as independent Docker Compose profiles (`twopc` and `raft`) so the original telemetry system remains unchanged.

---

## Q1 & Q2 — Two Phase Commit (2PC)

### Architecture

One coordinator and four participants run in separate containers.  Each node runs the same `twopc_node.py` binary but with different environment variables that set its role (`ROLE=coordinator` or `ROLE=participant`).

The protocol is split into two phases that communicate via gRPC on `localhost`, satisfying the requirement that the two phases could be implemented in different languages.

### gRPC Services (`twopc.proto`)

| Service | Methods | Purpose |
|---------|---------|---------|
| `TwoPCCoordinator` | `StartTransaction` | Client triggers a transaction on the coordinator |
| `TwoPCParticipant` | `VoteRequest`, `GlobalDecision` | Cross-node voting and decision delivery |
| `TwoPCPhase` | `MakeDecision`, `ApplyDecision` | Internal same-node communication between phases |

### Voting Phase (Q1)

1. Client calls `StartTransaction` on the coordinator.
2. Coordinator sends `VoteRequest` to all 4 participants.
3. Each participant returns `vote_commit=true` (ready) or `vote_commit=false` (abort).
4. If any RPC fails, the coordinator treats it as a vote-abort.

### Decision Phase (Q2)

5. Coordinator calls `MakeDecision` on `localhost` (internal gRPC), passing all collected votes.
6. Decision phase checks: if all votes are `true` → global commit; if any is `false` → global abort.
7. Coordinator broadcasts `GlobalDecision` to all participants.
8. Each participant calls `ApplyDecision` on `localhost` to record the final state.

### RPC Logging

Every RPC is printed on both sides in the required format:

```
# Client (sender) side:
Phase voting of Node coordinator sends RPC VoteRequest to Phase voting of Node p1

# Server (receiver) side:
Phase voting of Node p1 sends RPC VoteRequest to Phase voting of Node coordinator
```

### Screenshot 1 — Successful Commit (all participants vote YES)

*(Insert terminal screenshot here)*

Expected output:
- Coordinator prints `VoteRequest` to each participant
- All 4 participants reply `vote_commit=True`
- Coordinator prints `GlobalDecision` (commit=True) to each participant
- All 4 participants print `committed`

### Screenshot 2 — Abort (one participant votes NO)

*(Insert terminal screenshot here)*

Expected output:
- Coordinator prints `VoteRequest` to each participant
- `p1` replies `vote_commit=False`
- Coordinator prints `GlobalDecision` (commit=False) to each participant
- All participants print `aborted`

---

## Q3 — Raft Leader Election

### Timeout Settings

| Setting | Value |
|---------|-------|
| Heartbeat interval | 1 second (fixed, all nodes) |
| Election timeout | Random [1.5 s, 3.0 s] (per-node, re-randomized each election) |

Heartbeat is always shorter than the minimum election timeout, so a healthy leader prevents unnecessary elections.

### Election Protocol

1. All 5 nodes start as **followers**.
2. A follower that does not receive an `AppendEntries` heartbeat within its timeout becomes a **candidate**.
3. The candidate increments its term, votes for itself, and sends `RequestVote` to all peers.
4. A peer grants a vote if it has not voted for anyone else in this term.
5. If the candidate receives ≥ 3 votes (majority of 5), it becomes the **leader**.
6. The leader sends `AppendEntries` heartbeats every 1 second to all other nodes.
7. If a node receives a message with a higher term, it immediately steps down to follower.

Randomized election timeout prevents split votes: the node with the shortest timeout almost always wins uncontested before others time out.

### RPC Logging

```
# Sender side:
Node raft1 sends RPC RequestVote to Node raft2

# Receiver side:
Node raft2 runs RPC RequestVote called by Node raft1
```

### Screenshot 3 — Leader Election

*(Insert terminal screenshot here)*

Expected output:
- Multiple nodes showing `Node X starts election for term N`
- Winner showing `Node X becomes leader for term N with 3 votes`
- Status output showing one node as `leader`, others as `follower`

---

## Q4 — Raft Log Replication

### Protocol

1. Client sends `ClientCommand` to any node.
2. If the receiver is not the leader, it forwards the request directly to the known leader.
3. Leader creates a new log entry: `{index, term, operation}` and appends it locally.
4. Leader sends its **entire log** plus current `commit_index` to all followers via `AppendEntries`.
5. Each follower replaces its log with the leader's log and returns an ACK.
6. When leader receives ACKs from ≥ 3 nodes (including itself), it commits.
7. Leader applies committed entries to its state machine.
8. Leader sends another `AppendEntries` round so followers update their `commit_index` and apply entries.

### Log Entry Format

```
{index: 1, term: 1, operation: "set altitude=1000"}
```

- `index`: 1-based position in the log
- `term`: which leader term this entry was added in
- `operation`: the actual command string from the client

### Screenshot 4 — Log Replication

*(Insert terminal screenshot here)*

Expected output:
- Non-leader node receives command and forwards to leader
- Leader prints `Leader raftX appended {index:1, term:1, operation:...}`
- Leader prints `AppendEntries` RPC logs to each follower
- Leader prints `committed index 1 with 4 ACKs`
- Status shows all nodes with matching `log_length` and `commit_index`

### Screenshot 5 — Full Status Output

*(Insert `raft_client.py status` terminal screenshot here)*

Expected output:
```
raft1: state=leader term=2 leader=raft1 log=3 commit=3
  applied index=1 term=2 op=set altitude=1000
  applied index=2 term=2 op=set speed=50
  applied index=3 term=2 op=set mode=auto
raft2: state=follower term=2 leader=raft1 log=3 commit=3
  ...
```

---

## Q5 — Raft Failure Tests

All 8 tests are in `run_raft_tests.sh`.  Each test starts a fresh cluster.

### Test 1: Leader Failure Triggers New Election

Stop the current leader.  The 4 remaining nodes hold an election and a new leader is chosen.

**Demonstrates:** Raft's availability under leader crash.  The cluster remains operational as long as a majority (3 of 5) of nodes are alive.

*(Insert screenshot)*

---

### Test 2: One Follower Failure Still Allows Commit

Stop 1 follower.  Send a command.

**Demonstrates:** With 4 alive nodes, the leader still gets 3 ACKs (majority) and commits.

*(Insert screenshot)*

---

### Test 3: Two Follower Failures Still Allow Commit

Stop 2 followers.  Send a command.

**Demonstrates:** 3 alive nodes = exactly the majority threshold.  Cluster is still functional.

*(Insert screenshot)*

---

### Test 4: Majority Loss Prevents Commit

Stop 3 of 5 nodes.  Send a command.

**Demonstrates:** With only 2 alive nodes, no majority is reachable.  The command fails.  This is Raft's availability limit — it sacrifices availability to preserve safety (no incorrect commits).

*(Insert screenshot)*

---

### Test 5: Restarted Node Catches Up

Stop one follower, commit an entry, then restart the follower.

**Demonstrates:** The rejoined node receives the leader's full log on the next heartbeat and catches up to the same state as the rest of the cluster.

*(Insert screenshot — show the restarted node's log_length matching the others)*

---

### Test 6: New Node Joining the Cluster

Start 4 nodes, commit 2 entries, then start the 5th node which has an empty log.

**Demonstrates:** The assignment specifically lists "a new node entering the system" as a test case.  Raft handles this with no special protocol — the first heartbeat the new node receives contains the full log, and it replicates immediately.

*(Insert screenshot — show raft5's log catching up after joining)*

---

### Test 7: Rapid Successive Commands

Send 5 commands back-to-back without delay.

**Demonstrates:** The leader correctly serializes entries, log indices increment monotonically, and no entries are lost or duplicated under rapid load.

*(Insert screenshot — show all 5 entries in all nodes' state machine)*

---

### Test 8: Leader Failure Mid-Replication

Commit a baseline entry, then fire a second command and immediately kill the leader.

**Demonstrates:** Raft's safety guarantee — only entries replicated to a majority survive a leadership change.  The baseline (which was committed) always survives.  The in-flight entry may be lost if it did not reach a majority before the crash.  The cluster recovers and accepts new commands from the new leader.

*(Insert screenshot — show baseline entry present, new leader elected, recovery command committing)*

---

## Design Decisions

### Why use internal gRPC for same-node 2PC phase communication?

The requirement states that the voting and decision phases should be separable.  Using `TwoPCPhase` gRPC on `localhost:{PORT}` means the two phases are decoupled at the protocol level and could be written in different languages (Go, Java, etc.) without changing the interface.

### Why send the entire Raft log every AppendEntries?

The assignment specifies the simplified variant.  Full Raft finds the divergence point and only sends the diff, which is efficient for large logs.  Our simplified approach is functionally correct and much simpler to implement and verify.

### Why is election timeout randomized?

If all nodes used the same timeout they would all start elections simultaneously, producing a split vote loop.  Randomization ensures one node almost always wins before others time out.

### Majority = (N // 2) + 1

For 5 nodes, majority = 3.  This means the cluster tolerates up to 2 node failures while remaining fully operational.

---

## External References

1. Ongaro & Ousterhout, "In Search of an Understandable Consensus Algorithm," USENIX ATC 2014. https://raft.github.io/raft.pdf
2. Tanenbaum & Van Steen, *Distributed Systems: Principles and Paradigms*, Section 8.5 (2PC).
3. gRPC Python documentation. https://grpc.io/docs/languages/python/
4. Protocol Buffers Language Guide (proto3). https://protobuf.dev/programming-guides/proto3/
5. The Secret Lives of Data — Raft visualization. https://thesecretlivesofdata.com/raft/
