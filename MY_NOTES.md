# My Personal Notes — Code Logic, Deep Understanding, Demo Guide

This file is NOT for submission.  It is just for me (Shaoming) to fully understand every piece of code, be ready for the demo, and answer any question a professor asks.

---

## PART 1 — Understanding 2PC Code

### The Big Picture First

Think of 2PC like this:
- You are the **coordinator** (the manager).
- You have 4 **participants** (team members).
- You want everyone to save a new file at the same time.
- You ask everyone: "Can you save it?" → This is the **voting phase**.
- If ALL say YES → you tell everyone "Save it now" → This is the **decision phase**.
- If even ONE says NO → you tell everyone "Cancel it".

Why? Because you never want a situation where 3 people saved and 1 didn't.  Either everyone does it or nobody does.

---

### `twopc.proto` — Understanding the Messages

```
TransactionRequest      → client sends this to coordinator to start everything
VoteRequestMessage      → coordinator sends this to each participant: "please vote"
VoteReply               → participant sends this back: "I vote YES or NO"
GlobalDecisionMessage   → coordinator sends this to all: "final answer: commit or abort"
DecisionAck             → participant confirms it applied the decision
```

The two "Internal" messages are special:
```
InternalDecisionRequest      → voting phase code talks to decision phase code (same machine)
InternalApplyDecisionRequest → decision phase receives GlobalDecision, then tells itself to apply it
```

Why do voting and decision phase talk to each other via gRPC even though they are on the same machine?  
→ The assignment says these two phases must be able to run in different programming languages.  gRPC is the only way two different languages can talk.  Even on the same machine, gRPC works (it just uses localhost).

---

### `twopc_node.py` — Line by Line Logic

#### Environment variables at the top

```python
NODE_ID = os.environ.get("NODE_ID", "node")    # e.g. "coordinator", "p1", "p2"...
ROLE = os.environ.get("ROLE", "participant")    # either "coordinator" or "participant"
PORT = int(os.environ.get("PORT", "51000"))     # which port this node listens on
PARTICIPANTS = [...]                             # coordinator only: list of all participant addresses
VOTE_COMMIT = ...                               # participant only: should I vote YES or NO?
```

The same Python file runs on ALL containers.  The environment variables (set in docker-compose.yml) tell each container what role it plays.  This is a common pattern in Docker microservices.

#### Logging functions

```python
def client_log(src_phase, src_node, rpc_name, dst_phase, dst_node):
    # prints: "Phase voting of Node coordinator sends RPC VoteRequest to Phase voting of Node p1"
    
def server_log(dst_phase, dst_node, rpc_name, src_phase, src_node):
    # prints: "Phase voting of Node p1 sends RPC VoteRequest to Phase voting of Node coordinator"
```

Important: the print format looks the same for both sides.  The assignment asks for a specific format.  Both functions produce the same format string — the only difference is which node is calling it (client side = before making the call, server side = when receiving the call).

#### `ParticipantService.VoteRequest` — what happens when a participant gets asked to vote

```python
def VoteRequest(self, request, context):
    server_log(...)     # print that I received this RPC
    if VOTE_COMMIT:
        self.prepared[request.transaction_id] = request.operation  # remember this transaction
        return VoteReply(vote_commit=True, reason="prepared")
    else:
        return VoteReply(vote_commit=False, reason="configured to abort")
```

`self.prepared` is like a holding area.  When I vote YES, I "hold" the operation but don't do it yet.  I am waiting for the final decision.  If the final decision is COMMIT, I apply it.  If ABORT, I discard it.

#### `ParticipantService.GlobalDecision` — receiving the final decision

```python
def GlobalDecision(self, request, context):
    server_log(...)     # print that I received this RPC
    operation = self.prepared.pop(request.transaction_id, "")   # take the held operation out
    phase_stub = TwoPCPhaseStub(grpc.insecure_channel(f"localhost:{PORT}"))   # talk to myself
    client_log("decision", NODE_ID, "ApplyDecision", "decision", NODE_ID)     # print the internal call
    return phase_stub.ApplyDecision(...)    # forward to my own decision phase service
```

This is the internal gRPC call.  The participant receives a GlobalDecision from the coordinator, then calls its own `ApplyDecision` on localhost.  This is like the participant's voting phase part saying "hey decision phase part, you handle the actual apply."

#### `PhaseService.MakeDecision` — the coordinator's voting phase asking decision phase what to do

