// Native TLM-2.0 approximately-timed protocol reference.
// Build with CMake after installing SystemC. This deliberately shows the
// non-blocking four-phase interface used by the Python AT experiment engine.
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>
#include <iostream>

struct ATMemory : sc_core::sc_module {
  tlm_utils::simple_target_socket<ATMemory> socket{"socket"};
  sc_core::sc_time request_delay{2, sc_core::SC_NS};
  sc_core::sc_time service_delay{12, sc_core::SC_NS};

  ATMemory(sc_core::sc_module_name name) : sc_module(name) {
    socket.register_nb_transport_fw(this, &ATMemory::nb_transport_fw);
  }

  tlm::tlm_sync_enum nb_transport_fw(tlm::tlm_generic_payload& tx,
                                     tlm::tlm_phase& phase,
                                     sc_core::sc_time& delay) {
    if (phase != tlm::BEGIN_REQ) return tlm::TLM_ACCEPTED;
    phase = tlm::END_REQ;
    delay += request_delay;
    socket->nb_transport_bw(tx, phase, delay);
    phase = tlm::BEGIN_RESP;
    delay += service_delay;
    tx.set_response_status(tlm::TLM_OK_RESPONSE);
    return socket->nb_transport_bw(tx, phase, delay);
  }
};

struct ATDMA : sc_core::sc_module {
  tlm_utils::simple_initiator_socket<ATDMA> socket{"socket"};
  tlm::tlm_generic_payload tx;
  unsigned char data[64]{};

  ATDMA(sc_core::sc_module_name name) : sc_module(name) {
    socket.register_nb_transport_bw(this, &ATDMA::nb_transport_bw);
    SC_THREAD(run);
  }

  void run() {
    tx.set_command(tlm::TLM_READ_COMMAND);
    tx.set_address(0x80000000);
    tx.set_data_ptr(data);
    tx.set_data_length(sizeof(data));
    tx.set_streaming_width(sizeof(data));
    tlm::tlm_phase phase = tlm::BEGIN_REQ;
    sc_core::sc_time delay = sc_core::SC_ZERO_TIME;
    socket->nb_transport_fw(tx, phase, delay);
  }

  tlm::tlm_sync_enum nb_transport_bw(tlm::tlm_generic_payload& payload,
                                     tlm::tlm_phase& phase,
                                     sc_core::sc_time& delay) {
    if (phase == tlm::END_REQ) {
      std::cout << "END_REQ at " << sc_core::sc_time_stamp() + delay << '\n';
      return tlm::TLM_ACCEPTED;
    }
    if (phase == tlm::BEGIN_RESP) {
      std::cout << "BEGIN_RESP at " << sc_core::sc_time_stamp() + delay << '\n';
      phase = tlm::END_RESP;
      socket->nb_transport_fw(payload, phase, delay);
      std::cout << "END_RESP at " << sc_core::sc_time_stamp() + delay << '\n';
      return tlm::TLM_COMPLETED;
    }
    return tlm::TLM_ACCEPTED;
  }
};

int sc_main(int, char**) {
  ATDMA dma{"dma"};
  ATMemory memory{"memory"};
  dma.socket.bind(memory.socket);
  sc_core::sc_start(sc_core::sc_time(100, sc_core::SC_NS));
  return 0;
}
