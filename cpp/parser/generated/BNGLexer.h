
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
    SIMULATE_PLA = 87, SIMULATE_PS = 88, PLA_CONFIG = 89, PLA_OUTPUT = 90,
    SIMULATE_NF = 91, SIMULATE_RM = 92, PARAM = 93, COMPLEX = 94, GET_FINAL_STATE = 95,
    GML = 96, NOCSLF = 97, NOTF = 98, BINARY_OUTPUT = 99, UTL = 100, EQUIL = 101,
    PARAMETER_SCAN = 102, BIFURCATE = 103, LINEAR_PARAMETER_SENSITIVITY = 104,
    PARAMETER = 105, PAR_MIN = 106, PAR_MAX = 107, N_SCAN_PTS = 108, LOG_SCALE = 109,
    RESET_CONC = 110, READFILE = 111, FILE = 112, ATOMIZE = 113, BLOCKS = 114,
    SKIPACTIONS = 115, VISUALIZE = 116, TYPE = 117, BACKGROUND = 118, COLLAPSE = 119,
    OPTS = 120, WRITESSC = 121, WRITESSCCFG = 122, FORMAT = 123, WRITEFILE = 124,
    WRITEMODEL = 125, WRITEXML = 126, WRITENETWORK = 127, WRITESBML = 128,
    WRITESBMLMULTI = 129, WRITEMDL = 130, WRITELATEX = 131, INCLUDE_MODEL = 132,
    INCLUDE_NETWORK = 133, PRETTY_FORMATTING = 134, EVALUATE_EXPRESSIONS = 135,
    TEXTREACTION = 136, TEXTSPECIES = 137, WRITEMFILE = 138, WRITEMEXFILE = 139,
    WRITECPPFILE = 140, WRITECPYFILE = 141, BDF = 142, MAX_STEP = 143, MAXORDER = 144,
    STATS = 145, MAX_NUM_STEPS = 146, MAX_ERR_TEST_FAILS = 147, MAX_CONV_FAILS = 148,
    STIFF = 149, SETCONCENTRATION = 150, ADDCONCENTRATION = 151, SAVECONCENTRATIONS = 152,
    RESETCONCENTRATIONS = 153, SETPARAMETER = 154, SAVEPARAMETERS = 155,
    RESETPARAMETERS = 156, SETVOLUME = 157, SIMULATE_PSA = 158, SIMULATE_PROTOCOL = 159,
    PROTOCOL = 160, POPLEVEL = 161, MOL_THRESHOLD = 162, NFSIM_EXEC = 163,
    QUIT = 164, TRUE = 165, FALSE = 166, SAT = 167, MM = 168, HILL = 169,
    ARRHENIUS = 170, MRATIO = 171, TFUN = 172, FUNCTIONPRODUCT = 173, PRIORITY = 174,
    IF = 175, EXP = 176, LN = 177, LOG10 = 178, LOG2 = 179, SQRT = 180,
    RINT = 181, ABS = 182, SIN = 183, COS = 184, TAN = 185, ASIN = 186,
    ACOS = 187, ATAN = 188, SINH = 189, COSH = 190, TANH = 191, ASINH = 192,
    ACOSH = 193, ATANH = 194, PI = 195, EULERIAN = 196, MIN = 197, MAX = 198,
    SUM = 199, AVG = 200, TIME = 201, FLOAT = 202, INT = 203, STRING = 204,
    QUOTED_STRING = 205, SINGLE_QUOTED_STRING = 206, SEMI = 207, COLON = 208,
    LSBRACKET = 209, RSBRACKET = 210, LBRACKET = 211, RBRACKET = 212, COMMA = 213,
    DOT = 214, LPAREN = 215, RPAREN = 216, UNI_REACTION_SIGN = 217, BI_REACTION_SIGN = 218,
    DOLLAR = 219, TILDE = 220, AT = 221, GTE = 222, GT = 223, LTE = 224,
    LT = 225, ASSIGNS = 226, EQUALS = 227, NOT_EQUALS = 228, BECOMES = 229,
    LOGICAL_AND = 230, LOGICAL_OR = 231, LOGICAL_XOR = 232, DIV = 233, TIMES = 234,
    MINUS = 235, PLUS = 236, POWER = 237, MOLECULE_TAG_TOKEN = 238, MOD = 239,
    PIPE = 240, QMARK = 241, EMARK = 242, AMPERSAND = 243, VERSION_NUMBER = 244,
    ULB = 245
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

