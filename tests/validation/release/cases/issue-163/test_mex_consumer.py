"""Consume the exported MEX C source through a minimal MATLAB MEX ABI.

Compiling and executing the generated '*_mex.c' with a small mxArray shim is
a real producer-consumer check for the writeMEXfile/writeMexfile rows: the
observable trajectory must match the source model's closed-form law.
"""

from __future__ import annotations

import math
import shutil
import subprocess

import pytest

MODEL = """begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  decay: A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
writeMEXfile({overwrite=>1})
"""

MEX_HEADER = """#ifndef MEX_SHIM_H
#define MEX_SHIM_H
#include <stdio.h>
#include <stdlib.h>
typedef enum { mxREAL = 0 } mxComplexity;
typedef struct { double *data; size_t m, n; } mxArray;
#define mexPrintf printf
#define mexErrMsgTxt(msg) do { fprintf(stderr, "%s\\n", msg); return; } while (0)
mxArray *mxCreateDoubleMatrix(size_t m, size_t n, mxComplexity c);
double *mxGetPr(const mxArray *a);
size_t mxGetNumberOfElements(const mxArray *a);
void *mxMalloc(size_t n);
void mxFree(void *p);
#endif
"""

HARNESS = """#include "mex.h"
#include <iostream>
extern "C" {
#include "m_mex.c"
}
mxArray *mxCreateDoubleMatrix(size_t m, size_t n, mxComplexity) {
    mxArray *a = (mxArray*)malloc(sizeof(mxArray));
    a->m = m; a->n = n; a->data = (double*)calloc(m*n, sizeof(double));
    return a;
}
double *mxGetPr(const mxArray *a) { return a->data; }
size_t mxGetNumberOfElements(const mxArray *a) { return a->m * a->n; }
void *mxMalloc(size_t n) { return malloc(n); }
void mxFree(void *p) { free(p); }
int main() {
    double tp[3] = {0.0, 0.5, 1.0}, si[1] = {10.0}, pa[1] = {0.1};
    mxArray a0={tp,1,3}, a1={si,1,1}, a2={pa,1,1};
    const mxArray *in[3] = {&a0,&a1,&a2};
    mxArray *out[2] = {nullptr,nullptr};
    mexFunction(2, out, 3, in);
    if (!out[1]) return 2;
    std::cout.precision(12);
    std::cout << out[1]->data[2] << "\\n";
    return 0;
}
"""


def test_exported_mex_source_executes_against_analytic_law(tmp_path, bng_cpp):
    gpp = shutil.which("g++")
    if gpp is None:
        pytest.skip("g++ is not installed")
    source = tmp_path / "m.bngl"
    source.write_text(MODEL)
    result = subprocess.run(
        [str(bng_cpp), source.name], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr

    exported = tmp_path / "m_mex.c"
    assert exported.is_file()
    (tmp_path / "mex.h").write_text(MEX_HEADER)
    (tmp_path / "harness.cpp").write_text(HARNESS)
    binary = tmp_path / "harness"
    compile_result = subprocess.run(
        [gpp, "-std=c++17", "-w", "-I.", "harness.cpp", "-lm", "-o", str(binary)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    run_result = subprocess.run(
        [str(binary)], cwd=tmp_path, capture_output=True, text=True
    )
    assert run_result.returncode == 0, run_result.stdout + run_result.stderr
    assert float(run_result.stdout.strip()) == pytest.approx(
        10 * math.exp(-0.1), rel=1e-6
    )
