cmake_minimum_required(VERSION 3.21)

project(DIVEMesh LANGUAGES CXX)

get_filename_component(REEF3D_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)

file(GLOB DIVEMESH_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp")

add_executable(DiveMESH ${DIVEMESH_SOURCES})
target_include_directories(DiveMESH PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_compile_features(DiveMESH PRIVATE cxx_std_17)
target_compile_definitions(DiveMESH PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX _USE_MATH_DEFINES)

if(MSVC)
  target_compile_options(DiveMESH PRIVATE /EHsc /MP /bigobj /W0 /wd4819 "/FI${CMAKE_CURRENT_SOURCE_DIR}/cmake/win_compat.h")
else()
  target_compile_options(DiveMESH PRIVATE -include "${CMAKE_CURRENT_SOURCE_DIR}/cmake/win_compat.h")
endif()

set_target_properties(DiveMESH PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${REEF3D_ROOT}/bin"
  RUNTIME_OUTPUT_DIRECTORY_DEBUG "${REEF3D_ROOT}/bin"
  RUNTIME_OUTPUT_DIRECTORY_RELEASE "${REEF3D_ROOT}/bin"
  RUNTIME_OUTPUT_DIRECTORY_RELWITHDEBINFO "${REEF3D_ROOT}/bin"
  RUNTIME_OUTPUT_DIRECTORY_MINSIZEREL "${REEF3D_ROOT}/bin"
)
