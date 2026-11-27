import os, re, subprocess
from bionetgen.core.exc import BNGParseError, BNGPerlError
import shutil as spawn

from bionetgen.core.utils.logging import BNGLogger


class _StdlibActionParser:
    """Pure-Python fallback for ActionList.action_parser when pyparsing is absent.

    Produces the same flat token list consumed by BNGParser._parse_action_strings
    for normal ``{key=>val,...}``, square-bracket ``[...]``, two-argument, and
    zero/one-argument BNGL action calls.
    """

    _ACTION_RE = re.compile(
        r"^([A-Za-z][A-Za-z0-9_]*)\s*\((.*)\)\s*(;?)\s*$", re.DOTALL
    )
    _IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*")
    _INT_RE = re.compile(r"^[0-9]+")
    _EXPR_RE = re.compile(r"^[0-9.+\-eE()/*^]+")

    @staticmethod
    def _skip_ws(text: str, pos: int) -> int:
        n = len(text)
        while pos < n and text[pos].isspace():
            pos += 1
        return pos

    @staticmethod
    def _read_quoted(text: str, pos: int):
        if pos >= len(text) or text[pos] not in ('"', "'"):
            return None
        quote = text[pos]
        i = pos + 1
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                return text[pos : i + 1], i + 1
            i += 1
        return None

    def _parse_nested_dict(self, text: str, pos: int):
        tokens = ["{"]
        pos = self._skip_ws(text, pos + 1)
        if pos < len(text) and text[pos] == "}":
            tokens.append("}")
            return tokens, pos + 1
        while pos < len(text):
            q = self._read_quoted(text, pos)
            if q is None:
                raise ValueError(f"expected quoted key at {pos}")
            key_tok, pos = q
            pos = self._skip_ws(text, pos)
            if text[pos : pos + 2] != "=>":
                raise ValueError(f"expected '=>' at {pos}")
            pos = self._skip_ws(text, pos + 2)
            m = self._INT_RE.match(text[pos:])
            if not m:
                raise ValueError(f"expected integer value at {pos}")
            val_tok = m.group(0)
            pos = self._skip_ws(text, pos + len(val_tok))
            tokens.extend([key_tok, "=>", val_tok])
            if pos < len(text) and text[pos] == ",":
                pos = self._skip_ws(text, pos + 1)
                continue
            if pos < len(text) and text[pos] == "}":
                tokens.append("}")
                return tokens, pos + 1
            raise ValueError(f"expected ',' or '}}' at {pos}")
        raise ValueError("unterminated '{'")

    def _parse_nested_list(self, text: str, pos: int, quoted_only: bool = False):
        tokens = ["["]
        pos = self._skip_ws(text, pos + 1)
        if pos < len(text) and text[pos] == "]":
            tokens.append("]")
            return tokens, pos + 1
        while pos < len(text):
            q = self._read_quoted(text, pos)
            if q is not None:
                elem, pos = q
            elif not quoted_only:
                m = self._EXPR_RE.match(text[pos:])
                if not m:
                    raise ValueError(f"expected list element at {pos}")
                elem = m.group(0)
                pos += len(elem)
            else:
                raise ValueError(f"expected quoted element at {pos}")
            tokens.append(elem)
            pos = self._skip_ws(text, pos)
            if pos < len(text) and text[pos] == ",":
                pos = self._skip_ws(text, pos + 1)
                continue
            if pos < len(text) and text[pos] == "]":
                tokens.append("]")
                return tokens, pos + 1
            raise ValueError(f"expected ',' or ']' at {pos}")
        raise ValueError("unterminated '['")

    def _parse_dict_args(self, body: str):
        tokens = ["{"]
        pos = self._skip_ws(body, 1)
        n = len(body)
        if pos < n and body[pos] == "}":
            pos = self._skip_ws(body, pos + 1)
            if pos != n:
                raise ValueError("trailing characters after '}'")
            tokens.append("}")
            return tokens
        while pos < n:
            m = self._IDENT_RE.match(body[pos:])
            if not m:
                raise ValueError(f"expected argument name at {pos}")
            key = m.group(0)
            pos = self._skip_ws(body, pos + len(key))
            if body[pos : pos + 2] != "=>":
                raise ValueError(f"expected '=>' at {pos}")
            pos = self._skip_ws(body, pos + 2)
            tokens.extend([key, "=>"])
            if pos >= n:
                raise ValueError("missing argument value")
            ch = body[pos]
            if ch in ('"', "'"):
                q = self._read_quoted(body, pos)
                if q is None:
                    raise ValueError(f"unterminated string at {pos}")
                val, pos = q
                tokens.append(val)
            elif ch == "{":
                sub, pos = self._parse_nested_dict(body, pos)
                tokens.extend(sub)
            elif ch == "[":
                sub, pos = self._parse_nested_list(body, pos, quoted_only=False)
                tokens.extend(sub)
            else:
                em = self._EXPR_RE.match(body[pos:])
                if not em:
                    raise ValueError(f"unexpected argument value at {pos}")
                tokens.append(em.group(0))
                pos += len(em.group(0))
            pos = self._skip_ws(body, pos)
            if pos < n and body[pos] == ",":
                pos = self._skip_ws(body, pos + 1)
                continue
            if pos < n and body[pos] == "}":
                pos = self._skip_ws(body, pos + 1)
                if pos != n:
                    raise ValueError("trailing characters after '}'")
                tokens.append("}")
                return tokens
            raise ValueError(f"expected ',' or '}}' at {pos}")
        raise ValueError("unterminated '{'")

    def parseString(self, action: str):
        match = self._ACTION_RE.match(action.strip())
        if not match:
            raise ValueError(f"Malformed action: {action}")
        name, body, semi = match.group(1), match.group(2).strip(), match.group(3)
        tokens = [name, "("]
        if body:
            if body.startswith("{"):
                tokens.extend(self._parse_dict_args(body))
            elif body.startswith("["):
                sub, end = self._parse_nested_list(body, 0, quoted_only=True)
                if self._skip_ws(body, end) != len(body):
                    raise ValueError(f"trailing characters in list action: {action}")
                tokens.extend(sub)
            else:
                q = self._read_quoted(body, 0)
                if q is None:
                    raise ValueError(f"expected quoted argument in action: {action}")
                first_arg, pos = q
                pos = self._skip_ws(body, pos)
                if pos == len(body):
                    tokens.append(first_arg)
                elif body[pos] == ",":
                    second_arg = body[pos + 1 :].strip()
                    tokens.extend([first_arg, ",", second_arg])
                else:
                    raise ValueError(f"unexpected characters in action: {action}")
        tokens.append(")")
        if semi:
            tokens.append(";")
        return tokens


