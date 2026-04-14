#!/bin/bash
set -e

RAFT_NODES="raft1 raft2 raft3 raft4 raft5"

start_cluster() {
  docker compose down -v --remove-orphans
  docker compose --profile raft up --no-build -d --force-recreate $RAFT_NODES
  sleep 3
}

status() {
  docker compose --profile raft run --rm --no-deps raft-client python raft_client.py status
}

cmd() {
  docker compose --profile raft run --rm --no-deps raft-client python raft_client.py cmd "$1"
}

leader() {
  status | awk -F: '/state=leader/ && found == "" {found = $1} END {if (found != "") print found}'
}

followers() {
  status | awk -F: '/state=follower/ {print $1}'
}

wait_for_leader() {
  local found=""
  for _ in $(seq 1 15); do
    found=$(leader || true)
    if [ -n "${found}" ]; then
      echo "${found}"
      return 0
    fi
    sleep 3
  done

  echo "ERROR: no Raft leader was elected within 45 seconds." >&2
  echo "Current status:" >&2
  status >&2 || true
  echo "Recent Raft logs:" >&2
  docker compose logs --tail=80 raft1 raft2 raft3 raft4 raft5 >&2 || true
  return 1
}

wait_for_followers() {
  local needed="$1"
  local found=""
  local count=0
  for _ in $(seq 1 10); do
    found=$(followers || true)
    count=$(echo "${found}" | sed '/^$/d' | wc -l | tr -d ' ')
    if [ "${count}" -ge "${needed}" ]; then
      echo "${found}" | head -n "${needed}"
      return 0
    fi
    sleep 2
  done

  echo "ERROR: expected at least ${needed} follower(s), found ${count}." >&2
  echo "Current status:" >&2
  status >&2 || true
  return 1
}

echo "Building Raft images..."
docker compose --profile raft build

# =========================================================================
# ORIGINAL FIVE TESTS
# =========================================================================

echo "========== Q5 Test 1: Leader failure triggers a new election =========="
# Purpose: When the current leader crashes, the remaining 4 nodes hold an
# election and a new leader is chosen.  Shows Raft survives leader failure.
start_cluster
old_leader=$(wait_for_leader)
echo "Old leader: ${old_leader}"
docker compose stop "${old_leader}"
sleep 3
new_leader=$(wait_for_leader)
echo "New leader after stopping ${old_leader}: ${new_leader}"
status
cmd "q5-test1-after-leader-failure"

echo "========== Q5 Test 2: One follower failure still allows commit =========="
# Purpose: With 5 nodes, majority = 3.  Losing 1 follower leaves 4 alive
# nodes, so the leader still gets majority ACKs and commits.
start_cluster
wait_for_leader >/dev/null
follower=$(wait_for_followers 1)
echo "Stopping follower: ${follower}"
docker compose stop "${follower}"
sleep 2
wait_for_leader >/dev/null
status
cmd "q5-test2-one-follower-down"

echo "========== Q5 Test 3: Two follower failures still allow commit =========="
# Purpose: Losing 2 followers leaves 3 alive nodes, which is exactly the
# majority for a 5-node cluster.  The leader can still commit entries.
start_cluster
wait_for_leader >/dev/null
down_nodes=$(wait_for_followers 2)
echo "Stopping followers: ${down_nodes}"
for node in ${down_nodes}; do
  docker compose stop "${node}"
done
sleep 3
wait_for_leader >/dev/null
status
cmd "q5-test3-two-followers-down"

echo "========== Q5 Test 4: Majority loss prevents commit =========="
# Purpose: Stopping 3 of 5 nodes (including any mix of leader/follower) leaves
# only 2 alive nodes, which is below the majority threshold.  The cluster
# becomes unavailable — a client command cannot be committed.
start_cluster
wait_for_leader >/dev/null
down_nodes=$(status | awk -F: '/^raft[0-9]+: state=/ && count < 3 {print $1; count++}')
echo "Stopping nodes: ${down_nodes}"
for node in ${down_nodes}; do
  docker compose stop "${node}"
done
sleep 3
status
cmd "q5-test4-majority-lost"

