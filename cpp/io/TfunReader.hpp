#pragma once

#include <algorithm>
#include <cmath>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace bng::io {

struct TfunTable {
    std::vector<double> times;
    std::vector<double> values;
    std::string method = "linear";

    double interpolate(double t) const {
        if (times.empty()) return 0.0;
        if (times.size() != values.size()) {
            throw std::runtime_error("TFUN table has mismatched time and value columns");
        }
        if (std::isnan(t)) return std::numeric_limits<double>::quiet_NaN();
        if (times.size() == 1) return values[0];

        // Clamp to range (constant extrapolation)
        if (t <= times.front()) return values.front();
        if (t >= times.back()) return values.back();

        // Select the interval to the left of t.  upper_bound makes an exact
        // knot use the new value for step interpolation, matching NFsim's
        // TFUN implementation.
        auto it = std::upper_bound(times.begin(), times.end(), t);
        if (it == times.begin()) return values.front();
        if (it == times.end()) return values.back();
        const size_t right = static_cast<size_t>(it - times.begin());
        const size_t i = right - 1;

        // Linear or step interpolation
        const double t0 = times[i], t1 = times[right];
        const double v0 = values[i], v1 = values[right];
        if (method == "step") return v0;
        if (t1 == t0) return v0;
        const double alpha = (t - t0) / (t1 - t0);
        return v0 + alpha * (v1 - v0);
    }
};

class TfunReader {
public:
    static TfunTable read(const std::string& filePath) {
        TfunTable table;
        std::ifstream file(filePath);
        if (!file.good()) {
            throw std::runtime_error("Cannot open tfun file: " + filePath);
        }

        std::string line;
        while (std::getline(file, line)) {
            // Skip comments and empty lines
            if (line.empty() || line[0] == '#') continue;

            std::istringstream iss(line);
            double t, v;
            if (iss >> t >> v) {
                if (!std::isfinite(t) || !std::isfinite(v)) {
                    throw std::runtime_error("TFUN file contains non-finite value: " + filePath);
                }
                if (!table.times.empty() && t < table.times.back()) {
                    throw std::runtime_error(
                        "TFUN file x-values must be monotonically non-decreasing: " + filePath);
                }
                table.times.push_back(t);
                table.values.push_back(v);
            }
        }

        if (table.times.empty()) {
            throw std::runtime_error("Empty or invalid tfun file: " + filePath);
        }

        return table;
    }
};

class TfunRegistry {
public:
    void load(const std::string& name,
              const std::string& filePath,
              std::string method = "linear") {
        auto table = TfunReader::read(filePath);
        if (!method.empty()) table.method = std::move(method);
        tables_[name] = std::move(table);
    }

    void addTable(const std::string& name, TfunTable table) {
        tables_[name] = std::move(table);
    }

    double evaluate(const std::string& name, double t) const {
        auto it = tables_.find(name);
        if (it == tables_.end()) {
            throw std::runtime_error("Unknown tfun: " + name);
        }
        return it->second.interpolate(t);
    }

    bool has(const std::string& name) const {
        return tables_.find(name) != tables_.end();
    }

private:
    std::unordered_map<std::string, TfunTable> tables_;
};

} // namespace bng::io
