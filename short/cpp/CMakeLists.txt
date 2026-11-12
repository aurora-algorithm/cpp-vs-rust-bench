cmake_minimum_required(VERSION 3.24)
project(cpp_vs_rust_short CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
# Release = -O3 -DNDEBUG. Both languages build for the CPU they run on (target-cpu=native in rust/.cargo).
set(BENCH_ARCH_FLAGS "-march=native" CACHE STRING "CPU flags for every target")

include(FetchContent)
FetchContent_Declare(nlohmann_json
  URL https://github.com/nlohmann/json/releases/download/v3.12.0/json.tar.xz
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
FetchContent_Declare(simdjson
  GIT_REPOSITORY https://github.com/simdjson/simdjson.git
  GIT_TAG v5.1.0
  GIT_SHALLOW TRUE)
set(SIMDJSON_DEVELOPER_MODE OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(nlohmann_json simdjson)

foreach(t parse_popular parse_fastest)
  add_executable(${t} src/${t}.cpp)
  target_compile_options(${t} PRIVATE ${BENCH_ARCH_FLAGS})
endforeach()
target_link_libraries(parse_popular PRIVATE nlohmann_json::nlohmann_json)
target_link_libraries(parse_fastest PRIVATE simdjson::simdjson)
