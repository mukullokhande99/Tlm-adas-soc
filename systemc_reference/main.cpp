// Minimal SystemC/TLM-2.0 counterpart to the Python LT model.
// This is a buildable starting point once SystemC is installed; it is not a
// replacement for the full configurable Python experiment engine.
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>
#include <algorithm>
#include <iostream>

struct MemoryTile : sc_core::sc_module {
  tlm_utils::simple_target_socket<MemoryTile> socket{"socket"};
  double bytes_per_ns;
  sc_core::sc_time base_latency;

  MemoryTile(sc_core::sc_module_name name, double bw, sc_core::sc_time latency)
      : sc_module(name), bytes_per_ns(bw), base_latency(latency) {
    socket.register_b_transport(this, &MemoryTile::b_transport);
  }
  void b_transport(tlm::tlm_generic_payload& tx, sc_core::sc_time& delay) {
    delay += base_latency + sc_core::sc_time(tx.get_data_length() / bytes_per_ns,
                                              sc_core::SC_NS);
    tx.set_response_status(tlm::TLM_OK_RESPONSE);
  }
};

struct Accelerator : sc_core::sc_module {
  tlm_utils::simple_initiator_socket<Accelerator> dma{"dma"};
  double ops_per_cycle;
  double frequency_ghz;

  Accelerator(sc_core::sc_module_name name, double opc, double f)
      : sc_module(name), ops_per_cycle(opc), frequency_ghz(f) {
    SC_THREAD(run);
  }
  void run() {
    unsigned char data[64]{};
    tlm::tlm_generic_payload tx;
    tx.set_command(tlm::TLM_READ_COMMAND);
    tx.set_address(0);
    tx.set_data_ptr(data);
    tx.set_data_length(sizeof(data));
    tx.set_streaming_width(sizeof(data));
    sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
    dma->b_transport(tx, delay);               // LT DMA read transaction
    wait(delay);
    wait(sc_core::sc_time(1e6 / (ops_per_cycle * frequency_ghz), sc_core::SC_NS));
    std::cout << name() << " finished at " << sc_core::sc_time_stamp() << '\n';
  }
};

int sc_main(int, char**) {
  MemoryTile llc{"llc", 32.0, sc_core::sc_time(12, sc_core::SC_NS)};
  Accelerator fft{"fft", 64.0, 0.72};
  fft.dma.bind(llc.socket);
  sc_core::sc_start();
  return 0;
}
