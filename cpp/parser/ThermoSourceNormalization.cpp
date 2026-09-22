#include "ThermoSourceNormalization.hpp"

#include <algorithm>
#include <cctype>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace bng::parser {

namespace {

std::string toLower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

std::string trimCopy(const std::string& value) {
    const auto begin = value.find_first_not_of(" \t\r");
    if (begin == std::string::npos) return {};
    const auto end = value.find_last_not_of(" \t\r");
    return value.substr(begin, end - begin + 1);
}

// Splits a physical line into its code part and its trailing comment part so
// that neither block detection nor `driven_by` extraction ever inspects text
// the lexer will discard.
void splitComment(const std::string& line, std::string& code, std::string& comment) {
    const auto hash = line.find('#');
    if (hash == std::string::npos) {
        code = line;
        comment.clear();
        return;
    }
    code = line.substr(0, hash);
    comment = line.substr(hash);
}

std::string quoteSyntheticOption(const std::string& key, const std::string& value) {
    const auto quote = [](const std::string& text) {
        std::string result;
        result.reserve(text.size() + 2);
        result.push_back('"');
        for (const char character : text) {
            if (character == '\\' || character == '"') result.push_back('\\');
            result.push_back(character);
        }
        result.push_back('"');
        return result;
    };
    return "setOption(" + quote(key) + "," + quote(value) + ")";
}

// True when `code` ends with a backslash continuation, meaning the logical
// rule continues on the next physical line.
bool hasContinuation(const std::string& code) {
    const auto trimmed = trimCopy(code);
    return !trimmed.empty() && trimmed.back() == '\\';
}

// A leading `label:` on a rule line, or empty when absent. Only a simple
// single-token label is recognized; anything else is left untouched so the
// grammar keeps full responsibility for exotic label forms.
std::string leadingLabel(const std::string& code) {
    const auto trimmed = trimCopy(code);
    const auto colon = trimmed.find(':');
    if (colon == std::string::npos || colon == 0) return {};
    // A `::` is a molecule scope prefix (%x::), never a label separator.
    if (colon + 1 < trimmed.size() && trimmed[colon + 1] == ':') return {};
    const auto candidate = trimCopy(trimmed.substr(0, colon));
    if (candidate.empty()) return {};
    // Reject anything containing pattern punctuation: that colon belongs to a
    // compartment or scope construct rather than to a label.
    if (candidate.find_first_of("()!~+-.,<>@% \t") != std::string::npos) return {};
    return candidate;
}

// Extracts `driven_by(<expr>)` from a rule's code, returning the expression and
// erasing the annotation in place. Returns false when no annotation is present.
bool extractDrivingWork(std::string& code, std::string& expression) {
    static const std::string keyword = "driven_by";
    const auto lowered = toLower(code);

    std::size_t search = 0;
    std::size_t found = std::string::npos;
    while (true) {
        const auto candidate = lowered.find(keyword, search);
        if (candidate == std::string::npos) break;
        // Require an identifier boundary so a component or parameter named
        // e.g. `not_driven_byX` is never mistaken for the annotation.
        const bool leftBoundary =
            candidate == 0 ||
            (std::isalnum(static_cast<unsigned char>(code[candidate - 1])) == 0 &&
             code[candidate - 1] != '_');
        if (leftBoundary) {
            if (found != std::string::npos) {
                throw std::runtime_error(
                    "a reaction rule accepts at most one driven_by() annotation");
            }
            found = candidate;
        }
        search = candidate + keyword.size();
    }
    if (found == std::string::npos) return false;

    auto cursor = found + keyword.size();
    while (cursor < code.size() &&
           std::isspace(static_cast<unsigned char>(code[cursor])) != 0) {
        ++cursor;
    }
    if (cursor >= code.size() || code[cursor] != '(') {
        throw std::runtime_error("driven_by requires a parenthesized work expression");
    }

    const auto open = cursor;
    int depth = 0;
    std::size_t close = std::string::npos;
    for (auto index = open; index < code.size(); ++index) {
        if (code[index] == '(') {
            ++depth;
        } else if (code[index] == ')') {
            if (--depth == 0) {
                close = index;
                break;
            }
        }
    }
    if (close == std::string::npos) {
        throw std::runtime_error("driven_by has unbalanced parentheses");
    }

    expression = trimCopy(code.substr(open + 1, close - open - 1));
    if (expression.empty()) {
        throw std::runtime_error("driven_by requires a non-empty work expression");
    }

    code.erase(found, close - found + 1);
    return true;
}

// One logical (continuation-joined) line together with the physical lines it
// occupied, so the rewritten source keeps the original line numbering.
struct LogicalLine {
    std::string code;
    std::string comment;
    std::size_t physicalLines = 1;
};

enum class BlockKind {
    None,
    BarrierPatterns,
    ReactionRules,
};

BlockKind blockFromHeader(const std::string& trimmedLowerCode, bool& isBegin) {
    const auto matches = [&](const char* text) { return trimmedLowerCode == text; };
    isBegin = true;
    if (matches("begin barrier patterns")) return BlockKind::BarrierPatterns;
    if (matches("begin reaction rules") || matches("begin reaction_rules") ||
        matches("begin reactions")) {
        return BlockKind::ReactionRules;
    }
    isBegin = false;
    if (matches("end barrier patterns")) return BlockKind::BarrierPatterns;
    if (matches("end reaction rules") || matches("end reaction_rules") ||
        matches("end reactions")) {
        return BlockKind::ReactionRules;
    }
    return BlockKind::None;
}

} // namespace

