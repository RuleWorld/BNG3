if(NOT DEFINED BNG_CPP_PATH OR BNG_CPP_PATH STREQUAL "")
    message(FATAL_ERROR "BNG_CPP_PATH must name the bng_cpp executable")
endif()

if(NOT DEFINED WORK_DIR OR WORK_DIR STREQUAL "")
    set(WORK_DIR "${CMAKE_CURRENT_BINARY_DIR}/setparameter_numeric_power")
endif()

file(REMOVE_RECURSE "${WORK_DIR}")

foreach(action_scope IN ITEMS top_level protocol)
    set(model_dir "${WORK_DIR}/${action_scope}")
    file(MAKE_DIRECTORY "${model_dir}")

    if(action_scope STREQUAL "top_level")
        set(action_source "
setParameter(\"k\",2**3)
simulate_ode({t_start=>0,t_end=>1,n_steps=>8})
")
    else()
        set(action_source "
begin protocol
  setParameter(\"k\",2**3)
  simulate({method=>\"ode\",t_start=>0,t_end=>1,n_steps=>8})
end protocol
simulate_protocol()
")
    endif()

    set(model_path "${model_dir}/setparameter_${action_scope}.bngl")
    file(WRITE "${model_path}" "begin model
begin parameters
  k 0.4
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules A_count A()
  Molecules B_count B()
end observables
begin reaction rules
  convert: A() -> B() k
end reaction rules
${action_source}end model
")

    execute_process(
        COMMAND "${BNG_CPP_PATH}" "${model_path}"
        WORKING_DIRECTORY "${model_dir}"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE stdout_text
        ERROR_VARIABLE stderr_text
    )

    if(NOT result EQUAL 0)
        message(FATAL_ERROR
            "bng_cpp failed for ${action_scope} setParameter(\"k\",2**3) "
            "(exit ${result}).\nstdout:\n${stdout_text}\nstderr:\n${stderr_text}")
    endif()

    set(net_path "${model_dir}/setparameter_${action_scope}.net")
    if(NOT EXISTS "${net_path}")
        message(FATAL_ERROR
            "bng_cpp succeeded but wrote no network for ${action_scope} setParameter")
    endif()
    file(READ "${net_path}" net_text)
    if(NOT net_text MATCHES "[ \t]+k[ \t]+8([.]0*)?([ \t\r\n]|$)")
        message(FATAL_ERROR
            "${action_scope} setParameter(\"k\",2**3) should set k to 8.\n"
            "Network:\n${net_text}\nstdout:\n${stdout_text}\nstderr:\n${stderr_text}")
    endif()

    set(gdat_path "${model_dir}/setparameter_${action_scope}.gdat")
    if(NOT EXISTS "${gdat_path}")
        message(FATAL_ERROR
            "bng_cpp succeeded but wrote no trajectory for ${action_scope} setParameter")
    endif()
    file(READ "${gdat_path}" gdat_text)
    set(data_rows "")
    string(REPLACE "\n" ";" gdat_lines "${gdat_text}")
    foreach(raw_line IN LISTS gdat_lines)
        string(STRIP "${raw_line}" line)
        if(line STREQUAL "" OR line MATCHES "^#")
            continue()
        endif()
        list(APPEND data_rows "${line}")
    endforeach()
    list(LENGTH data_rows row_count)
    if(NOT row_count EQUAL 9)
        message(FATAL_ERROR
            "expected 9 trajectory rows for ${action_scope} setParameter, got ${row_count}.\n"
            "Trajectory:\n${gdat_text}")
    endif()
    list(GET data_rows 8 final_row)
    string(REGEX MATCH "^([0-9.eE+-]+)[ ]+([0-9.eE+-]+)" final_match "${final_row}")
    if(final_match STREQUAL "")
        message(FATAL_ERROR
            "could not read final time and A_count from ${action_scope} trajectory row:\n"
            "${final_row}")
    endif()
    set(final_time "${CMAKE_MATCH_1}")
    set(final_a_count "${CMAKE_MATCH_2}")
    if(NOT final_time STREQUAL "1.000000000000e+00")
        message(FATAL_ERROR
            "${action_scope} trajectory ended at ${final_time}, expected t=1.\n${gdat_text}")
    endif()
    # Matches test_ode_options.cpp's existing 2e-6 absolute bound for the
    # default CVODE tolerances and the analytic decay A(1) = 10*exp(-8).
    if(final_a_count LESS 0.003352626279 OR final_a_count GREATER 0.003356626279)
        message(FATAL_ERROR
            "${action_scope} setParameter(\"k\",2**3) trajectory ended at A=${final_a_count}; "
            "expected 10*exp(-8) within 2e-6.\nTrajectory:\n${gdat_text}")
    endif()
endforeach()

set(xor_dir "${WORK_DIR}/xor_guard")
file(MAKE_DIRECTORY "${xor_dir}")
file(WRITE "${xor_dir}/setparameter_xor.bngl" "begin model
begin parameters
  k 0.4
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules A_count A()
  Molecules B_count B()
end observables
begin reaction rules
  convert: A() -> B() k
end reaction rules
setParameter(\"k\",2^3)
end model
")
execute_process(
    COMMAND "${BNG_CPP_PATH}" "${xor_dir}/setparameter_xor.bngl"
    WORKING_DIRECTORY "${xor_dir}"
    RESULT_VARIABLE xor_result
    OUTPUT_VARIABLE xor_stdout
    ERROR_VARIABLE xor_stderr
)
if(xor_result EQUAL 0)
    message(FATAL_ERROR "setParameter(\"k\",2^3) must not treat Safe-Perl XOR as exponentiation")
endif()
string(FIND "${xor_stderr}\n${xor_stdout}"
    "Safe-Perl '^' is bitwise XOR; use '**' for exponentiation" xor_guard_message)
if(xor_guard_message EQUAL -1)
    message(FATAL_ERROR
        "setParameter XOR refusal did not explain Safe-Perl semantics.\n"
        "stdout:\n${xor_stdout}\nstderr:\n${xor_stderr}")
endif()

foreach(action_scope IN ITEMS top_level protocol)
    set(dynamic_xor_dir "${WORK_DIR}/dynamic_xor_${action_scope}")
    file(MAKE_DIRECTORY "${dynamic_xor_dir}")
    if(action_scope STREQUAL "top_level")
        set(dynamic_xor_actions "setParameter(\"k\",2^N)\n")
    else()
        set(dynamic_xor_actions "begin protocol
  setParameter(\"k\",2^N)
end protocol
simulate_protocol()
")
    endif()
    file(WRITE "${dynamic_xor_dir}/setparameter_dynamic_xor.bngl" "begin model
begin parameters
  k 0.4
  N 3
end parameters
${dynamic_xor_actions}end model
")
    execute_process(
        COMMAND "${BNG_CPP_PATH}" "setparameter_dynamic_xor.bngl"
        WORKING_DIRECTORY "${dynamic_xor_dir}"
        RESULT_VARIABLE dynamic_xor_result
        OUTPUT_VARIABLE dynamic_xor_stdout
        ERROR_VARIABLE dynamic_xor_stderr
    )
    if(dynamic_xor_result EQUAL 0)
        message(FATAL_ERROR
            "${action_scope} setParameter(\"k\",2^N) must refuse Safe-Perl XOR")
    endif()
    string(FIND "${dynamic_xor_stderr}\n${dynamic_xor_stdout}"
        "Safe-Perl '^' is bitwise XOR; use '**' for exponentiation" dynamic_xor_guard_message)
    if(dynamic_xor_guard_message EQUAL -1)
        message(FATAL_ERROR
            "${action_scope} dynamic setParameter XOR refusal did not explain Safe-Perl semantics.\n"
            "stdout:\n${dynamic_xor_stdout}\nstderr:\n${dynamic_xor_stderr}")
    endif()
endforeach()
