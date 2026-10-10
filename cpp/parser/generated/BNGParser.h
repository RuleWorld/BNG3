
// Generated from BNGParser.g4 by ANTLR 4.13.1

#pragma once

#include "../antlr_compat.hpp"
#include "antlr4-runtime.h"




class  BNGParser : public antlr4::Parser {
public:
  enum {
    LINE_COMMENT = 1, LB = 2, WS = 3, SEPARATOR_LINE = 4, MINUS_SEPARATOR_LINE = 5, 
    BEGIN = 6, END = 7, MODEL = 8, PARAMETERS = 9, COMPARTMENTS = 10, MOLECULE = 11, 
    MOLECULES = 12, COUNTER = 13, TYPES = 14, SEED = 15, SPECIES = 16, OBSERVABLES = 17, 
    FUNCTIONS = 18, REACTION = 19, REACTIONS = 20, RULES = 21, REACTION_RULES = 22, 
    MOLECULE_TYPES = 23, GROUPS = 24, ACTIONS = 25, POPULATION = 26, MAPS = 27, 
    ENERGY = 28, PATTERNS = 29, MOLECULAR = 30, MATCHONCE = 31, DELETEMOLECULES = 32, 
    MOVECONNECTED = 33, INCLUDE_REACTANTS = 34, INCLUDE_PRODUCTS = 35, EXCLUDE_REACTANTS = 36, 
    EXCLUDE_PRODUCTS = 37, TOTALRATE = 38, VERSION = 39, SET_OPTION = 40, 
    SET_MODEL_NAME = 41, SUBSTANCEUNITS = 42, PREFIX = 43, SUFFIX = 44, 
    GENERATENETWORK = 45, OVERWRITE = 46, MAX_AGG = 47, MAX_ITER = 48, MAX_STOICH = 49, 
    PRINT_ITER = 50, CHECK_ISO = 51, GENERATEHYBRIDMODEL = 52, SAFE = 53, 
    EXECUTE = 54, SIMULATE = 55, METHOD = 56, ODE = 57, SSA = 58, PLA = 59, 
    NF = 60, VERBOSE = 61, NETFILE = 62, ARGFILE = 63, CONTINUE = 64, T_START = 65, 
    T_END = 66, N_STEPS = 67, N_OUTPUT_STEPS = 68, MAX_SIM_STEPS = 69, OUTPUT_STEP_INTERVAL = 70, 
    SAMPLE_TIMES = 71, SAVE_PROGRESS = 72, PRINT_CDAT = 73, PRINT_FUNCTIONS = 74, 
    PRINT_NET = 75, PRINT_END = 76, STOP_IF = 77, PRINT_ON_STOP = 78, SIMULATE_ODE = 79, 
    ATOL = 80, RTOL = 81, STEADY_STATE = 82, SPARSE = 83, SIMULATE_SSA = 84, 
    SIMULATE_PLA = 85, PLA_CONFIG = 86, PLA_OUTPUT = 87, SIMULATE_NF = 88, 
    SIMULATE_RM = 89, PARAM = 90, COMPLEX = 91, GET_FINAL_STATE = 92, GML = 93, 
    NOCSLF = 94, NOTF = 95, BINARY_OUTPUT = 96, UTL = 97, EQUIL = 98, PARAMETER_SCAN = 99, 
    BIFURCATE = 100, LINEAR_PARAMETER_SENSITIVITY = 101, PARAMETER = 102, 
    PAR_MIN = 103, PAR_MAX = 104, N_SCAN_PTS = 105, LOG_SCALE = 106, RESET_CONC = 107, 
    READFILE = 108, FILE = 109, ATOMIZE = 110, BLOCKS = 111, SKIPACTIONS = 112, 
    VISUALIZE = 113, TYPE = 114, BACKGROUND = 115, COLLAPSE = 116, OPTS = 117, 
    WRITESSC = 118, WRITESSCCFG = 119, FORMAT = 120, WRITEFILE = 121, WRITEMODEL = 122, 
    WRITEXML = 123, WRITENETWORK = 124, WRITESBML = 125, WRITESBMLMULTI = 126, 
    WRITEMDL = 127, WRITELATEX = 128, INCLUDE_MODEL = 129, INCLUDE_NETWORK = 130, 
    PRETTY_FORMATTING = 131, EVALUATE_EXPRESSIONS = 132, TEXTREACTION = 133, 
    TEXTSPECIES = 134, WRITEMFILE = 135, WRITEMEXFILE = 136, WRITECPPFILE = 137, 
    WRITECPYFILE = 138, BDF = 139, MAX_STEP = 140, MAXORDER = 141, STATS = 142, 
    MAX_NUM_STEPS = 143, MAX_ERR_TEST_FAILS = 144, MAX_CONV_FAILS = 145, 
    STIFF = 146, SETCONCENTRATION = 147, ADDCONCENTRATION = 148, SAVECONCENTRATIONS = 149, 
    RESETCONCENTRATIONS = 150, SETPARAMETER = 151, SAVEPARAMETERS = 152, 
    RESETPARAMETERS = 153, SETVOLUME = 154, SIMULATE_PSA = 155, SIMULATE_PROTOCOL = 156, 
    PROTOCOL = 157, POPLEVEL = 158, MOL_THRESHOLD = 159, NFSIM_EXEC = 160, 
    QUIT = 161, TRUE = 162, FALSE = 163, SAT = 164, MM = 165, HILL = 166, 
    ARRHENIUS = 167, MRATIO = 168, TFUN = 169, FUNCTIONPRODUCT = 170, PRIORITY = 171, 
    IF = 172, EXP = 173, LN = 174, LOG10 = 175, LOG2 = 176, SQRT = 177, 
    RINT = 178, ABS = 179, SIN = 180, COS = 181, TAN = 182, ASIN = 183, 
    ACOS = 184, ATAN = 185, SINH = 186, COSH = 187, TANH = 188, ASINH = 189, 
    ACOSH = 190, ATANH = 191, PI = 192, EULERIAN = 193, MIN = 194, MAX = 195, 
    SUM = 196, AVG = 197, TIME = 198, FLOAT = 199, INT = 200, STRING = 201, 
    QUOTED_STRING = 202, SINGLE_QUOTED_STRING = 203, SEMI = 204, COLON = 205, 
    LSBRACKET = 206, RSBRACKET = 207, LBRACKET = 208, RBRACKET = 209, COMMA = 210, 
    DOT = 211, LPAREN = 212, RPAREN = 213, UNI_REACTION_SIGN = 214, BI_REACTION_SIGN = 215, 
    DOLLAR = 216, TILDE = 217, AT = 218, GTE = 219, GT = 220, LTE = 221, 
    LT = 222, ASSIGNS = 223, EQUALS = 224, NOT_EQUALS = 225, BECOMES = 226, 
    LOGICAL_AND = 227, LOGICAL_OR = 228, LOGICAL_XOR = 229, DIV = 230, TIMES = 231, 
    MINUS = 232, PLUS = 233, POWER = 234, MOLECULE_TAG_TOKEN = 235, MOD = 236, 
    PIPE = 237, QMARK = 238, EMARK = 239, AMPERSAND = 240, VERSION_NUMBER = 241, 
    ULB = 242
  };

