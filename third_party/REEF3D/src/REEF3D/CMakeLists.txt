cmake_minimum_required(VERSION 3.21)

project(REEF3D_Windows LANGUAGES CXX)

get_filename_component(REEF3D_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(HYPRE_ROOT "${REEF3D_ROOT}/build/hypre-install" CACHE PATH "Path to a Hypre install tree")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

foreach(_config DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
  string(TOUPPER "${_config}" _config_upper)
  set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_${_config_upper} "${REEF3D_ROOT}/bin")
endforeach()
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${REEF3D_ROOT}/bin")

execute_process(
  COMMAND git rev-parse --abbrev-ref HEAD
  WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
  OUTPUT_VARIABLE REEF3D_GIT_BRANCH
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)
execute_process(
  COMMAND git rev-parse --short=7 HEAD
  WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
  OUTPUT_VARIABLE REEF3D_GIT_COMMIT
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET
)
if(NOT REEF3D_GIT_BRANCH)
  set(REEF3D_GIT_BRANCH "unknown")
endif()
if(NOT REEF3D_GIT_COMMIT)
  set(REEF3D_GIT_COMMIT "unknown")
endif()

if(WIN32)
  set(_MSMPI_INC "C:/Program Files (x86)/Microsoft SDKs/MPI/Include")
  set(_MSMPI_LIB "C:/Program Files (x86)/Microsoft SDKs/MPI/Lib/x64/msmpi.lib")
endif()

find_package(MPI QUIET COMPONENTS CXX)

if(NOT MPI_CXX_FOUND AND TARGET MPI::MPI_CXX)
  set(MPI_CXX_FOUND TRUE)
endif()

if(NOT MPI_CXX_FOUND AND WIN32 AND EXISTS "${_MSMPI_INC}/mpi.h" AND EXISTS "${_MSMPI_LIB}")
  add_library(MPI::MPI_CXX INTERFACE IMPORTED)
  set_target_properties(MPI::MPI_CXX PROPERTIES
    INTERFACE_INCLUDE_DIRECTORIES "${_MSMPI_INC}"
    INTERFACE_LINK_LIBRARIES "${_MSMPI_LIB}"
  )
  set(MPI_CXX_FOUND TRUE)
endif()

if(NOT MPI_CXX_FOUND)
  message(FATAL_ERROR "MPI C++ was not found. Install MS-MPI runtime and SDK, or set MPI_CXX include/library cache variables.")
endif()

set(REEF3D_MPI_INCLUDE_DIRS ${MPI_CXX_INCLUDE_DIRS})
set(REEF3D_MPI_LIBRARIES ${MPI_CXX_LIBRARIES})
if(WIN32 AND EXISTS "${_MSMPI_INC}/mpi.h" AND EXISTS "${_MSMPI_LIB}")
  list(APPEND REEF3D_MPI_INCLUDE_DIRS "${_MSMPI_INC}")
  list(APPEND REEF3D_MPI_LIBRARIES "${_MSMPI_LIB}")
endif()

set(HYPRE_INCLUDE_DIR "${HYPRE_ROOT}/include")
set(HYPRE_LIBRARY "${HYPRE_ROOT}/lib/HYPRE.lib")
if(NOT EXISTS "${HYPRE_INCLUDE_DIR}/HYPRE.h" OR NOT EXISTS "${HYPRE_LIBRARY}")
  message(FATAL_ERROR "Hypre was not found at ${HYPRE_ROOT}. Build/install Hypre first, or pass -DHYPRE_ROOT=<path>.")
endif()

file(GLOB REEF3D_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp")

add_executable(reef3d ${REEF3D_SOURCES})
target_include_directories(reef3d PRIVATE
  "${CMAKE_CURRENT_SOURCE_DIR}/src"
  "${CMAKE_CURRENT_SOURCE_DIR}/ThirdParty/eigen-3.3.8"
  "${HYPRE_INCLUDE_DIR}"
  ${REEF3D_MPI_INCLUDE_DIRS}
)
target_link_libraries(reef3d PRIVATE MPI::MPI_CXX "${HYPRE_LIBRARY}" ${REEF3D_MPI_LIBRARIES})
target_compile_features(reef3d PRIVATE cxx_std_17)
target_compile_definitions(reef3d PRIVATE
  VERSION="${REEF3D_GIT_COMMIT}"
  BRANCH="${REEF3D_GIT_BRANCH}"
  BUILD="$<CONFIG>"
  EIGEN_MPL2_ONLY
  _CRT_SECURE_NO_WARNINGS
  NOMINMAX
  _USE_MATH_DEFINES
)

if(MSVC)
  target_compile_options(reef3d PRIVATE /EHsc /MP /bigobj /W0 /wd4819 "/FI${CMAKE_CURRENT_SOURCE_DIR}/cmake/win_compat.h")
else()
  target_compile_options(reef3d PRIVATE -include "${CMAKE_CURRENT_SOURCE_DIR}/cmake/win_compat.h")
endif()

set_target_properties(reef3d PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${REEF3D_ROOT}/bin"
  RUNTIME_OUTPUT_DIRECTORY_DEBUG "${REEF3D_ROOT}/bin"
  RUNTIME_OUTPUT_DIRECTORY_RELEASE "${REEF3D_ROOT}/bin"
  RUNTIME_OUTPUT_DIRECTORY_RELWITHDEBINFO "${REEF3D_ROOT}/bin"
  RUNTIME_OUTPUT_DIRECTORY_MINSIZEREL "${REEF3D_ROOT}/bin"
)

set(DIVEMESH_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../DIVEMesh")
if(EXISTS "${DIVEMESH_SOURCE_DIR}/CMakeLists.txt")
  add_subdirectory("${DIVEMESH_SOURCE_DIR}" "${CMAKE_BINARY_DIR}/DIVEMesh")
endif()
