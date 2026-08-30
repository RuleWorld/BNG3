#pragma once

#include <string>
#include <unordered_map>
#include <vector>
#include <stdexcept>
#include <fstream>
#include <sstream>
#include <algorithm>

namespace bng::io {

struct TfunTable {
    std::vector<double> times;
    std::vector<double> values;
    std::string method = "linear";

    double interpolate(double t) const {
        if (times.empty()) return 0.0;
        if (times.size() == 1) return values[0];

        // Clamp to range (constant extrapolation)
        if (t <= times.front()) return values.front();
        if (t >= times.back()) return values.back();

        // Select the interval to the left of t.  upper_bound makes an exact
        // knot use the new value for step interpolation, matching NFsim's
        // TFUN implementation.
        auto it = std::upper_bound(times.begin(), times.end(), t);
        size_t i = static_cast<size_t>(it - times.begin()) - 1;

        // Linear interpolation
        double t0 = times[i], t1 = times[i + 1];
        double v0 = values[i], v1 = values[i + 1];
        if (method == "step") return v0;
        double alpha = (t - t0) / (t1 - t0);
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
