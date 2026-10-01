#!/bin/bash
# Build the batch-SSA benchmark driver against the already-configured build/
# tree, reusing the exact compile flags and link libraries CMake used for the
# bng_cpp CLI. Doing it this way keeps cpp/CMakeLists.txt untouched (other
# operators own that file) while still producing a binary linked against the
# current libbng_engine.a.
#
# Usage: build_driver.sh <repo-root> <output-binary>

set -euo pipefail

ROOT="$1"
OUT="$2"
BUILD="$ROOT/build"
FLAGS="$BUILD/cpp/CMakeFiles/bng_cpp.dir/flags.make"
LINK="$BUILD/cpp/CMakeFiles/bng_cpp.dir/link.txt"

INCLUDES=$(sed -n 's/^CXX_INCLUDES = //p' "$FLAGS")
DEFINES=$(sed -n 's/^CXX_DEFINES = //p' "$FLAGS")
FLAGS_CXX=$(sed -n 's/^CXX_FLAGS = //p' "$FLAGS")

SRC="$ROOT/benchmarks/batch_ssa/bench_batch_ssa.cpp"
OBJ="$BUILD/bench_batch_ssa.o"

/usr/bin/time -l /usr/bin/c++ $FLAGS_CXX $DEFINES $INCLUDES -c "$SRC" -o "$OBJ"

# Link line: keep everything, swap the CLI's object for ours and the output path.
LIBLINE=$(sed -e "s|CMakeFiles/bng_cpp.dir/main.cpp.o|$OBJ|" -e "s|-o bng_cpp|-o $OUT|" "$LINK")
cd "$BUILD/cpp" && eval "$LIBLINE"

echo "built $OUT"