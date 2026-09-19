# cpp/CMakeLists.unify.snippet.cmake
# ----------------------------------------------------------------------------
# Mechanical dedup edits. These are the low-risk halves of WO-1 and WO-3:
# build hygiene only, no algorithm change. Apply them, rebuild, run
#   pytest tests/validation -m smoke
# Nothing here touches canonical-labeling or expression *semantics* — those are
# the gated algorithmic WOs (WO-1a, WO-3 evaluator unification).
#
# This file documents the exact edits to make in cpp/CMakeLists.txt. It is not
# included directly; copy the changes in.
# ----------------------------------------------------------------------------

# ============================================================================
# WO-1b — One nauty C library  [APPLIED 2026-09-17]
# ----------------------------------------------------------------------------
# STATUS: applied. cpp/nauty is the only compiled tree, cpp/nfsim/nauty24/ is
# deleted, nfsim_core links the `nauty` target, and complex.cpp includes the
# shared header. The trees were verified identical after normalizing the
# documented set->nset rename, so the unification adopted the nset variant
# (which also carries an MSVC HAVE_SYSTYPES_H guard cpp/nauty lacked).
# Locked in by tests/python/test_single_nauty_contract.py. See
# cpp/nauty/README.md. Link/runtime identity evidence still requires CI and an
# independent NFsim oracle.
#
# Historical instructions retained below for provenance.
# ----------------------------------------------------------------------------
# Today: `nauty` is built from cpp/nauty/*.c, and `nfsim_core` *additionally*
# globs and compiles cpp/nfsim/nauty24/*.c. Two builds of the same upstream
# library are linked into one binary. Link one.
#
# REMOVE from the nfsim_core section:
#     file(GLOB NFSIM_NAUTY_C "${NFSIM_DIR}/nauty24/*.c")
#     ... and the inclusion of NFSIM_NAUTY_C in nfsim_core's sources ...
#     target_include_directories(nfsim_core PUBLIC ... ${NFSIM_DIR}/nauty24 ...)
#
# REPLACE with: link the existing `nauty` target and point includes at it.
#
#   add_library(nfsim_core STATIC ${NFSIM_LIB_SOURCES})   # NFSIM_LIB_SOURCES no longer includes nauty24
#   target_link_libraries(nfsim_core PUBLIC nauty)
#   target_include_directories(nfsim_core PUBLIC
#       ${NFSIM_DIR}
#       ${NFSIM_DIR}/NFcore
#       # ... existing NFsim include dirs ...
#       $<TARGET_PROPERTY:nauty,INTERFACE_INCLUDE_DIRECTORIES>
#   )
#
# NOTE: cpp/nauty and cpp/nfsim/nauty24 must be byte-identical upstream nauty for
# this to be safe. Verify before deleting:
#     diff -r cpp/nauty/nauty24 cpp/nfsim/nauty24
# If they differ (patched headers, NFsim-local tweaks), reconcile first — do not
# assume. After the build is green, delete cpp/nfsim/nauty24/ (WO-6).

# ============================================================================
# WO-3b — Drop exprtk from nfsim_core  [APPLIED 2026-09-17]
# ----------------------------------------------------------------------------
# STATUS: applied, together with the WO-3 evaluator swap it depended on.
# nfsim_funcparser.h keeps the mu::Parser interface but is backed by
# bng::parser::parseExpression + bng::eval::evaluate. NFSIM_USE_EXPRTK, the
# exprtk include paths, and the root FetchContent_Declare(exprtk) block are all
# removed. Requires full CI: the expression and NFsim parity gates have not
# been run against the merged evaluator.
# ----------------------------------------------------------------------------
# Today: nfsim_core compiles with NFSIM_USE_EXPRTK and fetches exprtk for its
# function evaluation, parallel to bng::ast::Expression. After WO-3 routes NFsim
# functions through the shared evaluator (see ExpressionEval.hpp), exprtk is dead.
#
# REMOVE:
#     target_compile_definitions(nfsim_core PUBLIC TIXML_USE_STL NFSIM_USE_EXPRTK)
#     target_include_directories(nfsim_core PRIVATE ${exprtk_SOURCE_DIR})
#     # and the FetchContent_Declare/MakeAvailable(exprtk) block
#
# REPLACE compile defs with (keep TinyXML's STL flag):
#     target_compile_definitions(nfsim_core PUBLIC TIXML_USE_STL)
#
# Do this only AFTER WO-3's evaluator swap is green on -m expressions, or NFsim
# functions will fail to compile/evaluate.

# ============================================================================
# WO-4 — Stop building the NFsim standalone main on the default path
#        [ALREADY APPLIED]
# ----------------------------------------------------------------------------
# STATUS: applied. cpp/CMakeLists.txt already guards the NFsim executable with
# if(BUILD_NFSIM_CLI). Historical instructions retained below.
# ----------------------------------------------------------------------------
# The `NFsim` executable target stays (the validation harness uses it as the
# native oracle), but it is opt-in. Guard it so the default `pip install` /
# library build does not produce a second CLI that duplicates `bionetgen run`:
#
#   option(BUILD_NFSIM_CLI "Build the standalone NFsim executable (oracle only)" OFF)
#   if(BUILD_NFSIM_CLI)
#       add_executable(NFsim ${NFSIM_DIR}/NFsim.cpp ${NFSIM_TEST_SRC})
#       target_link_libraries(NFsim PRIVATE nfsim_core)
#       ...
#   endif()
#
# CI builds the oracle with -DBUILD_NFSIM_CLI=ON for the -m nf gate.
