#include "NFutil.hh"
#include <fstream>
#include <iostream>
#include <cstdlib>
#include <cerrno>
#include <climits>
#include <cctype>
#include <cmath>


using namespace NFutil;


TimeSeries NFutil::loadTimeSeries(const std::string& filePath, const std::string& callerName)
{
	TimeSeries ts;
	std::ifstream file(filePath.c_str());

	if (!file.good()) {
		throw std::runtime_error("File doesn't look like it exists: " + filePath);
	}

	try {
		std::string a, b;
		bool hasDirection = false;
		bool isIncreasing = false;
		double prevTime = 0.0;
		bool first = true;

		while (file >> a >> b) {
			double t = NFutil::convertToDouble(a);
			ts.time.push_back(t);

			double v = NFutil::convertToDouble(b);
			ts.values.push_back(v);

			if (first) {
				prevTime = t;
				first = false;
			} else {
				if (t == prevTime) {
					throw std::runtime_error("Time values in data file must be strictly monotonic. Found duplicate time: " + NFutil::toString(t));
				}

				if (!hasDirection) {
					isIncreasing = (t > prevTime);
					hasDirection = true;
				} else {
					if ((isIncreasing && t < prevTime) || (!isIncreasing && t > prevTime)) {
						throw std::runtime_error("Time values in data file must be strictly monotonic.");
					}
				}
				prevTime = t;
			}
		}

		if (ts.time.size() == 0) {
			throw std::runtime_error("Data file is empty or invalid format.");
		}
	} catch (std::runtime_error const & e) {
		// Re-throw our specifically constructed runtime_errors without wrapping them further
		throw;
	} catch (std::exception const & e) {
		throw std::runtime_error("Failed to either open or read the file, or invalid number format.\n" + std::string(e.what()));
	}

	return ts;
}

bool NFutil::tryConvertToDouble(const std::string& s, double& value)
{
	/* Preserve the legacy stream parser's decimal-number grammar while avoiding
	 * allocation and exceptions when a field is actually a parameter name. */
	const char *begin = s.c_str();
	const char *p = begin;
	while (*p && std::isspace(static_cast<unsigned char>(*p))) ++p;
	if (*p == '+' || *p == '-') ++p;

	bool haveDigit = false;
	while (*p >= '0' && *p <= '9') { haveDigit = true; ++p; }
	if (*p == '.') {
		++p;
		while (*p >= '0' && *p <= '9') { haveDigit = true; ++p; }
	}
	if (!haveDigit) return false;
	if (*p == 'e' || *p == 'E') {
		++p;
		if (*p == '+' || *p == '-') ++p;
		const char *expBegin = p;
		while (*p >= '0' && *p <= '9') ++p;
		if (p == expBegin) return false;
	}
	if (*p != '\0') return false;

	char *end = 0;
	errno = 0;
	double x = std::strtod(begin, &end);
	if (end == begin || end == 0 || *end != '\0' || !std::isfinite(x)) return false;
	value = x;
	return true;
}

double NFutil::convertToDouble(const std::string& s)
{
	double x = 0.0;
	if (!NFutil::tryConvertToDouble(s, x))
		throw std::runtime_error("error in NFutil::convertToDouble(\"" + s + "\")");
	return x;
}
bool NFutil::tryConvertToInt(const std::string& s, int& value)
{
	const char *begin = s.c_str();
	char *end = 0;
	errno = 0;
	long x = std::strtol(begin, &end, 10);
	if (end == begin || end == 0 || *end != '\0' || errno == ERANGE ||
			x < INT_MIN || x > INT_MAX)
		return false;
	value = static_cast<int>(x);
	return true;
}
int NFutil::convertToInt(const std::string& s)
{
	const char *begin = s.c_str();
	char *end = 0;
	errno = 0;
	long x = std::strtol(begin, &end, 10);
	if (end == begin || end == 0 || *end != '\0' || errno == ERANGE ||
			x < INT_MIN || x > INT_MAX)
		throw std::runtime_error("error in NFutil::convertToInt(\"" + s + "\")");
	return static_cast<int>(x);
}


string NFutil::toString(double x)
{
	std::ostringstream o;
	if (!(o << x)) {
		cout<<endl; cerr<<"Error converting double to string."<<endl;
		exit(1);
	}
	return o.str();
}
string NFutil::toString(int x)
{
	std::ostringstream o;
	if (!(o << x)) {
		cout<<endl; cerr<<"Error converting double to string."<<endl;
		exit(1);
	}
	return o.str();
}
