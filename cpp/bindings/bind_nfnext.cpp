#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "ast/Model.hpp"
#include "compile/Document.hpp"
#include "nfnext/from_bng.hpp"

#include <string>
#include <vector>

namespace py = pybind11;

namespace {

using namespace bng::compile;
using namespace nfnext;

const char* predicateKindName(PredicateKind kind) {
    switch (kind) {
    case PredicateKind::SiteStateEq: return "site_state_eq";
    case PredicateKind::SiteBound: return "site_bound";
    case PredicateKind::SiteFree: return "site_free";
    case PredicateKind::PositionEq: return "position_eq";
    case PredicateKind::PositionRange: return "position_range";
    case PredicateKind::NeighborFree: return "neighbor_free";
    case PredicateKind::NeighborOccupied: return "neighbor_occupied";
    }
    return "unknown";
}

const char* actionKindName(ActionKind kind) {
    switch (kind) {
    case ActionKind::SetSiteState: return "set_site_state";
    case ActionKind::Bind: return "bind";
    case ActionKind::Unbind: return "unbind";
    case ActionKind::Create: return "create";
    case ActionKind::Destroy: return "destroy";
    case ActionKind::DestroyComplex: return "destroy_complex";
    case ActionKind::MovePosition: return "move_position";
    }
    return "unknown";
}

const char* rateLawKindName(nfnext::RateLawKind kind) {
    switch (kind) {
    case nfnext::RateLawKind::Elementary: return "elementary";
    case nfnext::RateLawKind::Function: return "function";
    }
    return "unknown";
}

const char* molecularityKindName(MolecularityKind kind) {
    switch (kind) {
    case MolecularityKind::SameComplex: return "same_complex";
    case MolecularityKind::DifferentComplex: return "different_complex";
    }
    return "unknown";
}

const char* siteConstraintKindName(PatternIR::SiteConstraintKind kind) {
    switch (kind) {
    case PatternIR::SiteConstraintKind::State: return "state";
    case PatternIR::SiteConstraintKind::StateSet: return "state_set";
    case PatternIR::SiteConstraintKind::Free: return "free";
    case PatternIR::SiteConstraintKind::Bound: return "bound";
    }
    return "unknown";
}

py::dict patternSnapshot(const PatternIR& pattern) {
    py::dict result;
    py::list nodes;
    for (const auto& node : pattern.nodes) {
        py::dict item;
        item["molecule_type"] = node.molecule_type;
        py::list constraints;
        for (const auto& constraint : node.constraints) {
            py::dict entry;
            entry["kind"] = siteConstraintKindName(constraint.kind);
            entry["site"] = constraint.site;
            entry["state"] = constraint.state;
            py::list states;
            for (const auto value : constraint.states) states.append(value);
            entry["states"] = std::move(states);
            constraints.append(std::move(entry));
        }
        item["constraints"] = std::move(constraints);
        nodes.append(std::move(item));
    }
    result["nodes"] = std::move(nodes);
    py::list bonds;
    for (const auto& bond : pattern.bonds) {
        py::dict item;
        item["first"] = bond.first;
        item["first_site"] = bond.first_site;
        item["second"] = bond.second;
        item["second_site"] = bond.second_site;
        bonds.append(std::move(item));
    }
    result["bonds"] = std::move(bonds);
    py::list molecularity;
    for (const auto& constraint : pattern.molecularity) {
        py::dict item;
        item["kind"] = molecularityKindName(constraint.kind);
        item["left"] = constraint.left;
        item["right"] = constraint.right;
        molecularity.append(std::move(item));
    }
    result["molecularity"] = std::move(molecularity);
    py::list aliases;
    for (const auto& alias : pattern.aliases) {
        py::list pair;
        pair.append(alias.first);
        pair.append(alias.second);
        aliases.append(std::move(pair));
    }
    result["aliases"] = std::move(aliases);
    py::list connected;
    for (const auto& entry : pattern.connected_to) {
        py::list pair;
        pair.append(entry.first);
        pair.append(entry.second);
        connected.append(std::move(pair));
    }
    result["connected_to"] = std::move(connected);
    return result;
}

py::dict ruleSnapshot(const ExpandedRuleIR& rule) {
    py::dict result;
    result["id"] = rule.id;
    result["name"] = rule.name;
    result["rate"] = rule.rate;
    result["rate_law_kind"] = rateLawKindName(rule.rate_law.kind);
    result["rate_law_expression"] = rule.rate_law.expression;
    py::list predicates;
    for (const auto& predicate : rule.predicates) {
        py::dict item;
        item["kind"] = predicateKindName(predicate.kind);
        item["molecule_type"] = predicate.molecule_type;
        item["site"] = predicate.site;
        item["value"] = predicate.value;
        item["aux"] = predicate.aux;
        item["node"] = predicate.node;
        py::list states;
        for (const auto value : predicate.state_set) states.append(value);
        item["state_set"] = std::move(states);
        predicates.append(std::move(item));
    }
    result["predicates"] = std::move(predicates);
    py::list actions;
    for (const auto& action : rule.actions) {
        py::dict item;
        item["kind"] = actionKindName(action.kind);
        item["molecule_type"] = action.molecule_type;
        item["site"] = action.site;
        item["value"] = action.value;
        item["aux"] = action.aux;
        item["target_node"] = action.target_node;
        item["partner_node"] = action.partner_node;
        item["partner_site"] = action.partner_site;
        actions.append(std::move(item));
    }
    result["actions"] = std::move(actions);
    result["pattern"] = patternSnapshot(rule.pattern);
    py::dict annotations;
    for (const auto& entry : rule.annotations) {
        annotations[py::str(entry.first)] = entry.second;
    }
    result["annotations"] = std::move(annotations);
    return result;
}

py::dict lowerSnapshot(const bng::ast::Model& astModel) {
    Document document(astModel);
    const auto& model = document.model();
    py::dict result;
    result["valid"] = document.valid();
    const auto lowered = lowerFromBioNetGen(model);
    result["ok"] = lowered.ok();
    py::list issues;
    for (const auto& issue : lowered.issues) {
        py::dict item;
        item["severity"] =
            issue.severity == BngLoweringSeverity::Error ? "error" : "warning";
        item["entity"] = issue.entity;
        item["message"] = issue.message;
        issues.append(std::move(item));
    }
    result["issues"] = std::move(issues);
    result["format_version"] = ModelIR::kFormatVersion;
    result["model_name"] = lowered.model.model_name;
    py::list types;
    for (const auto& type : lowered.model.molecule_types) {
        py::dict item;
        item["id"] = type.id;
        item["name"] = type.name;
        py::list sites;
        for (const auto& site : type.sites) {
            py::dict entry;
            entry["name"] = site.name;
            py::list states;
            for (const auto& state : site.states) states.append(state);
            entry["states"] = std::move(states);
            sites.append(std::move(entry));
        }
        item["sites"] = std::move(sites);
        types.append(std::move(item));
    }
    result["molecule_types"] = std::move(types);
    py::list rules;
    for (const auto& rule : lowered.model.expanded_rules) {
        rules.append(ruleSnapshot(rule));
    }
    result["rules"] = std::move(rules);
    py::list families;
    for (const auto& family : lowered.model.rule_families) {
        py::dict item;
        item["id"] = family.id;
        item["name"] = family.name;
        item["default_rate"] = family.default_rate;
        item["rate_law_kind"] = rateLawKindName(family.rate_law.kind);
        item["rate_law_expression"] = family.rate_law.expression;
        families.append(std::move(item));
    }
    result["rule_families"] = std::move(families);
    return result;
}

py::dict executeSnapshot(const bng::ast::Model& astModel,
                          const std::vector<double>& sampleTimes,
                          std::uint64_t seed,
                          std::uint64_t maxEvents,
                          std::size_t maxParticles) {
    Document document(astModel);
    py::dict result;
    if (!document.valid()) {
        result["refused"] = true;
        result["reason"] = "the compiled model contains semantic errors";
        return result;
    }
    BngExecutionRequest request;
    request.sample_times = sampleTimes;
    request.seed = seed;
    request.max_events = maxEvents;
    request.max_particles = maxParticles;
    try {
        const auto execution = executeFromBioNetGen(document.model(), request);
        result["refused"] = false;
        py::list columns;
        for (const auto& column : execution.columns) columns.append(column);
        result["columns"] = std::move(columns);
        py::list rows;
        for (const auto& row : execution.rows) {
            py::list values;
            for (const auto value : row) values.append(value);
            rows.append(std::move(values));
        }
        result["rows"] = std::move(rows);
        result["event_count"] = execution.event_count;
    } catch (const std::exception& error) {
        result["refused"] = true;
        result["reason"] = error.what();
    }
    return result;
}

} // namespace

void bind_nfnext(py::module_& m) {
    m.def(
        "_nfnext_lower",
        [](const bng::ast::Model& model) { return lowerSnapshot(model); },
        py::arg("model"),
        "Lower a compiled BioNetGen model into NFnext's NFIR representation "
        "and report the lowered rules, issues and format version.");
    m.def(
        "_nfnext_execute",
        [](const bng::ast::Model& model,
           const std::vector<double>& sample_times,
           std::uint64_t seed,
           std::uint64_t max_events,
           std::size_t max_particles) {
            return executeSnapshot(model, sample_times, seed, max_events,
                                   max_particles);
        },
        py::arg("model"), py::arg("sample_times"), py::arg("seed") = 0,
        py::arg("max_events") = 1000000, py::arg("max_particles") = 1000000,
        "Execute NFnext's unary site-state executor for a compiled "
        "BioNetGen model and report the sampled rows or the explicit refusal.");
}