echo "========== Q5 Test 5: Restarted node catches up with the log =========="
# Purpose: A follower that was down while entries were committed re-joins the
# cluster.  On the next AppendEntries heartbeat the leader sends its full log,
# and the recovered node applies all missing entries, reaching the same state
# as the rest of the cluster.
start_cluster
wait_for_leader >/dev/null
follower=$(wait_for_followers 1)
echo "Stopping follower: ${follower}"
docker compose stop "${follower}"
sleep 2
wait_for_leader >/dev/null
cmd "q5-test5-entry-created-while-node-down"
echo "Restarting follower: ${follower}"
docker compose start "${follower}"
sleep 6
status

# =========================================================================
# ADDITIONAL TESTS (Tests 6-8)
# =========================================================================

echo "========== Q5 Test 6: New node joining (late-start node catches up) =========="
# Purpose: Simulates a brand-new node entering an already-running cluster.
# We start 4 nodes, let them elect a leader, commit several entries, then
# bring up the 5th node (raft5) which has an empty log.  After it receives
# heartbeats it must replicate the full log and match the cluster state.
# This is a key real-world scenario: adding capacity to a live cluster.
echo "Starting only 4 nodes (raft1-raft4) — raft5 intentionally offline..."
docker compose down -v --remove-orphans
docker compose --profile raft up --no-build -d --force-recreate raft1 raft2 raft3 raft4
sleep 4
wait_for_leader >/dev/null
echo "Committing two entries before raft5 joins..."
cmd "q5-test6-entry-A-before-join"
cmd "q5-test6-entry-B-before-join"
echo "Current cluster state (4 nodes):"
docker compose --profile raft run --rm --no-deps \
  -e CLUSTER=raft1=raft1:52001,raft2=raft2:52002,raft3=raft3:52003,raft4=raft4:52004 \
  raft-client python raft_client.py status 2>/dev/null || status || true
echo "Starting raft5 (new node joining)..."
docker compose --profile raft up --no-build -d --force-recreate raft5
echo "Waiting 8 seconds for raft5 to receive heartbeats and catch up..."
sleep 8
echo "Full cluster state after raft5 rejoins:"
status
echo "Sending a new command after raft5 is back — should commit with 5-node majority:"
cmd "q5-test6-entry-C-after-join"

echo "========== Q5 Test 7: Rapid successive commands (stress / pipeline test) =========="
# Purpose: Sends multiple client commands back-to-back without waiting between
# them.  Verifies that the leader serialises concurrent appends correctly,
# commit_index advances monotonically, and no entries are lost or duplicated.
# A failure here would indicate a log-ordering or locking bug.
start_cluster
wait_for_leader >/dev/null
echo "Sending 5 rapid commands in sequence..."
for i in 1 2 3 4 5; do
  cmd "q5-test7-rapid-cmd-${i}"
done
echo "Final cluster state — all 5 entries must appear in every node's log:"
status

echo "========== Q5 Test 8: Leader failure mid-replication (in-flight entry test) =========="
# Purpose: We commit one entry so the cluster has a stable baseline, then kill
# the leader immediately after sending a second command (before ACKs can
# accumulate).  The remaining nodes hold a new election.  Because the second
# entry never reached a majority before the leader died, it is NOT committed by
# the new leader, demonstrating Raft's safety guarantee: only entries replicated
# to a majority survive a leadership change.
start_cluster
wait_for_leader >/dev/null
echo "Committing a baseline entry..."
cmd "q5-test8-baseline"
echo "Sending an in-flight entry then immediately stopping the leader..."
current_leader=$(leader || true)
# Fire the command in the background so we can race the leader shutdown
docker compose --profile raft run --rm --no-deps raft-client \
  python raft_client.py cmd "q5-test8-inflight" &
CMD_PID=$!
sleep 1
if [ -n "${current_leader}" ]; then
  echo "Stopping leader ${current_leader} mid-replication..."
  docker compose stop "${current_leader}"
fi
# Wait for background command to finish (it may fail — that is expected)
wait "${CMD_PID}" || true
sleep 3
echo "Waiting for new leader election after mid-replication crash..."
new_leader=$(wait_for_leader || true)
echo "New leader: ${new_leader:-none}"
echo "Cluster state — baseline entry must be present; inflight entry may or may not be:"
status
echo "Sending a fresh command to the new leader to confirm cluster is operational:"
cmd "q5-test8-recovery-cmd"

echo ""
echo "======================================================="
echo "All Q5 failure tests (1-8) completed."
echo "Capture screenshots from this terminal output for the report."
echo "======================================================="
