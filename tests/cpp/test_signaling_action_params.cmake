# CLI-level regression: an action value may name a parameter whose name
# contains 'd'.
#
# `parseScalarValue` rewrote d/D to e/E across the whole value string before
# consulting the parameter table, so `simulate_ode({t_end=>t_end})` searched for
# a parameter spelled `t_en` and refused the run with
# "Unsupported scalar action value: 't_end'". `t_end` is the conventional
# horizon name and is what models/performance_test_models/push_pull.bngl uses.
#
# The acceptance criterion is the trajectory, not the exit code: the run must
# succeed AND the .gdat must span the declared horizon, which only happens if
# `t_end` resolved to 5 rather than being refused.

set(model_dir "${CMAKE_CURRENT_BINARY_DIR}/signaling_action_params")
file(REMOVE_RECURSE "${model_dir}")
file(MAKE_DIRECTORY "${model_dir}")

set(model "${model_dir}/param_d_name.bngl")
file(WRITE "${model}" "begin model
begin parameters
  t_end 5.0
  n_steps 10
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A A
end observables
end model
begin actions
  simulate_ode({t_end=>t_end,n_steps=>n_steps})
end actions
")

execute_process(
    COMMAND "${BNG_CPP_PATH}" "param_d_name.bngl"
    WORKING_DIRECTORY "${model_dir}"
    RESULT_VARIABLE result
    OUTPUT_VARIABLE stdout_text
    ERROR_VARIABLE stderr_text
)

if(NOT result EQUAL 0)
    message(FATAL_ERROR
        "bng_cpp refused an action value naming the parameter 't_end' "
        "(exit ${result}). The d->e rewrite must apply only to the numeric "
        "spelling, never to the identifier being looked up.\n"
        "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
endif()

set(gdat "${model_dir}/param_d_name.gdat")
if(NOT EXISTS "${gdat}")
    message(FATAL_ERROR "bng_cpp reported success but wrote no .gdat to ${gdat}")
endif()
file(READ "${gdat}" gdat_text)
set(data_rows "")
string(REPLACE "\n" ";" gdat_lines "${gdat_text}")
foreach(raw_line IN LISTS gdat_lines)
    string(STRIP "${raw_line}" stripped)
    if(stripped STREQUAL "")
        continue()
    endif()
    if(stripped MATCHES "^#")
        continue()
    endif()
    list(APPEND data_rows "${stripped}")
endforeach()

list(LENGTH data_rows row_count)

# 10 output steps plus the t=0 row, so 11 rows. A run that silently fell back
# to a default horizon would have a different count, which is why the count is
# asserted and not just the last time.
if(NOT row_count EQUAL 11)
    message(FATAL_ERROR
        "expected 11 output rows for n_steps=10, got ${row_count}.\n${gdat_text}")
endif()

list(GET data_rows 10 last_row)
string(REGEX MATCH "^[0-9.eE+-]+" last_time "${last_row}")
if(NOT last_time STREQUAL "5.000000000000e+00")
    message(FATAL_ERROR
        "the run did not end at t_end=5 read from the parameter 't_end'; "
        "last sampled time is '${last_time}'.\n${gdat_text}")
endif()
