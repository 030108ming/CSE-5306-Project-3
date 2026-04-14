import time
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
import grpc
import drone_pb2
import drone_pb2_grpc


TARGET = "server:50053"


def measure_latency(stub, iterations=500):
    times = []

    for _ in range(iterations):
        start = time.perf_counter()
        stub.SendCommand(drone_pb2.Command(text="sensor voltage"))
        end = time.perf_counter()
        times.append((end - start) * 1000)

    print("\n--- Latency Benchmark ---")
    print(f"Samples: {iterations}")
    print(f"Avg: {statistics.mean(times):.2f} ms")
    print(f"StdDev: {statistics.stdev(times):.2f} ms")
    print(f"Min: {min(times):.2f} ms")
    print(f"Max: {max(times):.2f} ms")
    print(f"P95: {sorted(times)[int(0.95 * len(times))]:.2f} ms")
    print("--------------------------\n")


def measure_throughput(stub, duration=10):
    count = 0
    end_time = time.time() + duration

    while time.time() < end_time:
        stub.SendCommand(drone_pb2.Command(text="sensor voltage"))
        count += 1

    print("\n--- Throughput Test ---")
    print(f"Duration: {duration} sec")
    print(f"Total Requests: {count}")
    print(f"Requests/sec: {count/duration:.2f}")
    print("------------------------\n")


def stress_test(clients=5, duration=10):
    print(f"\n--- Stress Test ({clients} clients, {duration}s) ---")

    def worker():
        channel = grpc.insecure_channel(TARGET)
        stub = drone_pb2_grpc.ServerStub(channel)
        end_time = time.time() + duration
        count = 0
        while time.time() < end_time:
            stub.SendCommand(drone_pb2.Command(text="sensor voltage"))
            count += 1
        return count

    with ThreadPoolExecutor(max_workers=clients) as executor:
        results = list(executor.map(lambda _: worker(), range(clients)))

    total = sum(results)
    print(f"Total Requests: {total}")
    print(f"Aggregate Requests/sec: {total/duration:.2f}")
    print("-------------------------------\n")


def interactive_loop(stub):
    print("Type 'help' for commands.")
    print("Benchmark commands:")
    print("  benchmark <iterations>")
    print("  throughput <seconds>")
    print("  stress <clients> <seconds>\n")

    while True:
        cmd = input("> ").strip()

        if cmd.startswith("benchmark"):
            parts = cmd.split()
            n = int(parts[1]) if len(parts) > 1 else 500
            measure_latency(stub, n)
            continue

        if cmd.startswith("throughput"):
            parts = cmd.split()
            sec = int(parts[1]) if len(parts) > 1 else 10
            measure_throughput(stub, sec)
            continue

        if cmd.startswith("stress"):
            parts = cmd.split()
            clients = int(parts[1]) if len(parts) > 1 else 5
            sec = int(parts[2]) if len(parts) > 2 else 10
            stress_test(clients, sec)
            continue

        if cmd == "quit":
            break

        start = time.perf_counter()
        response = stub.SendCommand(drone_pb2.Command(text=cmd))
        end = time.perf_counter()

        print(f"[Latency: {(end - start)*1000:.2f} ms]")
        print(response.text)


def main():
    channel = grpc.insecure_channel(TARGET)
    stub = drone_pb2_grpc.ServerStub(channel)
    interactive_loop(stub)


if __name__ == "__main__":
    main()