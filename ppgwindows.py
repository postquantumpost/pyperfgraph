"""Windows CPU usage sampling for pyperfgraph, using NtQuerySystemInformation."""

import ctypes
import os
from ctypes import wintypes

SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION_CLASS = 8
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004


class SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("IdleTime", ctypes.c_longlong),
        ("KernelTime", ctypes.c_longlong),  # includes IdleTime
        ("UserTime", ctypes.c_longlong),
        ("DpcTime", ctypes.c_longlong),
        ("InterruptTime", ctypes.c_longlong),
        ("InterruptCount", wintypes.ULONG),
    ]


_ntdll = ctypes.WinDLL("ntdll")
_ntdll.NtQuerySystemInformation.argtypes = [
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
]
_ntdll.NtQuerySystemInformation.restype = ctypes.c_ulong

_count = max(os.cpu_count() or 1, 1)


def read_cpu_times():
    """Return cumulative CPU times as a list of (idle, total) tuples.

    Index 0 is the combined "all" entry; indices 1..N are the individual
    CPUs ordered by CPU number.
    """
    global _count
    entry_size = ctypes.sizeof(SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION)
    while True:
        buf = (SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION * _count)()
        returned = wintypes.ULONG(0)
        status = _ntdll.NtQuerySystemInformation(
            SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION_CLASS,
            ctypes.byref(buf),
            ctypes.sizeof(buf),
            ctypes.byref(returned),
        )
        if status == STATUS_INFO_LENGTH_MISMATCH:
            _count *= 2
            continue
        if status != 0:
            raise OSError("NtQuerySystemInformation failed: 0x%08X" % status)
        break

    per_cpu = []
    for info in buf[: returned.value // entry_size]:
        total = info.KernelTime + info.UserTime
        per_cpu.append((info.IdleTime, total))
    combined = (sum(c[0] for c in per_cpu), sum(c[1] for c in per_cpu))
    return [combined] + per_cpu
