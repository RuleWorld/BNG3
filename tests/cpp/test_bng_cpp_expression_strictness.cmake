if(NOT DEFINED BNG_CPP_PATH OR BNG_CPP_PATH STREQUAL "")
    message(FATAL_ERROR "BNG_CPP_PATH must name the bng_cpp executable")
endif()
if(NOT DEFINED WORK_DIR OR WORK_DIR STREQUAL "")
    set(WORK_DIR "${CMAKE_CURRENT_BINARY_DIR}/expression_strictness")
endif()

file(REMOVE_RECURSE "${WORK_DIR}")

function(write_model model_path stop_if_expression)
    file(WRITE "${model_path}"
"begin model
begin parameters
  N 4
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
  convert: A() -> B() 1
end reaction rules
end model
simulate_ode({t_start=>0,t_end=>1,n_steps=>8,stop_if=>\"${stop_if_expression}\"})
")
endfunction()

function(run_case case_name stop_if_expression expect_success)
    set(case_dir "${WORK_DIR}/${case_name}")
    file(MAKE_DIRECTORY "${case_dir}")
    set(model_path "${case_dir}/expression.bngl")
    write_model("${model_path}" "${stop_if_expression}")

    execute_process(
        COMMAND "${BNG_CPP_PATH}" "expression.bngl"
        WORKING_DIRECTORY "${case_dir}"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE stdout_text
        ERROR_VARIABLE stderr_text
    )
    if(expect_success)
        if(NOT result EQUAL 0)
            message(SEND_ERROR
                "${case_name} valid stop_if failed (exit ${result}).\n"
                "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
            return()
        endif()
        set(gdat_path "${case_dir}/expression.gdat")
        if(NOT EXISTS "${gdat_path}")
            message(SEND_ERROR "${case_name} valid stop_if wrote no trajectory")
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
        if(NOT row_count EQUAL 2)
            message(SEND_ERROR
                "${case_name} valid stop_if should stop after the first step, got "
                "${row_count} rows.\nTrajectory:\n${gdat_text}")
        endif()
        return()
    endif()

    if(result EQUAL 0)
        message(SEND_ERROR
            "${case_name} malformed stop_if was accepted (exit 0).\n"
            "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
    elseif(NOT "${stdout_text}${stderr_text}" MATCHES "stop_if|parse expression")
        message(SEND_ERROR
            "${case_name} failed for an unrelated reason (exit ${result}).\n"
            "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
    endif()
endfunction()

run_case(valid_caret "2^N" TRUE)
run_case(trailing_token "2^N junk" FALSE)
run_case(unknown_character "2`^N" FALSE)
