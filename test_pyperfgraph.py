import ctypes
import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import ppglinux
import pyperfgraph


ROOT = Path(__file__).parent


class CoreDisplayTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(pyperfgraph.core_labels([2, 1, 2, 1]),
                         ["P", "E", "P", "E"])
        self.assertEqual(pyperfgraph.core_labels([30, 20, 10, None]),
                         ["P", "E1", "E2", ""])
        self.assertEqual(pyperfgraph.core_labels([1, 1, None]), ["", "", ""])
        self.assertEqual(pyperfgraph.core_labels([]), [])

    def test_clock_normalization(self):
        for current, expected in ((400, 0), (2200, 0.5), (4000, 1),
                                  (100, 0), (4500, 1)):
            self.assertEqual(pyperfgraph.clock_fraction((current, 400, 4000)),
                             expected)
        for frequency in (None, (1000, 1000, 1000), (0, 400, 4000),
                          (1000, -1, 4000), (1000, 4000, 400)):
            self.assertIsNone(pyperfgraph.clock_fraction(frequency))

    def graph(self):
        graph = pyperfgraph.PerfGraph.__new__(pyperfgraph.PerfGraph)
        graph.count = 4
        graph.names = ["All", "CPU0", "CPU1", "CPU2"]
        graph.colors = ["#202020", "#ff0000", "#00ff00", "#0000ff"]
        graph.current = [25, 50, 75, 100]
        graph.core_labels = ["", "P", "E1", "E2"]
        graph.clocks = [None, 0, 0.5, 1]
        graph.history = [[], [], [], []]
        graph.span = 60
        graph.canvas = Mock()
        return graph

    def test_marker_geometry_and_order(self):
        graph = self.graph()
        graph.draw_bars(0, 0, 400, 300)
        lines = [call for call in graph.canvas.create_line.call_args_list
                 if call.kwargs["fill"] in ("white", "black")]
        self.assertEqual(len(lines), 6)
        top, bottom = 46, 276
        for i, expected in enumerate((bottom - 1, (top + bottom - 1) / 2, top)):
            white, black = lines[i * 2:i * 2 + 2]
            self.assertEqual(white.kwargs["fill"], "white")
            self.assertEqual(black.kwargs["fill"], "black")
            self.assertEqual(white.args[1], expected)
            self.assertEqual(black.args[1], expected + 1)
            self.assertEqual(white.args[::2], black.args[::2])
            self.assertGreaterEqual(white.args[1], top)
            self.assertLessEqual(black.args[1], bottom)

    def test_legend_overlays_and_variable_width(self):
        graph = self.graph()
        font = Mock()
        font.measure.side_effect = lambda text: 8 * len(text)
        with patch.object(pyperfgraph.tkfont, "Font", return_value=font):
            graph.draw_history(0, 0, 1000, 400)
        labels = [call for call in graph.canvas.create_text.call_args_list
                  if call.kwargs["text"] in ("P", "E1", "E2")]
        self.assertEqual(len(labels), 6)
        boxes = graph.canvas.create_rectangle.call_args_list[1:]
        self.assertTrue(all(call.args[2] - call.args[0] >= 18 for call in boxes))

    def test_telemetry_alignment_and_hotplug(self):
        graph = self.graph()
        with patch.object(pyperfgraph.platform_cpu, "read_cpu_details",
                          return_value=[(2, (2200, 400, 4000)),
                                        (1, None), (1, (400, 400, 4000))]):
            graph.read_cpu_details()
        self.assertEqual(graph.core_labels, ["", "P", "E", "E"])
        self.assertEqual(graph.clocks, [None, 0.5, None, 0])
        with patch.object(pyperfgraph.platform_cpu, "read_cpu_details",
                          return_value=[(2, None)]):
            graph.read_cpu_details()
        self.assertEqual(graph.core_labels, [""] * 4)
        self.assertEqual(graph.clocks, [None] * 4)


class LinuxTelemetryTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.cpu = self.base / "cpu"
        self.pmu = self.base / "pmu"
        self.stat = self.base / "stat"
        self.stat.write_text("cpu 10 0 0 20\ncpu0 5 0 0 10\ncpu3 5 0 0 10\n")
        for name, value in (("SYS_CPU", self.cpu), ("SYS_PMU", self.pmu),
                            ("PROC_STAT", str(self.stat))):
            patcher = patch.object(ppglinux, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, relative, text):
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_hybrid_pmu_and_sparse_cpu_numbers(self):
        self.write("pmu/cpu_core/cpus", "0-2,5")
        self.write("pmu/cpu_atom/cpus", "3-4")
        self.write("cpu/cpu0/cpufreq/scaling_cur_freq", "2200000")
        self.write("cpu/cpu0/cpufreq/cpuinfo_min_freq", "400000")
        self.write("cpu/cpu0/cpufreq/cpuinfo_max_freq", "4000000")
        self.assertEqual(ppglinux.read_cpu_details(),
                         [(2, (2200000, 400000, 4000000)), (1, None)])
        self.assertEqual(ppglinux.read_cpu_times(), [(20, 30), (10, 15), (10, 15)])

    def test_topology_preferred_and_capacity_fallback(self):
        self.write("cpu/cpu0/topology/core_type", "2")
        self.write("cpu/cpu3/topology/core_type", "1")
        self.write("cpu/cpu0/cpu_capacity", "100")
        self.write("cpu/cpu3/cpu_capacity", "100")
        self.assertEqual(ppglinux.read_cpu_details(), [(2, None), (1, None)])
        (self.cpu / "cpu3/topology/core_type").unlink()
        self.write("cpu/cpu0/cpu_capacity", "1024")
        self.write("cpu/cpu3/cpu_capacity", "512")
        self.assertEqual(ppglinux.read_cpu_details(), [(1024, None), (512, None)])

    def test_missing_and_invalid_telemetry(self):
        self.assertEqual(ppglinux.read_cpu_details(), [(None, None), (None, None)])
        self.write("cpu/cpu0/topology/core_type", "invalid")
        with self.assertRaises(ValueError):
            ppglinux.read_cpu_details()


class WindowsTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.kernel = Mock()
        self.power = Mock()
        dlls = {"kernel32": self.kernel, "powrprof": self.power, "ntdll": Mock()}
        spec = importlib.util.spec_from_file_location(
            "test_windows_backend", ROOT / "ppgwindows.py")
        self.windows = importlib.util.module_from_spec(spec)
        with patch.object(ctypes, "WinDLL", side_effect=lambda name, **kw: dlls[name],
                          create=True):
            spec.loader.exec_module(self.windows)
        self.kernel.GetActiveProcessorGroupCount.return_value = 1
        self.kernel.GetActiveProcessorCount.return_value = 2

    def test_cpu_set_layout_and_ranks(self):
        records = bytearray()
        for cpu, rank in ((0, 8), (1, 2)):
            record = bytearray(32)
            struct.pack_into("<II", record, 0, 32, 0)
            struct.pack_into("<HB", record, 12, 0, cpu)
            record[18] = rank
            records.extend(record)

        def cpu_sets(buf, size, returned, process, flags):
            returned._obj.value = len(records)
            if buf is None:
                return False
            ctypes.memmove(buf, bytes(records), len(records))
            return True

        self.kernel.GetSystemCpuSetInformation.side_effect = cpu_sets
        with patch.object(ctypes, "get_last_error", return_value=122, create=True):
            self.assertEqual(self.windows._performance_classes(),
                             {(0, 0): 8, (0, 1): 2})

    def test_native_clock_mapping(self):
        def power_info(level, input_buf, input_size, buf, size):
            self.assertEqual(level, 11)
            for index, info in enumerate(buf):
                info.Number = 1 - index
                info.MaxMhz = 4000
                info.CurrentMhz = 2000 + info.Number * 1000
                info.MhzLimit = 4000
            return 0

        self.power.CallNtPowerInformation.side_effect = power_info
        with patch.object(self.windows, "_performance_classes",
                          return_value={(0, 0): 8, (0, 1): 2}), \
                patch.object(self.windows, "_minimum_percent", return_value=10):
            self.assertEqual(self.windows.read_cpu_details(),
                             [(8, (2000, 400, 4000)), (2, (3000, 400, 4000))])

    def test_policy_memory_is_freed(self):
        def get_scheme(root, scheme):
            scheme._obj.value = 1234
            return 0

        def power_status(buf):
            buf[0] = 0
            return True

        def read_policy(root, scheme, subgroup, setting, value):
            value._obj.value = 5
            return 0

        self.power.PowerGetActiveScheme.side_effect = get_scheme
        self.kernel.GetSystemPowerStatus.side_effect = power_status
        self.power.PowerReadDCValueIndex.side_effect = read_policy
        self.assertEqual(self.windows._minimum_percent(), 5)
        self.kernel.LocalFree.assert_called_once()
        self.power.PowerReadACValueIndex.assert_not_called()
        self.power.PowerReadDCValueIndex.side_effect = RuntimeError("policy failure")
        with self.assertRaisesRegex(RuntimeError, "policy failure"):
            self.windows._minimum_percent()
        self.assertEqual(self.kernel.LocalFree.call_count, 2)

    def test_multi_group_does_not_misassign_clocks(self):
        self.kernel.GetActiveProcessorGroupCount.return_value = 2
        with patch.object(self.windows, "_performance_classes", return_value={}), \
                self.assertWarnsRegex(RuntimeWarning, "processor groups"):
            self.assertEqual(self.windows.read_cpu_details(), [(None, None)] * 4)
        self.power.CallNtPowerInformation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