std::string normalizeThermodynamicSyntax(const std::string& source) {
    // Cheap rejection: neither construct present means the source is returned
    // byte-for-byte, so ordinary models pay nothing for this pass.
    const auto lowered = toLower(source);
    const bool mayHaveBarrier = lowered.find("barrier patterns") != std::string::npos;
    const bool mayHaveDrive = lowered.find("driven_by") != std::string::npos;
    if (!mayHaveBarrier && !mayHaveDrive) return source;

    // --- Split into physical lines, preserving a trailing newline ----------
    std::vector<std::string> physical;
    const bool hadTrailingNewline = !source.empty() && source.back() == '\n';
    {
        std::size_t start = 0;
        while (start <= source.size()) {
            const auto end = source.find('\n', start);
            const auto length =
                end == std::string::npos ? source.size() - start : end - start;
            physical.push_back(source.substr(start, length));
            if (end == std::string::npos) break;
            start = end + 1;
        }
        if (hadTrailingNewline && !physical.empty() && physical.back().empty()) {
            physical.pop_back();
        }
    }

    std::vector<std::string> output;
    std::vector<std::string> hoisted;
    BlockKind currentBlock = BlockKind::None;
    std::size_t barrierCount = 0;
    std::size_t ordinaryRuleCount = 0;

    for (std::size_t index = 0; index < physical.size();) {
        std::string code;
        std::string comment;
        splitComment(physical[index], code, comment);

        // --- Block headers -------------------------------------------------
        const auto trimmedLower = toLower(trimCopy(code));
        bool isBegin = false;
        const auto header = blockFromHeader(trimmedLower, isBegin);
        if (header != BlockKind::None) {
            if (isBegin) {
                if (currentBlock != BlockKind::None) {
                    throw std::runtime_error(
                        "nested '" + trimmedLower + "' inside another rule block");
                }
                currentBlock = header;
            } else {
                if (currentBlock != header) {
                    throw std::runtime_error("'" + trimmedLower +
                                             "' does not close an open matching block");
                }
                currentBlock = BlockKind::None;
            }

            if (header == BlockKind::BarrierPatterns) {
                // An empty barrier block is legal: it simply yields an empty
                // reaction rules block and no synthetic rules.
                //
                // A barrier patterns block is expressed to the grammar as an
                // ordinary reaction rules block; the synthetic labels are what
                // separate the two after parsing.
                const auto leading = code.substr(0, code.find_first_not_of(" \t"));
                output.push_back(leading +
                                 (isBegin ? "begin reaction rules" : "end reaction rules") +
                                 (comment.empty() ? std::string() : " " + comment));
            } else {
                output.push_back(physical[index]);
            }
            ++index;
            continue;
        }

        // --- Join continuation lines into one logical line -----------------
        LogicalLine logical;
        logical.code = code;
        logical.comment = comment;
        std::size_t consumed = 1;
        while (hasContinuation(logical.code) && index + consumed < physical.size()) {
            std::string nextCode;
            std::string nextComment;
            splitComment(physical[index + consumed], nextCode, nextComment);
            // Drop the backslash and splice, matching the lexer's ULB rule.
            const auto slash = logical.code.rfind('\\');
            logical.code.erase(slash);
            logical.code += " " + trimCopy(nextCode);
            if (!nextComment.empty()) {
                logical.comment += (logical.comment.empty() ? "" : " ") + nextComment;
            }
            ++consumed;
        }
        logical.physicalLines = consumed;

        const auto trimmedCode = trimCopy(logical.code);
        const bool isDefinition = !trimmedCode.empty();

        if (currentBlock == BlockKind::BarrierPatterns && isDefinition) {
            // Reject rate-law commas: a barrier is symmetric, so a second
            // expression has no meaning and must not be quietly ignored.
            if (trimmedCode.find(',') != std::string::npos) {
                throw std::runtime_error(
                    "a barrier pattern takes one transition-state energy, not a rate pair");
            }
            if (trimmedCode.find("->") == std::string::npos) {
                throw std::runtime_error(
                    "a barrier pattern must be written as a transition, e.g. A(s~U) -> A(s~P) Gbar");
            }

            const auto userLabel = leadingLabel(logical.code);
            std::string body = trimmedCode;
            if (!userLabel.empty()) {
                // Re-emit the user label through the option channel so the
                // synthetic label can own the leading position.
                hoisted.push_back(quoteSyntheticOption(
                    std::string(kBarrierLabelOptionPrefix) + std::to_string(barrierCount),
                    userLabel));
                const auto colon = body.find(':');
                body = trimCopy(body.substr(colon + 1));
            }
            if (body.empty()) {
                throw std::runtime_error("barrier pattern has no transition");
            }

            const auto leading = logical.code.substr(0, logical.code.find_first_not_of(" \t"));
            output.push_back(leading + std::string(kBarrierRuleLabelPrefix) +
                             std::to_string(barrierCount) + ": " + body +
                             (logical.comment.empty() ? std::string()
                                                      : " " + logical.comment));
            ++barrierCount;
            // Keep the original physical line count so error messages and
            // source spans still point at the user's line.
            for (std::size_t filler = 1; filler < logical.physicalLines; ++filler) {
                output.push_back("# BNG3: barrier pattern continuation normalized");
            }
            index += consumed;
            continue;
        }

        if (currentBlock == BlockKind::ReactionRules && isDefinition) {
            std::string work;
            bool hasWork = false;
            try {
                hasWork = extractDrivingWork(logical.code, work);
            } catch (const std::runtime_error& error) {
                throw std::runtime_error(std::string(error.what()) + " (rule '" +
                                         trimmedCode + "')");
            }
            if (hasWork) {
                hoisted.push_back(quoteSyntheticOption(
                    std::string(kDrivingWorkOptionPrefix) +
                        std::to_string(ordinaryRuleCount),
                    work));
            }
            ++ordinaryRuleCount;
            output.push_back(logical.code +
                             (logical.comment.empty() ? std::string()
                                                      : " " + logical.comment));
            for (std::size_t filler = 1; filler < logical.physicalLines; ++filler) {
                output.push_back("# BNG3: reaction rule continuation normalized");
            }
            index += consumed;
            continue;
        }

        // Outside the blocks of interest, and blank/comment lines inside them,
        // pass through untouched.
        for (std::size_t offset = 0; offset < consumed; ++offset) {
            output.push_back(physical[index + offset]);
        }
        index += consumed;
    }

    if (currentBlock != BlockKind::None) {
        throw std::runtime_error("unterminated rule block at end of source");
    }

    std::ostringstream normalized;
    for (const auto& option : hoisted) normalized << option << '\n';
    for (std::size_t line = 0; line < output.size(); ++line) {
        normalized << output[line];
        if (line + 1 < output.size() || hadTrailingNewline) normalized << '\n';
    }
    return normalized.str();
}

} // namespace bng::parser
