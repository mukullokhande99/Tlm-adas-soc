# SystemC TLM-2.0 Migration Contract

The executable model is intentionally LT and transport-oriented. It maps to a
SystemC implementation without changing the experiment configuration:

| Python model | SystemC/TLM-2.0 equivalent |
| --- | --- |
| `Transaction` | `tlm::tlm_generic_payload` plus byte-enable/extension metadata |
| `MeshNoC.transport()` | NoC target socket / router process, annotated `sc_time` delay |
| `QueuedResource.service()` | memory target `b_transport()` service queue |
| accelerator job | initiator process, MMIO programming transaction, DMA initiator socket |
| `TokenPowerManager` | PM-controller module, analysis port plus V/F state table |
| JSON job trace | software workload trace, QEMU/SystemC virtual-platform stimulus |

## Recommended implementation order

1. Turn every CPU, accelerator, memory partition, and router into a
   `sc_module`; keep the JSON address/tile configuration unchanged.
2. Use `tlm_utils::simple_initiator_socket` for accelerator DMA and
   `simple_target_socket` for LLC/SPAD/DRAM endpoints.
3. Implement blocking transport first and pass modeled NoC and memory delay
   through `sc_time& delay`.
4. Replace the link availability scalar with per-router virtual channels for
   approximately timed (four-phase) transactions only if queue attribution is
   insufficient.
5. Connect a RISC-V ISS/QEMU only after trace-based traffic validates the
   architecture assumptions; it should replace workload injection, not the
   NoC/memory/DHPM model.

## Included native AT reference

`systemc_reference/at_reference.cpp` is a compact, buildable TLM-2.0 protocol
example once SystemC is installed. It exchanges `BEGIN_REQ`, `END_REQ`,
`BEGIN_RESP`, and `END_RESP` through `nb_transport_fw()` and
`nb_transport_bw()`. The runnable Python AT engine uses the same phase contract
for full mesh and workload experiments.

## Calibration data still needed

- router flit width, packetization, arbitration/QoS and clock domains;
- LLC and DRAM queue policies, DMA burst sizes, coherency transactions;
- accelerator compute/traffic traces per workload and dependency graph;
- measured V/F/token LUT and LDO/TRO settling behavior.

Those data should be added as configuration or traces rather than embedded in
the SystemC source, preserving reproducibility across design variants.
