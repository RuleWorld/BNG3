file(MAKE_DIRECTORY "${WORK_DIR}")
set(model_path "${WORK_DIR}/physical_units_forced_xml.bngl")
file(WRITE "${model_path}" [=[
begin model
  setOption("units", "strict")
  setOption("NumberPerQuantityUnit", 6.02214076e23)
  begin parameters
    k = 1e-9 [M/second]
  end parameters
  begin compartments
    cell 3 2 [fL]
  end compartments
  begin molecule types
    A()
  end molecule types
  begin seed species
    A()@cell 0
  end seed species
  begin reaction rules
    source: 0 -> A()@cell k
  end reaction rules
  begin actions
    simulate_nf({prefix=>"forced_xml",t_end=>1e-14,n_steps=>1,seed=>42})
  end actions
end model
]=])

execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env
        --unset=BNG_NFSIM_REQUIRE_DIRECT
        BNG_NFSIM_FORCE_XML=1
        BNG_NFSIM_ALLOW_XML_FALLBACK=1
        "${BNG_CPP_PATH}" "${model_path}"
    RESULT_VARIABLE result
    OUTPUT_VARIABLE stdout_text
    ERROR_VARIABLE stderr_text
    WORKING_DIRECTORY "${WORK_DIR}"
)

if(NOT result EQUAL 1)
    message(FATAL_ERROR
        "bng_cpp should reject physical-unit XML fallback with exit code 1, got '${result}'.\n"
        "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
endif()

if(NOT stderr_text MATCHES "cannot preserve physical units")
    message(FATAL_ERROR
        "bng_cpp did not report the physical-unit XML fallback boundary:\n${stderr_text}")
endif()
