"""Windows CPU usage sampling for pyperfgraph, using NtQuerySystemInformationEx.

Windows places logical processors in processor groups of up to 64 CPUs each,
so each active group is queried separately to support up to MAX_CPUS CPUs.
"""

import ctypes
from ctypes import wintypes

MAX_CPUS = 1024
SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION_CLASS = 8


class SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("IdleTime", ctypes.c_longlong),
        ("KernelTime", ctypes.c_longlong),  # includes IdleTime
        ("UserTime", ctypes.c_longlong),
        ("DpcTime", ctypes.c_longlong),
        ("InterruptTime", ctypes.c_longlong),
        ("InterruptCount", wintypes.ULONG),
    ]


_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetActiveProcessorGroupCount.restype = wintypes.WORD
_kernel32.GetActiveProcessorCount.argtypes = [wintypes.WORD]
_kernel32.GetActiveProcessorCount.restype = wintypes.DWORD

_ntdll = ctypes.WinDLL("ntdll")
_ntdll.NtQuerySystemInformationEx.argtypes = [
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
]
_ntdll.NtQuerySystemInformationEx.restype = ctypes.c_ulong


def _query_group(group, count):
    entry_size = ctypes.sizeof(SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION)
    buf = (SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION * count)()
    group_arg = wintypes.USHORT(group)
    returned = wintypes.ULONG(0)
    status = _ntdll.NtQuerySystemInformationEx(
        SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION_CLASS,
        ctypes.byref(group_arg),
        ctypes.sizeof(group_arg),
        ctypes.byref(buf),
        ctypes.sizeof(buf),
        ctypes.byref(returned),
    )
    if status != 0:
        raise OSError("NtQuerySystemInformationEx failed for group %d: 0x%08X"
                      % (group, status))
    return buf[: returned.value // entry_size]


def read_cpu_times():
    """Return cumulative CPU times as a list of (idle, total) tuples.

    Index 0 is the combined "all" entry; indices 1..N are the individual
    CPUs ordered by CPU number (at most MAX_CPUS).
    """
    per_cpu = []
    for group in range(_kernel32.GetActiveProcessorGroupCount()):
        count = _kernel32.GetActiveProcessorCount(group)
        if count == 0:
            continue
        for info in _query_group(group, count):
            per_cpu.append((info.IdleTime, info.KernelTime + info.UserTime))
            if len(per_cpu) >= MAX_CPUS:
                break
        if len(per_cpu) >= MAX_CPUS:
            break
    combined = (sum(c[0] for c in per_cpu), sum(c[1] for c in per_cpu))
    return [combined] + per_cpu
