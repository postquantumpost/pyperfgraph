#!/usr/bin/env python3
"""pyperfgraph - a local window that graphs CPU usage on Linux and Windows.

The top half of the window shows a scrolling history graph of each CPU's
usage (plus the combined "All" usage); the bottom half shows a bar graph of
the current usage, with "All" first followed by each CPU in numeric order.
"""

import argparse
import colorsys
import math
import sys
import tkinter as tk
from collections import deque

if sys.platform.startswith("win"):
    import ppgwindows as platform_cpu
elif sys.platform.startswith("linux"):
    import ppglinux as platform_cpu
else:
    sys.exit("pyperfgraph: unsupported platform: " + sys.platform)

HISTORY_SECONDS = 60
ALL_COLOR = "#202020"
BG_COLOR = "#ffffff"
PLOT_BG_COLOR = "#fafafa"
GRID_COLOR = "#d8d8d8"
TEXT_COLOR = "#303030"
FONT = ("TkDefaultFont", 9)
TITLE_FONT = ("TkDefaultFont", 10, "bold")
LEGEND_COLUMNS = 4
LEGEND_ROW_HEIGHT = 20


def make_colors(n):
    """Return n distinct colors, alternating brightness between neighbours."""
    colors = []
    for i in range(n):
        hue = i / max(n, 1)
        value = 0.90 if i % 2 == 0 else 0.70
        r, g, b = colorsys.hsv_to_rgb(hue, 0.85, value)
        colors.append("#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255)))
    return colors


def usage_percent(prev, cur):
    idle = cur[0] - prev[0]
    total = cur[1] - prev[1]
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (total - idle) / total))


