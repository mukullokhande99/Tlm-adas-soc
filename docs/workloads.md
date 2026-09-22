# Supplied workload cases

The workload cases are executable job traces in the configuration file under
the scenarios key. Each job supplies its accelerator endpoint, release time,
input/output traffic, abstract operation count, memory-orchestration mode and
optional producer dependency.

| Scenario | Jobs | Intent |
| --- | --- | --- |
| baseline | vision, NLP, navigation, AES, analytics | One LLC bank and non-coherent DMA reference case |
| llc_spad | vision, NLP, navigation, AES, analytics | LLC/SPAD partitioning plus coherent and flush traffic |
| direct_stream | audio decode to FFT | Accelerator-to-accelerator stream without a DRAM round trip |
| dhpm_5accel | NVDLA, NLP, vision, crypto, Viterbi | Five overlapping accelerators competing for DHPM power tokens |

List them directly:

    python3 experiments/list_workloads.py

Run a workload through the AT model:

    python3 -m esp_tlm.at_run --config configs/esp_isscc2024.json --scenario dhpm_5accel

These workloads are architectural traces for comparative exploration; they are
not confidential firmware traces from the ISSCC chip.