```python
def MakeDecision(self, request, context):
    server_log(...)     # print received
    should_commit = bool(request.votes) and all(vote.vote_commit for vote in request.votes)
    # all() returns True only if EVERY vote is True
    # bool(request.votes) makes sure there are actually votes (empty list would commit wrongly)
    reason = "all participants voted commit" if should_commit else "someone voted abort"
    return GlobalDecisionMessage(commit=should_commit, reason=reason)
```

This is the brain of the decision.  `all(vote.vote_commit for vote in request.votes)` checks every vote in the list.  If any one of them is False, `all()` returns False immediately → ABORT.

#### `CoordinatorService.StartTransaction` — the full flow on the coordinator

Step 1: Generate transaction ID
```python
transaction_id = request.transaction_id or f"tx-{int(time.time() * 1000)}"
```
Uses timestamp as a unique ID if the client didn't provide one.

Step 2: Voting phase — ask every participant
```python
for participant_id, stub in self.participant_stubs.items():
    try:
        client_log(...)                      # print I'm about to call VoteRequest
        vote = stub.VoteRequest(...)         # actually call it, timeout=5 seconds
        votes.append(vote)
    except grpc.RpcError as exc:
        votes.append(VoteReply(vote_commit=False, reason=f"RPC failure: {exc.code().name}"))
        # If the participant is unreachable → treat it as voting ABORT
```

Step 3: Call internal MakeDecision
```python
phase_stub = TwoPCPhaseStub(grpc.insecure_channel(f"localhost:{PORT}"))
client_log("voting", NODE_ID, "MakeDecision", "decision", NODE_ID)  # print internal call
decision = phase_stub.MakeDecision(...)     # get back the global decision
```

Step 4: Broadcast the decision
```python
for participant_id, stub in self.participant_stubs.items():
    client_log("decision", NODE_ID, "GlobalDecision", "decision", participant_id)
    ack = stub.GlobalDecision(decision, timeout=5)
```

#### `serve()` — how the server starts up

```python
server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
participant_service = ParticipantService()
twopc_pb2_grpc.add_TwoPCParticipantServicer_to_server(participant_service, server)
twopc_pb2_grpc.add_TwoPCPhaseServicer_to_server(PhaseService(participant_service), server)
if ROLE == "coordinator":
    twopc_pb2_grpc.add_TwoPCCoordinatorServicer_to_server(CoordinatorService(), server)
server.add_insecure_port(f"[::]:{PORT}")
server.start()
```

All three services run on the SAME port.  gRPC uses the service name in the message to route to the right handler.  The coordinator container has all three; participant containers only register the first two.

---

## PART 2 — Understanding Raft Code

### The Big Picture First

Think of Raft like a company with a president (leader) and employees (followers):
- There is always exactly one president at a time.
- Only the president accepts orders from clients.
- The president records every order in a logbook and tells all employees to copy it.
- If the president disappears, employees hold a vote to elect a new one.
- A new employee who just joined gets a copy of the full logbook from the president.

The key guarantee: every node has the SAME ordered list of operations.  Even if some nodes crash and restart, they all catch up and agree on the same history.

---

### `raft.proto` — Understanding the Messages

```
RequestVoteRequest     → candidate → others: "vote for me for term T"
RequestVoteReply       → others → candidate: "yes" or "no"

AppendEntriesRequest   → leader → followers: "here is my log + heartbeat"
AppendEntriesReply     → followers → leader: "got it / rejected"

ClientCommandRequest   → client → any node: "please do this operation"
ClientCommandReply     → node → client: success/fail + who is leader

StatusRequest/Reply    → for debugging: see all node states
```

What is a **term**?  
A term is a counter that goes up every time an election starts.  Term 1 = first leader.  Term 2 = after the first leader dies and a new one is elected, etc.  Every message carries the sender's current term.  If you receive a message with a higher term than yours, you immediately know there is a newer world out there, and you step down/update.

What is a **LogEntry**?
```
{index: 3, term: 2, operation: "set altitude=500"}
```
- index: position in the log (starts at 1, never decreases)
- term: which term this entry was added by a leader
- operation: the actual command

What is **commit_index**?
The highest index that has been replicated to a majority.  Only committed entries are guaranteed to survive.

---

### `raft_node.py` — Line by Line Logic

#### Constants

```python
HEARTBEAT_INTERVAL_SECONDS = 1.0          # leader sends heartbeat every 1 second
ELECTION_TIMEOUT_MIN_SECONDS = 1.5        # I wait at least 1.5 seconds before starting election
ELECTION_TIMEOUT_MAX_SECONDS = 3.0        # I wait at most 3 seconds before starting election
```

Why heartbeat < min election timeout?  
If a leader is alive, it sends a heartbeat every 1 second.  My election timeout is at least 1.5 seconds.  So a healthy leader ALWAYS resets my timer before I start an unnecessary election.

