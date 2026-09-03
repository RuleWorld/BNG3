"""Public utility surface ported from the Playground atomizer helpers."""

from __future__ import annotations

import copy
import os
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict, Generic, Iterable, List, Optional
from typing import Set, Tuple, TypeVar

from .core import levenshtein, similarity
from .types import standardize_name

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")
R = TypeVar("R")


def randInt(minimum: int, maximum: int) -> int:
    """Return a random integer in the inclusive range from the reference API."""

    return random.randint(minimum, maximum)


def deepCopy(value: T) -> T:
    """Return a recursive copy, matching the helper's public contract."""

    return copy.deepcopy(value)


class Counter(Dict[T, int], Generic[T]):
    """Small Map-like occurrence counter used by the atomizer reference."""

    def __init__(self, items: Optional[Iterable[T]] = None) -> None:
        super().__init__()
        if items is not None:
            self.update(items)

    def update(self, items: Iterable[T]) -> None:  # type: ignore[override]
        for item in items:
            self[item] = self.get(item, 0) + 1

    def getCount(self, item: T) -> int:
        return self.get(item, 0)

    def mostCommon(self, count: Optional[int] = None) -> List[Tuple[T, int]]:
        values = sorted(self.items(), key=lambda item: item[1], reverse=True)
        return values if count is None else values[:count]

    def total(self) -> int:
        return sum(self.values())

    def elements(self) -> List[T]:
        result: List[T] = []
        for item, count in self.items():
            result.extend([item] * max(0, count))
        return result

    def subtract(self, other: "Counter[T] | Iterable[T]") -> None:
        if isinstance(other, Counter):
            for item, count in other.items():
                self[item] = self.get(item, 0) - count
            return
        for item in other:
            self[item] = self.get(item, 0) - 1

    # Python spellings are useful to callers while the camelCase names retain
    # the public names exported by the TypeScript reference.
    get_count = getCount
    most_common = mostCommon


class DefaultDict(Dict[K, V], Generic[K, V]):
    """Dictionary whose ``get`` creates a value for missing keys."""

    def __init__(self, default_factory: Callable[[], V]) -> None:
        super().__init__()
        self.default_factory = default_factory

    def get(self, key: K, default: object = None) -> V:  # type: ignore[override]
        if key not in self:
            value = self.default_factory()
            self[key] = value
            return value
        return super().get(key)  # type: ignore[return-value]


_GLOBAL_MEMO_CACHES: Dict[str, Dict[str, Any]] = {}


def pmemoize(
    function: Callable[..., R], cache_key: Optional[str] = None
) -> Callable[..., R]:
    """Memoize calls using the Playground's process-global named caches."""

    name = cache_key or f"{function.__module__}.{function.__qualname__}"
    cache = _GLOBAL_MEMO_CACHES.setdefault(name, {})

    @wraps(function)
    def memoized(*args: Any, **kwargs: Any) -> R:
        key = repr((args, sorted(kwargs.items())))
        if key not in cache:
            cache[key] = function(*args, **kwargs)
        return cache[key]

    return memoized


class Memoize(Generic[R]):
    def __init__(self, function: Callable[..., R]) -> None:
        self.function = function
        self.cache: Dict[str, R] = {}

    def call(self, *args: Any) -> R:
        key = repr(args)
        if key not in self.cache:
            self.cache[key] = self.function(*args)
        return self.cache[key]

    def clear(self) -> None:
        self.cache.clear()


class MemoizeMapped(Generic[R]):
    def __init__(
        self, function: Callable[..., R], key_function: Callable[..., str]
    ) -> None:
        self.function = function
        self.key_function = key_function
        self.cache: Dict[str, R] = {}

    def call(self, *args: Any) -> R:
        key = self.key_function(*args)
        if key not in self.cache:
            self.cache[key] = self.function(*args)
        return self.cache[key]

    def clear(self) -> None:
        self.cache.clear()


def sequenceMatcherRatio(first: List[T], second: List[T]) -> float:
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    matches = 0
    remaining = list(second)
    for item in first:
        if item in remaining:
            matches += 1
            remaining.remove(item)
    return (2 * matches) / (len(first) + len(second))


def longestCommonSubstring(first: str, second: str) -> str:
    if not first or not second:
        return ""
    previous = [0] * (len(second) + 1)
    longest = 0
    end = 0
    for first_index, first_char in enumerate(first, 1):
        current = [0]
        for second_index, second_char in enumerate(second, 1):
            value = previous[second_index - 1] + 1 if first_char == second_char else 0
            current.append(value)
            if value > longest:
                longest = value
                end = first_index
        previous = current
    return first[end - longest : end]


def isValidBNGLName(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))


def factorial(value: float) -> int:
    if value <= 1:
        return 1
    result = 1
    current = 2
    while current <= value:
        result *= current
        current += 1
    return result


