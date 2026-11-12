cmake_minimum_required(VERSION 3.24)
project(everyday CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
# Release = -O3 -DNDEBUG. Both languages build for the CPU they run on (target-cpu=native in rust/.cargo).
set(BENCH_ARCH_FLAGS "-march=native" CACHE STRING "CPU flags for the measured program")

add_executable(everyday src/everyday.cpp)
target_compile_options(everyday PRIVATE ${BENCH_ARCH_FLAGS})
