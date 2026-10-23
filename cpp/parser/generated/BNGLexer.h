
#include <cctype>


// Generated from BNGLexer.g4 by ANTLR 4.13.2

#pragma once

#include "../antlr_compat.hpp"


#include "antlr4-runtime.h"




class  BNGLexer : public antlr4::Lexer {
public:
  enum {
    LINE_COMMENT = 1, LB = 2, WS = 3, SEPARATOR_LINE = 4, MINUS_SEPARATOR_LINE = 5,
    BEGIN = 6, END = 7, MODEL = 8, PARAMETERS = 9, COMPARTMENTS = 10, MOLECULE = 11,
    MOLECULES = 12, COUNTER = 13, TYPES = 14, SEED = 15, SPECIES = 16, OBSERVABLES = 17,
    FUNCTIONS = 18, REACTION = 19, REACTIONS = 20, RULES = 21, REACTION_RULES = 22,
    MOLECULE_TYPES = 23, GROUPS = 24, ACTIONS = 25, POPULATION = 26, MAPS = 27,
    ENERGY = 28, PATTERNS = 29, MOLECULAR = 30, MATCHONCE = 31, DELETEMOLECULES = 32,
    MOVECONNECTED = 33, DELAY = 34, NONCONSUMING = 35, INCLUDE_REACTANTS = 36,
    INCLUDE_PRODUCTS = 37, EXCLUDE_REACTANTS = 38, EXCLUDE_PRODUCTS = 39,
    TOTALRATE = 40, VERSION = 41, SET_OPTION = 42, SET_MODEL_NAME = 43,
    SUBSTANCEUNITS = 44, PREFIX = 45, SUFFIX = 46, GENERATENETWORK = 47,
    OVERWRITE = 48, MAX_AGG = 49, MAX_ITER = 50, MAX_STOICH = 51, PRINT_ITER = 52,
    CHECK_ISO = 53, GENERATEHYBRIDMODEL = 54, SAFE = 55, EXECUTE = 56, SIMULATE = 57,
    METHOD = 58, ODE = 59, SSA = 60, PLA = 61, NF = 62, VERBOSE = 63, NETFILE = 64,
    ARGFILE = 65, CONTINUE = 66, T_START = 67, T_END = 68, N_STEPS = 69,
    N_OUTPUT_STEPS = 70, MAX_SIM_STEPS = 71, OUTPUT_STEP_INTERVAL = 72,
    SAMPLE_TIMES = 73, SAVE_PROGRESS = 74, PRINT_CDAT = 75, PRINT_FUNCTIONS = 76,
    PRINT_NET = 77, PRINT_END = 78, STOP_IF = 79, PRINT_ON_STOP = 80, SIMULATE_ODE = 81,
    ATOL = 82, RTOL = 83, STEADY_STATE = 84, SPARSE = 85, SIMULATE_SSA = 86,
    SIMULATE_PLA = 87, PLA_CONFIG = 88, PLA_OUTPUT = 89, SIMULATE_NF = 90,
    SIMULATE_RM = 91, PARAM = 92, COMPLEX = 93, GET_FINAL_STATE = 94, GML = 95,
    NOCSLF = 96, NOTF = 97, BINARY_OUTPUT = 98, UTL = 99, EQUIL = 100, PARAMETER_SCAN = 101,
    BIFURCATE = 102, LINEAR_PARAMETER_SENSITIVITY = 103, PARAMETER = 104,
    PAR_MIN = 105, PAR_MAX = 106, N_SCAN_PTS = 107, LOG_SCALE = 108, RESET_CONC = 109,
    READFILE = 110, FILE = 111, ATOMIZE = 112, BLOCKS = 113, SKIPACTIONS = 114,
    VISUALIZE = 115, TYPE = 116, BACKGROUND = 117, COLLAPSE = 118, OPTS = 119,
    WRITESSC = 120, WRITESSCCFG = 121, FORMAT = 122, WRITEFILE = 123, WRITEMODEL = 124,
    WRITEXML = 125, WRITENETWORK = 126, WRITESBML = 127, WRITESBMLMULTI = 128,
    WRITEMDL = 129, WRITELATEX = 130, INCLUDE_MODEL = 131, INCLUDE_NETWORK = 132,
    PRETTY_FORMATTING = 133, EVALUATE_EXPRESSIONS = 134, TEXTREACTION = 135,
    TEXTSPECIES = 136, WRITEMFILE = 137, WRITEMEXFILE = 138, WRITECPPFILE = 139,
    WRITECPYFILE = 140, BDF = 141, MAX_STEP = 142, MAXORDER = 143, STATS = 144,
    MAX_NUM_STEPS = 145, MAX_ERR_TEST_FAILS = 146, MAX_CONV_FAILS = 147,
    STIFF = 148, SETCONCENTRATION = 149, ADDCONCENTRATION = 150, SAVECONCENTRATIONS = 151,
    RESETCONCENTRATIONS = 152, SETPARAMETER = 153, SAVEPARAMETERS = 154,
    RESETPARAMETERS = 155, SETVOLUME = 156, SIMULATE_PSA = 157, SIMULATE_PROTOCOL = 158,
    PROTOCOL = 159, POPLEVEL = 160, MOL_THRESHOLD = 161, NFSIM_EXEC = 162,
    QUIT = 163, TRUE = 164, FALSE = 165, SAT = 166, MM = 167, HILL = 168,
    ARRHENIUS = 169, MRATIO = 170, TFUN = 171, FUNCTIONPRODUCT = 172, PRIORITY = 173,
    IF = 174, EXP = 175, LN = 176, LOG10 = 177, LOG2 = 178, SQRT = 179,
    RINT = 180, ABS = 181, SIN = 182, COS = 183, TAN = 184, ASIN = 185,
    ACOS = 186, ATAN = 187, SINH = 188, COSH = 189, TANH = 190, ASINH = 191,
    ACOSH = 192, ATANH = 193, PI = 194, EULERIAN = 195, MIN = 196, MAX = 197,
    SUM = 198, AVG = 199, TIME = 200, FLOAT = 201, INT = 202, STRING = 203,
    QUOTED_STRING = 204, SINGLE_QUOTED_STRING = 205, SEMI = 206, COLON = 207,
    LSBRACKET = 208, RSBRACKET = 209, LBRACKET = 210, RBRACKET = 211, COMMA = 212,
    DOT = 213, LPAREN = 214, RPAREN = 215, UNI_REACTION_SIGN = 216, BI_REACTION_SIGN = 217,
    DOLLAR = 218, TILDE = 219, AT = 220, GTE = 221, GT = 222, LTE = 223,
    LT = 224, ASSIGNS = 225, EQUALS = 226, NOT_EQUALS = 227, BECOMES = 228,
    LOGICAL_AND = 229, LOGICAL_OR = 230, LOGICAL_XOR = 231, DIV = 232, TIMES = 233,
    MINUS = 234, PLUS = 235, POWER = 236, MOLECULE_TAG_TOKEN = 237, MOD = 238,
    PIPE = 239, QMARK = 240, EMARK = 241, AMPERSAND = 242, VERSION_NUMBER = 243,
    ULB = 244
  };

  explicit BNGLexer(antlr4::CharStream *input);

  ~BNGLexer() override;


  std::string getGrammarFileName() const override;

  const std::vector<std::string>& getRuleNames() const override;

  const std::vector<std::string>& getChannelNames() const override;

  const std::vector<std::string>& getModeNames() const override;

  const antlr4::dfa::Vocabulary& getVocabulary() const override;

  antlr4::atn::SerializedATNView getSerializedATN() const override;

  const antlr4::atn::ATN& getATN() const override;

  bool sempred(antlr4::RuleContext *_localctx, size_t ruleIndex, size_t predicateIndex) override;

  // By default the static state used to implement the lexer is lazily initialized during the first
  // call to the constructor. You can call this function if you wish to initialize the static state
  // ahead of time.
  static void initialize();

private:

  // Individual action functions triggered by action() above.

  // Individual semantic predicate functions triggered by sempred() above.
  bool FLOATSempred(antlr4::RuleContext *_localctx, size_t predicateIndex);

};