def comb(n: float, k: float) -> float:
    if k < 0 or k > n:
        return 0
    if k == 0 or k == n:
        return 1
    return factorial(n) / (factorial(k) * factorial(n - k))


def _split_arguments(value: str) -> List[str]:
    arguments: List[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(value):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            arguments.append(value[start:index].strip())
            start = index + 1
    arguments.append(value[start:].strip())
    return arguments


def _replace_calls(
    expression: str, name: str, render: Callable[[List[str]], str]
) -> str:
    pattern = re.compile(rf"\b{re.escape(name)}\s*\(")
    result = expression
    cursor = 0
    while True:
        match = pattern.search(result, cursor)
        if match is None:
            return result
        opening = result.find("(", match.start(), match.end())
        depth = 0
        closing = -1
        for index in range(opening, len(result)):
            character = result[index]
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing < 0:
            return result
        arguments = _split_arguments(result[opening + 1 : closing])
        original = result[match.start() : closing + 1]
        replacement = render(arguments)
        if replacement == "":
            replacement = original
        result = result[: match.start()] + replacement + result[closing + 1 :]
        cursor = match.start() + len(replacement)


def convertMathFunction(math_string: str) -> str:
    """Convert common MathML/libSBML function spellings from the reference."""

    result = str(math_string)
    result = _replace_calls(
        result,
        "pow",
        lambda args: (
            f"(({args[0]})^({args[1]}))"
            if len(args) >= 2
            else "pow(" + ", ".join(args) + ")"
        ),
    )
    result = _replace_calls(
        result,
        "sqrt",
        lambda args: f"(({args[0]})^(1/2))" if args else "sqrt()",
    )
    result = _replace_calls(
        result,
        "sqr",
        lambda args: f"(({args[0]})^2)" if args else "sqr()",
    )
    result = _replace_calls(
        result,
        "root",
        lambda args: (
            f"(({args[1]})^(1/({args[0]})))"
            if len(args) >= 2
            else "root(" + ", ".join(args) + ")"
        ),
    )
    result = _replace_calls(
        result,
        "exp",
        lambda args: (f"(2.71828182845905^({args[0]}))" if args else "exp()"),
    )

    # Resolve log's two-argument base form before the one-argument natural log.
    result = _replace_calls(
        result,
        "log",
        lambda args: (
            f"(ln({args[1]})/ln({args[0]}))"
            if len(args) >= 2
            else f"ln({args[0]})" if args else "log()"
        ),
    )
    result = _replace_calls(
        result,
        "log10",
        lambda args: f"(ln({args[0]})/2.302585093)" if args else "log10()",
    )

    for name, operator in {
        "gt": ">",
        "lt": "<",
        "geq": ">=",
        "leq": "<=",
        "eq": "==",
        "neq": "!=",
        "and": "&&",
        "or": "||",
    }.items():
        result = _replace_calls(
            result,
            name,
            lambda args, operator=operator, name=name: (
                f"({args[0]} {operator} {args[1]})"
                if len(args) >= 2
                else f"{name}(" + ", ".join(args) + ")"
            ),
        )
    result = _replace_calls(
        result,
        "not",
        lambda args: (
            f"(!{args[0]})" if len(args) == 1 else "not(" + ", ".join(args) + ")"
        ),
    )
    result = _replace_calls(
        result,
        "ceil",
        lambda args: (
            f"min(rint(({args[0]})+0.5),rint(({args[0]})+1))" if args else "ceil()"
        ),
    )
    result = _replace_calls(
        result,
        "floor",
        lambda args: (
            f"min(rint(({args[0]})-0.5),rint(({args[0]})+0.5))" if args else "floor()"
        ),
    )

    result = re.sub(r"\binf\b", "1e20", result, flags=re.IGNORECASE)
    result = re.sub(r"\bpi\b", "3.14159265358979", result)
    result = re.sub(r"\be\b(?!\s*\^)", "2.71828182845905", result)
    result = re.sub(r"\btrue\b", "1", result, flags=re.IGNORECASE)
    result = re.sub(r"\bfalse\b", "0", result, flags=re.IGNORECASE)
    return result


def cleanParameterValue(value: str) -> str:
    result = re.sub(r"\b(?:infinity|inf)\b", "1e20", str(value), flags=re.IGNORECASE)
    result = re.sub(r"\bnan\b", "0", result, flags=re.IGNORECASE)
    return re.sub(
        r"(?<![A-Za-z_])(\d+)[eE]([+-]?\d+)(?![A-Za-z_])",
        r"\1e\2",
        result,
    )


LogLevel = str
_LOG_LEVELS = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}


@dataclass
class LogMessage:
    level: LogLevel
    code: str
    message: str
    context: Optional[str]
    timestamp: datetime


