"""Linux CPU usage and hardware telemetry for pyperfgraph."""

from pathlib import Path

PROC_STAT = "/proc/stat"
SYS_CPU = Path("/sys/devices/system/cpu")
SYS_PMU = Path("/sys/bus/event_source/devices")
MAX_CPUS = 1024


def _read_stat():
    combined = None
    per_cpu = {}
    with open(PROC_STAT, "r", encoding="ascii") as f:
        for line in f:
            if not line.startswith("cpu"):
                continue
            fields = line.split()
            name = fields[0]
            values = [int(v) for v in fields[1:]]
            # user nice system idle iowait irq softirq steal (guest time is
            # already accounted for in user/nice, so it is excluded).
            values = (values + [0] * 8)[:8]
            idle = values[3] + values[4]
            total = sum(values)
            if name == "cpu":
                combined = (idle, total)
            else:
                per_cpu[int(name[3:])] = (idle, total)
    if combined is None:
        raise RuntimeError("Unable to read CPU statistics from " + PROC_STAT)
    return combined, per_cpu


def read_cpu_times():
    """Return (idle, total) times: All, then online CPUs in numeric order."""
    combined, per_cpu = _read_stat()
    return [combined] + [per_cpu[n] for n in sorted(per_cpu)[:MAX_CPUS]]


def _read_optional(path):
    try:
        return path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None


def _pmu_cpus(name):
    text = _read_optional(SYS_PMU / name / "cpus")
    cpus = set()
    if text:
        for part in text.split(","):
            first, _, last = part.partition("-")
            cpus.update(range(int(first), int(last or first) + 1))
    return cpus


def read_cpu_details():
    """Return (performance rank, frequency) for each online logical CPU.

    Frequency is (current, minimum, maximum), in kHz, or None when cpufreq
    is unavailable. Ranks are OS-reported core types/capacities, not clocks.
    """
    _, per_cpu = _read_stat()
    ids = sorted(per_cpu)[:MAX_CPUS]
    core_cpus = _pmu_cpus("cpu_core")
    atom_cpus = _pmu_cpus("cpu_atom")
    types, capacities, frequencies = [], [], []
    for cpu in ids:
        base = SYS_CPU / ("cpu%d" % cpu)
        core_type = _read_optional(base / "topology/core_type")
        # Intel hybrid PMUs expose the same distinction on older kernels.
        rank = int(core_type) if core_type else 0
        if not rank:
            rank = 2 if cpu in core_cpus else (1 if cpu in atom_cpus else None)
        types.append(rank)
        capacity = _read_optional(base / "cpu_capacity")
        capacities.append(int(capacity) if capacity else None)
        values = [_read_optional(base / "cpufreq" / name) for name in
                  ("scaling_cur_freq", "cpuinfo_min_freq", "cpuinfo_max_freq")]
        frequencies.append(tuple(int(v) for v in values)
                           if all(v is not None for v in values) else None)
    ranks = types if all(t is not None for t in types) else capacities
    return list(zip(ranks, frequencies))
