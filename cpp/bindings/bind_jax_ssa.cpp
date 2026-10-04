// Flattened reaction-network export for the opt-in JAX batch-SSA backend
// (python/bionetgen/jax_ssa.py).
//
// The Python side cannot rebuild this data from the existing exported API:
// GeneratedNetwork only exposes species/reaction names and labels, and the
// compiled per-reaction rate data lives inside OdeIntegrator. The JAX kernel
// consumes the same CSR arrays the Metal/CUDA kernels consume, so this binding
// exposes FlattenedReactionNetwork::fromModelAndNetwork verbatim and inherits
// its fail-closed validation (functional rates, TotalRate, non-finite rate
// constants). The JAX extra is optional; nothing here is reachable from a
// default import.

#include <cstring>
#include <string>
#include <vector>

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "engine/BatchSsa.hpp"

namespace py = pybind11;
using bng::engine::FlattenedReactionNetwork;
using bng::engine::GeneratedNetwork;

namespace {

template <typename T>
py::array_t<T> as_array(const std::vector<T>& values) {
    py::array_t<T> arr(values.size());
    if (!values.empty()) {
        std::memcpy(arr.mutable_data(), values.data(), values.size() * sizeof(T));
    }
    return arr;
}

} // namespace

#if defined(_WIN32) || defined(__CYGWIN__)
#  define BNG_EXPORT __declspec(dllexport)
#else
#  define BNG_EXPORT __attribute__((visibility("default")))
#endif

BNG_EXPORT void bind_jax_ssa(py::module_& m) {
    m.def(
        "jax_ssa_flatten",
        [](const bng::ast::Model& model, const GeneratedNetwork& network) {
            FlattenedReactionNetwork flat =
                FlattenedReactionNetwork::fromModelAndNetwork(model, network);

            py::dict out;
            out["num_species"] = flat.numSpecies;
            out["num_reactions"] = flat.numReactions;
            out["num_observables"] = flat.numObservables;
            out["initial_species"] = as_array(flat.initialSpecies);
            out["rate_constants"] = as_array(flat.rateConstants);
            out["reactant_offsets"] = as_array(flat.reactantOffsets);
            out["reactant_species"] = as_array(flat.reactantSpecies);
            out["reactant_stoich_offsets"] = as_array(flat.reactantStoichOffsets);
            out["react_change_offsets"] = as_array(flat.reactChangeOffsets);
            out["react_change_species"] = as_array(flat.reactChangeSpecies);
            out["prod_change_offsets"] = as_array(flat.prodChangeOffsets);
            out["prod_change_species"] = as_array(flat.prodChangeSpecies);
            out["obs_offsets"] = as_array(flat.obsOffsets);
            out["obs_species"] = as_array(flat.obsSpecies);
            out["obs_weights"] = as_array(flat.obsWeights);

            py::list names;
            for (const std::string& name : flat.observableNames) {
                names.append(name);
            }
            out["observable_names"] = names;
            return out;
        },
        py::arg("model"), py::arg("network"),
        "Flatten a generated network into the CSR arrays the direct batched-SSA "
        "kernels consume (the same structure the Metal/CUDA backends use). "
        "Raises on models the direct method cannot reproduce exactly.");
}