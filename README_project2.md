# Distributed Drone Telemetry System  
CSE 5306 – Project 2  
gRPC + Docker Compose

---

# 1. Overview

This project implements a distributed drone telemetry processing pipeline using:

- Python 3.11  
- gRPC  
- Docker Compose  

The system simulates multiple independent sensor services that generate telemetry data and alert conditions. Telemetry flows through a multi-stage processing pipeline before reaching an interactive client interface.

Two architectures are implemented:

1. Distributed Microservices Architecture
2. Monolithic Architecture (Single Container)

Both architectures expose the same gRPC interface to ensure functional equivalence and allow direct performance comparison.

---

# 2. System Architecture

## Distributed Telemetry Flow

Sensors → Aggregation → Analysis → Update → Server → Client  

Command Flow:

Client ↔ Server ↔ Update  

Each stage runs inside its own Docker container and communicates via gRPC.

---

## Monolithic Architecture

All telemetry generation and processing logic runs inside a single container.

This removes inter-container RPC overhead while preserving identical client functionality.

---

# 3. Project Structure

src/
  aggregation.py
  analysis.py
  update.py
  server.py
  client.py
  monolith.py
  imu_sensor.py
  gps_sensor.py
  engine_sensor.py
  battery_sensor.py
  airdata_sensor.py
  drone.proto
  drone_pb2.py
  drone_pb2_grpc.py

Dockerfiles/
  Dockerfile.airdata
  Dockerfile.battery
  Dockerfile.engine
  Dockerfile.gps
  Dockerfile.imu
  Dockerfile.aggregation
  Dockerfile.analysis
  Dockerfile.update
  Dockerfile.server
  Dockerfile.client
  Dockerfile.monolith

docker-compose.yml
run_distributed.sh
run_monolith.sh
README.md

All Python source files reside in `src/`.

---

# 4. Running the System

Run all commands from the project root (where docker-compose.yml is located).

Docker Compose profiles are used to isolate architectures.

---

## 🔵 Run Distributed Architecture

./run_distributed.sh

Equivalent manual commands:

docker compose down -v --remove-orphans
docker compose --profile distributed up -d --build
docker compose run --rm client

---

## 🟣 Run Monolithic Architecture

./run_monolith.sh

Equivalent manual commands:

docker compose down -v --remove-orphans
docker compose --profile monolith up -d --build
docker compose run --rm client

---

## 🔄 Switching Architectures

No manual cleanup required.

Each run script automatically executes:

docker compose down -v --remove-orphans

Important:
Both architectures bind to port 50053.  
Do NOT attempt to run them simultaneously.

---

# 5. Available Client Commands

help  
  Displays available commands.

status  
  Displays system status.

health  
  Displays overall health (based on alerts).

list  
  Lists available sensor names.

sensor <name>  
  Displays current value for a specific sensor.

alerts  
  Displays all currently active alerts.

benchmark latency <samples>  
  Runs latency benchmark using <samples> RPC calls.

benchmark throughput <seconds>  
  Runs throughput benchmark for <seconds>.

benchmark stress <clients> <seconds>  
  Runs concurrency stress test using <clients> for <seconds>.

quit  
  Exits the client.

### Sensor Names

- altitude
- airspeed
- voltage
- egt
- latitude
- longitude
- vibration

Example:

sensor voltage

---

# 6. Units Used

| Sensor     | Units |
|------------|-------|
| altitude   | ft    |
| airspeed   | kt    |
| voltage    | V     |
| egt        | °C    |
| latitude   | deg   |
| longitude  | deg   |
| vibration  | g     |

---

# 7. Benchmarking

Run benchmarks while inside the client.

Latency test (example):

benchmark latency 2000

Throughput test:

benchmark throughput 10
benchmark throughput 30

Concurrency stress test:

benchmark stress 5 15
benchmark stress 20 20

---

# 8. Docker Resource Monitoring

While the system is running in another terminal:

docker stats

This displays:

- CPU usage
- Memory usage
- Network I/O
- Container resource consumption

Stop monitoring with Ctrl + C.

---

# 9. Performance Comparison Summary

Distributed Architecture:
- Service isolation
- Modular design
- RPC chaining overhead
- Centralized pipeline stages

Monolithic Architecture:
- No inter-container serialization
- Reduced RPC overhead
- Single failure domain
- Lower architectural separation

---

# 10. Troubleshooting

Make scripts executable:

chmod +x run_distributed.sh
chmod +x run_monolith.sh

Check running containers:

docker ps

Force shutdown everything:

docker compose down -v --remove-orphans

---

# 11. Notes

- Do not run distributed and monolith simultaneously.
- Always switch using provided scripts.
- Ensure port 50053 is free before starting either architecture.
- Benchmarks should be run with minimal host background load for accurate results.

---

# 12. Project 3 Consensus Extension

This repo also includes a Project 3 extension for 2PC and simplified Raft.

2PC:

```bash
./run_twopc.sh
./run_twopc.sh "set drone_mode=stable"
```

Raft:

```bash
./run_raft.sh
docker compose --profile raft run --rm raft-client python raft_client.py status
docker compose --profile raft run --rm raft-client python raft_client.py cmd "set drone_mode=stable"
```

Raft failure tests for Q5:

```bash
./run_raft_tests.sh
```

Detailed implementation notes are in `ASSIGNMENT3_GUIDE.md`.
