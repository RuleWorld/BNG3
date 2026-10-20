# Install script for directory: /private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/src/sundials

# Set the install prefix
if(NOT DEFINED CMAKE_INSTALL_PREFIX)
  set(CMAKE_INSTALL_PREFIX "/usr/local")
endif()
string(REGEX REPLACE "/$" "" CMAKE_INSTALL_PREFIX "${CMAKE_INSTALL_PREFIX}")

# Set the install configuration name.
if(NOT DEFINED CMAKE_INSTALL_CONFIG_NAME)
  if(BUILD_TYPE)
    string(REGEX REPLACE "^[^A-Za-z0-9_]+" ""
           CMAKE_INSTALL_CONFIG_NAME "${BUILD_TYPE}")
  else()
    set(CMAKE_INSTALL_CONFIG_NAME "RelWithDebInfo")
  endif()
  message(STATUS "Install configuration: \"${CMAKE_INSTALL_CONFIG_NAME}\"")
endif()

# Set the component getting installed.
if(NOT CMAKE_INSTALL_COMPONENT)
  if(COMPONENT)
    message(STATUS "Install component: \"${COMPONENT}\"")
    set(CMAKE_INSTALL_COMPONENT "${COMPONENT}")
  else()
    set(CMAKE_INSTALL_COMPONENT)
  endif()
endif()

# Is this installation the result of a crosscompile?
if(NOT DEFINED CMAKE_CROSSCOMPILING)
  set(CMAKE_CROSSCOMPILING "FALSE")
endif()

# Set path to fallback-tool for dependency-resolution.
if(NOT DEFINED CMAKE_OBJDUMP)
  set(CMAKE_OBJDUMP "/usr/bin/objdump")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  MESSAGE("
Install shared components
")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "/private/tmp/bng3-issue-reconcile/build-asan/_deps/sundials-build/src/sundials/libsundials_core.a")
  if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/libsundials_core.a" AND
     NOT IS_SYMLINK "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/libsundials_core.a")
    execute_process(COMMAND "/usr/bin/ranlib" "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/libsundials_core.a")
  endif()
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include/sundials" TYPE FILE FILES
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_adaptcontroller.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_adaptcontroller.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_adjointcheckpointscheme.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_adjointcheckpointscheme.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_adjointstepper.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_adjointstepper.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_band.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_base.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_classview.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_context.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_context.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_convertibleto.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_core.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_core.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_dense.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_direct.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_domeigestimator.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_domeigestimator.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_errors.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_futils.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_iterative.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_linearsolver.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_linearsolver.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_logger.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_logger.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_math.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_matrix.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_matrix.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_memory.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_memory.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_mpi_types.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_nonlinearsolver.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_nonlinearsolver.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_nvector.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_nvector.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_profiler.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_profiler.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_stepper.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_stepper.hpp"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_types_deprecated.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_types.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/sundials_version.h"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include/sundials/priv" TYPE FILE FILES
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/priv/sundials_context_impl.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/priv/sundials_errors_impl.h"
    "/private/tmp/bng3-issue-reconcile/build/_deps/sundials-src/include/sundials/priv/sundials_logger_macros.h"
    )
endif()

string(REPLACE ";" "\n" CMAKE_INSTALL_MANIFEST_CONTENT
       "${CMAKE_INSTALL_MANIFEST_FILES}")
if(CMAKE_INSTALL_LOCAL_ONLY)
  file(WRITE "/private/tmp/bng3-issue-reconcile/build-asan/_deps/sundials-build/src/sundials/install_local_manifest.txt"
     "${CMAKE_INSTALL_MANIFEST_CONTENT}")
endif()