  enum {
    RuleProg = 0, RuleHeader_block = 1, RuleVersion_def = 2, RuleSubstance_def = 3, 
    RuleSet_option = 4, RuleSet_model_name = 5, RuleProgram_block = 6, RuleParameters_block = 7, 
    RuleParameter_def = 8, RuleParam_name = 9, RuleMolecule_types_block = 10, 
    RuleMolecule_type_def = 11, RuleMolecule_def = 12, RuleMolecule_attributes = 13, 
    RuleComponent_def_list = 14, RuleComponent_def = 15, RuleKeyword_as_component_name = 16, 
    RuleKeyword_as_mol_name = 17, RuleState_list = 18, RuleState_name = 19, 
    RuleSeed_species_block = 20, RuleSeed_species_def = 21, RuleSeed_amount_annotation = 22, 
    RuleSpecies_def = 23, RuleMolecule_compartment = 24, RuleMolecule_pattern = 25, 
    RuleScope_prefix = 26, RulePattern_bond_wildcard = 27, RuleMolecule_tag = 28, 
    RuleComponent_pattern_list = 29, RuleComponent_pattern = 30, RuleState_value = 31, 
    RuleBond_spec = 32, RuleComponent_label = 33, RuleBond_id = 34, RuleObservables_block = 35, 
    RuleObservable_def = 36, RuleObservable_type = 37, RuleObservable_pattern_list = 38, 
    RuleObservable_pattern = 39, RuleReaction_rules_block = 40, RuleReaction_rule_def = 41, 
    RuleLabel_def = 42, RuleReactant_patterns = 43, RuleProduct_patterns = 44, 
    RuleReaction_sign = 45, RuleRate_law = 46, RuleRate_law_expr = 47, RuleRate_law_or_expr = 48, 
    RuleRate_law_xor_expr = 49, RuleRate_law_and_expr = 50, RuleRate_law_eq_expr = 51, 
    RuleRate_law_add_expr = 52, RuleRate_law_mul_expr = 53, RuleRate_law_pow_expr = 54, 
    RuleRate_law_unary_expr = 55, RuleRate_law_primary_expr = 56, RuleRule_modifiers = 57, 
    RulePattern_list = 58, RuleFunctions_block = 59, RuleFunction_def = 60, 
    RuleFunction_name = 61, RuleParam_list = 62, RuleCompartments_block = 63, 
    RuleCompartment_def = 64, RuleEnergy_patterns_block = 65, RuleEnergy_pattern_def = 66, 
    RulePopulation_maps_block = 67, RulePopulation_map_def = 68, RuleBng3_events_block = 69, 
    RuleEvent_def = 70, RuleEvent_delay = 71, RuleEvent_priority = 72, RuleEvent_assignment = 73, 
    RuleBoolean_literal = 74, RuleActions_block = 75, RuleWrapped_actions_block = 76, 
    RuleBegin_actions_block = 77, RuleProtocol_block = 78, RuleAction_command = 79, 
    RuleSimulate_protocol_cmd = 80, RuleGenerate_network_cmd = 81, RuleSimulate_cmd = 82, 
    RuleWrite_cmd = 83, RuleSet_cmd = 84, RuleOther_action_cmd = 85, RuleAction_args = 86, 
    RuleAction_arg_list = 87, RuleAction_arg = 88, RuleAction_arg_value = 89, 
    RuleQuoted_string = 90, RuleKeyword_as_value = 91, RuleNested_hash_list = 92, 
    RuleNested_hash_item = 93, RuleArg_name = 94, RuleExpression_list = 95, 
    RuleExpression = 96, RuleConditional_expr = 97, RuleOr_expr = 98, RuleXor_expr = 99, 
    RuleAnd_expr = 100, RuleEquality_expr = 101, RuleRelational_expr = 102, 
    RuleAdditive_expr = 103, RuleMultiplicative_expr = 104, RulePower_expr = 105, 
    RuleUnary_expr = 106, RulePrimary_expr = 107, RuleFunction_call = 108, 
    RuleObservable_ref = 109, RuleLiteral = 110, RuleObservable_name = 111
  };

  explicit BNGParser(antlr4::TokenStream *input);

  BNGParser(antlr4::TokenStream *input, const antlr4::atn::ParserATNSimulatorOptions &options);

  ~BNGParser() override;

  std::string getGrammarFileName() const override;

  const antlr4::atn::ATN& getATN() const override;

  const std::vector<std::string>& getRuleNames() const override;

  const antlr4::dfa::Vocabulary& getVocabulary() const override;

  antlr4::atn::SerializedATNView getSerializedATN() const override;


  class ProgContext;
  class Header_blockContext;
  class Version_defContext;
  class Substance_defContext;
  class Set_optionContext;
  class Set_model_nameContext;
  class Program_blockContext;
  class Parameters_blockContext;
  class Parameter_defContext;
  class Param_nameContext;
  class Molecule_types_blockContext;
  class Molecule_type_defContext;
  class Molecule_defContext;
  class Molecule_attributesContext;
  class Component_def_listContext;
  class Component_defContext;
  class Keyword_as_component_nameContext;
  class Keyword_as_mol_nameContext;
  class State_listContext;
  class State_nameContext;
  class Seed_species_blockContext;
  class Seed_species_defContext;
  class Seed_amount_annotationContext;
  class Species_defContext;
  class Molecule_compartmentContext;
  class Molecule_patternContext;
  class Scope_prefixContext;
  class Pattern_bond_wildcardContext;
  class Molecule_tagContext;
  class Component_pattern_listContext;
  class Component_patternContext;
  class State_valueContext;
  class Bond_specContext;
  class Component_labelContext;
  class Bond_idContext;
  class Observables_blockContext;
  class Observable_defContext;
  class Observable_typeContext;
  class Observable_pattern_listContext;
  class Observable_patternContext;
  class Reaction_rules_blockContext;
  class Reaction_rule_defContext;
  class Label_defContext;
  class Reactant_patternsContext;
  class Product_patternsContext;
  class Reaction_signContext;
  class Rate_lawContext;
  class Rate_law_exprContext;
  class Rate_law_or_exprContext;
  class Rate_law_xor_exprContext;
  class Rate_law_and_exprContext;
  class Rate_law_eq_exprContext;
  class Rate_law_add_exprContext;
  class Rate_law_mul_exprContext;
  class Rate_law_pow_exprContext;
  class Rate_law_unary_exprContext;
  class Rate_law_primary_exprContext;
  class Rule_modifiersContext;
  class Pattern_listContext;
  class Functions_blockContext;
  class Function_defContext;
  class Function_nameContext;
  class Param_listContext;
  class Compartments_blockContext;
  class Compartment_defContext;
  class Energy_patterns_blockContext;
  class Energy_pattern_defContext;
  class Population_maps_blockContext;
  class Population_map_defContext;
  class Bng3_events_blockContext;
  class Event_defContext;
  class Event_delayContext;
  class Event_priorityContext;
  class Event_assignmentContext;
  class Boolean_literalContext;
  class Actions_blockContext;
  class Wrapped_actions_blockContext;
  class Begin_actions_blockContext;
  class Protocol_blockContext;
  class Action_commandContext;
  class Simulate_protocol_cmdContext;
  class Generate_network_cmdContext;
  class Simulate_cmdContext;
  class Write_cmdContext;
  class Set_cmdContext;
  class Other_action_cmdContext;
  class Action_argsContext;
  class Action_arg_listContext;
  class Action_argContext;
  class Action_arg_valueContext;
  class Quoted_stringContext;
  class Keyword_as_valueContext;
  class Nested_hash_listContext;
  class Nested_hash_itemContext;
  class Arg_nameContext;
  class Expression_listContext;
  class ExpressionContext;
  class Conditional_exprContext;
  class Or_exprContext;
  class Xor_exprContext;
  class And_exprContext;
  class Equality_exprContext;
  class Relational_exprContext;
  class Additive_exprContext;
  class Multiplicative_exprContext;
  class Power_exprContext;
  class Unary_exprContext;
  class Primary_exprContext;
  class Function_callContext;
  class Observable_refContext;
  class LiteralContext;
  class Observable_nameContext; 

  class  ProgContext : public antlr4::ParserRuleContext {
  public:
    ProgContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *EOF();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Header_blockContext *> header_block();
    Header_blockContext* header_block(size_t i);
    std::vector<Action_commandContext *> action_command();
    Action_commandContext* action_command(size_t i);
    Wrapped_actions_blockContext *wrapped_actions_block();
    Actions_blockContext *actions_block();
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> MODEL();
    antlr4::tree::TerminalNode* MODEL(size_t i);
    std::vector<Program_blockContext *> program_block();
    Program_blockContext* program_block(size_t i);
    antlr4::tree::TerminalNode *END();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ProgContext* prog();

  class  Header_blockContext : public antlr4::ParserRuleContext {
  public:
    Header_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Version_defContext *version_def();
    Substance_defContext *substance_def();
    Set_optionContext *set_option();
    Set_model_nameContext *set_model_name();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Header_blockContext* header_block();

  class  Version_defContext : public antlr4::ParserRuleContext {
  public:
    Version_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *VERSION();
    antlr4::tree::TerminalNode *LPAREN();
    Quoted_stringContext *quoted_string();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *SEMI();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Version_defContext* version_def();

  class  Substance_defContext : public antlr4::ParserRuleContext {
  public:
    Substance_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SUBSTANCEUNITS();
    antlr4::tree::TerminalNode *LPAREN();
    Quoted_stringContext *quoted_string();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *SEMI();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Substance_defContext* substance_def();

  class  Set_optionContext : public antlr4::ParserRuleContext {
  public:
    Set_optionContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SET_OPTION();
    antlr4::tree::TerminalNode *LPAREN();
    std::vector<Quoted_stringContext *> quoted_string();
    Quoted_stringContext* quoted_string(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);
    std::vector<Action_arg_valueContext *> action_arg_value();
    Action_arg_valueContext* action_arg_value(size_t i);
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *SEMI();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Set_optionContext* set_option();

  class  Set_model_nameContext : public antlr4::ParserRuleContext {
  public:
    Set_model_nameContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SET_MODEL_NAME();
    antlr4::tree::TerminalNode *LPAREN();
    Quoted_stringContext *quoted_string();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *SEMI();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Set_model_nameContext* set_model_name();

