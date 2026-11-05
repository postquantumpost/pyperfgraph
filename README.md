# pyperfgraph
A local performance monitor that produces a graph in a window for linux and windows.

## Requirements
- Python 3 with tkinter (on Debian/Ubuntu: `sudo apt install python3-tk`). No other packages are needed.

## Usage
```
python3 pyperfgraph.py [--update SECONDS]
```
`--update` sets the refresh interval in seconds (floating point, default `0.2`).

The top half of the window shows a scrolling history of each CPU's usage (0–100%), and the bottom half
shows a bar graph of current usage. The combined "All" entry comes first, then each CPU in numeric order starting at CPU0.
Up to 1024 CPUs are displayed.

On hybrid CPUs, the legend's color squares carry `P` for the fastest core type
and `E` for the more efficient type. With more than two OS-reported types, the
lower-ranked types are labeled `E1`, `E2`, etc., in descending performance order.
Homogeneous CPUs and CPUs without reported type information have no labels.

Each CPU bar also shows a horizontal clock marker when variable-clock telemetry
is available: a white line immediately above a black line. The bottom represents
minimum frequency and the top maximum frequency, independently of CPU usage.
The marker follows the OS-reported current clock setting (not a measurement of
work performed). There is no clock marker for the combined "All" bar.
Linux uses cpufreq's hardware minimum/maximum and current scaling frequency;
core types come from topology, Intel hybrid PMUs, or CPU capacity.
Windows uses CPU-set efficiency classes and processor power information, with
the active power plan's minimum processor state as its lower bound and the
reported maximum/thermal limit as its upper bound. Windows clock markers are
disabled with a warning on multi-processor-group systems, where that API does
not guarantee per-CPU clock mapping. Missing telemetry leaves usage graphs intact.

Platform-specific CPU sampling lives in `ppglinux.py` (reads `/proc/stat`) and `ppgwindows.py`
(uses `NtQuerySystemInformationEx` per processor group).
