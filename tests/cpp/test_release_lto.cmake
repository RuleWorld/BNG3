# Source-derived from NFsim commit 301bfbeb: Release LTO must be guarded by
# CheckIPOSupported and applied to the shared NFsim implementation plus each
# built consumer, while an explicit opt-out must disable the properties.

if(NOT DEFINED CONTRACT_PATH OR NOT EXISTS "${CONTRACT_PATH}")
    message(FATAL_ERROR "BNG3 LTO contract report is missing")
endif()

file(READ "${CONTRACT_PATH}" contract)
string(REPLACE "\n" ";" contract_lines "${contract}")

function(_contract_value key output)
    foreach(line IN LISTS contract_lines)
        if(line MATCHES "^${key}=(.*)$")
            set(${output} "${CMAKE_MATCH_1}" PARENT_SCOPE)
            return()
        endif()
    endforeach()
    message(FATAL_ERROR "BNG3 LTO contract report lacks ${key}")
endfunction()

_contract_value(NFSIM_ENABLE_LTO enable)
_contract_value(NFSIM_IPO_SUPPORTED supported)

set(targets
    nfsim_core
    bng_cpp
    _bionetgen_cpp
    NFsim)
foreach(target IN LISTS targets)
    _contract_value(${target}_RELEASE_IPO _${target}_ipo)
    set(${target}_RELEASE_IPO "${_${target}_ipo}")
endforeach()

set(expected FALSE)
if(enable STREQUAL "ON" AND supported STREQUAL "TRUE")
    set(expected TRUE)
endif()

foreach(target IN LISTS targets)
    set(actual "${${target}_RELEASE_IPO}")
    if(NOT actual STREQUAL "NOT_BUILT" AND NOT actual STREQUAL "${expected}")
        message(FATAL_ERROR
            "${target} Release IPO is ${actual}; expected ${expected}"
        )
    endif()
endforeach()
