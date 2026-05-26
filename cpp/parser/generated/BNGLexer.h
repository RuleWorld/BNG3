
// Generated from BNGLexer.g4 by ANTLR 4.13.2

#pragma once


#include "antlr4-runtime.h"




class  BNGLexer : public antlr4::Lexer {
public:
  enum {
    LINE_COMMENT = 1, LB = 2, WS = 3, BEGIN = 4, END = 5, MODEL = 6, PARAMETERS = 7, 
    COMPARTMENTS = 8, MOLECULE = 9, MOLECULES = 10, COUNTER = 11, TYPES = 12, 
    SEED = 13, SPECIES = 14, OBSERVABLES = 15, FUNCTIONS = 16, REACTION = 17, 
    REACTIONS = 18, RULES = 19, REACTION_RULES = 20, MOLECULE_TYPES = 21, 
    GROUPS = 22, ACTIONS = 23, POPULATION = 24, MAPS = 25, ENERGY = 26, 
    PATTERNS = 27, MOLECULAR = 28, MATCHONCE = 29, DELETEMOLECULES = 30, 
    MOVECONNECTED = 31, INCLUDE_REACTANTS = 32, INCLUDE_PRODUCTS = 33, EXCLUDE_REACTANTS = 34, 
    EXCLUDE_PRODUCTS = 35, TOTALRATE = 36, VERSION = 37, SET_OPTION = 38, 
    SET_MODEL_NAME = 39, SUBSTANCEUNITS = 40, PREFIX = 41, SUFFIX = 42, 
    GENERATENETWORK = 43, OVERWRITE = 44, MAX_AGG = 45, MAX_ITER = 46, MAX_STOICH = 47, 
    PRINT_ITER = 48, CHECK_ISO = 49, GENERATEHYBRIDMODEL = 50, SAFE = 51, 
    EXECUTE = 52, SIMULATE = 53, METHOD = 54, ODE = 55, SSA = 56, PLA = 57, 
    NF = 58, VERBOSE = 59, NETFILE = 60, ARGFILE = 61, CONTINUE = 62, T_START = 63, 
    T_END = 64, N_STEPS = 65, N_OUTPUT_STEPS = 66, MAX_SIM_STEPS = 67, OUTPUT_STEP_INTERVAL = 68, 
    SAMPLE_TIMES = 69, SAVE_PROGRESS = 70, PRINT_CDAT = 71, PRINT_FUNCTIONS = 72, 
    PRINT_NET = 73, PRINT_END = 74, STOP_IF = 75, PRINT_ON_STOP = 76, SIMULATE_ODE = 77, 
    ATOL = 78, RTOL = 79, STEADY_STATE = 80, SPARSE = 81, SIMULATE_SSA = 82, 
    SIMULATE_PLA = 83, PLA_CONFIG = 84, PLA_OUTPUT = 85, SIMULATE_NF = 86, 
    SIMULATE_RM = 87, PARAM = 88, COMPLEX = 89, GET_FINAL_STATE = 90, GML = 91, 
    NOCSLF = 92, NOTF = 93, BINARY_OUTPUT = 94, UTL = 95, EQUIL = 96, PARAMETER_SCAN = 97, 
    BIFURCATE = 98, LINEAR_PARAMETER_SENSITIVITY = 99, PARAMETER = 100, 
    PAR_MIN = 101, PAR_MAX = 102, N_SCAN_PTS = 103, LOG_SCALE = 104, RESET_CONC = 105, 
    READFILE = 106, FILE = 107, ATOMIZE = 108, BLOCKS = 109, SKIPACTIONS = 110, 
    VISUALIZE = 111, TYPE = 112, BACKGROUND = 113, COLLAPSE = 114, OPTS = 115, 
    WRITESSC = 116, WRITESSCCFG = 117, FORMAT = 118, WRITEFILE = 119, WRITEMODEL = 120, 
    WRITEXML = 121, WRITENETWORK = 122, WRITESBML = 123, WRITESBMLMULTI = 124, 
    WRITEMDL = 125, WRITELATEX = 126, INCLUDE_MODEL = 127, INCLUDE_NETWORK = 128, 
    PRETTY_FORMATTING = 129, EVALUATE_EXPRESSIONS = 130, TEXTREACTION = 131, 
    TEXTSPECIES = 132, WRITEMFILE = 133, WRITEMEXFILE = 134, WRITECPPFILE = 135, 
    WRITECPYFILE = 136, BDF = 137, MAX_STEP = 138, MAXORDER = 139, STATS = 140, 
    MAX_NUM_STEPS = 141, MAX_ERR_TEST_FAILS = 142, MAX_CONV_FAILS = 143, 
    STIFF = 144, SETCONCENTRATION = 145, ADDCONCENTRATION = 146, SAVECONCENTRATIONS = 147, 
    RESETCONCENTRATIONS = 148, SETPARAMETER = 149, SAVEPARAMETERS = 150, 
    RESETPARAMETERS = 151, SETVOLUME = 152, SIMULATE_PSA = 153, SIMULATE_PROTOCOL = 154, 
    PROTOCOL = 155, POPLEVEL = 156, MOL_THRESHOLD = 157, NFSIM_EXEC = 158, 
    QUIT = 159, TRUE = 160, FALSE = 161, SAT = 162, MM = 163, HILL = 164, 
    ARRHENIUS = 165, MRATIO = 166, TFUN = 167, FUNCTIONPRODUCT = 168, PRIORITY = 169, 
    IF = 170, EXP = 171, LN = 172, LOG10 = 173, LOG2 = 174, SQRT = 175, 
    RINT = 176, ABS = 177, SIN = 178, COS = 179, TAN = 180, ASIN = 181, 
    ACOS = 182, ATAN = 183, SINH = 184, COSH = 185, TANH = 186, ASINH = 187, 
    ACOSH = 188, ATANH = 189, PI = 190, EULERIAN = 191, MIN = 192, MAX = 193, 
    SUM = 194, AVG = 195, TIME = 196, FLOAT = 197, INT = 198, STRING = 199, 
    QUOTED_STRING = 200, SINGLE_QUOTED_STRING = 201, SEMI = 202, COLON = 203, 
    LSBRACKET = 204, RSBRACKET = 205, LBRACKET = 206, RBRACKET = 207, COMMA = 208, 
    DOT = 209, LPAREN = 210, RPAREN = 211, UNI_REACTION_SIGN = 212, BI_REACTION_SIGN = 213, 
    DOLLAR = 214, TILDE = 215, AT = 216, GTE = 217, GT = 218, LTE = 219, 
    LT = 220, ASSIGNS = 221, EQUALS = 222, NOT_EQUALS = 223, BECOMES = 224, 
    LOGICAL_AND = 225, LOGICAL_OR = 226, LOGICAL_XOR = 227, DIV = 228, TIMES = 229, 
    MINUS = 230, PLUS = 231, POWER = 232, MOLECULE_TAG_TOKEN = 233, MOD = 234, 
    PIPE = 235, QMARK = 236, EMARK = 237, AMPERSAND = 238, VERSION_NUMBER = 239, 
    ULB = 240
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