def format_age(seconds):
    if seconds <= 0:
        return ""
    if seconds % 60 == 0:
        minutes = int(seconds // 60)
        return "%d min" % minutes if minutes == 1 else "%d mins" % minutes
    return "%g secs" % seconds


class PerfGraph:
    def __init__(self, root, update):
        self.root = root
        self.update = update
        self.span = max(HISTORY_SECONDS, update * 10)
        self.prev = platform_cpu.read_cpu_times()
        self.count = len(self.prev)  # "All" + each CPU
        self.names = ["All"] + ["CPU%d" % n for n in range(1, self.count)]
        self.colors = [ALL_COLOR] + make_colors(self.count - 1)
        max_samples = int(math.ceil(self.span / update)) + 2
        self.history = [deque(maxlen=max_samples) for _ in range(self.count)]
        self.current = [0.0] * self.count

        root.title("pyperfgraph - CPU")
        root.configure(bg=BG_COLOR)
        self.canvas = tk.Canvas(root, width=1000, height=800, bg=BG_COLOR,
                                highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw())
        root.after(int(update * 1000), self.tick)

    def tick(self):
        cur = platform_cpu.read_cpu_times()
        if len(cur) != self.count:
            # CPU set changed (e.g. hotplug); restart sampling from scratch.
            self.__init_counts(cur)
        else:
            for i in range(self.count):
                self.current[i] = usage_percent(self.prev[i], cur[i])
                self.history[i].append(self.current[i])
        self.prev = cur
        self.draw()
        self.root.after(int(self.update * 1000), self.tick)

    def __init_counts(self, cur):
        self.count = len(cur)
        self.names = ["All"] + ["CPU%d" % n for n in range(1, self.count)]
        self.colors = [ALL_COLOR] + make_colors(self.count - 1)
        maxlen = self.history[0].maxlen
        self.history = [deque(maxlen=maxlen) for _ in range(self.count)]
        self.current = [0.0] * self.count

    def draw(self):
        c = self.canvas
        c.delete("all")
        width = c.winfo_width()
        height = c.winfo_height()
        if width < 50 or height < 50:
            return
        half = height // 2
        self.draw_history(10, 0, width - 10, half)
        c.create_line(0, half, width, half, fill=GRID_COLOR)
        self.draw_bars(10, half, width - 10, height)

    def draw_history(self, x0, y0, x1, y1):
        c = self.canvas
        c.create_text(x0, y0 + 6, text="CPU History", anchor="nw",
                      font=TITLE_FONT, fill=TEXT_COLOR)
        legend_rows = int(math.ceil(self.count / LEGEND_COLUMNS))
        legend_h = legend_rows * LEGEND_ROW_HEIGHT + 6
        left, right = x0, x1 - 45
        top, bottom = y0 + 28, y1 - legend_h - 20
        if bottom - top < 20 or right - left < 20:
            return

        c.create_rectangle(left, top, right, bottom, fill=PLOT_BG_COLOR,
                           outline=GRID_COLOR)
        for pct in range(0, 101, 20):
            y = bottom - (bottom - top) * pct / 100.0
            c.create_line(left, y, right, y, fill=GRID_COLOR)
            c.create_text(right + 5, y, text="%d %%" % pct, anchor="w",
                          font=FONT, fill=TEXT_COLOR)
        step = self.span / 6.0
        for k in range(7):
            age = self.span - k * step
            x = left + (right - left) * k / 6.0
            c.create_line(x, top, x, bottom, fill=GRID_COLOR)
            c.create_text(x, bottom + 3, text=format_age(round(age, 1)),
                          anchor="n" if 0 < k < 6 else ("nw" if k == 0 else "ne"),
                          font=FONT, fill=TEXT_COLOR)

        # Draw individual CPUs first, then "All" on top with a thicker line.
        for i in list(range(1, self.count)) + [0]:
            values = self.history[i]
            n = len(values)
            if n < 2:
                continue
            points = []
            for j, v in enumerate(values):
                age = (n - 1 - j) * self.update
                x = right - (right - left) * age / self.span
                if x < left:
                    continue
                points.extend((x, bottom - (bottom - top) * v / 100.0))
            if len(points) >= 4:
                c.create_line(*points, fill=self.colors[i], smooth=True,
                              width=3 if i == 0 else 1.5)

        col_w = (x1 - x0) / LEGEND_COLUMNS
        ly0 = bottom + 24
        for i in range(self.count):
            col, row = divmod(i, legend_rows)
            lx = x0 + col * col_w
            ly = ly0 + row * LEGEND_ROW_HEIGHT
            c.create_rectangle(lx, ly + 2, lx + 28, ly + 15,
                               fill=self.colors[i], outline=TEXT_COLOR)
            c.create_text(lx + 36, ly + 8, text=self.names[i], anchor="w",
                          font=FONT, fill=TEXT_COLOR)
            c.create_text(lx + 140, ly + 8, text="%5.1f%%" % self.current[i],
                          anchor="e", font=FONT, fill=TEXT_COLOR)

    def draw_bars(self, x0, y0, x1, y1):
        c = self.canvas
        c.create_text(x0, y0 + 6, text="CPU Usage", anchor="nw",
                      font=TITLE_FONT, fill=TEXT_COLOR)
        left, right = x0 + 40, x1
        top, bottom = y0 + 46, y1 - 24
        if bottom - top < 20 or right - left < 20:
            return

        for pct in range(0, 101, 20):
            y = bottom - (bottom - top) * pct / 100.0
            c.create_line(left, y, right, y, fill=GRID_COLOR)
            c.create_text(left - 5, y, text="%d %%" % pct, anchor="e",
                          font=FONT, fill=TEXT_COLOR)

        slot = (right - left) / self.count
        bar_w = max(2.0, slot * 0.7)
        for i in range(self.count):
            cx = left + slot * (i + 0.5)
            bx0, bx1 = cx - bar_w / 2, cx + bar_w / 2
            c.create_rectangle(bx0, top, bx1, bottom, fill=PLOT_BG_COLOR,
                               outline=GRID_COLOR)
            pct = self.current[i]
            by = bottom - (bottom - top) * pct / 100.0
            c.create_rectangle(bx0, by, bx1, bottom, fill=self.colors[i],
                               outline=self.colors[i])
            c.create_text(cx, by - 3, text="%.0f%%" % pct, anchor="s",
                          font=FONT, fill=TEXT_COLOR)
            c.create_text(cx, bottom + 4, text=self.names[i], anchor="n",
                          font=FONT, fill=TEXT_COLOR)


def positive_float(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("invalid float value: %r" % text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("update rate must be a positive number")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Display a live graph of CPU performance.")
    parser.add_argument("--update", type=positive_float, default=1.0,
                        metavar="SECONDS",
                        help="update rate in seconds (default: 1.0)")
    args = parser.parse_args(argv)

    root = tk.Tk()
    PerfGraph(root, args.update)
    root.mainloop()


if __name__ == "__main__":
    main()
