if(NOT DEFINED BNG_CPP_PATH OR BNG_CPP_PATH STREQUAL "")
    message(FATAL_ERROR "BNG_CPP_PATH must name the bng_cpp executable")
endif()

if(NOT DEFINED WORK_DIR OR WORK_DIR STREQUAL "")
    set(WORK_DIR "${CMAKE_CURRENT_BINARY_DIR}/setparameter_identifier_spelling")
endif()

file(REMOVE_RECURSE "${WORK_DIR}")
set(failures "")

foreach(action_scope IN ITEMS top_level protocol)
    set(model_dir "${WORK_DIR}/${action_scope}")
    file(MAKE_DIRECTORY "${model_dir}")

    set(setter_actions "setParameter(\"p_mul\",\"2*Nd\")
setParameter(\"p_ne_mul\",\"2*Ne\")
setParameter(\"p_sum\",\"Nd+1\")
setParameter(\"p_ne_sum\",\"Ne+1\")
setParameter(\"p_d_sum\",\"D+1\")
setParameter(\"p_e_sum\",\"E+1\")
")
    if(action_scope STREQUAL "top_level")
        set(top_level_setter_actions "${setter_actions}setParameter(\"p_fortran\",\"1D-3\")
")
        set(model_program_source "")
        set(action_source "${top_level_setter_actions}generate_network({overwrite=>1})
")
    else()
        set(model_program_source "begin protocol
  ${setter_actions}  simulate({method=>\"ode\",t_start=>0,t_end=>1,n_steps=>8})
end protocol
")
        set(action_source "simulate_protocol()
")
    endif()

    set(model_path "${model_dir}/setparameter_${action_scope}.bngl")
    file(WRITE "${model_path}" "begin model
begin parameters
  Nd 4
  Ne 40
  D 3
  E 30
  p_mul 0
  p_ne_mul 0
  p_sum 0
  p_ne_sum 0
  p_d_sum 0
  p_e_sum 0
  p_fortran 0
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
begin reaction rules
  convert: A() -> B() k
end reaction rules
${model_program_source}end model
${action_source}")

    execute_process(
        COMMAND "${BNG_CPP_PATH}" "${model_path}"
        WORKING_DIRECTORY "${model_dir}"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE stdout_text
        ERROR_VARIABLE stderr_text
    )
    if(NOT result EQUAL 0)
        list(APPEND failures
            "bng_cpp failed for ${action_scope} quoted setParameter expressions "
            "(exit ${result}).\nstdout:\n${stdout_text}\nstderr:\n${stderr_text}")
        continue()
    endif()

    set(net_path "${model_dir}/setparameter_${action_scope}.net")
    if(NOT EXISTS "${net_path}")
        list(APPEND failures
            "bng_cpp wrote no network for ${action_scope} quoted setParameter expressions")
        continue()
    endif()
    file(READ "${net_path}" net_text)

    set(expected_values
        "p_mul|8"
        "p_ne_mul|80"
        "p_sum|5"
        "p_ne_sum|41"
        "p_d_sum|4"
        "p_e_sum|31"
    )
    if(action_scope STREQUAL "top_level")
        list(APPEND expected_values "p_fortran|0[.]001")
    endif()
    foreach(expected IN LISTS expected_values)
        string(REPLACE "|" ";" expected_fields "${expected}")
        list(GET expected_fields 0 parameter_name)
        list(GET expected_fields 1 expected_value)
        if(NOT net_text MATCHES "[ \t]+${parameter_name}[ \t]+${expected_value}([.]0*)?([ \t\r\n]|$)")
            list(APPEND failures
                "${action_scope} setParameter for ${parameter_name} changed its identifier spelling "
                "or Fortran exponent value; expected ${expected_value}.\n"
                "Network:\n${net_text}\nstdout:\n${stdout_text}\nstderr:\n${stderr_text}")
        endif()
    endforeach()
endforeach()

if(failures)
    string(JOIN "\n\n" failure_text ${failures})
    message(FATAL_ERROR "quoted setParameter identifier regression:\n${failure_text}")
endif()
