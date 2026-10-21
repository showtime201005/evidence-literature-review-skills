"""Low-frequency process-tree and host measurements on Windows and Linux."""
import os
import threading
import psutil


class ResourceMonitor:
    def __init__(self, interval=1.0):
        self.interval = interval
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.process = psutil.Process()
        self.data = {"measurement": "sampled peaks, including observed CLI child processes",
                     "interval_seconds": interval, "logical_cpus": os.cpu_count(),
                     "peak_process_tree_rss_bytes": 0, "peak_host_cpu_percent": 0,
                     "peak_process_cpu_percent_of_machine": 0,
                     "minimum_host_available_bytes": psutil.virtual_memory().available,
                     "low_memory_samples": 0, "samples": 0}
        self.process.cpu_percent()
        psutil.cpu_percent()
        self.thread = threading.Thread(target=self._run, daemon=True, name="literature-resources")
        self.thread.start()

    def _run(self):
        while not self.stop_event.wait(self.interval):
            try:
                members = [self.process, *self.process.children(recursive=True)]
                rss = 0
                for member in members:
                    try:
                        rss += member.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                cpu = self.process.cpu_percent() / max(1, os.cpu_count() or 1)
                host_cpu = psutil.cpu_percent()
                available = psutil.virtual_memory().available
                with self.lock:
                    self.data["samples"] += 1
                    self.data["peak_process_tree_rss_bytes"] = max(self.data["peak_process_tree_rss_bytes"], rss)
                    self.data["peak_process_cpu_percent_of_machine"] = max(self.data["peak_process_cpu_percent_of_machine"], cpu)
                    self.data["peak_host_cpu_percent"] = max(self.data["peak_host_cpu_percent"], host_cpu)
                    self.data["minimum_host_available_bytes"] = min(self.data["minimum_host_available_bytes"], available)
                    self.data["low_memory_samples"] += int(available < 4 * 1024**3)
            except psutil.Error:
                continue

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=max(2, self.interval * 2))
        with self.lock:
            return dict(self.data)