class ActionList:
    """
    Class to store everything related to BioNetGen actions.
    This class stores information about the list of BNG actions, their
    arguments as well as their syntax information. The class also provides
    an argument parser using pyparsing.

    Usage: ActionList()

    Attributes
    ----------
    normal_types : list

    no_setter_syntax : list
        actions without => syntax
    square_braces : list
        actions that use [] syntax in them
    before_model : list
        actions that are supposed to come before the model
    possible_types : list
        the list of all possible actions
    arg_dict : dict
        dictionary that contains every argument of every action
    irregular_args : dict
        actions that have arguments that aren't simply arg=>val

    Methods
    ---------
    is_before_model : bool
        checks if a given action is supposed to come before `begin model`
    define_parser : None
        sets ActionList.action_parser to a pyparsing parser that's capable of
        splitting up any BNG action into parts
    """

    def __init__(self):
        # these are all the action types, categorized
        # by their argument syntax
        self.normal_types = [
            "generate_network",
            "generate_hybrid_model",
            "simulate",
            "simulate_ode",
            "simulate_ssa",
            "simulate_pla",
            "simulate_nf",
            "simulate_psa",
            "parameter_scan",
            "bifurcate",
            "readFile",
            "writeFile",
            "writeModel",
            "writeNetwork",
            "writeXML",
            "writeSBML",
            "writeMfile",
            "writeCPYfile",
            "writeMexfile",
            "writeMDL",
            "visualize",
        ]
        self.no_setter_syntax = [
            "setConcentration",
            "addConcentration",
            "setParameter",
            "quit",
            "setModelName",
            "substanceUnits",
            "version",
            "setOption",
        ]
        self.square_braces = [
            "saveConcentrations",
            "resetConcentrations",
            "resetParameters",
            "saveParameters",
        ]
        # remember what's written before models
        self.before_model = [
            "setModelName",
            "substanceUnits",
            "version",
            "setOption",
        ]
        self.possible_types = (
            self.normal_types + self.no_setter_syntax + self.square_braces
        )
        # Use dictionary to keep track of all possible args (and types?) for each action
        self.arg_dict = {}
        # arg_dict["action"] = ["arg1", "arg2", "etc."]
        # normal_types
        self.arg_dict["generate_network"] = [
            "prefix",
            "suffix",
            "verbose",
            "overwrite",
            "print_iter",
            "max_agg",
            "max_iter",
            "max_stoich",
            "check_iso",
            "TextReaction",
            "TextSpecies",
        ]
        self.arg_dict["generate_hybrid_model"] = [
            "prefix",
            "suffix",
            "verbose",
            "overwrite",
            "actions",
            "execute",
            "safe",
        ]
        self.arg_dict["simulate"] = [
            "prefix",
            "suffix",
            "verbose",
            "method",
            "argfile",
            "continue",
            "t_start",
            "t_end",
            "n_steps",
            "n_output_steps",
            "sample_times",
            "output_step_interval",
            "max_sim_steps",
            "stop_if",
            "print_on_stop",
            "print_end",
            "print_net",
            "save_progress",
            "print_CDAT",
            "print_functions",
            "netfile",
            "seed",
        ]
        self.arg_dict["simulate_ode"] = [
            "prefix",
            "suffix",
            "verbose",
            "argfile",
            "continue",
            "t_start",
            "t_end",
            "n_steps",
            "n_output_steps",
            "sample_times",
            "output_step_interval",
            "max_sim_steps",
            "stop_if",
            "print_on_stop",
            "print_end",
            "print_net",
            "save_progress",
            "print_CDAT",
            "print_functions",
            "netfile",
            "seed",
            "atol",
            "rtol",
            "sparse",
            "steady_state",
        ]
        self.arg_dict["simulate_ssa"] = [
            "prefix",
            "suffix",
            "verbose",
            "argfile",
            "continue",
            "t_start",
            "t_end",
            "n_steps",
            "n_output_steps",
            "sample_times",
            "output_step_interval",
            "max_sim_steps",
            "stop_if",
            "print_on_stop",
            "print_end",
            "print_net",
            "save_progress",
            "print_CDAT",
            "print_functions",
            "netfile",
            "seed",
        ]
        self.arg_dict["simulate_pla"] = [
            "prefix",
            "suffix",
            "verbose",
            "argfile",
            "continue",
            "t_start",
            "t_end",
            "n_steps",
            "n_output_steps",
            "sample_times",
            "output_step_interval",
            "max_sim_steps",
            "stop_if",
            "print_on_stop",
            "print_end",
            "print_net",
            "save_progress",
            "print_CDAT",
            "print_functions",
            "netfile",
            "seed",
            "pla_config",
            "pla_output",
        ]
        self.arg_dict["simulate_nf"] = [
            "prefix",
            "suffix",
            "verbose",
            "argfile",
            "continue",
            "t_start",
            "t_end",
            "n_steps",
            "n_output_steps",
            "sample_times",
            "output_step_interval",
            "max_sim_steps",
            "stop_if",
            "print_on_stop",
            "print_end",
            "print_net",
            "save_progress",
            "print_CDAT",
            "print_functions",
            "netfile",
            "seed",
            "complex",
            "nocslf",
            "notf",
            "binary_output",
            "gml",
            "equil",
            "get_final_state",
            "utl",
            "param",
        ]
        self.arg_dict["simulate_psa"] = [
            "prefix",
            "suffix",
            "verbose",
            "argfile",
            "continue",
            "t_start",
            "t_end",
            "n_steps",
            "n_output_steps",
            "sample_times",
            "output_step_interval",
            "max_sim_steps",
            "stop_if",
            "print_on_stop",
            "print_end",
            "print_net",
            "save_progress",
            "print_CDAT",
            "print_functions",
            "netfile",
            "seed",
            # TODO: arguments for a method called "psa" that is not documented in
            # https://docs.google.com/spreadsheets/d/1Co0bPgMmOyAFxbYnGCmwKzoEsY2aUCMtJXQNpQCEUag/
            "poplevel",
            "check_product_scale",
        ]
        self.arg_dict["simulate"] = list(
            set(
                self.arg_dict["simulate"]
                + self.arg_dict["simulate_ode"]
                + self.arg_dict["simulate_ssa"]
                + self.arg_dict["simulate_pla"]
                + self.arg_dict["simulate_nf"]
                + self.arg_dict["simulate_psa"]
            )
        )
        self.arg_dict["parameter_scan"] = [
            "prefix",
            "suffix",
            "verbose",
            "method",
            "argfile",
            "continue",
            "t_start",
            "t_end",
            "n_steps",
            "n_output_steps",
            "sample_times",
            "output_step_interval",
            "max_sim_steps",
            "stop_if",
            "print_on_stop",
            "print_end",
            "print_net",
            "save_progress",
            "print_CDAT",
            "print_functions",
            "netfile",
            "seed",
            "parameter",
            "par_min",
            "par_max",
            "n_scan_pts",
            "log_scale",
            "par_scan_vals",
            "reset_conc",
        ]
        self.arg_dict["parameter_scan"] = list(
            set(self.arg_dict["parameter_scan"] + self.arg_dict["simulate"])
        )
        self.arg_dict["bifurcate"] = [
            "prefix",
            "suffix",
            "verbose",
            "method",
            "argfile",
            "continue",
            "t_start",
            "t_end",
            "n_steps",
            "n_output_steps",
            "sample_times",
            "output_step_interval",
            "max_sim_steps",
            "stop_if",
            "print_on_stop",
            "print_end",
            "print_net",
            "save_progress",
            "print_CDAT",
            "print_functions",
            "netfile",
            "seed",
            "parameter",
            "par_min",
            "par_max",
            "n_scan_pts",
            "log_scale",
            "par_scan_vals",
        ]
        self.arg_dict["bifurcate"] = list(
            set(self.arg_dict["bifurcate"] + self.arg_dict["parameter_scan"])
        )
        self.arg_dict["bifurcate"].remove("reset_conc")
        self.arg_dict["readFile"] = ["file", "blocks", "atomize", "skip_actions"]
        self.arg_dict["writeFile"] = [
            "format",
            "prefix",
            "suffix",
            "evaluate_expressions",
            "include_model",
            "include_network",
            "overwrite",
            "pretty_formatting",
            "TextReaction",
            "TextSpecies",
        ]
        self.arg_dict["writeModel"] = [
            "format",
            "prefix",
            "suffix",
            "evaluate_expressions",
            "include_model",
            "include_network",
            "overwrite",
            "pretty_formatting",
            "TextReaction",
            "TextSpecies",
        ]
        self.arg_dict["writeNetwork"] = [
            "format",
            "prefix",
            "suffix",
            "evaluate_expressions",
            "include_model",
            "include_network",
            "overwrite",
            "pretty_formatting",
            "TextReaction",
            "TextSpecies",
        ]
        self.arg_dict["writeXML"] = [
            "format",
            "prefix",
            "suffix",
            "evaluate_expressions",
            "include_model",
            "include_network",
            "overwrite",
            "pretty_formatting",
            "TextReaction",
            "TextSpecies",
        ]
        self.arg_dict["writeSBML"] = ["prefix", "suffix"]
        self.arg_dict["writeMfile"] = [
            "prefix",
            "suffix",
            "t_start",
            "t_end",
            "n_steps",
            "atol",
            "rtol",
            "max_step",
            "bdf",
            "maxOrder",
            "stats",
        ]
        self.arg_dict["writeCPYfile"] = [
            "prefix",
            "suffix",
            "t_start",
            "t_end",
            "n_steps",
            "atol",
            "rtol",
            "max_step",
            "bdf",
            "maxOrder",
            "stats",
        ]
        self.arg_dict["writeMexfile"] = [
            "prefix",
            "suffix",
            "t_start",
            "t_end",
            "n_steps",
            "atol",
            "rtol",
            "max_step",
            "max_num_steps",
            "max_err_test_fails",
            "max_conv_fails",
            "stiff",
            "sparse",
        ]
        self.arg_dict["writeMDL"] = ["prefix", "suffix"]
        self.arg_dict["visualize"] = [
            "type",
            "help",
            "suffix",
            "each",
            "background",
            "groups",
            "collapse",
            "filter",
            "level",
            "textonly",
            "opts",
            "ruleNames",
        ]
        # no_setter_syntax
        self.arg_dict["setConcentration"] = []
        self.arg_dict["addConcentration"] = []
        self.arg_dict["setParameter"] = []
        self.arg_dict["saveParameters"] = []
        self.arg_dict["quit"] = None
        self.arg_dict["setModelName"] = []
        self.arg_dict["substanceUnits"] = []
        self.arg_dict["version"] = []
        self.arg_dict["setOption"] = []
        # square_braces
        self.arg_dict["saveConcentrations"] = []
        self.arg_dict["resetConcentrations"] = []
        self.arg_dict["resetParameters"] = []

        # irregular arg types
        self.irregular_args = {}
        self.irregular_args["max_stoich"] = "dict"
        self.irregular_args["actions"] = "list"
        self.irregular_args["sample_times"] = "list"
        self.irregular_args["par_scan_vals"] = "list"
        self.irregular_args["blocks"] = "list"
        self.irregular_args["opts"] = "list"

        self.positional_arity = {
            "quit": (0, 0),
            "setModelName": (1, 1),
            "substanceUnits": (0, 1),
            "version": (0, 1),
            "setOption": (2, 2),
            "setConcentration": (2, 2),
            "addConcentration": (2, 2),
            "setParameter": (2, 2),
        }

    def validate_action(self, action_type, action_args):
        """Validate the legacy dictionary accepted by the model API."""
        if action_type not in self.possible_types:
            raise BNGParseError(message=f"Action type {action_type} not recognized!")
        if not isinstance(action_args, dict):
            raise BNGParseError(
                message=f"Action {action_type} arguments must be a dict, "
                f"got {type(action_args).__name__}"
            )
        if action_type in self.normal_types:
            allowed = self.arg_dict.get(action_type)
            if allowed is None and action_args:
                raise BNGParseError(
                    message=f"Action {action_type} does not take arguments"
                )
            for argument in action_args:
                if allowed and argument not in allowed:
                    raise BNGParseError(
                        message=f"Action argument {argument} not recognized for action {action_type}!"
                    )
            return

        for argument, value in action_args.items():
            if value is not None:
                raise BNGParseError(
                    message=f"Action {action_type} is positional; pass each value as a "
                    f"dict key mapped to None (got {argument!r}={value!r}). "
                    """For example: {'"A()"': None, '100': None}."""
                )
        if action_type not in self.positional_arity:
            return
        minimum, maximum = self.positional_arity[action_type]
        count = len(action_args)
        if not minimum <= count <= maximum:
            expected = (
                f"exactly {minimum}"
                if minimum == maximum
                else f"between {minimum} and {maximum}"
            )
            raise BNGParseError(
                message=f"Action {action_type} expects {expected} positional argument(s); got {count}."
            )

    def is_before_model(self, action_name):
        if action_name in self.before_model:
            return True
        return False

    def define_parser(self):
        ## Define action grammar
        try:
            import pyparsing as pp
        except ImportError:
            self.action_parser = _StdlibActionParser()
            return

        #
        base_name = pp.Word(pp.alphas, pp.alphanums + "_")
        action_name = base_name
        #
        dquote_word = pp.dblQuotedString
        squote_word = pp.sglQuotedString
        quote_word = dquote_word ^ squote_word
        # all action argument types
        list_arg = "[" + pp.Optional(pp.delimitedList(quote_word)) + "]"
        #
        arg_type_bool = pp.Word("0") ^ pp.Word("1")
        arg_type_int = pp.Word(pp.nums)
        arg_type_float = pp.Word(pp.nums + ".")
        arg_type_expr = pp.Word(
            pp.nums + "." + "+" + "-" + "e" + "E" + "(" + ")" + "/" + "*" + "^"
        )
        arg_type_list = (
            "[" + pp.Optional(pp.delimitedList(quote_word ^ arg_type_expr)) + "]"
        )
        arg_type_string = quote_word
        #
        curly_arg_token = quote_word + "=>" + arg_type_int
        arg_type_curly = "{" + pp.Optional(pp.delimitedList(curly_arg_token)) + "}"
        arg_types = (
            arg_type_bool
            ^ arg_type_int
            ^ arg_type_float
            ^ arg_type_list
            ^ arg_type_list
            ^ arg_type_string
            ^ arg_type_curly
            ^ arg_type_expr
        )
        #
        one_arg = quote_word
        two_arg = quote_word + "," + (arg_type_expr ^ quote_word)
        #
        single_arg = base_name + "=>" + arg_types
        #
        reg_arg_full = "{" + pp.Optional(pp.delimitedList(single_arg)) + "}"
        #
        reg_action_tk = (
            action_name + "(" + reg_arg_full + ")" + pp.Optional(";") + pp.stringEnd
        )
        two_arg_action_tk = (
            action_name
            + "("
            + quote_word
            + ","
            + pp.SkipTo(")" + pp.Optional(";") + pp.stringEnd)
            + ")"
            + pp.Optional(";")
            + pp.stringEnd
        )
        one_arg_action_tk = (
            action_name
            + "("
            + pp.Optional(one_arg)
            + ")"
            + pp.Optional(";")
            + pp.stringEnd
        )
        list_arg_action_tk = (
            action_name + "(" + list_arg + ")" + pp.Optional(";") + pp.stringEnd
        )
        full_action_tk = (
            reg_action_tk ^ list_arg_action_tk ^ two_arg_action_tk ^ one_arg_action_tk
        )
        ## Action grammar done
        self.action_parser = full_action_tk


