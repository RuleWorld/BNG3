#include <pybind11/pybind11.h>

namespace py = pybind11;

void bind_model(py::module_& m);
void bind_parser(py::module_& m);
void bind_engine(py::module_& m);
void bind_nfsim(py::module_& m);
void bind_io(py::module_& m);
void bind_viz(py::module_& m);

PYBIND11_MODULE(_bionetgen_cpp, m) {
    m.doc() = "BioNetGen C++ backend: BNGL parsing, network generation, and simulation";

    bind_model(m);
    bind_parser(m);
    bind_engine(m);
    bind_nfsim(m);
    bind_io(m);
    bind_viz(m);
}
