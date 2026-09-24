file(MAKE_DIRECTORY "${WORK_DIR}")

foreach(fixture issue_265_last issue_265_second_to_last)
    set(source "${FIXTURE_DIR}/${fixture}.bngl")
    file(READ "${source}" model_text)
    string(FIND "${model_text}" "method=>\"ssa\"" method_position)
    if(method_position EQUAL -1)
        message(FATAL_ERROR "${source} no longer contains the expected SSA action")
    endif()
    string(REPLACE "method=>\"ssa\"" "method=>\"psa\"" model_text "${model_text}")

    set(model "${WORK_DIR}/${fixture}_psa.bngl")
    file(WRITE "${model}" "${model_text}")
    execute_process(
        COMMAND "${BNG_CPP_PATH}" "${model}"
        WORKING_DIRECTORY "${WORK_DIR}"
        RESULT_VARIABLE result
        OUTPUT_VARIABLE stdout_text
        ERROR_VARIABLE stderr_text
        TIMEOUT 10
    )
    if(NOT result EQUAL 0)
        message(FATAL_ERROR
            "PSA stress run failed for ${fixture}: '${result}'.\n"
            "stdout:\n${stdout_text}\nstderr:\n${stderr_text}")
    endif()

    file(REMOVE
        "${WORK_DIR}/${fixture}_psa.net"
        "${WORK_DIR}/${fixture}_psa.cdat"
        "${WORK_DIR}/${fixture}_psa.gdat"
    )
endforeach()