def find_BNG_path(BNGPATH=None):
    """
    A simple function finds the path to BNG2.pl from
    * Environment variable
    * Assuming it's under PATH
    * Given optional path as argument

    Usage: test_bngexec(path)
           test_bngexec()

    Arguments
    ---------
    BNGPATH : str
        (optional) path to the folder that contains BNG2.pl
    """

    def _try_path(candidate_path):
        if candidate_path is None:
            return None
        # candidate can be either a directory or a direct path to BNG2.pl
        if os.path.basename(candidate_path).lower() == "bng2.pl":
            candidate_dir = os.path.dirname(candidate_path)
            candidate_exec = candidate_path
        else:
            candidate_dir = candidate_path
            candidate_exec = os.path.join(candidate_path, "BNG2.pl")
        if test_bngexec(candidate_exec):
            return candidate_dir, candidate_exec
        return None

    # 1) Prefer explicit argument
    tried = []
    if BNGPATH is not None:
        tried.append(BNGPATH)
        hit = _try_path(BNGPATH)
        if hit is not None:
            return hit

    # 2) Environment variable
    env_path = os.environ.get("BNGPATH")
    if env_path:
        tried.append(env_path)
        hit = _try_path(env_path)
        if hit is not None:
            return hit

    # 3) On PATH
    bng_on_path = spawn.which("BNG2.pl")
    if bng_on_path:
        tried.append(bng_on_path)
        hit = _try_path(bng_on_path)
        if hit is not None:
            os.environ["BNGPATH"] = hit[0]
            return hit

    # If we get here, BNG2.pl is not available. Some users may only need
    # basic BNGL parsing behavior and may not have BioNetGen installed.
    # Return (None, None) so callers can either raise a clearer error or
    # fall back to a minimal in-Python parse.
    return None, None


