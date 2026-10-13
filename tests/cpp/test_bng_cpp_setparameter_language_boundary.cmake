if(NOT DEFINED BNG_CPP_PATH OR BNG_CPP_PATH STREQUAL "")
    message(FATAL_ERROR "BNG_CPP_PATH must name the bng_cpp executable")
endif()
if(NOT DEFINED WORK_DIR OR WORK_DIR STREQUAL "")
    set(WORK_DIR "${CMAKE_CURRENT_BINARY_DIR}/setparameter_language_boundary")
endif()

file(REMOVE_RECURSE "${WORK_DIR}")

function(write_model model_path model_program_source action_source)
    set(extra_parameters "")
    if(ARGC GREATER 3)
        set(extra_parameters "${ARGV3}")
    endif()
    file(WRITE "${model_path}" "begin model
begin parameters
  N 3
  Nd 3
  p 1
  k 0.4
${extra_parameters}end parameters
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
${model_program_source}end model
${action_source}
")
endfunction()

function(run_positive_case
         action_scope case_name setter_source expected_k final_a_min final_a_max)
    set(case_dir "${WORK_DIR}/${action_scope}_${case_name}")
    file(MAKE_DIRECTORY "${case_dir}")
    if(action_scope STREQUAL "top_level")
        set(model_program_source "")
        string(CONCAT action_source
            "${setter_source}simulate_ode({t_start=>0,t_end=>1,n_steps=>8})\n"
            "generate_network({evaluate_expressions=>0})\n")
    else()
        string(CONCAT model_program_source
            "begin protocol\n"
            "${setter_source}"
            "simulate({method=>\"ode\",t_start=>0,t_end=>1,n_steps=>8})\n"
            "end protocol\n")
        string(CONCAT action_source
            "simulate_protocol()\n"
            "generate_network({evaluate_expressions=>0})\n")
    endif()

    set(model_path "${case_dir}/setparameter.bngl")
    write_model("${model_path}" "${model_program_source}" "${action_source}")
    execute_process(
        COMMAND "${BNG_CPP_PATH}" "setparameter.bngl"
        WORKING_DIRECTORY "${case_dir}"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE stdout_text
        ERROR_VARIABLE stderr_text
    )
    if(NOT result EQUAL 0)
        message(FATAL_ERROR
            "${action_scope} ${case_name} setParameter failed (exit ${result}).\n"
            "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
    endif()

    set(net_path "${case_dir}/setparameter.net")
    if(NOT EXISTS "${net_path}")
        message(FATAL_ERROR "${action_scope} ${case_name} setParameter wrote no network")
    endif()
    file(READ "${net_path}" net_text)
    set(gdat_path "${case_dir}/setparameter.gdat")
    if(NOT EXISTS "${gdat_path}")
        message(FATAL_ERROR "${action_scope} ${case_name} setParameter wrote no trajectory")
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
            "expected 9 trajectory rows for ${action_scope} ${case_name}, got ${row_count}.\n"
            "Trajectory:\n${gdat_text}")
    endif()
    list(GET data_rows 8 final_row)
    string(REGEX MATCH "^([0-9.eE+-]+)[ ]+([0-9.eE+-]+)" final_match "${final_row}")
    if(final_match STREQUAL "")
        message(FATAL_ERROR "could not read final trajectory row: ${final_row}")
    endif()
    set(final_time "${CMAKE_MATCH_1}")
    set(final_a_count "${CMAKE_MATCH_2}")
    if(NOT final_time STREQUAL "1.000000000000e+00")
        message(FATAL_ERROR
            "${action_scope} ${case_name} trajectory ended at ${final_time}, expected t=1.\n"
            "${gdat_text}")
    endif()
    if(final_a_count LESS final_a_min OR final_a_count GREATER final_a_max)
        message(FATAL_ERROR
            "${action_scope} ${case_name} trajectory ended at A=${final_a_count}; "
            "expected [${final_a_min},${final_a_max}].\nTrajectory:\n${gdat_text}")
    endif()

    if(expected_k MATCHES "^expr:")
        string(REPLACE "expr:" "" expected_expression "${expected_k}")
        string(FIND "${net_text}" " k ${expected_expression}" parameter_position)
        if(parameter_position EQUAL -1)
            message(FATAL_ERROR
                "${action_scope} ${case_name} should retain k as ${expected_expression}.\n"
                "Network:\n${net_text}\nstdout:\n${stdout_text}\nstderr:\n${stderr_text}")
        endif()
    elseif(NOT net_text MATCHES "[ \t]+k[ \t]+${expected_k}([.]0*)?([ \t\r\n]|$)")
        message(FATAL_ERROR
            "${action_scope} ${case_name} setParameter should set k to ${expected_k}.\n"
            "Network:\n${net_text}\nstdout:\n${stdout_text}\nstderr:\n${stderr_text}")
    endif()
endfunction()

function(run_refusal_case action_scope case_name setter_source expected_message)
    set(extra_parameters "")
    if(ARGC GREATER 4)
        set(extra_parameters "${ARGV4}")
    endif()
    set(case_dir "${WORK_DIR}/${action_scope}_refused_${case_name}")
    file(MAKE_DIRECTORY "${case_dir}")
    if(action_scope STREQUAL "top_level")
        set(model_program_source "")
        set(action_source "${setter_source}")
    else()
        string(CONCAT model_program_source
            "begin protocol\n"
            "${setter_source}"
            "end protocol\n")
        set(action_source "simulate_protocol()\n")
    endif()

    set(model_path "${case_dir}/setparameter.bngl")
    write_model("${model_path}" "${model_program_source}" "${action_source}"
        "${extra_parameters}")
    execute_process(
        COMMAND "${BNG_CPP_PATH}" "setparameter.bngl"
        WORKING_DIRECTORY "${case_dir}"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE stdout_text
        ERROR_VARIABLE stderr_text
    )
    if(result EQUAL 0)
        message(FATAL_ERROR "${action_scope} ${case_name} must be refused")
    endif()
    string(FIND "${stderr_text}\n${stdout_text}" "${expected_message}" message_position)
    if(message_position EQUAL -1)
        message(FATAL_ERROR
            "${action_scope} ${case_name} refusal did not explain the boundary.\n"
            "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
    endif()
    if(EXISTS "${case_dir}/setparameter.net")
        message(FATAL_ERROR "${action_scope} ${case_name} wrote a network after refusal")
    endif()
endfunction()

function(run_existing_network_continue_case action_scope)
    set(case_dir "${WORK_DIR}/${action_scope}_existing_network_continue")
    file(MAKE_DIRECTORY "${case_dir}")
    if(action_scope STREQUAL "top_level")
        set(model_program_source "")
        string(CONCAT action_source
            "simulate_ode({t_start=>0,t_end=>0.5,n_steps=>4})\n"
            "setParameter(\"k\",\"2^N\")\n"
            "setParameter(\"N\",4)\n"
            "simulate_ode({t_end=>0.5,n_steps=>4,continue=>1})\n"
            "generate_network({evaluate_expressions=>0})\n")
    else()
        string(CONCAT model_program_source
            "begin protocol\n"
            "simulate({method=>\"ode\",t_start=>0,t_end=>0.5,n_steps=>4})\n"
            "setParameter(\"k\",\"2^N\")\n"
            "setParameter(\"N\",4)\n"
            "simulate({method=>\"ode\",t_end=>0.5,n_steps=>4})\n"
            "end protocol\n")
        string(CONCAT action_source
            "simulate_protocol()\n"
            "generate_network({evaluate_expressions=>0})\n")
    endif()

    set(model_path "${case_dir}/setparameter.bngl")
    write_model("${model_path}" "${model_program_source}" "${action_source}")
    execute_process(
        COMMAND "${BNG_CPP_PATH}" "setparameter.bngl"
        WORKING_DIRECTORY "${case_dir}"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE stdout_text
        ERROR_VARIABLE stderr_text
    )
    if(NOT result EQUAL 0)
        message(FATAL_ERROR
            "${action_scope} existing-network continue failed (exit ${result}).\n"
            "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
    endif()

    set(gdat_path "${case_dir}/setparameter.gdat")
    if(NOT EXISTS "${gdat_path}")
        message(FATAL_ERROR "${action_scope} existing-network continue wrote no trajectory")
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
            "expected 9 trajectory rows for ${action_scope} existing-network continue, "
            "got ${row_count}.\nTrajectory:\n${gdat_text}")
    endif()
    list(GET data_rows 8 final_row)
    string(REGEX MATCH "^([0-9.eE+-]+)[ ]+([0-9.eE+-]+)" final_match "${final_row}")
    if(final_match STREQUAL "")
        message(FATAL_ERROR "could not read final trajectory row: ${final_row}")
    endif()
    set(final_time "${CMAKE_MATCH_1}")
    set(final_a_count "${CMAKE_MATCH_2}")
    if(NOT final_time STREQUAL "1.000000000000e+00")
        message(FATAL_ERROR
            "${action_scope} existing-network continue ended at ${final_time}, expected t=1.\n"
            "${gdat_text}")
    endif()
    if(final_a_count LESS 0.002744535699 OR final_a_count GREATER 0.002748535700)
        message(FATAL_ERROR
            "${action_scope} existing-network continue ended at A=${final_a_count}; "
            "expected 10*exp(-0.2-8) within the existing 2e-6 absolute tolerance.\n"
            "Trajectory:\n${gdat_text}")
    endif()

    set(net_path "${case_dir}/setparameter.net")
    if(NOT EXISTS "${net_path}")
        message(FATAL_ERROR
            "${action_scope} existing-network continue wrote no network")
    endif()
    file(READ "${net_path}" net_text)
    string(FIND "${net_text}" " k (2 ^ N)" parameter_position)
    if(parameter_position EQUAL -1)
        message(FATAL_ERROR
            "${action_scope} existing-network continue did not retain k's AST.\n"
            "Network:\n${net_text}")
    endif()
endfunction()

foreach(action_scope IN ITEMS top_level protocol)
    run_existing_network_continue_case("${action_scope}")
endforeach()

foreach(action_scope IN ITEMS top_level protocol)
    run_positive_case("${action_scope}" setter_expression_then_mutate_N
        "setParameter(\"k\",\"2^N\")\nsetParameter(\"N\",4)\n"
        "expr:(2 ^ N)" 0 0.000003125352)
    # These intervals reuse the existing absolute 2e-6 CVODE check from the
    # numeric setParameter test, centered on 10*exp(-k) for each compiled rate.
    run_positive_case("${action_scope}" quoted_static
        "setParameter(\"k\",\"2^3\")\n"
        8 0.003352626279 0.003356626279)
    run_positive_case("${action_scope}" quoted_dynamic
        "setParameter(\"N\",4)\nsetParameter(\"k\",\"2^N\")\n"
        "expr:(2 ^ N)" 0 0.000003125352)
    run_positive_case("${action_scope}" quoted_chained_caret
        "setParameter(\"N\",4)\nsetParameter(\"k\",\"2^N^2\")\n"
        "expr:((2 ^ N) ^ 2)" -0.000002 0.000002)
    run_positive_case("${action_scope}" quoted_dynamic_identifier_with_d
        "setParameter(\"Nd\",4)\nsetParameter(\"k\",\"2^Nd\")\n"
        "expr:(2 ^ Nd)" 0 0.000003125352)
    run_positive_case("${action_scope}" quoted_dynamic_parameter_base
        "setParameter(\"N\",4)\nsetParameter(\"k\",\"-N^2\")\n"
        "expr:(-N ^ 2)" 0 0.000003125352)
    run_positive_case("${action_scope}" bare_identifier
        "setParameter(\"N\",4)\nsetParameter(\"k\",N)\n"
        4 0.183154388887 0.183158388887)
endforeach()

foreach(action_scope IN ITEMS top_level protocol)
    run_refusal_case("${action_scope}" setter_self_reference
        "setParameter(\"N\",\"N^2\")\n"
        "self-reference")
    run_refusal_case("${action_scope}" retained_dependency_becomes_nonfinite
        "setParameter(\"p\",\"(1/N)^2\")\nsetParameter(\"N\",0)\n"
        "non-finite")
    run_refusal_case("${action_scope}" time_dependent_parameter_reference
        "setParameter(\"k\",\"2^q\")\n"
        "time-dependent" "  q time\n")
    run_refusal_case("${action_scope}" transitive_time_dependent_parameter_reference
        "setParameter(\"k\",\"2^q\")\n"
        "time-dependent" "  q r\n  r time\n")
endforeach()

foreach(action_scope IN ITEMS top_level protocol)
    foreach(expression IN ITEMS "-2^N" "(-2)^N" "2**N^2" "2**N" "2**3")
        if(action_scope STREQUAL "top_level")
            set(model_program_source "")
            string(CONCAT action_source
                "setParameter(\"N\",4)\n"
                "setParameter(\"k\",\"${expression}\")\n"
                "simulate_ode({t_start=>0,t_end=>1,n_steps=>8})\n")
        else()
            string(CONCAT model_program_source
                "begin protocol\n"
                "  setParameter(\"N\",4)\n"
                "  setParameter(\"k\",\"${expression}\")\n"
                "  simulate({method=>\"ode\",t_start=>0,t_end=>1,n_steps=>8})\n"
                "end protocol\n")
            set(action_source "simulate_protocol()\n")
        endif()
        string(REPLACE "-" "minus" case_name "${expression}")
        string(REPLACE "(" "lp" case_name "${case_name}")
        string(REPLACE ")" "rp" case_name "${case_name}")
        string(REPLACE "*" "mul" case_name "${case_name}")
        string(REPLACE "^" "caret" case_name "${case_name}")
        set(case_dir "${WORK_DIR}/${action_scope}_unsafe_quoted_${case_name}")
        file(MAKE_DIRECTORY "${case_dir}")
        set(model_path "${case_dir}/setparameter.bngl")
        write_model("${model_path}" "${model_program_source}" "${action_source}")
        execute_process(
            COMMAND "${BNG_CPP_PATH}" "setparameter.bngl"
            WORKING_DIRECTORY "${case_dir}"
            RESULT_VARIABLE result
            OUTPUT_VARIABLE stdout_text
            ERROR_VARIABLE stderr_text
        )
        if(result EQUAL 0)
            message(FATAL_ERROR
                "${action_scope} setParameter(\"${expression}\") must refuse unsupported quoted power syntax")
        endif()
        string(FIND "${stderr_text}\n${stdout_text}"
            "invalid setParameter value" refusal_message)
        if(refusal_message EQUAL -1)
            message(FATAL_ERROR
                "${action_scope} setParameter(\"${expression}\") failed for an unrelated reason.\n"
                "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
        endif()
    endforeach()
endforeach()

foreach(action_scope IN ITEMS top_level protocol)
    foreach(expression IN ITEMS "time^2" "t^2" "time()^2" "sqrt(N)^2"
            "TFUN([0,1],[2,4],N)^2" "N % 2^2")
        if(action_scope STREQUAL "top_level")
            set(model_program_source "")
            string(CONCAT action_source
                "setParameter(\"N\",4)\n"
                "setParameter(\"k\",\"${expression}\")\n"
                "simulate_ode({t_start=>0,t_end=>1,n_steps=>8})\n")
        else()
            string(CONCAT model_program_source
                "begin protocol\n"
                "  setParameter(\"N\",4)\n"
                "  setParameter(\"k\",\"${expression}\")\n"
                "  simulate({method=>\"ode\",t_start=>0,t_end=>1,n_steps=>8})\n"
                "end protocol\n")
            set(action_source "simulate_protocol()\n")
        endif()
        string(REPLACE "*" "mul" case_name "${expression}")
        string(REPLACE "%" "mod" case_name "${case_name}")
        string(REPLACE "(" "lp" case_name "${case_name}")
        string(REPLACE ")" "rp" case_name "${case_name}")
        string(REPLACE "[" "lb" case_name "${case_name}")
        string(REPLACE "]" "rb" case_name "${case_name}")
        string(REPLACE "^" "caret" case_name "${case_name}")
        set(case_dir "${WORK_DIR}/${action_scope}_unsupported_quoted_caret_${case_name}")
        file(MAKE_DIRECTORY "${case_dir}")
        set(model_path "${case_dir}/setparameter.bngl")
        write_model("${model_path}" "${model_program_source}" "${action_source}")
        execute_process(
            COMMAND "${BNG_CPP_PATH}" "setparameter.bngl"
            WORKING_DIRECTORY "${case_dir}"
            RESULT_VARIABLE result
            OUTPUT_VARIABLE stdout_text
            ERROR_VARIABLE stderr_text
        )
        if(result EQUAL 0)
            message(FATAL_ERROR
                "${action_scope} setParameter(\"${expression}\") must refuse unsupported quoted caret dependencies")
        endif()
        string(FIND "${stderr_text}\n${stdout_text}"
            "quoted caret expressions require simple parameter arithmetic" refusal_message)
        if(refusal_message EQUAL -1)
            message(FATAL_ERROR
                "${action_scope} setParameter(\"${expression}\") refusal did not explain the boundary.\n"
                "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
        endif()
    endforeach()
endforeach()

foreach(action_scope IN ITEMS top_level protocol)
    foreach(expression IN ITEMS "2*N" "N+1" "2**N")
        if(action_scope STREQUAL "top_level")
            set(model_program_source "")
            string(CONCAT action_source
                "setParameter(\"N\",4)\n"
                "setParameter(\"k\",${expression})\n"
                "simulate_ode({t_start=>0,t_end=>1,n_steps=>8})\n")
        else()
            string(CONCAT model_program_source
                "begin protocol\n"
                "  setParameter(\"N\",4)\n"
                "  setParameter(\"k\",${expression})\n"
                "  simulate({method=>\"ode\",t_start=>0,t_end=>1,n_steps=>8})\n"
                "end protocol\n")
            set(action_source "simulate_protocol()\n")
        endif()
        string(REPLACE "*" "mul" case_name "${expression}")
        string(REPLACE "+" "plus" case_name "${case_name}")
        set(case_dir "${WORK_DIR}/${action_scope}_unquoted_${case_name}")
        file(MAKE_DIRECTORY "${case_dir}")
        set(model_path "${case_dir}/setparameter.bngl")
        write_model("${model_path}" "${model_program_source}" "${action_source}")
        execute_process(
            COMMAND "${BNG_CPP_PATH}" "setparameter.bngl"
            WORKING_DIRECTORY "${case_dir}"
            RESULT_VARIABLE result
            OUTPUT_VARIABLE stdout_text
            ERROR_VARIABLE stderr_text
        )
        if(result EQUAL 0)
            message(FATAL_ERROR
                "${action_scope} unquoted setParameter(${expression}) must refuse named arithmetic")
        endif()
        string(FIND "${stderr_text}\n${stdout_text}"
            "unquoted named arithmetic" refusal_message)
        if(refusal_message EQUAL -1)
            message(FATAL_ERROR
                "${action_scope} setParameter(${expression}) refusal did not "
                "explain the boundary.\n"
                "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
        endif()
    endforeach()
endforeach()