  class  Program_blockContext : public antlr4::ParserRuleContext {
  public:
    Program_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Parameters_blockContext *parameters_block();
    Molecule_types_blockContext *molecule_types_block();
    Seed_species_blockContext *seed_species_block();
    Observables_blockContext *observables_block();
    Reaction_rules_blockContext *reaction_rules_block();
    Functions_blockContext *functions_block();
    Compartments_blockContext *compartments_block();
    Energy_patterns_blockContext *energy_patterns_block();
    Population_maps_blockContext *population_maps_block();
    Bng3_events_blockContext *bng3_events_block();
    Protocol_blockContext *protocol_block();
    Wrapped_actions_blockContext *wrapped_actions_block();
    Begin_actions_blockContext *begin_actions_block();
    Set_optionContext *set_option();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Program_blockContext* program_block();

  class  Parameters_blockContext : public antlr4::ParserRuleContext {
  public:
    Parameters_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> PARAMETERS();
    antlr4::tree::TerminalNode* PARAMETERS(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Parameter_defContext *> parameter_def();
    Parameter_defContext* parameter_def(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Parameters_blockContext* parameters_block();

  class  Parameter_defContext : public antlr4::ParserRuleContext {
  public:
    Parameter_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Param_nameContext *> param_name();
    Param_nameContext* param_name(size_t i);
    antlr4::tree::TerminalNode *INT();
    antlr4::tree::TerminalNode *COLON();
    antlr4::tree::TerminalNode *BECOMES();
    ExpressionContext *expression();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Parameter_defContext* parameter_def();

  class  Param_nameContext : public antlr4::ParserRuleContext {
  public:
    Param_nameContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING();
    Arg_nameContext *arg_name();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Param_nameContext* param_name();

  class  Molecule_types_blockContext : public antlr4::ParserRuleContext {
  public:
    Molecule_types_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> MOLECULE();
    antlr4::tree::TerminalNode* MOLECULE(size_t i);
    std::vector<antlr4::tree::TerminalNode *> TYPES();
    antlr4::tree::TerminalNode* TYPES(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Molecule_type_defContext *> molecule_type_def();
    Molecule_type_defContext* molecule_type_def(size_t i);
    std::vector<antlr4::tree::TerminalNode *> MOLECULE_TYPES();
    antlr4::tree::TerminalNode* MOLECULE_TYPES(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Molecule_types_blockContext* molecule_types_block();

  class  Molecule_type_defContext : public antlr4::ParserRuleContext {
  public:
    Molecule_type_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Molecule_defContext *molecule_def();
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *COLON();
    antlr4::tree::TerminalNode *POPULATION();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Molecule_type_defContext* molecule_type_def();

  class  Molecule_defContext : public antlr4::ParserRuleContext {
  public:
    Molecule_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING();
    Keyword_as_mol_nameContext *keyword_as_mol_name();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    Molecule_attributesContext *molecule_attributes();
    Component_def_listContext *component_def_list();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Molecule_defContext* molecule_def();

  class  Molecule_attributesContext : public antlr4::ParserRuleContext {
  public:
    Molecule_attributesContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LBRACKET();
    antlr4::tree::TerminalNode *RBRACKET();
    Action_arg_listContext *action_arg_list();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Molecule_attributesContext* molecule_attributes();

  class  Component_def_listContext : public antlr4::ParserRuleContext {
  public:
    Component_def_listContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Component_defContext *> component_def();
    Component_defContext* component_def(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Component_def_listContext* component_def_list();

  class  Component_defContext : public antlr4::ParserRuleContext {
  public:
    Component_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *INT();
    Keyword_as_component_nameContext *keyword_as_component_name();
    antlr4::tree::TerminalNode *TILDE();
    State_listContext *state_list();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Component_defContext* component_def();

  class  Keyword_as_component_nameContext : public antlr4::ParserRuleContext {
  public:
    Keyword_as_component_nameContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SIN();
    antlr4::tree::TerminalNode *COS();
    antlr4::tree::TerminalNode *TAN();
    antlr4::tree::TerminalNode *ASIN();
    antlr4::tree::TerminalNode *ACOS();
    antlr4::tree::TerminalNode *ATAN();
    antlr4::tree::TerminalNode *SINH();
    antlr4::tree::TerminalNode *COSH();
    antlr4::tree::TerminalNode *TANH();
    antlr4::tree::TerminalNode *ASINH();
    antlr4::tree::TerminalNode *ACOSH();
    antlr4::tree::TerminalNode *ATANH();
    antlr4::tree::TerminalNode *EXP();
    antlr4::tree::TerminalNode *LN();
    antlr4::tree::TerminalNode *LOG10();
    antlr4::tree::TerminalNode *LOG2();
    antlr4::tree::TerminalNode *SQRT();
    antlr4::tree::TerminalNode *ABS();
    antlr4::tree::TerminalNode *MIN();
    antlr4::tree::TerminalNode *MAX();
    antlr4::tree::TerminalNode *SUM();
    antlr4::tree::TerminalNode *AVG();
    antlr4::tree::TerminalNode *IF();
    antlr4::tree::TerminalNode *TIME();
    antlr4::tree::TerminalNode *SAT();
    antlr4::tree::TerminalNode *MM();
    antlr4::tree::TerminalNode *HILL();
    antlr4::tree::TerminalNode *ARRHENIUS();
    antlr4::tree::TerminalNode *MRATIO();
    antlr4::tree::TerminalNode *TFUN();
    antlr4::tree::TerminalNode *FUNCTIONPRODUCT();
    antlr4::tree::TerminalNode *TYPE();
    antlr4::tree::TerminalNode *METHOD();
    antlr4::tree::TerminalNode *PARAMETER();
    antlr4::tree::TerminalNode *FILE();
    antlr4::tree::TerminalNode *FORMAT();
    antlr4::tree::TerminalNode *PREFIX();
    antlr4::tree::TerminalNode *SUFFIX();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Keyword_as_component_nameContext* keyword_as_component_name();

  class  Keyword_as_mol_nameContext : public antlr4::ParserRuleContext {
  public:
    Keyword_as_mol_nameContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SPECIES();
    antlr4::tree::TerminalNode *MOLECULE();
    antlr4::tree::TerminalNode *MOLECULES();
    antlr4::tree::TerminalNode *REACTION();
    antlr4::tree::TerminalNode *REACTIONS();
    antlr4::tree::TerminalNode *RULES();
    antlr4::tree::TerminalNode *PARAMETERS();
    antlr4::tree::TerminalNode *OBSERVABLES();
    antlr4::tree::TerminalNode *FUNCTIONS();
    antlr4::tree::TerminalNode *COMPARTMENTS();
    antlr4::tree::TerminalNode *ENERGY();
    antlr4::tree::TerminalNode *PATTERNS();
    antlr4::tree::TerminalNode *MODEL();
    antlr4::tree::TerminalNode *SEED();
    antlr4::tree::TerminalNode *GROUPS();
    antlr4::tree::TerminalNode *POPULATION();
    antlr4::tree::TerminalNode *COUNTER();
    antlr4::tree::TerminalNode *PRIORITY();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Keyword_as_mol_nameContext* keyword_as_mol_name();

  class  State_listContext : public antlr4::ParserRuleContext {
  public:
    State_listContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<State_nameContext *> state_name();
    State_nameContext* state_name(size_t i);
    std::vector<antlr4::tree::TerminalNode *> TILDE();
    antlr4::tree::TerminalNode* TILDE(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  State_listContext* state_list();

  class  State_nameContext : public antlr4::ParserRuleContext {
  public:
    State_nameContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *INT();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  State_nameContext* state_name();

  class  Seed_species_blockContext : public antlr4::ParserRuleContext {
  public:
    Seed_species_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> SEED();
    antlr4::tree::TerminalNode* SEED(size_t i);
    std::vector<antlr4::tree::TerminalNode *> SPECIES();
    antlr4::tree::TerminalNode* SPECIES(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Seed_species_defContext *> seed_species_def();
    Seed_species_defContext* seed_species_def(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Seed_species_blockContext* seed_species_block();

  class  Seed_species_defContext : public antlr4::ParserRuleContext {
  public:
    Seed_species_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Species_defContext *species_def();
    antlr4::tree::TerminalNode *INT();
    std::vector<antlr4::tree::TerminalNode *> STRING();
    antlr4::tree::TerminalNode* STRING(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COLON();
    antlr4::tree::TerminalNode* COLON(size_t i);
    antlr4::tree::TerminalNode *DOLLAR();
    antlr4::tree::TerminalNode *AT();
    ExpressionContext *expression();
    Seed_amount_annotationContext *seed_amount_annotation();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Seed_species_defContext* seed_species_def();

  class  Seed_amount_annotationContext : public antlr4::ParserRuleContext {
  public:
    Seed_amount_annotationContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *MOD();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Seed_amount_annotationContext* seed_amount_annotation();

  class  Species_defContext : public antlr4::ParserRuleContext {
  public:
    Species_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Molecule_patternContext *> molecule_pattern();
    Molecule_patternContext* molecule_pattern(size_t i);
    std::vector<antlr4::tree::TerminalNode *> AT();
    antlr4::tree::TerminalNode* AT(size_t i);
    std::vector<antlr4::tree::TerminalNode *> STRING();
    antlr4::tree::TerminalNode* STRING(size_t i);
    antlr4::tree::TerminalNode *COLON();
    std::vector<Molecule_compartmentContext *> molecule_compartment();
    Molecule_compartmentContext* molecule_compartment(size_t i);
    std::vector<antlr4::tree::TerminalNode *> DOT();
    antlr4::tree::TerminalNode* DOT(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Species_defContext* species_def();

  class  Molecule_compartmentContext : public antlr4::ParserRuleContext {
  public:
    Molecule_compartmentContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *AT();
    antlr4::tree::TerminalNode *STRING();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Molecule_compartmentContext* molecule_compartment();

  class  Molecule_patternContext : public antlr4::ParserRuleContext {
  public:
    Molecule_patternContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING();
    Keyword_as_mol_nameContext *keyword_as_mol_name();
    Scope_prefixContext *scope_prefix();
    Molecule_compartmentContext *molecule_compartment();
    std::vector<Molecule_tagContext *> molecule_tag();
    Molecule_tagContext* molecule_tag(size_t i);
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    Pattern_bond_wildcardContext *pattern_bond_wildcard();
    Molecule_attributesContext *molecule_attributes();
    Component_pattern_listContext *component_pattern_list();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Molecule_patternContext* molecule_pattern();

  class  Scope_prefixContext : public antlr4::ParserRuleContext {
  public:
    Scope_prefixContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *MOLECULE_TAG_TOKEN();
    std::vector<antlr4::tree::TerminalNode *> COLON();
    antlr4::tree::TerminalNode* COLON(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Scope_prefixContext* scope_prefix();

  class  Pattern_bond_wildcardContext : public antlr4::ParserRuleContext {
  public:
    Pattern_bond_wildcardContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *EMARK();
    antlr4::tree::TerminalNode *PLUS();
    antlr4::tree::TerminalNode *QMARK();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Pattern_bond_wildcardContext* pattern_bond_wildcard();

  class  Molecule_tagContext : public antlr4::ParserRuleContext {
  public:
    Molecule_tagContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *MOLECULE_TAG_TOKEN();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Molecule_tagContext* molecule_tag();

  class  Component_pattern_listContext : public antlr4::ParserRuleContext {
  public:
    Component_pattern_listContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Component_patternContext *> component_pattern();
    Component_patternContext* component_pattern(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Component_pattern_listContext* component_pattern_list();

  class  Component_patternContext : public antlr4::ParserRuleContext {
  public:
    Component_patternContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *INT();
    Keyword_as_component_nameContext *keyword_as_component_name();
    std::vector<Bond_specContext *> bond_spec();
    Bond_specContext* bond_spec(size_t i);
    std::vector<Component_labelContext *> component_label();
    Component_labelContext* component_label(size_t i);
    std::vector<antlr4::tree::TerminalNode *> DOT();
    antlr4::tree::TerminalNode* DOT(size_t i);
    std::vector<antlr4::tree::TerminalNode *> TILDE();
    antlr4::tree::TerminalNode* TILDE(size_t i);
    std::vector<State_valueContext *> state_value();
    State_valueContext* state_value(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Component_patternContext* component_pattern();

  class  State_valueContext : public antlr4::ParserRuleContext {
  public:
    State_valueContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *INT();
    antlr4::tree::TerminalNode *QMARK();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  State_valueContext* state_value();

  class  Bond_specContext : public antlr4::ParserRuleContext {
  public:
    Bond_specContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *DOT();
    antlr4::tree::TerminalNode *EMARK();
    Bond_idContext *bond_id();
    antlr4::tree::TerminalNode *PLUS();
    antlr4::tree::TerminalNode *QMARK();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Bond_specContext* bond_spec();

  class  Component_labelContext : public antlr4::ParserRuleContext {
  public:
    Component_labelContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *MOLECULE_TAG_TOKEN();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Component_labelContext* component_label();

  class  Bond_idContext : public antlr4::ParserRuleContext {
  public:
    Bond_idContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *INT();
    antlr4::tree::TerminalNode *STRING();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Bond_idContext* bond_id();

  class  Observables_blockContext : public antlr4::ParserRuleContext {
  public:
    Observables_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> OBSERVABLES();
    antlr4::tree::TerminalNode* OBSERVABLES(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Observable_defContext *> observable_def();
    Observable_defContext* observable_def(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Observables_blockContext* observables_block();

  class  Observable_defContext : public antlr4::ParserRuleContext {
  public:
    Observable_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Observable_nameContext *observable_name();
    Observable_pattern_listContext *observable_pattern_list();
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *COLON();
    Observable_typeContext *observable_type();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Observable_defContext* observable_def();

  class  Observable_typeContext : public antlr4::ParserRuleContext {
  public:
    Observable_typeContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *MOLECULES();
    antlr4::tree::TerminalNode *SPECIES();
    antlr4::tree::TerminalNode *COUNTER();
    antlr4::tree::TerminalNode *STRING();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Observable_typeContext* observable_type();

  class  Observable_pattern_listContext : public antlr4::ParserRuleContext {
  public:
    Observable_pattern_listContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Observable_patternContext *> observable_pattern();
    Observable_patternContext* observable_pattern(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Observable_pattern_listContext* observable_pattern_list();

  class  Observable_patternContext : public antlr4::ParserRuleContext {
  public:
    Observable_patternContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Species_defContext *species_def();
    antlr4::tree::TerminalNode *GT();
    antlr4::tree::TerminalNode *INT();
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *EQUALS();
    antlr4::tree::TerminalNode *GTE();
    antlr4::tree::TerminalNode *LT();
    antlr4::tree::TerminalNode *LTE();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Observable_patternContext* observable_pattern();

  class  Reaction_rules_blockContext : public antlr4::ParserRuleContext {
  public:
    Reaction_rules_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> REACTION();
    antlr4::tree::TerminalNode* REACTION(size_t i);
    std::vector<antlr4::tree::TerminalNode *> RULES();
    antlr4::tree::TerminalNode* RULES(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Reaction_rule_defContext *> reaction_rule_def();
    Reaction_rule_defContext* reaction_rule_def(size_t i);
    std::vector<antlr4::tree::TerminalNode *> REACTION_RULES();
    antlr4::tree::TerminalNode* REACTION_RULES(size_t i);
    std::vector<antlr4::tree::TerminalNode *> REACTIONS();
    antlr4::tree::TerminalNode* REACTIONS(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Reaction_rules_blockContext* reaction_rules_block();

  class  Reaction_rule_defContext : public antlr4::ParserRuleContext {
  public:
    Reaction_rule_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Reactant_patternsContext *reactant_patterns();
    Reaction_signContext *reaction_sign();
    Product_patternsContext *product_patterns();
    Rate_lawContext *rate_law();
    Label_defContext *label_def();
    antlr4::tree::TerminalNode *LBRACKET();
    std::vector<Rule_modifiersContext *> rule_modifiers();
    Rule_modifiersContext* rule_modifiers(size_t i);
    antlr4::tree::TerminalNode *RBRACKET();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Reaction_rule_defContext* reaction_rule_def();

  class  Label_defContext : public antlr4::ParserRuleContext {
  public:
    Label_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *COLON();
    std::vector<antlr4::tree::TerminalNode *> INT();
    antlr4::tree::TerminalNode* INT(size_t i);
    std::vector<antlr4::tree::TerminalNode *> STRING();
    antlr4::tree::TerminalNode* STRING(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LPAREN();
    antlr4::tree::TerminalNode* LPAREN(size_t i);
    std::vector<antlr4::tree::TerminalNode *> RPAREN();
    antlr4::tree::TerminalNode* RPAREN(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Label_defContext* label_def();

  class  Reactant_patternsContext : public antlr4::ParserRuleContext {
  public:
    Reactant_patternsContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Species_defContext *> species_def();
    Species_defContext* species_def(size_t i);
    std::vector<antlr4::tree::TerminalNode *> INT();
    antlr4::tree::TerminalNode* INT(size_t i);
    std::vector<antlr4::tree::TerminalNode *> PLUS();
    antlr4::tree::TerminalNode* PLUS(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Reactant_patternsContext* reactant_patterns();

  class  Product_patternsContext : public antlr4::ParserRuleContext {
  public:
    Product_patternsContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Species_defContext *> species_def();
    Species_defContext* species_def(size_t i);
    std::vector<antlr4::tree::TerminalNode *> INT();
    antlr4::tree::TerminalNode* INT(size_t i);
    std::vector<antlr4::tree::TerminalNode *> PLUS();
    antlr4::tree::TerminalNode* PLUS(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Product_patternsContext* product_patterns();

  class  Reaction_signContext : public antlr4::ParserRuleContext {
  public:
    Reaction_signContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *UNI_REACTION_SIGN();
    antlr4::tree::TerminalNode *BI_REACTION_SIGN();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Reaction_signContext* reaction_sign();

  class  Rate_lawContext : public antlr4::ParserRuleContext {
  public:
    Rate_lawContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Rate_law_exprContext *> rate_law_expr();
    Rate_law_exprContext* rate_law_expr(size_t i);
    antlr4::tree::TerminalNode *COMMA();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rate_lawContext* rate_law();

  class  Rate_law_exprContext : public antlr4::ParserRuleContext {
  public:
    Rate_law_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Rate_law_or_exprContext *rate_law_or_expr();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rate_law_exprContext* rate_law_expr();

  class  Rate_law_or_exprContext : public antlr4::ParserRuleContext {
  public:
    Rate_law_or_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Rate_law_xor_exprContext *> rate_law_xor_expr();
    Rate_law_xor_exprContext* rate_law_xor_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LOGICAL_OR();
    antlr4::tree::TerminalNode* LOGICAL_OR(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rate_law_or_exprContext* rate_law_or_expr();

  class  Rate_law_xor_exprContext : public antlr4::ParserRuleContext {
  public:
    Rate_law_xor_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Rate_law_and_exprContext *> rate_law_and_expr();
    Rate_law_and_exprContext* rate_law_and_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LOGICAL_XOR();
    antlr4::tree::TerminalNode* LOGICAL_XOR(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rate_law_xor_exprContext* rate_law_xor_expr();

  class  Rate_law_and_exprContext : public antlr4::ParserRuleContext {
  public:
    Rate_law_and_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Rate_law_eq_exprContext *> rate_law_eq_expr();
    Rate_law_eq_exprContext* rate_law_eq_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LOGICAL_AND();
    antlr4::tree::TerminalNode* LOGICAL_AND(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rate_law_and_exprContext* rate_law_and_expr();

  class  Rate_law_eq_exprContext : public antlr4::ParserRuleContext {
  public:
    Rate_law_eq_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Rate_law_add_exprContext *> rate_law_add_expr();
    Rate_law_add_exprContext* rate_law_add_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> EQUALS();
    antlr4::tree::TerminalNode* EQUALS(size_t i);
    std::vector<antlr4::tree::TerminalNode *> NOT_EQUALS();
    antlr4::tree::TerminalNode* NOT_EQUALS(size_t i);
    std::vector<antlr4::tree::TerminalNode *> GTE();
    antlr4::tree::TerminalNode* GTE(size_t i);
    std::vector<antlr4::tree::TerminalNode *> GT();
    antlr4::tree::TerminalNode* GT(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LTE();
    antlr4::tree::TerminalNode* LTE(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LT();
    antlr4::tree::TerminalNode* LT(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rate_law_eq_exprContext* rate_law_eq_expr();

  class  Rate_law_add_exprContext : public antlr4::ParserRuleContext {
  public:
    Rate_law_add_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Rate_law_mul_exprContext *> rate_law_mul_expr();
    Rate_law_mul_exprContext* rate_law_mul_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> PLUS();
    antlr4::tree::TerminalNode* PLUS(size_t i);
    std::vector<antlr4::tree::TerminalNode *> MINUS();
    antlr4::tree::TerminalNode* MINUS(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rate_law_add_exprContext* rate_law_add_expr();

  class  Rate_law_mul_exprContext : public antlr4::ParserRuleContext {
  public:
    Rate_law_mul_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Rate_law_pow_exprContext *> rate_law_pow_expr();
    Rate_law_pow_exprContext* rate_law_pow_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> TIMES();
    antlr4::tree::TerminalNode* TIMES(size_t i);
    std::vector<antlr4::tree::TerminalNode *> DIV();
    antlr4::tree::TerminalNode* DIV(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rate_law_mul_exprContext* rate_law_mul_expr();

  class  Rate_law_pow_exprContext : public antlr4::ParserRuleContext {
  public:
    Rate_law_pow_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Rate_law_unary_exprContext *> rate_law_unary_expr();
    Rate_law_unary_exprContext* rate_law_unary_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> POWER();
    antlr4::tree::TerminalNode* POWER(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rate_law_pow_exprContext* rate_law_pow_expr();

  class  Rate_law_unary_exprContext : public antlr4::ParserRuleContext {
  public:
    Rate_law_unary_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Rate_law_primary_exprContext *rate_law_primary_expr();
    antlr4::tree::TerminalNode *PLUS();
    antlr4::tree::TerminalNode *MINUS();
    antlr4::tree::TerminalNode *EMARK();
    antlr4::tree::TerminalNode *TILDE();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rate_law_unary_exprContext* rate_law_unary_expr();

  class  Rate_law_primary_exprContext : public antlr4::ParserRuleContext {
  public:
    Rate_law_primary_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    Rate_law_exprContext *rate_law_expr();
    antlr4::tree::TerminalNode *RPAREN();
    Function_callContext *function_call();
    Observable_refContext *observable_ref();
    LiteralContext *literal();
    Arg_nameContext *arg_name();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rate_law_primary_exprContext* rate_law_primary_expr();

  class  Rule_modifiersContext : public antlr4::ParserRuleContext {
  public:
    Rule_modifiersContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *DELETEMOLECULES();
    antlr4::tree::TerminalNode *MOVECONNECTED();
    antlr4::tree::TerminalNode *MATCHONCE();
    antlr4::tree::TerminalNode *TOTALRATE();
    antlr4::tree::TerminalNode *PRIORITY();
    antlr4::tree::TerminalNode *BECOMES();
    ExpressionContext *expression();
    antlr4::tree::TerminalNode *INCLUDE_REACTANTS();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *INT();
    antlr4::tree::TerminalNode *COMMA();
    Pattern_listContext *pattern_list();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *EXCLUDE_REACTANTS();
    antlr4::tree::TerminalNode *INCLUDE_PRODUCTS();
    antlr4::tree::TerminalNode *EXCLUDE_PRODUCTS();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Rule_modifiersContext* rule_modifiers();

  class  Pattern_listContext : public antlr4::ParserRuleContext {
  public:
    Pattern_listContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Species_defContext *> species_def();
    Species_defContext* species_def(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Pattern_listContext* pattern_list();

  class  Functions_blockContext : public antlr4::ParserRuleContext {
  public:
    Functions_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> FUNCTIONS();
    antlr4::tree::TerminalNode* FUNCTIONS(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Function_defContext *> function_def();
    Function_defContext* function_def(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Functions_blockContext* functions_block();

  class  Function_defContext : public antlr4::ParserRuleContext {
  public:
    Function_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Function_nameContext *function_name();
    ExpressionContext *expression();
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *COLON();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *BECOMES();
    Param_listContext *param_list();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Function_defContext* function_def();

  class  Function_nameContext : public antlr4::ParserRuleContext {
  public:
    Function_nameContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Arg_nameContext *arg_name();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Function_nameContext* function_name();

  class  Param_listContext : public antlr4::ParserRuleContext {
  public:
    Param_listContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<antlr4::tree::TerminalNode *> STRING();
    antlr4::tree::TerminalNode* STRING(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Param_listContext* param_list();

  class  Compartments_blockContext : public antlr4::ParserRuleContext {
  public:
    Compartments_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> COMPARTMENTS();
    antlr4::tree::TerminalNode* COMPARTMENTS(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Compartment_defContext *> compartment_def();
    Compartment_defContext* compartment_def(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Compartments_blockContext* compartments_block();

  class  Compartment_defContext : public antlr4::ParserRuleContext {
  public:
    Compartment_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<antlr4::tree::TerminalNode *> STRING();
    antlr4::tree::TerminalNode* STRING(size_t i);
    antlr4::tree::TerminalNode *INT();
    ExpressionContext *expression();
    antlr4::tree::TerminalNode *COLON();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Compartment_defContext* compartment_def();

  class  Energy_patterns_blockContext : public antlr4::ParserRuleContext {
  public:
    Energy_patterns_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> ENERGY();
    antlr4::tree::TerminalNode* ENERGY(size_t i);
    std::vector<antlr4::tree::TerminalNode *> PATTERNS();
    antlr4::tree::TerminalNode* PATTERNS(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Energy_pattern_defContext *> energy_pattern_def();
    Energy_pattern_defContext* energy_pattern_def(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Energy_patterns_blockContext* energy_patterns_block();

  class  Energy_pattern_defContext : public antlr4::ParserRuleContext {
  public:
    Energy_pattern_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Species_defContext *species_def();
    ExpressionContext *expression();
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *COLON();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Energy_pattern_defContext* energy_pattern_def();

  class  Population_maps_blockContext : public antlr4::ParserRuleContext {
  public:
    Population_maps_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> POPULATION();
    antlr4::tree::TerminalNode* POPULATION(size_t i);
    std::vector<antlr4::tree::TerminalNode *> MAPS();
    antlr4::tree::TerminalNode* MAPS(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Population_map_defContext *> population_map_def();
    Population_map_defContext* population_map_def(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Population_maps_blockContext* population_maps_block();

  class  Population_map_defContext : public antlr4::ParserRuleContext {
  public:
    Population_map_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Species_defContext *species_def();
    antlr4::tree::TerminalNode *UNI_REACTION_SIGN();
    std::vector<antlr4::tree::TerminalNode *> STRING();
    antlr4::tree::TerminalNode* STRING(size_t i);
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *COLON();
    Param_listContext *param_list();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Population_map_defContext* population_map_def();

  class  Bng3_events_blockContext : public antlr4::ParserRuleContext {
  public:
    Bng3_events_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> STRING();
    antlr4::tree::TerminalNode* STRING(size_t i);
    antlr4::tree::TerminalNode *VERSION();
    antlr4::tree::TerminalNode *INT();
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Event_defContext *> event_def();
    Event_defContext* event_def(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Bng3_events_blockContext* bng3_events_block();

  class  Event_defContext : public antlr4::ParserRuleContext {
  public:
    Event_defContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<antlr4::tree::TerminalNode *> STRING();
    antlr4::tree::TerminalNode* STRING(size_t i);
    Quoted_stringContext *quoted_string();
    std::vector<antlr4::tree::TerminalNode *> COLON();
    antlr4::tree::TerminalNode* COLON(size_t i);
    ExpressionContext *expression();
    std::vector<Boolean_literalContext *> boolean_literal();
    Boolean_literalContext* boolean_literal(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    Event_delayContext *event_delay();
    Event_priorityContext *event_priority();
    std::vector<Event_assignmentContext *> event_assignment();
    Event_assignmentContext* event_assignment(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Event_defContext* event_def();

  class  Event_delayContext : public antlr4::ParserRuleContext {
  public:
    Event_delayContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *COLON();
    ExpressionContext *expression();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Event_delayContext* event_delay();

  class  Event_priorityContext : public antlr4::ParserRuleContext {
  public:
    Event_priorityContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *PRIORITY();
    antlr4::tree::TerminalNode *COLON();
    ExpressionContext *expression();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Event_priorityContext* event_priority();

  class  Event_assignmentContext : public antlr4::ParserRuleContext {
  public:
    Event_assignmentContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *COLON();
    Param_nameContext *param_name();
    antlr4::tree::TerminalNode *BECOMES();
    ExpressionContext *expression();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Event_assignmentContext* event_assignment();

  class  Boolean_literalContext : public antlr4::ParserRuleContext {
  public:
    Boolean_literalContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *TRUE();
    antlr4::tree::TerminalNode *FALSE();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Boolean_literalContext* boolean_literal();

  class  Actions_blockContext : public antlr4::ParserRuleContext {
  public:
    Actions_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Action_commandContext *> action_command();
    Action_commandContext* action_command(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Actions_blockContext* actions_block();

  class  Wrapped_actions_blockContext : public antlr4::ParserRuleContext {
  public:
    Wrapped_actions_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> ACTIONS();
    antlr4::tree::TerminalNode* ACTIONS(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Action_commandContext *> action_command();
    Action_commandContext* action_command(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Wrapped_actions_blockContext* wrapped_actions_block();

  class  Begin_actions_blockContext : public antlr4::ParserRuleContext {
  public:
    Begin_actions_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> ACTIONS();
    antlr4::tree::TerminalNode* ACTIONS(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Action_commandContext *> action_command();
    Action_commandContext* action_command(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Begin_actions_blockContext* begin_actions_block();

  class  Protocol_blockContext : public antlr4::ParserRuleContext {
  public:
    Protocol_blockContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *BEGIN();
    std::vector<antlr4::tree::TerminalNode *> PROTOCOL();
    antlr4::tree::TerminalNode* PROTOCOL(size_t i);
    antlr4::tree::TerminalNode *END();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);
    std::vector<Action_commandContext *> action_command();
    Action_commandContext* action_command(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Protocol_blockContext* protocol_block();

  class  Action_commandContext : public antlr4::ParserRuleContext {
  public:
    Action_commandContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Generate_network_cmdContext *generate_network_cmd();
    Simulate_cmdContext *simulate_cmd();
    Simulate_protocol_cmdContext *simulate_protocol_cmd();
    Write_cmdContext *write_cmd();
    Set_cmdContext *set_cmd();
    Other_action_cmdContext *other_action_cmd();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Action_commandContext* action_command();

  class  Simulate_protocol_cmdContext : public antlr4::ParserRuleContext {
  public:
    Simulate_protocol_cmdContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *SIMULATE_PROTOCOL();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    Action_argsContext *action_args();
    antlr4::tree::TerminalNode *SEMI();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Simulate_protocol_cmdContext* simulate_protocol_cmd();

  class  Generate_network_cmdContext : public antlr4::ParserRuleContext {
  public:
    Generate_network_cmdContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *GENERATENETWORK();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    Action_argsContext *action_args();
    antlr4::tree::TerminalNode *SEMI();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Generate_network_cmdContext* generate_network_cmd();

  class  Simulate_cmdContext : public antlr4::ParserRuleContext {
  public:
    Simulate_cmdContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *SIMULATE();
    antlr4::tree::TerminalNode *SIMULATE_ODE();
    antlr4::tree::TerminalNode *SIMULATE_SSA();
    antlr4::tree::TerminalNode *SIMULATE_PLA();
    antlr4::tree::TerminalNode *SIMULATE_NF();
    antlr4::tree::TerminalNode *SIMULATE_RM();
    antlr4::tree::TerminalNode *SIMULATE_PSA();
    Action_argsContext *action_args();
    antlr4::tree::TerminalNode *SEMI();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Simulate_cmdContext* simulate_cmd();

  class  Write_cmdContext : public antlr4::ParserRuleContext {
  public:
    Write_cmdContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *WRITEFILE();
    antlr4::tree::TerminalNode *WRITEXML();
    antlr4::tree::TerminalNode *WRITESBML();
    antlr4::tree::TerminalNode *WRITESBMLMULTI();
    antlr4::tree::TerminalNode *WRITENETWORK();
    antlr4::tree::TerminalNode *WRITEMODEL();
    antlr4::tree::TerminalNode *WRITEMFILE();
    antlr4::tree::TerminalNode *WRITEMEXFILE();
    antlr4::tree::TerminalNode *WRITECPPFILE();
    antlr4::tree::TerminalNode *WRITECPYFILE();
    antlr4::tree::TerminalNode *WRITELATEX();
    antlr4::tree::TerminalNode *WRITEMDL();
    antlr4::tree::TerminalNode *WRITESSC();
    antlr4::tree::TerminalNode *WRITESSCCFG();
    Action_argsContext *action_args();
    antlr4::tree::TerminalNode *SEMI();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Write_cmdContext* write_cmd();

  class  Set_cmdContext : public antlr4::ParserRuleContext {
  public:
    Set_cmdContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    Quoted_stringContext *quoted_string();
    antlr4::tree::TerminalNode *COMMA();
    Action_arg_valueContext *action_arg_value();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *SETCONCENTRATION();
    antlr4::tree::TerminalNode *ADDCONCENTRATION();
    antlr4::tree::TerminalNode *SETPARAMETER();
    antlr4::tree::TerminalNode *SEMI();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Set_cmdContext* set_cmd();

  class  Other_action_cmdContext : public antlr4::ParserRuleContext {
  public:
    Other_action_cmdContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *SAVECONCENTRATIONS();
    antlr4::tree::TerminalNode *RESETCONCENTRATIONS();
    antlr4::tree::TerminalNode *SAVEPARAMETERS();
    antlr4::tree::TerminalNode *RESETPARAMETERS();
    antlr4::tree::TerminalNode *QUIT();
    antlr4::tree::TerminalNode *PARAMETER_SCAN();
    antlr4::tree::TerminalNode *BIFURCATE();
    antlr4::tree::TerminalNode *LINEAR_PARAMETER_SENSITIVITY();
    antlr4::tree::TerminalNode *VISUALIZE();
    antlr4::tree::TerminalNode *GENERATEHYBRIDMODEL();
    antlr4::tree::TerminalNode *READFILE();
    antlr4::tree::TerminalNode *SETVOLUME();
    antlr4::tree::TerminalNode *INCLUDE_MODEL();
    antlr4::tree::TerminalNode *INCLUDE_NETWORK();
    Action_argsContext *action_args();
    Action_arg_valueContext *action_arg_value();
    antlr4::tree::TerminalNode *SEMI();
    std::vector<antlr4::tree::TerminalNode *> LB();
    antlr4::tree::TerminalNode* LB(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Other_action_cmdContext* other_action_cmd();

  class  Action_argsContext : public antlr4::ParserRuleContext {
  public:
    Action_argsContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LBRACKET();
    antlr4::tree::TerminalNode *RBRACKET();
    Action_arg_listContext *action_arg_list();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Action_argsContext* action_args();

  class  Action_arg_listContext : public antlr4::ParserRuleContext {
  public:
    Action_arg_listContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Action_argContext *> action_arg();
    Action_argContext* action_arg(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Action_arg_listContext* action_arg_list();

  class  Action_argContext : public antlr4::ParserRuleContext {
  public:
    Action_argContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Arg_nameContext *arg_name();
    antlr4::tree::TerminalNode *ASSIGNS();
    Action_arg_valueContext *action_arg_value();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Action_argContext* action_arg();

  class  Action_arg_valueContext : public antlr4::ParserRuleContext {
  public:
    Action_arg_valueContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    ExpressionContext *expression();
    Keyword_as_valueContext *keyword_as_value();
    std::vector<Quoted_stringContext *> quoted_string();
    Quoted_stringContext* quoted_string(size_t i);
    antlr4::tree::TerminalNode *LSBRACKET();
    Expression_listContext *expression_list();
    antlr4::tree::TerminalNode *RSBRACKET();
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);
    antlr4::tree::TerminalNode *LBRACKET();
    antlr4::tree::TerminalNode *RBRACKET();
    Nested_hash_listContext *nested_hash_list();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Action_arg_valueContext* action_arg_value();

  class  Quoted_stringContext : public antlr4::ParserRuleContext {
  public:
    Quoted_stringContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *QUOTED_STRING();
    antlr4::tree::TerminalNode *SINGLE_QUOTED_STRING();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Quoted_stringContext* quoted_string();

  class  Keyword_as_valueContext : public antlr4::ParserRuleContext {
  public:
    Keyword_as_valueContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *ODE();
    antlr4::tree::TerminalNode *SSA();
    antlr4::tree::TerminalNode *NF();
    antlr4::tree::TerminalNode *PLA();
    antlr4::tree::TerminalNode *SPARSE();
    antlr4::tree::TerminalNode *VERBOSE();
    antlr4::tree::TerminalNode *OVERWRITE();
    antlr4::tree::TerminalNode *CONTINUE();
    antlr4::tree::TerminalNode *SAFE();
    antlr4::tree::TerminalNode *EXECUTE();
    antlr4::tree::TerminalNode *BINARY_OUTPUT();
    antlr4::tree::TerminalNode *STEADY_STATE();
    antlr4::tree::TerminalNode *BDF();
    antlr4::tree::TerminalNode *STIFF();
    antlr4::tree::TerminalNode *METHOD();
    antlr4::tree::TerminalNode *TRUE();
    antlr4::tree::TerminalNode *FALSE();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Keyword_as_valueContext* keyword_as_value();

  class  Nested_hash_listContext : public antlr4::ParserRuleContext {
  public:
    Nested_hash_listContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Nested_hash_itemContext *> nested_hash_item();
    Nested_hash_itemContext* nested_hash_item(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Nested_hash_listContext* nested_hash_list();

  class  Nested_hash_itemContext : public antlr4::ParserRuleContext {
  public:
    Nested_hash_itemContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *ASSIGNS();
    Action_arg_valueContext *action_arg_value();
    antlr4::tree::TerminalNode *STRING();
    Quoted_stringContext *quoted_string();
    Arg_nameContext *arg_name();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Nested_hash_itemContext* nested_hash_item();

  class  Arg_nameContext : public antlr4::ParserRuleContext {
  public:
    Arg_nameContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *TIME();
    antlr4::tree::TerminalNode *OVERWRITE();
    antlr4::tree::TerminalNode *MAX_AGG();
    antlr4::tree::TerminalNode *MAX_ITER();
    antlr4::tree::TerminalNode *MAX_STOICH();
    antlr4::tree::TerminalNode *PRINT_ITER();
    antlr4::tree::TerminalNode *CHECK_ISO();
    antlr4::tree::TerminalNode *METHOD();
    antlr4::tree::TerminalNode *T_START();
    antlr4::tree::TerminalNode *T_END();
    antlr4::tree::TerminalNode *N_STEPS();
    antlr4::tree::TerminalNode *N_OUTPUT_STEPS();
    antlr4::tree::TerminalNode *ATOL();
    antlr4::tree::TerminalNode *RTOL();
    antlr4::tree::TerminalNode *STEADY_STATE();
    antlr4::tree::TerminalNode *SPARSE();
    antlr4::tree::TerminalNode *VERBOSE();
    antlr4::tree::TerminalNode *NETFILE();
    antlr4::tree::TerminalNode *CONTINUE();
    antlr4::tree::TerminalNode *PREFIX();
    antlr4::tree::TerminalNode *SUFFIX();
    antlr4::tree::TerminalNode *FORMAT();
    antlr4::tree::TerminalNode *FILE();
    antlr4::tree::TerminalNode *PRINT_CDAT();
    antlr4::tree::TerminalNode *PRINT_FUNCTIONS();
    antlr4::tree::TerminalNode *PRINT_NET();
    antlr4::tree::TerminalNode *PRINT_END();
    antlr4::tree::TerminalNode *STOP_IF();
    antlr4::tree::TerminalNode *PRINT_ON_STOP();
    antlr4::tree::TerminalNode *SAVE_PROGRESS();
    antlr4::tree::TerminalNode *MAX_SIM_STEPS();
    antlr4::tree::TerminalNode *OUTPUT_STEP_INTERVAL();
    antlr4::tree::TerminalNode *SAMPLE_TIMES();
    antlr4::tree::TerminalNode *PLA_CONFIG();
    antlr4::tree::TerminalNode *PLA_OUTPUT();
    antlr4::tree::TerminalNode *SEED();
    antlr4::tree::TerminalNode *POPLEVEL();
    antlr4::tree::TerminalNode *ARGFILE();
    antlr4::tree::TerminalNode *PARAM();
    antlr4::tree::TerminalNode *COMPLEX();
    antlr4::tree::TerminalNode *GET_FINAL_STATE();
    antlr4::tree::TerminalNode *GML();
    antlr4::tree::TerminalNode *NOCSLF();
    antlr4::tree::TerminalNode *NOTF();
    antlr4::tree::TerminalNode *BINARY_OUTPUT();
    antlr4::tree::TerminalNode *UTL();
    antlr4::tree::TerminalNode *EQUIL();
    antlr4::tree::TerminalNode *NFSIM_EXEC();
    antlr4::tree::TerminalNode *MOL_THRESHOLD();
    antlr4::tree::TerminalNode *ACTIONS();
    antlr4::tree::TerminalNode *PARAMETER();
    antlr4::tree::TerminalNode *PAR_MIN();
    antlr4::tree::TerminalNode *PAR_MAX();
    antlr4::tree::TerminalNode *N_SCAN_PTS();
    antlr4::tree::TerminalNode *LOG_SCALE();
    antlr4::tree::TerminalNode *RESET_CONC();
    antlr4::tree::TerminalNode *BDF();
    antlr4::tree::TerminalNode *MAX_STEP();
    antlr4::tree::TerminalNode *MAXORDER();
    antlr4::tree::TerminalNode *STATS();
    antlr4::tree::TerminalNode *MAX_NUM_STEPS();
    antlr4::tree::TerminalNode *MAX_ERR_TEST_FAILS();
    antlr4::tree::TerminalNode *MAX_CONV_FAILS();
    antlr4::tree::TerminalNode *STIFF();
    antlr4::tree::TerminalNode *ATOMIZE();
    antlr4::tree::TerminalNode *BLOCKS();
    antlr4::tree::TerminalNode *SKIPACTIONS();
    antlr4::tree::TerminalNode *INCLUDE_MODEL();
    antlr4::tree::TerminalNode *INCLUDE_NETWORK();
    antlr4::tree::TerminalNode *PRETTY_FORMATTING();
    antlr4::tree::TerminalNode *EVALUATE_EXPRESSIONS();
    antlr4::tree::TerminalNode *TYPE();
    antlr4::tree::TerminalNode *BACKGROUND();
    antlr4::tree::TerminalNode *COLLAPSE();
    antlr4::tree::TerminalNode *OPTS();
    antlr4::tree::TerminalNode *GROUPS();
    antlr4::tree::TerminalNode *SAFE();
    antlr4::tree::TerminalNode *EXECUTE();
    antlr4::tree::TerminalNode *TEXTREACTION();
    antlr4::tree::TerminalNode *TEXTSPECIES();
    antlr4::tree::TerminalNode *PRIORITY();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Arg_nameContext* arg_name();

  class  Expression_listContext : public antlr4::ParserRuleContext {
  public:
    Expression_listContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<ExpressionContext *> expression();
    ExpressionContext* expression(size_t i);
    std::vector<antlr4::tree::TerminalNode *> COMMA();
    antlr4::tree::TerminalNode* COMMA(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Expression_listContext* expression_list();

  class  ExpressionContext : public antlr4::ParserRuleContext {
  public:
    ExpressionContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Conditional_exprContext *conditional_expr();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  ExpressionContext* expression();

  class  Conditional_exprContext : public antlr4::ParserRuleContext {
  public:
    Conditional_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Or_exprContext *or_expr();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Conditional_exprContext* conditional_expr();

  class  Or_exprContext : public antlr4::ParserRuleContext {
  public:
    Or_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Xor_exprContext *> xor_expr();
    Xor_exprContext* xor_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LOGICAL_OR();
    antlr4::tree::TerminalNode* LOGICAL_OR(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Or_exprContext* or_expr();

  class  Xor_exprContext : public antlr4::ParserRuleContext {
  public:
    Xor_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<And_exprContext *> and_expr();
    And_exprContext* and_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LOGICAL_XOR();
    antlr4::tree::TerminalNode* LOGICAL_XOR(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Xor_exprContext* xor_expr();

  class  And_exprContext : public antlr4::ParserRuleContext {
  public:
    And_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Equality_exprContext *> equality_expr();
    Equality_exprContext* equality_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LOGICAL_AND();
    antlr4::tree::TerminalNode* LOGICAL_AND(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  And_exprContext* and_expr();

  class  Equality_exprContext : public antlr4::ParserRuleContext {
  public:
    Equality_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Relational_exprContext *> relational_expr();
    Relational_exprContext* relational_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> EQUALS();
    antlr4::tree::TerminalNode* EQUALS(size_t i);
    std::vector<antlr4::tree::TerminalNode *> NOT_EQUALS();
    antlr4::tree::TerminalNode* NOT_EQUALS(size_t i);
    std::vector<antlr4::tree::TerminalNode *> GTE();
    antlr4::tree::TerminalNode* GTE(size_t i);
    std::vector<antlr4::tree::TerminalNode *> GT();
    antlr4::tree::TerminalNode* GT(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LTE();
    antlr4::tree::TerminalNode* LTE(size_t i);
    std::vector<antlr4::tree::TerminalNode *> LT();
    antlr4::tree::TerminalNode* LT(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Equality_exprContext* equality_expr();

  class  Relational_exprContext : public antlr4::ParserRuleContext {
  public:
    Relational_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Additive_exprContext *additive_expr();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Relational_exprContext* relational_expr();

  class  Additive_exprContext : public antlr4::ParserRuleContext {
  public:
    Additive_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Multiplicative_exprContext *> multiplicative_expr();
    Multiplicative_exprContext* multiplicative_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> PLUS();
    antlr4::tree::TerminalNode* PLUS(size_t i);
    std::vector<antlr4::tree::TerminalNode *> MINUS();
    antlr4::tree::TerminalNode* MINUS(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Additive_exprContext* additive_expr();

  class  Multiplicative_exprContext : public antlr4::ParserRuleContext {
  public:
    Multiplicative_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Power_exprContext *> power_expr();
    Power_exprContext* power_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> TIMES();
    antlr4::tree::TerminalNode* TIMES(size_t i);
    std::vector<antlr4::tree::TerminalNode *> DIV();
    antlr4::tree::TerminalNode* DIV(size_t i);
    std::vector<antlr4::tree::TerminalNode *> MOD();
    antlr4::tree::TerminalNode* MOD(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Multiplicative_exprContext* multiplicative_expr();

  class  Power_exprContext : public antlr4::ParserRuleContext {
  public:
    Power_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    std::vector<Unary_exprContext *> unary_expr();
    Unary_exprContext* unary_expr(size_t i);
    std::vector<antlr4::tree::TerminalNode *> POWER();
    antlr4::tree::TerminalNode* POWER(size_t i);

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Power_exprContext* power_expr();

  class  Unary_exprContext : public antlr4::ParserRuleContext {
  public:
    Unary_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Primary_exprContext *primary_expr();
    antlr4::tree::TerminalNode *PLUS();
    antlr4::tree::TerminalNode *MINUS();
    antlr4::tree::TerminalNode *EMARK();
    antlr4::tree::TerminalNode *TILDE();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Unary_exprContext* unary_expr();

  class  Primary_exprContext : public antlr4::ParserRuleContext {
  public:
    Primary_exprContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    ExpressionContext *expression();
    antlr4::tree::TerminalNode *RPAREN();
    Function_callContext *function_call();
    Observable_refContext *observable_ref();
    LiteralContext *literal();
    Arg_nameContext *arg_name();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Primary_exprContext* primary_expr();

  class  Function_callContext : public antlr4::ParserRuleContext {
  public:
    Function_callContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    antlr4::tree::TerminalNode *EXP();
    antlr4::tree::TerminalNode *LN();
    antlr4::tree::TerminalNode *LOG10();
    antlr4::tree::TerminalNode *LOG2();
    antlr4::tree::TerminalNode *SQRT();
    antlr4::tree::TerminalNode *ABS();
    antlr4::tree::TerminalNode *SIN();
    antlr4::tree::TerminalNode *COS();
    antlr4::tree::TerminalNode *TAN();
    antlr4::tree::TerminalNode *ASIN();
    antlr4::tree::TerminalNode *ACOS();
    antlr4::tree::TerminalNode *ATAN();
    antlr4::tree::TerminalNode *SINH();
    antlr4::tree::TerminalNode *COSH();
    antlr4::tree::TerminalNode *TANH();
    antlr4::tree::TerminalNode *ASINH();
    antlr4::tree::TerminalNode *ACOSH();
    antlr4::tree::TerminalNode *ATANH();
    antlr4::tree::TerminalNode *RINT();
    antlr4::tree::TerminalNode *MIN();
    antlr4::tree::TerminalNode *MAX();
    antlr4::tree::TerminalNode *SUM();
    antlr4::tree::TerminalNode *AVG();
    antlr4::tree::TerminalNode *IF();
    antlr4::tree::TerminalNode *SAT();
    antlr4::tree::TerminalNode *MM();
    antlr4::tree::TerminalNode *HILL();
    antlr4::tree::TerminalNode *ARRHENIUS();
    antlr4::tree::TerminalNode *TIME();
    antlr4::tree::TerminalNode *T_START();
    antlr4::tree::TerminalNode *T_END();
    antlr4::tree::TerminalNode *MRATIO();
    antlr4::tree::TerminalNode *TFUN();
    antlr4::tree::TerminalNode *FUNCTIONPRODUCT();
    Expression_listContext *expression_list();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Function_callContext* function_call();

  class  Observable_refContext : public antlr4::ParserRuleContext {
  public:
    Observable_refContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    Observable_nameContext *observable_name();
    antlr4::tree::TerminalNode *LPAREN();
    antlr4::tree::TerminalNode *RPAREN();
    Expression_listContext *expression_list();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Observable_refContext* observable_ref();

  class  LiteralContext : public antlr4::ParserRuleContext {
  public:
    LiteralContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *INT();
    antlr4::tree::TerminalNode *FLOAT();
    antlr4::tree::TerminalNode *PI();
    antlr4::tree::TerminalNode *EULERIAN();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  LiteralContext* literal();

  class  Observable_nameContext : public antlr4::ParserRuleContext {
  public:
    Observable_nameContext(antlr4::ParserRuleContext *parent, size_t invokingState);
    virtual size_t getRuleIndex() const override;
    antlr4::tree::TerminalNode *STRING();
    antlr4::tree::TerminalNode *PRIORITY();

    virtual void enterRule(antlr4::tree::ParseTreeListener *listener) override;
    virtual void exitRule(antlr4::tree::ParseTreeListener *listener) override;

    virtual std::any accept(antlr4::tree::ParseTreeVisitor *visitor) override;
   
  };

  Observable_nameContext* observable_name();


  // By default the static state used to implement the parser is lazily initialized during the first
  // call to the constructor. You can call this function if you wish to initialize the static state
  // ahead of time.
  static void initialize();

private:
};

