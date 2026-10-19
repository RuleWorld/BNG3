#pragma once
#include "matcher.hh"
#include <vector>
namespace NFcore2 {
static const std::uint32_t TRANSFORM_INFER_PARTNER_SLOT = 0xffffffffu;
enum TransformOpcode { TRANSFORM_SET_STATE_WORD, TRANSFORM_ADD_STATE_WORD, TRANSFORM_SET_SCAFFOLD_STATE, TRANSFORM_MOVE_OCCUPANT, TRANSFORM_POPULATION_ADD, TRANSFORM_BIND, TRANSFORM_UNBIND, TRANSFORM_CREATE_MOLECULE, TRANSFORM_DELETE_MOLECULE, TRANSFORM_DELETE_SPECIES, TRANSFORM_MOVE_MOLECULE, TRANSFORM_MOVE_SPECIES, TRANSFORM_DELETE_MOLECULE_CONDITIONAL, TRANSFORM_END };
struct TransformInstruction { std::uint16_t opcode; std::uint16_t target,other; std::uint32_t a,b; std::uint64_t value; FeatureId feature; bool target_is_graph_node; std::uint32_t target_graph_node; std::vector<std::uint32_t> excluded_graph_nodes; TransformInstruction(std::uint16_t op=TRANSFORM_END):opcode(op),target(0),other(0),a(0),b(0),value(0),feature(),target_is_graph_node(false),target_graph_node(0){} };
class TransformProgram{public:void add(const TransformInstruction&i){code_.push_back(i);}void execute(SimulationState&,ScaffoldStore&,MatchContext&,FeatureDelta&)const;const std::vector<TransformInstruction>& code()const{return code_;}private:std::vector<TransformInstruction>code_;};
class TransformRegistry{public:TransformProgramId add(const TransformProgram&p){programs_.push_back(p);return TransformProgramId((std::uint32_t)programs_.size()-1);}const TransformProgram&at(TransformProgramId id)const{return programs_.at(id.value());}std::size_t size()const{return programs_.size();}const std::vector<TransformProgram>& programs()const{return programs_;}private:std::vector<TransformProgram>programs_;};
}
