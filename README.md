# pyperfgraph
A local performance monitor that produces a graph in a window for linux and windows.

## Requirements
- Python 3 with tkinter (on Debian/Ubuntu: `sudo apt install python3-tk`). No other packages are needed.

## Usage
```
python3 pyperfgraph.py [--update SECONDS]
```
`--update` sets the refresh interval in seconds (floating point, default `1.0`).

The top half of the window shows a scrolling history of each CPU's usage (0–100%), and the bottom half
shows a bar graph of current usage. The combined "All" entry comes first, then each CPU in numeric order.

Platform-specific CPU sampling lives in `ppglinux.py` (reads `/proc/stat`) and `ppgwindows.py`
(uses `NtQuerySystemInformation`).
