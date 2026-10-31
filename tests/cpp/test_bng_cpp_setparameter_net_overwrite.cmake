if(NOT DEFINED BNG_CPP_PATH OR BNG_CPP_PATH STREQUAL "")
    message(FATAL_ERROR "BNG_CPP_PATH must name the bng_cpp executable")
endif()

if(NOT DEFINED WORK_DIR OR WORK_DIR STREQUAL "")
    set(WORK_DIR "${CMAKE_CURRENT_BINARY_DIR}/setparameter_net_overwrite")
endif()

file(REMOVE_RECURSE "${WORK_DIR}")
file(MAKE_DIRECTORY "${WORK_DIR}")

set(model_path "${WORK_DIR}/param_net_test.bngl")
file(WRITE "${model_path}" "begin model
begin parameters
  k1 1.0
  k2 10.0
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 100
  B() 0
end seed species
begin observables
  Molecules A_count A()
  Molecules B_count B()
end observables
begin reaction rules
  A() -> B() k1
end reaction rules
generate_network({overwrite=>1})
simulate({method=>\"ode\",t_end=>1,n_steps=>5})
setParameter(\"k1\",0.0)
simulate({method=>\"ode\",t_end=>2,n_steps=>5})
end model
")

execute_process(
    COMMAND "${BNG_CPP_PATH}" "${model_path}"
    WORKING_DIRECTORY "${WORK_DIR}"
    RESULT_VARIABLE result
    OUTPUT_VARIABLE stdout_text
    ERROR_VARIABLE stderr_text
)

if(NOT result EQUAL 0)
    message(FATAL_ERROR
        "bng_cpp failed on param_net_test (exit ${result}).\n"
        "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
endif()

set(net_path "${WORK_DIR}/param_net_test.net")
if(NOT EXISTS "${net_path}")
    message(FATAL_ERROR "Expected .net file at ${net_path} was not generated.")
endif()

file(READ "${net_path}" net_text)

# The .net file generated at generate_network time should reflect k1 = 1.0, NOT 0.0 from setParameter.
if(NOT net_text MATCHES "[ \t]+k1[ \t]+1([.]0*)?([ \t\r\n]|$)")
    message(FATAL_ERROR
        "param_net_test.net should preserve initial parameter k1 = 1.0 from generate_network(), "
        "not overwritten by setParameter(\"k1\",0.0).\n"
        "Network contents:\n${net_text}")
endif()

if(net_text MATCHES "[ \t]+k1[ \t]+0([.]0*)?([ \t\r\n]|$)")
    message(FATAL_ERROR
        "param_net_test.net was incorrectly overwritten with setParameter value k1 = 0.\n"
        "Network contents:\n${net_text}")
endif()