#### `__init__` — what each node stores

```python
self.state = "follower"       # everyone starts as follower
self.current_term = 0         # term starts at 0
self.voted_for = ""           # I haven't voted for anyone yet
self.leader_id = ""           # I don't know who the leader is yet
self.log = []                 # empty log at start
self.commit_index = 0         # nothing committed yet
self.last_applied = 0         # nothing applied to state machine yet
self.state_machine = []       # the list of "executed" operations
self.election_deadline = self._new_election_deadline()  # random 1.5-3 seconds from now
```

`self.peers` = all other nodes (not me)  
`self.stubs` = gRPC client objects for each peer (pre-created so we don't reconnect every time)  
`self.majority = (len(self.peers) + 1) // 2 + 1` = for 5 nodes: (4+1)//2 + 1 = 3

#### `_new_election_deadline` — why randomness matters

```python
def _new_election_deadline(self):
    return time.time() + random.uniform(1.5, 3.0)
```

Returns a random moment between 1.5 and 3 seconds from now.  This is reset every time we hear from a leader (reset election timer) or start a new election.

Why random?  If all 5 nodes had the same timeout of 2.0 seconds, they would ALL start elections at exactly 2.0 seconds, each voting for themselves → nobody gets 3 votes → nobody wins → repeat forever.  Randomness means one node (the one with, say, 1.5s timeout) starts first, wins, and sends heartbeats to prevent others from even starting.

#### `RequestVote` — the vote handler

```python
def RequestVote(self, request, context):
    rpc_server_log(...)   # print I received this RPC
    with self.lock:
        if request.term < self.current_term:
            return RequestVoteReply(vote_granted=False)  # reject stale candidate
        
        if request.term > self.current_term:
            self._become_follower(request.term)  # update to the new term, reset voted_for
        
        vote_available = self.voted_for in ("", request.candidate_id)
        # "" means I haven't voted yet this term
        # request.candidate_id means I already voted for this same candidate (idempotent)
        
        vote_granted = vote_available and request.term == self.current_term
        if vote_granted:
            self.voted_for = request.candidate_id
            self._reset_election_timeout()   # don't start my own election if someone just won
```

Key rule: **each node votes only ONCE per term**, on a first-come-first-served basis.

#### `AppendEntries` — the heartbeat + log sync handler

```python
def AppendEntries(self, request, context):
    rpc_server_log(...)   # print I received this RPC
    with self.lock:
        if request.term < self.current_term:
            return AppendEntriesReply(success=False)  # reject stale leader
        
        self._become_follower(request.term, request.leader_id)  # accept this leader
        self._copy_entries_from_rpc(request.entries)            # replace my log with leader's log
        self.commit_index = min(request.commit_index, len(self.log))  # update commit index
        self._apply_committed_entries()                         # execute newly committed entries
```

The simplified Raft approach: just replace the entire log.  This is safe because the leader always has the correct log (Raft's election ensures the winner has the most up-to-date log).

`_become_follower` resets the election timer every time.  This is why the leader's heartbeat keeps everyone from starting unnecessary elections.

#### `ClientCommand` — what happens when a client sends a request

```python
def ClientCommand(self, request, context):
    rpc_server_log(...)
    
    with self.lock:
        if self.state != "leader":
            leader_id = self.leader_id
            leader_stub = self.stubs.get(leader_id)
            if not leader_id or not leader_stub:
                return ClientCommandReply(success=False, result="leader unknown")
    
    if self.state != "leader":
        # forward to the actual leader
        rpc_client_log(NODE_ID, "ClientCommand", leader_id)
        return leader_stub.ClientCommand(request, timeout=10)
```

If I am not the leader, I look up who the leader is (`self.leader_id`, which I learned from the last AppendEntries I received) and forward the request.  The client has no idea the forwarding happened.

```python
    with self.lock:
        entry = {"index": len(self.log) + 1, "term": self.current_term, "operation": request.operation}
        self.log.append(entry)
    
    ack_count = 1   # count myself as 1 ACK
    for peer_id in self.stubs:
        if self._replicate_to_peer(peer_id):
            ack_count += 1
    
    if ack_count >= self.majority:
        with self.lock:
            self.commit_index = len(self.log)
            self._apply_committed_entries()
        # send another round to update followers' commit_index
        for peer_id in self.stubs:
            self._replicate_to_peer(peer_id)
        return ClientCommandReply(success=True, result=self.state_machine[-1])
```

I count myself as 1 ACK, then ask each peer.  If I get 3+ (including myself) I commit.

#### `start_election` — the candidate logic

```python
def start_election(self):
    with self.lock:
        self.state = "candidate"
        self.current_term += 1           # increment term: this is MY election
        self.voted_for = NODE_ID         # vote for myself
        self.leader_id = ""              # there is no leader right now
        self._reset_election_timeout()   # give myself time to collect votes
    
    votes = 1   # my own vote
    for peer_id, stub in self.stubs.items():
        try:
            rpc_client_log(NODE_ID, "RequestVote", peer_id)
            reply = stub.RequestVote(RequestVoteRequest(term=term, candidate_id=NODE_ID), timeout=2)
        except grpc.RpcError:
            continue  # peer unreachable → no vote, but that's OK
        
        with self.lock:
            if reply.term > self.current_term:
                self._become_follower(reply.term)  # I found out someone has a higher term → step down
                return
        
        if reply.vote_granted:
            votes += 1
    
    with self.lock:
        if self.state == "candidate" and self.current_term == term and votes >= self.majority:
            self.state = "leader"
            self.leader_id = NODE_ID
```

The check `self.current_term == term` is critical.  What if while I was collecting votes, another node started a higher-term election and I stepped down?  My term would now be different from the `term` I started with.  This check prevents claiming leadership in the wrong term.

#### `election_loop` — background thread that watches for timeout

```python
def election_loop(self):
    while True:
        time.sleep(0.05)   # check every 50ms
        with self.lock:
            should_start = self.state != "leader" and time.time() >= self.election_deadline
        if should_start:
            self.start_election()
```

Every 50ms it checks: "am I a non-leader whose deadline has passed?"  If yes, start an election.  The 50ms polling interval means we react within 50ms of the deadline.

#### `heartbeat_loop` — background thread for the leader

```python
def heartbeat_loop(self):
    while True:
        time.sleep(1.0)   # every 1 second
        with self.lock:
            is_leader = self.state == "leader"
        if is_leader:
            for peer_id in self.stubs:
                self._replicate_to_peer(peer_id)   # send full log to every peer
```

The leader calls `_replicate_to_peer` which sends `AppendEntries` with the full log.  Even if there are no new entries, this resets the followers' election timers.

#### Why `threading.RLock` instead of `Lock`?

`RLock` = "re-entrant lock."  It allows the SAME thread to acquire the lock multiple times without deadlocking.  Normal `Lock` would deadlock if a function that holds the lock calls another function that also tries to acquire the lock.  Here, some methods call `_become_follower` while already holding the lock.

---

## PART 3 — How to Demo

### 2PC Demo Script

**Show normal commit:**

1. Open terminal. Run:
```bash
./run_twopc.sh "update flight_plan=route-A"
```

2. Point out in the logs:
   - "Phase voting of Node coordinator sends RPC VoteRequest to Phase voting of Node p1" (and p2, p3, p4)
   - Each participant: "Phase voting of Node p1 sends RPC VoteRequest to Phase voting of Node coordinator" (server side)
   - "Phase voting of Node coordinator sends RPC MakeDecision to Phase decision of Node coordinator" (internal)
   - "Phase decision of Node coordinator sends RPC GlobalDecision to Phase decision of Node p1" etc.
   - Final: "Participant p1 commits transaction tx-xxx: update flight_plan=route-A"
   - Last line: `committed: True`

**Show abort:**

1. In docker-compose.yml, change `twopc-p1`'s `VOTE_COMMIT: "true"` to `VOTE_COMMIT: "false"`
2. Run:
```bash
docker compose --profile twopc up --build -d twopc-coordinator twopc-p1 twopc-p2 twopc-p3 twopc-p4
docker compose --profile twopc run --rm --no-deps twopc-client python twopc_client.py "update flight_plan=route-A"
docker compose logs twopc-coordinator twopc-p1
```
3. Point out: p1 returns `vote_commit: False` → coordinator decides ABORT → all participants abort.

**What to say:** "2PC is atomic: if any single participant votes NO, the entire transaction is aborted everywhere. No node is left in an inconsistent state."

---

### Raft Demo Script

**Show leader election:**

1. Run:
```bash
./run_raft.sh
```
2. Watch the logs. Point out:
   - "Node raft3 starts election for term 1" (first timeout)
   - "Node raft3 sends RPC RequestVote to Node raft1" (and raft2, raft4, raft5)
   - "Node raft1 runs RPC RequestVote called by Node raft3"
   - "Node raft3 becomes leader for term 1 with 3 votes" (or more)
3. Run status:
```bash
docker compose --profile raft run --rm raft-client python raft_client.py status
```
Point out: exactly one node is `state=leader`, others are `state=follower`.  All followers show the same `leader=raftX`.

**Show log replication:**

```bash
docker compose --profile raft run --rm raft-client python raft_client.py cmd "set altitude=1000"
```
Point out:
- "Node raft3 sends RPC AppendEntries to Node raft1" (and others)
- "Leader raft3 committed index 1 with 4 ACKs"
- Run status again: all nodes show `log=1 commit=1` and the state machine entry

**Show forwarding (send to non-leader):**

If raft3 is the leader, manually send to raft1:
```bash
docker exec -it <raft1-container-id> python raft_client.py cmd "set speed=50"
```
Or just note that `raft_client.py` tries all nodes and the non-leader will forward.

**Show failure tests:**

```bash
./run_raft_tests.sh
```

Point out for Test 1:
- Old leader stopped
- New node times out, starts election, wins
- New command commits on the new leader

Point out for Test 4:
- 3 nodes stopped
- Command fails → "not enough ACKs"
- This shows safety: the system refuses to commit when it can't be sure

Point out for Test 5:
- Follower down, entry committed
- Follower restarted → status shows it caught up to the same log_length

---

## PART 4 — Likely Professor Questions and Exact Answers

**Q: What if the coordinator in 2PC crashes after sending VoteRequest but before sending GlobalDecision?**

A: This is the classic "2PC blocking problem." The participants voted YES and are holding the transaction but do not know if they should commit or abort. They are stuck until the coordinator recovers. Our implementation does not handle this because it requires persistent storage (write-ahead log). In production systems, the coordinator writes its decision to disk before broadcasting, so it can recover and resume.

**Q: What stops two nodes from both becoming leaders in Raft?**

A: Two things. First, majority voting: to become leader, a candidate needs more than half of all votes (3 out of 5). Two candidates cannot both get 3 votes from the same 5-node pool. Second, term numbers: if two candidates start elections, one will be in a higher term (the one that started later). Any node that already voted for the lower-term candidate will reject the higher-term candidate's RequestVote if it already voted, but accept it if the term is higher and update its own term. Raft's proof shows only one leader per term is possible.

**Q: What is the difference between commit and apply in Raft?**

A: Commit means the entry is durably replicated on a majority — it is guaranteed to survive any future leader change. Apply means the state machine has actually executed the operation. commit_index tracks what is committed; last_applied tracks what is applied. Normally they are equal, but there is a brief moment after a new heartbeat updates commit_index where the apply loop has not run yet.

**Q: Why does Raft use majority (more than half) instead of all?**

A: Using all would mean a single node failure makes the cluster unavailable. Majority allows the cluster to keep working even when some nodes fail. The math: if you need ACKs from k out of n nodes, you can tolerate n-k failures. For majority (k = n/2 + 1), you can tolerate n/2 failures. For 5 nodes: tolerate 2 failures.

**Q: In your simplified Raft, the leader sends the entire log every time. Why is this not done in real Raft?**

A: In production, if the log grows to millions of entries, sending the entire log every heartbeat would be very expensive (bandwidth, serialization time). Real Raft tracks for each follower what is the highest log index it already has (`nextIndex` per follower), and only sends entries after that index. The simplified approach in this assignment is functionally correct but not scalable.

**Q: What happens if a Raft follower receives AppendEntries from an old leader (stale leader)?**

A: The follower checks `request.term < self.current_term`. If the sender's term is lower than the follower's current term, the follower rejects it and returns its own (higher) term in the reply. The old leader sees the higher term in the reply and calls `_become_follower`, stepping down immediately. This guarantees at most one active leader per term.

**Q: What does your state machine do?**

A: Our state machine is a simple list of strings. Every committed log entry is "applied" by appending a string like `"applied index=1 term=2 op=set altitude=1000"` to the list. In a real database, the state machine would execute the SQL operation or key-value update. We kept it simple to focus on the consensus logic rather than the application logic.

**Q: How does a client find the leader in Raft?**

A: The client tries nodes in order. If a node is not the leader, it returns the leader's ID in the reply (`leader_id` field). The client then retries directly with the leader. If the leader is unknown (during election), the client sleeps 2 seconds and retries up to 5 times.

**Q: What is the split-brain problem and how does Raft prevent it?**

A: Split-brain means two nodes both think they are the leader and both accept writes, causing inconsistency. Raft prevents this with majority quorums. A new leader can only be elected if it gets more than half of all votes. The old leader (if it is partitioned away) can only commit entries if it gets ACKs from more than half of all nodes. Since the new leader took the majority, the old leader cannot reach a majority on the other side. So there can never be two leaders both making progress simultaneously.
