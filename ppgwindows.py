"""Windows CPU usage sampling for pyperfgraph, using NtQuerySystemInformationEx.

Windows places logical processors in processor groups of up to 64 CPUs each,
so each active group is queried separately to support up to MAX_CPUS CPUs.
"""

import ctypes
import struct
import uuid
import warnings
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


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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

_cpu_sets = getattr(_kernel32, "GetSystemCpuSetInformation", None)
if _cpu_sets is not None:
    _cpu_sets.argtypes = [ctypes.c_void_p, wintypes.ULONG,
                         ctypes.POINTER(wintypes.ULONG), wintypes.HANDLE,
                         wintypes.ULONG]
    _cpu_sets.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p
_kernel32.GetSystemPowerStatus.argtypes = [ctypes.c_void_p]
_kernel32.GetSystemPowerStatus.restype = wintypes.BOOL

_power = ctypes.WinDLL("powrprof")
_power.CallNtPowerInformation.argtypes = [
    ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
    ctypes.c_void_p, wintypes.ULONG,
]
_power.CallNtPowerInformation.restype = ctypes.c_ulong
_power.PowerGetActiveScheme.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
]
_power.PowerGetActiveScheme.restype = wintypes.DWORD
for _name in ("PowerReadACValueIndex", "PowerReadDCValueIndex"):
    _reader = getattr(_power, _name)
    _reader.argtypes = [ctypes.c_void_p] * 4 + [ctypes.POINTER(wintypes.DWORD)]
    _reader.restype = wintypes.DWORD


class PROCESSOR_POWER_INFORMATION(ctypes.Structure):
    _fields_ = [(name, wintypes.ULONG) for name in
                ("Number", "MaxMhz", "CurrentMhz", "MhzLimit",
                 "MaxIdleState", "CurrentIdleState")]


def _performance_classes():
    if _cpu_sets is None:
        return {}
    size = wintypes.ULONG()
    if not _cpu_sets(None, 0, ctypes.byref(size), None, 0):
        error = ctypes.get_last_error()
        if error != 122:  # ERROR_INSUFFICIENT_BUFFER
            raise ctypes.WinError(error)
    if not size.value:
        return {}
    while True:
        buf = ctypes.create_string_buffer(size.value)
        if _cpu_sets(buf, len(buf), ctypes.byref(size), None, 0):
            break
        error = ctypes.get_last_error()
        if error != 122:
            raise ctypes.WinError(error)
    classes = {}
    offset = 0
    while offset < size.value:
        if size.value - offset < 8:
            raise RuntimeError("Truncated Windows CPU set header")
        length, kind = struct.unpack_from("<II", buf, offset)
        if length < 8 or offset + length > size.value:
            raise RuntimeError("Invalid Windows CPU set length")
        if kind == 0:
            if length < 20:
                raise RuntimeError("Truncated Windows CPU set")
            group, cpu = struct.unpack_from("<HB", buf, offset + 12)
            classes[group, cpu] = buf.raw[offset + 18]
        offset += length
    return classes


def _guid(text):
    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


def _minimum_percent():
    """Read the active AC/DC policy's minimum processor state."""
    scheme = ctypes.c_void_p()
    status = _power.PowerGetActiveScheme(None, ctypes.byref(scheme))
    if status:
        raise ctypes.WinError(status)
    try:
        power_status = (ctypes.c_ubyte * 12)()
        if not _kernel32.GetSystemPowerStatus(power_status):
            raise ctypes.WinError(ctypes.get_last_error())
        if power_status[0] == 255:
            warnings.warn("AC/DC status unavailable; clock markers disabled",
                          RuntimeWarning)
            return None
        reader = (_power.PowerReadDCValueIndex if power_status[0] == 0
                  else _power.PowerReadACValueIndex)
        subgroup = _guid("54533251-82be-4824-96c1-47b60b740d00")
        setting = _guid("893dee8e-2bef-41e0-89c6-b55d0929964c")
        value = wintypes.DWORD()
        status = reader(None, scheme, subgroup, setting, ctypes.byref(value))
        if status:
            raise ctypes.WinError(status)
        if value.value > 100:
            raise RuntimeError("Invalid minimum processor state: %d" % value.value)
        return value.value
    finally:
        _kernel32.LocalFree(scheme)


def read_cpu_details():
    """Return OS performance ranks and (current, minimum, maximum) MHz.

    Windows exposes a policy minimum rather than a hardware minimum.
    ProcessorInformation has no group argument: on multi-group systems its
    clock-to-CPU mapping is not guaranteed, so only core labels are supplied.
    """
    classes = _performance_classes()
    groups = [(group, _kernel32.GetActiveProcessorCount(group))
              for group in range(_kernel32.GetActiveProcessorGroupCount())]
    ranks = [classes.get((group, cpu)) for group, count in groups
             for cpu in range(count)][:MAX_CPUS]
    if len(groups) != 1:
        warnings.warn("Per-CPU clocks unavailable across Windows processor groups",
                      RuntimeWarning)
        return [(rank, None) for rank in ranks]
    count = groups[0][1]
    buf = (PROCESSOR_POWER_INFORMATION * count)()
    status = _power.CallNtPowerInformation(
        11, None, 0, buf, ctypes.sizeof(buf))  # ProcessorInformation
    if status in (0xC0000002, 0xC00000BB):  # NOT_IMPLEMENTED / NOT_SUPPORTED
        warnings.warn("Processor clock telemetry is unsupported", RuntimeWarning)
        return [(rank, None) for rank in ranks]
    if status:
        raise OSError("CallNtPowerInformation failed: 0x%08X" % status)
    minimum = _minimum_percent()
    frequencies = {}
    if minimum is not None:
        for info in buf:
            frequencies[info.Number] = (
                info.CurrentMhz, info.MaxMhz * minimum / 100.0,
                min(info.MaxMhz, info.MhzLimit) if info.MhzLimit else info.MaxMhz)
    return [(rank, frequencies.get(cpu)) for cpu, rank in enumerate(ranks)]


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
