"""Linux CPU usage sampling for pyperfgraph, based on /proc/stat."""

PROC_STAT = "/proc/stat"
MAX_CPUS = 1024


def read_cpu_times():
    """Return cumulative CPU times as a list of (idle, total) tuples.

    Index 0 is the combined "all" entry; indices 1..N are the individual
    CPUs ordered by CPU number (at most MAX_CPUS).
    """
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
    return [combined] + [per_cpu[n] for n in sorted(per_cpu)[:MAX_CPUS]]
