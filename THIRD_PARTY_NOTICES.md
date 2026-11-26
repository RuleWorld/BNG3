# Third-Party Notices

BioNetGen 3 (BNG3) is licensed under the MIT License (see [LICENSE](LICENSE)).

BNG3 builds against, embeds, or derives from the following open-source third-party software components and upstream RuleWorld projects.

## Upstream RuleWorld Provenance

- **BioNetGen / BNG2** (`RuleWorld/bionetgen`, MIT License): canonical BNGL grammar, network generation, and simulation reference implementation.
- **NFsim** (`RuleWorld/NFsim`, MIT License): network-free stochastic simulator embedded under `cpp/nfsim/`.
- **PyBioNetGen** (`RuleWorld/PyBioNetGen`, MIT License): Python CLI/API compatibility surface and vendored Atomizer / model-API compatibility layers under `python/bionetgen/`.

## Bundled Third-Party Sources

### nauty 2.4 (`cpp/nauty/`)
- **Author:** Brendan D. McKay (Australian National University)
- **Website:** http://cs.anu.edu.au/~bdm/nauty/
- **License:** Permissive nauty license / Apache License 2.0 (see `cpp/nauty/nauty24/COPYRIGHT` in the source tree).
- **Notes:** Used for canonical graph labeling in both `bng_core` and `nfsim_core` with the `set` -> `nset` typedef patch documented in `cpp/nauty/README.md`.

### TinyXML (`cpp/nfsim/NFinput/TinyXML/`)
- **Author:** Lee Thomason
- **License:** zlib License (see `cpp/nfsim/NFinput/TinyXML/tinyxml.h` and `readme.txt`).
- **Notes:** Used by `nfsim_core` for NFsim XML parsing.

### MTrand (`cpp/nfsim/NFutil/MTrand/`)
- **Authors:** Takuji Nishimura and Makoto Matsumoto (original Mersenne Twister MT19937 algorithm); C++ port by Jasper Bedaux.
- **License:** Permissive / BSD-style notice (see `cpp/nfsim/NFutil/MTrand/mtrand.h` and `mtreadme.txt`).
- **Notes:** Used by `nfsim_core` for stochastic random number generation.

## Statically Linked Build Dependencies (Fetched via CMake)

The following open-source libraries are fetched during CMake builds and statically linked into BNG3 binary artifacts (`bng_cpp`, `NFsim`, and the `_bionetgen_cpp` Python extension):

### ANTLR4 C++ Runtime (v4.13.2)
- **Upstream:** https://github.com/antlr/antlr4
- **License:** BSD 3-Clause License
- **Usage:** BNGL lexer and parser runtime (`antlr4_static`).

### SUNDIALS — CVODE and IDA (v7.6.0)
- **Upstream:** https://github.com/LLNL/sundials
- **Copyright:** Lawrence Livermore National Security, LLC and Southern Methodist University
- **License:** BSD 3-Clause License
- **Usage:** Stiff/non-stiff ODE (`CVODE`) and DAE (`IDA`) numerical integration (`sundials_cvode_static`, `sundials_ida_static`, and supporting NVector/SUNMatrix/SUNLinSol/SUNNonlinSol static libraries).

### pybind11 (v2.13.6)
- **Upstream:** https://github.com/pybind/pybind11
- **License:** BSD 3-Clause License
- **Usage:** C++/Python extension bindings (`_bionetgen_cpp`).

### Catch2 (v3.4.0, test builds only)
- **Upstream:** https://github.com/catchorg/Catch2
- **License:** Boost Software License 1.0
- **Usage:** C++ test suite only (`BUILD_TESTS=ON`; not linked into released wheels or CLI binaries).
