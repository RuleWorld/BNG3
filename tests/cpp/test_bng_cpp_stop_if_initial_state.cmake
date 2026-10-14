if(NOT DEFINED BNG_CPP_PATH OR BNG_CPP_PATH STREQUAL "")
    message(FATAL_ERROR "BNG_CPP_PATH must name the bng_cpp executable")
endif()
if(NOT DEFINED WORK_DIR OR WORK_DIR STREQUAL "")
    set(WORK_DIR "${CMAKE_CURRENT_BINARY_DIR}/stop_if_initial_state")
endif()

file(REMOVE_RECURSE "${WORK_DIR}")

function(write_model model_path method rate stop_if_expression sample_times seed_amount t_start t_end)
    set(n_steps_option "n_steps=>2,")
    if(NOT "${sample_times}" STREQUAL "")
        # Supplying both options makes n_steps take precedence in ActionDispatch.
        set(n_steps_option "")
    endif()
    set(sample_times_option "")
    if(NOT "${sample_times}" STREQUAL "")
        set(sample_times_option ",sample_times=>${sample_times}")
    endif()
    set(seed_option "")
    if(method STREQUAL "ssa")
        set(seed_option ",seed=>31415")
    endif()

    file(WRITE "${model_path}"
"begin model
begin parameters
  N 4
  k ${rate}
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() ${seed_amount}
  B() 0
end seed species
begin observables
  Molecules A_count A()
  Molecules B_count B()
end observables
begin reaction rules
  convert: A() -> B() k
end reaction rules
simulate({method=>\"${method}\",t_start=>${t_start},t_end=>${t_end},${n_steps_option}stop_if=>\"${stop_if_expression}\"${sample_times_option}${seed_option}})
end model
")
endfunction()

function(assert_initial_row case_name initial_row expected_time expected_a expected_b gdat_text)
    string(REGEX MATCH "^([0-9.eE+-]+)[ \t]+([0-9.eE+-]+)[ \t]+([0-9.eE+-]+)"
        initial_match "${initial_row}")
    if(initial_match STREQUAL "")
        message(SEND_ERROR
            "${case_name} could not read the initial time/A/B values from row:\n"
            "${initial_row}\nTrajectory:\n${gdat_text}")
        return()
    endif()
    set(initial_time "${CMAKE_MATCH_1}")
    set(initial_a "${CMAKE_MATCH_2}")
    set(initial_b "${CMAKE_MATCH_3}")
    if((NOT expected_time STREQUAL "*" AND
        NOT initial_time STREQUAL expected_time) OR
       (NOT expected_a STREQUAL "*" AND NOT initial_a STREQUAL expected_a) OR
       (NOT expected_b STREQUAL "*" AND NOT initial_b STREQUAL expected_b))
        message(SEND_ERROR
            "${case_name} initial row was (${initial_time}, ${initial_a}, ${initial_b}), "
            "expected (${expected_time}, ${expected_a}, ${expected_b}).\n"
            "Trajectory:\n${gdat_text}")
    endif()
endfunction()

function(run_case case_name method rate stop_if_expression expected_rows sample_times seed_amount t_start t_end expected_time expected_a expected_b)
    set(case_dir "${WORK_DIR}/${case_name}")
    file(MAKE_DIRECTORY "${case_dir}")
    set(model_path "${case_dir}/stop_if.bngl")
    write_model("${model_path}" "${method}" "${rate}" "${stop_if_expression}"
        "${sample_times}" "${seed_amount}" "${t_start}" "${t_end}")

    execute_process(
        COMMAND "${BNG_CPP_PATH}" "stop_if.bngl"
        WORKING_DIRECTORY "${case_dir}"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE stdout_text
        ERROR_VARIABLE stderr_text
    )
    if(NOT result EQUAL 0)
        message(SEND_ERROR
            "${case_name} simulation failed (exit ${result}).\n"
            "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
        return()
    endif()

    set(gdat_path "${case_dir}/stop_if.gdat")
    if(NOT EXISTS "${gdat_path}")
        message(SEND_ERROR "${case_name} simulation wrote no trajectory")
        return()
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
    if(NOT row_count EQUAL expected_rows)
        message(SEND_ERROR
            "${case_name} expected ${expected_rows} rows, got ${row_count}.\n"
            "Trajectory:\n${gdat_text}")
    endif()
    if(row_count GREATER 0)
        list(GET data_rows 0 initial_row)
        assert_initial_row("${case_name}" "${initial_row}" "${expected_time}"
            "${expected_a}" "${expected_b}" "${gdat_text}")
    endif()
endfunction()

function(run_zero_species_case case_name sample_times t_start t_end expected_time)
    set(case_dir "${WORK_DIR}/${case_name}")
    file(MAKE_DIRECTORY "${case_dir}")
    set(model_path "${case_dir}/stop_if.bngl")
    set(n_steps_option "n_steps=>2,")
    set(sample_times_option "")
    if(NOT "${sample_times}" STREQUAL "")
        set(n_steps_option "")
        set(sample_times_option ",sample_times=>${sample_times}")
    endif()
    file(WRITE "${model_path}"
"begin model
begin parameters
  N 4
end parameters
begin molecule types
  A()
end molecule types
simulate({method=>\"cvode\",t_start=>${t_start},t_end=>${t_end},${n_steps_option}stop_if=>\"2^N\"${sample_times_option}})
end model
")

    execute_process(
        COMMAND "${BNG_CPP_PATH}" "stop_if.bngl"
        WORKING_DIRECTORY "${case_dir}"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE stdout_text
        ERROR_VARIABLE stderr_text
    )
    if(NOT result EQUAL 0)
        message(SEND_ERROR
            "${case_name} failed (exit ${result}).\n"
            "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
        return()
    endif()

    set(gdat_path "${case_dir}/stop_if.gdat")
    if(NOT EXISTS "${gdat_path}")
        message(SEND_ERROR "${case_name} wrote no trajectory")
        return()
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
    if(NOT row_count EQUAL 1)
        message(SEND_ERROR
            "${case_name} should keep only the initial row, got ${row_count}.\n"
            "Trajectory:\n${gdat_text}")
        return()
    endif()
    list(GET data_rows 0 initial_row)
    string(REGEX MATCH "^([0-9.eE+-]+)" initial_match "${initial_row}")
    if(initial_match STREQUAL "")
        message(SEND_ERROR
            "${case_name} could not read the initial time from row '${initial_row}'.\n"
            "Trajectory:\n${gdat_text}")
        return()
    endif()
    set(initial_time "${CMAKE_MATCH_1}")
    if(NOT initial_time STREQUAL expected_time)
        message(SEND_ERROR
            "${case_name} should retain t=${expected_time}, got t=${initial_time}.\n"
            "Trajectory:\n${gdat_text}")
    endif()
endfunction()

# The default output grid includes t_start, so an already-true stop_if must
# retain that initial row and stop before advancing. A false condition still
# produces the complete three-row grid.
foreach(method IN ITEMS cvode euler rk4)
    run_case("${method}_initial_true" "${method}" "1" "2^N" 1 ""
        "10" "0" "1" "0.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")
    run_case("${method}_initial_false" "${method}" "1" "2^N < 0" 3 ""
        "10" "0" "1" "0.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")
endforeach()

# A fixed seed and high propensity make this SSA event path reproducible. Its
# initial condition must stop before the first reaction event.
run_case("ssa_initial_true" "ssa" "1e9" "2^N" 1 ""
    "10" "0" "1" "0.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")
run_case("ssa_initial_false" "ssa" "1e9" "2^N < 0" 3 ""
    "10" "0" "1" "0.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")

# The state resolver must see seed observables at a nonzero initial time for
# both a deterministic default grid and the SSA event path.
run_case("cvode_observable_initial_true_nonzero_start" "cvode" "0"
    "A_count > 9" 1 "" "10" "2" "3"
    "2.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")
run_case("ssa_observable_initial_true_nonzero_start" "ssa" "0"
    "A_count > 9" 1 "" "10" "2" "3"
    "2.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")

# CVODE scales small states by their initial derivative. The stop_if check at
# the default-grid initial point must use the raw model state, not the scaled
# state reconstructed through a multiply that can round below 0.1.
run_case("cvode_scaled_initial_state_false" "cvode" "31.41592653589793"
    "A_count < 0.1" 2 "" "0.1" "0" "1"
    "0.000000000000e+00" "1.000000000000e-01" "0.000000000000e+00")

# An already-true stop_if is checked at t_start even when explicit sample
# times are requested. BNGL actions include t_start in the output even when an
# explicit sample grid omits it; the low-level API keeps its exact grid.
foreach(method IN ITEMS cvode euler rk4)
    run_case("${method}_explicit_true_includes_start" "${method}" "1"
        "A_count > 9" 1 "[2,2.25,2.5,2.75]"
        "10" "2" "3" "2.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")
    run_case("${method}_explicit_true_excludes_start" "${method}" "1"
        "A_count > 9" 1 "[2.25,2.5,2.75]"
        "10" "2" "3" "2.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")
    run_case("${method}_explicit_false_includes_start" "${method}" "0"
        "A_count < 0" 5 "[2,2.25,2.5,2.75]"
        "10" "2" "3" "2.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")
    run_case("${method}_explicit_false_excludes_start" "${method}" "0"
        "A_count < 0" 5 "[2.25,2.5,2.75]"
        "10" "2" "3" "2.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")
endforeach()

run_case("ssa_explicit_true_includes_start" "ssa" "1e9" "A_count > 9" 1
    "[2,2.25,2.5,2.75]" "10" "2" "3"
    "2.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")
run_case("ssa_explicit_true_excludes_start" "ssa" "1e9" "A_count > 9" 1
    "[2.25,2.5,2.75]" "10" "2" "3"
    "2.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")
run_case("ssa_explicit_false_includes_start" "ssa" "0" "A_count < 0" 5
    "[2,2.25,2.5,2.75]" "10" "2" "3"
    "2.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")
run_case("ssa_explicit_false_excludes_start" "ssa" "0" "A_count < 0" 5
    "[2.25,2.5,2.75]" "10" "2" "3"
    "2.000000000000e+00" "1.000000000000e+01" "0.000000000000e+00")

# Equality at the initial threshold is false. The CVODE scale/unscale path
# must not turn the exact raw value 0.1 into a value below the threshold, and
# the first later sample must check its integrated state rather than the raw
# initial state.
run_case("cvode_explicit_sample_times_scaled_initial_state_false" "cvode"
    "31.41592653589793" "A_count < 0.1" 2 "[2.25,2.5,2.75]"
    "0.1" "2" "3" "2.000000000000e+00"
    "1.000000000000e-01" "0.000000000000e+00")

# A false initial condition can become true at the first requested output.
# The test also guards Euler and RK4, whose explicit-grid loops must check the
# state at the first sample when t_start was omitted.
foreach(method IN ITEMS cvode euler rk4)
    run_case("${method}_explicit_first_sample_true" "${method}" "1"
        "A_count < 9.9" 2 "[2.25,2.5,2.75]"
        "10" "2" "3" "2.000000000000e+00"
        "1.000000000000e+01" "0.000000000000e+00")
endforeach()

# SSA evaluates the predicate on its rounded molecule-count state before any
# reaction draw. A fractional seed distinguishes that state from the raw 0.6.
run_case("ssa_fractional_seed_initial_true" "ssa" "1e9" "A_count > 0.9" 1
    "[2.25,2.5,2.75]" "0.6" "2" "3"
    "2.000000000000e+00" "1.000000000000e+00" "0.000000000000e+00")

run_zero_species_case("cvode_zero_species_initial_true" "" "0" "1"
    "0.000000000000e+00")
run_zero_species_case("cvode_zero_species_explicit_initial_true"
    "[2.25,2.5,2.75]" "2" "3" "2.000000000000e+00")
