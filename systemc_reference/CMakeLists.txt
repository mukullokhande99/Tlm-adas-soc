cmake_minimum_required(VERSION 3.18)
project(esp_tlm_reference LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)

# Set SYSTEMC_HOME or pass -DSystemC_ROOT=<install-prefix>.
find_package(SystemC REQUIRED)
add_executable(esp_tlm_reference main.cpp)
target_link_libraries(esp_tlm_reference PRIVATE SystemC::systemc)

add_executable(esp_tlm_at_reference at_reference.cpp)
target_link_libraries(esp_tlm_at_reference PRIVATE SystemC::systemc)