def test_perl(app=None, perl_path=None):
    """
    Test if perl is working

    Arguments
    ---------
    perl_path : str
        (optional) path to the folder that contains perl
    """
    logger = BNGLogger(app=app)
    logger.debug("Checking if perl is installed.", loc=f"{__file__} : test_perl()")
    # find path to perl binary
    if perl_path is None:
        perl_path = spawn.which("perl")
    if perl_path is None:
        raise BNGPerlError
    # check if perl is actually working
    command = [perl_path, "-v"]
    rc, _ = run_command(command)
    if rc != 0:
        raise BNGPerlError


def test_bngexec(bngexec):
    """
    A simple function that test if BNG2.pl given runs

    Usage: test_bngexec(path)

    Arguments
    ---------
    bngexec : str
        path to BNG2.pl to test
    """
    command = ["perl", bngexec]
    rc, _ = run_command(command)
    if rc == 0:
        return True
    else:
        return False


def run_command(command, suppress=True, timeout=None, cwd=None):
    """
    A convenience function to run a given command. The command should be
    given as a list of values e.g. ['command', 'arg1', 'arg2'] etc.

    Suppress kwarg suppresses all output from the command and timeout kwarg
    allows you to set a time period in seconds after which the command will
    be killed.
    """
    if timeout is not None:
        if suppress:
            # I am unsure how to do both timeout and the live polling of stdo
            rc = subprocess.run(
                command,
                timeout=timeout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=cwd,
            )
            return rc.returncode, rc
        else:
            # I am unsure how to do both timeout and the live polling of stdo
            rc = subprocess.run(command, timeout=timeout, capture_output=True, cwd=cwd)
            return rc.returncode, rc
    else:
        if suppress:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                bufsize=-1,
                cwd=cwd,
            )
            rc = process.wait()
            return rc, process
        else:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, encoding="utf8", cwd=cwd
            )
            out = []
            while True:
                output = process.stdout.readline()
                if output == "" and process.poll() is not None:
                    break
                if output:
                    o = output.strip()
                    out.append(o)
                    # print(o) # Removed to avoid bottleneck in tests
            rc = process.wait()
            return rc, out
