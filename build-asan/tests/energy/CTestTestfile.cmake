# CMake generated Testfile for 
# Source directory: /private/tmp/bng3-issue-reconcile/tests/energy
# Build directory: /private/tmp/bng3-issue-reconcile/build-asan/tests/energy
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test(energy_validation_harness "/opt/homebrew/bin/cmake" "-E" "env" "PYTHONPATH=/private/tmp/bng3-issue-reconcile/tests/energy" "PYTHONDONTWRITEBYTECODE=1" "/opt/anaconda3/bin/python3.14" "-m" "pytest" "-q" "-p" "no:cacheprovider" "tests/python")
set_tests_properties(energy_validation_harness PROPERTIES  LABELS "energy;harness" TIMEOUT "120" WORKING_DIRECTORY "/private/tmp/bng3-issue-reconcile/tests/energy" _BACKTRACE_TRIPLES "/private/tmp/bng3-issue-reconcile/tests/energy/CMakeLists.txt;5;add_test;/private/tmp/bng3-issue-reconcile/tests/energy/CMakeLists.txt;0;")
subdirs("tests/cpp")
