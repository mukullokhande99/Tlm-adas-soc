# Supplied workload cases

The workload cases are executable job traces in the configuration scenarios
key. Each job supplies its accelerator endpoint, release time, input/output
traffic, abstract operation count, memory-orchestration mode and optional
producer dependency.

## Architecture stress cases

| Scenario | Jobs | Intent |
| --- | --- | --- |
| baseline | vision, NLP, navigation, AES, analytics | One LLC bank and non-coherent DMA reference case |
| llc_spad | vision, NLP, navigation, AES, analytics | LLC/SPAD partitioning plus coherent and flush traffic |
| direct_stream | audio decode to FFT | Accelerator-to-accelerator stream without a DRAM round trip |
| dhpm_5accel | NVDLA, NLP, vision, crypto, Viterbi | Five overlapping accelerators competing for DHPM power tokens |

## ADAS workload suite

| Scenario | Pipeline represented | Prior-work basis |
| --- | --- | --- |
| adas_front_perception | 1920x1200 camera ISP, vehicle/pedestrian detection, lane segmentation, traffic-sign classification, 2D tracking, EKF localization and collision risk | YOLO/KITTI, Caltech pedestrian, Caltech Lane, GTSRB/BTSD/STSD |
| adas_driver_monitoring | NIR ISP, face detection, head pose, eye-gaze/blink, hand tracking, driver-state classification and attention alert | ICT-3DHP, Yale B, in-cabin driver status work |
| adas_surround_fusion | Front/side perception, radar FFT, IMU-visual EKF, BEV fusion, world tracking and hazard decision | Four-camera ADAS flow with radar/IMU fusion |
| adas_pilotnet_control | Camera ISP, PilotNet inference, lane geometry and steering/throttle/brake decision | PilotNet end-to-end driving workload |
| adas_event_hazard | Event denoising, event object/lane perception, temporal tracking and hazard alert | Event-based perception and NEST-ADAS-style temporal pipeline |

The configured jobs deliberately use the available SoC endpoints as
architecture-model mappings: isp0 for camera preprocessing, NVDLA/vision
tiles for neural perception, AD for tracking, GPS for EKF/localization, FFT for
radar preprocessing and matrix for fusion or safety decision stages.

List every workload:

    python3 experiments/list_workloads.py

Run all AT workloads:

    python3 experiments/run_at_all.py

Run one workload:

    python3 -m esp_tlm.at_run --config configs/esp_isscc2024.json --scenario adas_surround_fusion

These are architectural traces for comparative exploration, not confidential
firmware traces or claims of application accuracy.
