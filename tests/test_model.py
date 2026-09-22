import json
import unittest
from pathlib import Path

from esp_tlm.run import parse_jobs
from esp_tlm.at import ATMeshNoC, ATSoCSimulator
from esp_tlm.simulator import SoCSimulator
from esp_tlm.types import Transaction
from esp_tlm.noc import MeshNoC


ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "configs" / "esp_isscc2024.json").read_text())


class TestPlatform(unittest.TestCase):
    def test_mesh_adds_delay(self):
        noc = MeshNoC(rows=6, cols=6, planes=1, hop_ns=1.0, bytes_per_ns=16.0)
        arrival, delay = noc.transport(Transaction("x", 0, 5, 160, 0))
        self.assertEqual(arrival, delay)
        self.assertGreater(delay, 10)

    def test_direct_stream_skips_dram(self):
        scoped = {**CFG, "tiles": {**CFG["tiles"], **CFG["scenarios"]["direct_stream"]["tile_override"]}}
        r = SoCSimulator(scoped).run("direct", parse_jobs(CFG["scenarios"]["direct_stream"]["jobs"]))
        self.assertEqual(r.dram_bytes, 0)
        self.assertEqual(len(r.jobs), 2)

    def test_spad_scenario_runs(self):
        scenario = CFG["scenarios"]["llc_spad"]
        scoped = {**CFG, "tiles": {**CFG["tiles"], **scenario["tile_override"]}}
        report = SoCSimulator(scoped).run("spad", parse_jobs(scenario["jobs"]))
        self.assertGreater(report.makespan_ns, 0)
        self.assertEqual(len(report.jobs), 5)

    def test_at_engine_emits_four_phase_transactions(self):
        scenario = CFG["scenarios"]["direct_stream"]
        scoped = {**CFG, "tiles": {**CFG["tiles"], **scenario["tile_override"]}}
        report = ATSoCSimulator(scoped).run("at_direct", parse_jobs(scenario["jobs"]))
        phases = {event.phase for event in report.events}
        self.assertTrue({"BEGIN_REQ", "END_REQ", "BEGIN_RESP", "END_RESP"}.issubset(phases))
        self.assertGreater(report.packets, 0)
        self.assertGreater(len(report.events), 20)

    def test_at_virtual_channel_queue_is_observable(self):
        noc_cfg = {**CFG["noc"], "planes": 1}
        at_cfg = {**CFG["at"], "virtual_channels": 1}
        noc = ATMeshNoC(noc_cfg, at_cfg)
        noc.route("first", "REQ", 0, 1, 4096, 0)
        noc.route("second", "REQ", 0, 1, 4096, 0)
        self.assertGreater(noc.max_queue_ns, 0)

    def test_at_model_has_explicit_control_modules(self):
        scenario = CFG["scenarios"]["llc_spad"]
        scoped = {**CFG, "tiles": {**CFG["tiles"], **scenario["tile_override"]}}
        report = ATSoCSimulator(scoped).run("explicit", parse_jobs(scenario["jobs"]))
        modules = {module["name"]: module for module in report.explicit_modules}
        self.assertGreater(modules["iommu"]["transactions"], 0)
        self.assertGreater(modules["plic"]["transactions"], 0)
        self.assertGreater(modules["coherence_manager"]["transactions"], 0)

    def test_adas_workload_suite_runs(self):
        scenario = CFG["scenarios"]["adas_front_perception"]
        scoped = {**CFG, "tiles": {**CFG["tiles"], **scenario["tile_override"]}}
        report = ATSoCSimulator(scoped).run("adas_front", parse_jobs(scenario["jobs"]))
        self.assertEqual(len(report.jobs), 7)
        self.assertGreater(report.makespan_ns, 0)
        self.assertTrue(any(job.accelerator == "isp0" for job in report.jobs))


if __name__ == "__main__":
    unittest.main()
