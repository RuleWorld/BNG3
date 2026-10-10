
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

