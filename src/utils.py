import os
import shutil
import psutil
import glob
from logging_setup import get_logger

logger = get_logger()


def init_storage_in_ram(video_path_in_ram: str) -> None:
    """Initialize video storage in RAM by cleaning and creating directory"""
    if os.path.isdir(video_path_in_ram):
        shutil.rmtree(video_path_in_ram)
    os.makedirs(video_path_in_ram, exist_ok=True)


def _read_cpu_temperature_c_generic() -> float | None:
    """Read CPU temperature from various system sources"""
    # 1) psutil (works on Linux, some BSD/macOS; usually empty on Windows)
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False)
        if temps:
            candidates = []
            for name, entries in temps.items():
                for e in entries:
                    if e.current is None:
                        continue
                    label = (e.label or name or "").lower()
                    score = 0
                    if any(k in label for k in ("cpu", "core", "package", "soc", "arm")):
                        score += 2
                    candidates.append((score, float(e.current)))
            if candidates:
                return max(candidates)[1]
    except Exception:
        pass

    # 2) Linux sysfs fallback
    try:
        vals = []
        for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
            try:
                with open(path) as f:
                    v = f.read().strip()
                if v:
                    x = float(v)
                    vals.append(x / 1000.0 if x > 1000 else x)  # some expose millidegC
            except Exception:
                continue
        if vals:
            return max(vals)  # pick hottest zone
    except Exception:
        pass

    return None


def monitor_resources_usages(stop_event, sample_sec: float = 10.0) -> None:
    """Monitor CPU and memory usage in a loop until stop_event is set"""
    proc = psutil.Process(os.getpid())

    # Prime CPU counters so next calls return a delta over the interval
    proc.cpu_percent(None)
    psutil.cpu_percent(None)

    while not stop_event.is_set():
        # Block for the sample window (system CPU over the same interval)
        system_cpu = psutil.cpu_percent(interval=sample_sec)             # 0–100 * total cores
        # Now get the process CPU over that same window
        proc_cpu_total = proc.cpu_percent(None)                          # may be >100 on multi-core
        proc_cpu_norm  = proc_cpu_total / psutil.cpu_count(logical=True) # normalize to 0–100 of one core

        # Process memory
        mem_info = proc.memory_info()
        proc_rss_mb = mem_info.rss / (1024**2)

        # System memory
        vm = psutil.virtual_memory()
        sys_used_mib = vm.used / (1024**2)

        logger.debug("[SYS] CPU")
        logger.debug(f"  |-- process: {proc_cpu_norm:.2f} %")
        logger.debug(f"  |-- system:  {system_cpu:.2f} %")
        logger.debug(f"  |-- temperature:  {_read_cpu_temperature_c_generic()} °C")

        logger.debug("[SYS] RAM")
        logger.debug(f"  |-- process: {proc_rss_mb:.2f} MB")
        logger.debug(f"  |-- system:  {sys_used_mib:.2f} MB")