class Logger:
    def __init__(self) -> None:
        level = os.environ.get("ATOMIZER_LOG_LEVEL", "WARNING").upper()
        self._level = level if level in _LOG_LEVELS else "WARNING"
        self._quiet = os.environ.get("ATOMIZER_QUIET", "") == "1"
        self._messages: List[LogMessage] = []

    def setLevel(self, level: LogLevel) -> None:
        self._level = level

    def setQuietMode(self, quiet: bool) -> None:
        self._quiet = quiet

    def log(
        self,
        level: LogLevel,
        code: str,
        message: str,
        context: Optional[str] = None,
    ) -> None:
        if _LOG_LEVELS[level] < _LOG_LEVELS[self._level]:
            return
        entry = LogMessage(level, code, message, context, datetime.now())
        self._messages.append(entry)
        if self._quiet:
            return
        suffix = f" ({context})" if context else ""
        stream = sys.stderr if level in {"WARNING", "ERROR", "CRITICAL"} else sys.stdout
        print(f"[{level}] {code}: {message}{suffix}", file=stream)

    def debug(self, code: str, message: str, context: Optional[str] = None) -> None:
        self.log("DEBUG", code, message, context)

    def info(self, code: str, message: str, context: Optional[str] = None) -> None:
        self.log("INFO", code, message, context)

    def warning(self, code: str, message: str, context: Optional[str] = None) -> None:
        self.log("WARNING", code, message, context)

    def error(self, code: str, message: str, context: Optional[str] = None) -> None:
        self.log("ERROR", code, message, context)

    def critical(self, code: str, message: str, context: Optional[str] = None) -> None:
        self.log("CRITICAL", code, message, context)

    def getMessages(self) -> List[LogMessage]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def getMessagesByLevel(self, level: LogLevel) -> List[LogMessage]:
        return [message for message in self._messages if message.level == level]

    def hasErrors(self) -> bool:
        return any(message.level in {"ERROR", "CRITICAL"} for message in self._messages)


logger = Logger()


def logMess(code_and_level: str, message: str) -> None:
    match = re.match(r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL):(.+)$", code_and_level)
    if match:
        logger.log(match.group(1), match.group(2), message)
        return
    parts = code_and_level.split(":")
    if len(parts) >= 2 and parts[0] in _LOG_LEVELS:
        logger.log(parts[0], ":".join(parts[1:]), message)
    else:
        logger.info(code_and_level, message)


def isNode() -> bool:
    """The Python port is never running in the TypeScript Node runtime."""

    return False


def compareLists(first: List[T], second: List[T]) -> bool:
    if len(first) != len(second):
        return False
    left = Counter(map(str, first))
    right = Counter(map(str, second))
    return left == right


def setIntersection(first: Set[T], second: Set[T]) -> Set[T]:
    return first.intersection(second)


def setDifference(first: Set[T], second: Set[T]) -> Set[T]:
    return first.difference(second)


def setUnion(first: Set[T], second: Set[T]) -> Set[T]:
    return first.union(second)


class TranslationException(Exception):
    pass


class CycleError(Exception):
    def __init__(self, memory: Any) -> None:
        super().__init__("Cycle detected in dependency graph")
        self.memory = memory


class BindingException(Exception):
    def __init__(self, value: Any, combinations: Any) -> None:
        super().__init__(str(value))
        self.value = value
        self.combinations = combinations


# CamelCase names are the Playground exports. Snake-case aliases make the
# same utility surface natural for Python callers.
standardizeName = standardize_name
is_valid_bngl_name = isValidBNGLName
convert_math_function = convertMathFunction
clean_parameter_value = cleanParameterValue
compare_lists = compareLists
set_intersection = setIntersection
set_difference = setDifference
set_union = setUnion
rand_int = randInt
deep_copy = deepCopy
log_mess = logMess
sequence_matcher_ratio = sequenceMatcherRatio
longest_common_substring = longestCommonSubstring


__all__ = [
    "BindingException",
    "Counter",
    "CycleError",
    "DefaultDict",
    "LogLevel",
    "LogMessage",
    "Logger",
    "Memoize",
    "MemoizeMapped",
    "TranslationException",
    "cleanParameterValue",
    "clean_parameter_value",
    "comb",
    "compareLists",
    "compare_lists",
    "convertMathFunction",
    "convert_math_function",
    "deepCopy",
    "deep_copy",
    "factorial",
    "isNode",
    "isValidBNGLName",
    "is_valid_bngl_name",
    "levenshtein",
    "logMess",
    "log_mess",
    "logger",
    "longestCommonSubstring",
    "longest_common_substring",
    "pmemoize",
    "randInt",
    "rand_int",
    "sequenceMatcherRatio",
    "sequence_matcher_ratio",
    "setDifference",
    "setIntersection",
    "setUnion",
    "set_difference",
    "set_intersection",
    "set_union",
    "similarity",
    "standardizeName",
    "standardize_name",
]
