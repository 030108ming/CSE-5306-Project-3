# CSE 5306 Project 3 — Implementation Guide

**Team:**
- Shaoming Pan (1002340635)
- Chenchuhui Hu (1002341126)

**Base implementation:** Project 2 — Distributed Drone Telemetry System (Python + gRPC + Docker Compose).
**GitHub:** *(https://github.com/030108ming/CSE-5306-Project-3)*
---

## Overview 

This repository extends the Project 2 drone telemetry system with two consensus algorithm implementations:

- **Q1 / Q2 — Two Phase Commit (2PC):** 1 coordinator + 4 participants, full voting and decision phases with internal gRPC communication between phases on the same node.
- **Q3 / Q4 — Raft:** 5-node cluster with leader election and log replication.
- **Q5 — Raft Failure Tests:** 8 failure scenarios (5 required + 3 additional).

The original telemetry code is untouched. The consensus code runs under separate Docker Compose profiles (`twopc`, `raft`) so everything can coexist.

---

## Prerequisites

- Docker Desktop running
- `docker compose` available (v2)

Make scripts executable (run once):

```bash
chmod +x run_twopc.sh run_raft.sh run_raft_tests.sh
```

---

## Q1 & Q2 — Two Phase Commit

### Files

| File | Purpose |
|------|---------|
| `twopc.proto` | gRPC message types and service definitions |
| `src/twopc_node.py` | Coordinator + participant logic |
| `src/twopc_client.py` | External client |
| `Dockerfiles/Dockerfile.twopc` | Node image |
| `Dockerfiles/Dockerfile.twopc_client` | Client image |

### Nodes

| Container | Role | Port |
|-----------|------|------|
| `twopc-coordinator` | Coordinator | 51000 |
| `twopc-p1` | Participant | 51001 |
| `twopc-p2` | Participant | 51002 |
| `twopc-p3` | Participant | 51003 |
| `twopc-p4` | Participant | 51004 |
| `twopc-client` | External client | — |

### Run

```bash
./run_twopc.sh
```

Run with a custom operation:

```bash
./run_twopc.sh "set drone_mode=stable"
```

### Test: Abort scenario (one participant votes NO)

In `docker-compose.yml`, change `VOTE_COMMIT: "true"` to `VOTE_COMMIT: "false"` for `twopc-p1`, then:

```bash
docker compose --profile twopc up --build -d twopc-coordinator twopc-p1 twopc-p2 twopc-p3 twopc-p4
docker compose --profile twopc run --rm --no-deps twopc-client python twopc_client.py "test abort"
docker compose logs twopc-coordinator twopc-p1 twopc-p2 twopc-p3 twopc-p4
```

### View logs manually

```bash
docker compose logs twopc-coordinator twopc-p1 twopc-p2 twopc-p3 twopc-p4
```

---

## Q3 & Q4 — Raft

### Files

| File | Purpose |
|------|---------|
| `raft.proto` | gRPC message types and service definitions |
| `src/raft_node.py` | Raft node (election + log replication) |
| `src/raft_client.py` | External client (status + commands) |
| `Dockerfiles/Dockerfile.raft` | Node image |
| `Dockerfiles/Dockerfile.raft_client` | Client image |

### Nodes

| Container | Port |
|-----------|------|
| `raft1` | 52001 |
| `raft2` | 52002 |
| `raft3` | 52003 |
| `raft4` | 52004 |
| `raft5` | 52005 |

### Run

```bash
./run_raft.sh
```

### Check node status

```bash
docker compose --profile raft run --rm raft-client python raft_client.py status
```

### Send a command (log replication)

```bash
docker compose --profile raft run --rm raft-client python raft_client.py cmd "set altitude=1000"
```

### View logs

```bash
docker compose logs raft1 raft2 raft3 raft4 raft5
```

---

## Q5 — Raft Failure Tests

### Run all 8 tests

```bash
./run_raft_tests.sh
```

The script rebuilds images, then runs each test in sequence.  Each test starts a fresh cluster so tests do not affect each other.

### Test summary

| Test | Scenario | Expected Result |
|------|---------|----------------|
| 1 | Stop the leader | New leader elected; commands still commit |
| 2 | Stop 1 follower | Command commits (4 nodes alive, majority = 3) |
| 3 | Stop 2 followers | Command commits (3 nodes alive = majority) |
| 4 | Stop 3 nodes | Command fails (only 2 nodes alive, below majority) |
| 5 | Stop follower, commit entry, restart follower | Restarted node copies full log and catches up |
| 6 | Start 4 nodes, commit entries, then add 5th node | New node receives full log on first heartbeat |
| 7 | Send 5 commands back-to-back | All 5 commit in order; all logs match |
| 8 | Stop leader immediately after sending command | Baseline entry survives; cluster recovers |

### Run individual tests manually

```bash
# Start a fresh cluster
docker compose down -v --remove-orphans
docker compose --profile raft up --build -d raft1 raft2 raft3 raft4 raft5
sleep 5

# Check status
docker compose --profile raft run --rm raft-client python raft_client.py status

# Send a command
docker compose --profile raft run --rm raft-client python raft_client.py cmd "my-operation"

# Stop a specific node
docker compose stop raft2

# Restart a stopped node
docker compose start raft2
```
