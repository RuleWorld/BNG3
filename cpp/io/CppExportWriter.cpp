#include "CppExportWriter.hpp"

#include "EnergyExportGuard.hpp"
#include "engine/DelayedSemanticsGuard.hpp"

#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cctype>
#include <cmath>
#include <map>

#include "ast/Model.hpp"
#include "compile/CompiledModel.hpp"
#include "engine/ObservableProjection.hpp"

namespace bng::io {

std::string CppExportWriter::write(const ast::Model& model, const engine::GeneratedNetwork& network) {
    Options opts;
    return write(model, network, opts);
}

std::string CppExportWriter::write(const ast::Model& model, const engine::GeneratedNetwork& network, const Options& opts) {
    engine::requireNoDelayedSemantics(model, network, "C++ export");
    requireNoEnergySemantics(model, "C++ export");
    compile::requireNoNativeEvents(model, "C++ export");
    std::ostringstream out;

    const std::string modelName = model.getModelName();
    const std::size_t nSpecies = network.species.size();
    const std::size_t nRxns = network.reactions.size();

    // Compute observable groups and stoichiometry
    auto groups = computeObservableGroups(model, network);
    auto stoich = computeStoichiometry(network, nSpecies);

    // Collect parameter info
    std::vector<std::string> paramNames;
    std::vector<double> paramValues;
    for (const auto& param : model.getParameters().all()) {
        paramNames.push_back(param.getName());
        paramValues.push_back(param.getValue());
    }
    const std::size_t nParams = paramNames.size();

    // Detect fixed species
    std::vector<bool> fixedSpecies(nSpecies, false);
    for (std::size_t i = 0; i < nSpecies; ++i) {
        fixedSpecies[i] = network.species.get(i).isConstant();
    }

    // CVODE solver settings
    std::string linearMultistep = opts.stiff ? "CV_BDF" : "CV_ADAMS";
    std::string solverSetup;
    if (!opts.stiff) {
        solverSetup =
            "    resources.nonlinear = SUNNonlinSol_FixedPoint(species, 0, resources.context);\n"
            "    if (!resources.nonlinear) return failure();\n"
            "    flag = CVodeSetNonlinearSolver(cvode_mem, resources.nonlinear);\n";
    } else if (opts.sparse) {
        solverSetup =
            "    resources.linear = SUNLinSol_SPGMR(species, SUN_PREC_NONE, 0, resources.context);\n"
            "    if (!resources.linear) return failure();\n"
            "    flag = CVodeSetLinearSolver(cvode_mem, resources.linear, nullptr);\n";
    } else {
        solverSetup =
            "    resources.matrix = SUNDenseMatrix(__N_SPECIES__, __N_SPECIES__, resources.context);\n"
            "    if (!resources.matrix) return failure();\n"
            "    resources.linear = SUNLinSol_Dense(species, resources.matrix, resources.context);\n"
            "    if (!resources.linear) return failure();\n"
            "    flag = CVodeSetLinearSolver(cvode_mem, resources.linear, resources.matrix);\n";
    }

    // ===== Header comment =====
    out << "/*\n";
    out << "**   " << modelName << "_cvode.h\n";
    out << "**\n";
    out << "**   Cvode-C++ implementation of BioNetGen model '" << modelName << "'.\n";
    out << "**\n";
    out << "**   Code Adapted from templates provided by Mathworks and Sundials.\n";
    out << "**\n";
    out << "**   Requires the CVODE libraries:  sundials_cvode and sundials_nvecserial.\n";
    out << "**   https://computation.llnl.gov/casc/sundials/main.html\n";
    out << "**\n";
    out << "**-----------------------------------------------------------------------------\n";
    out << "**\n";
    out << "**   Compilation notes:\n";
    out << "**\n";
    out << "**   include the model in your C++ file with\n";
    out << "**\n";
    out << "**   #include <" << modelName << ".h>\n";
    out << "**\n";
    out << "**   and compile with\n";
    out << "**\n";
    out << "**   g++ -I/path/to/" << modelName << ".h -c your_script.cpp\n";
    out << "**   g++  your_script.o -L/path/to/sundials/lib -lsundials_cvode -lsundials_nvecserial -o run_model\n";
    out << "**   ./run_model\n";
    out << "**\n";
    out << "**   note1: if cvode is in your library path, you can omit path specifications.\n";
    out << "**\n";
    out << "**-----------------------------------------------------------------------------\n";
    out << "**\n";
    out << "**   Usage in C++ :\n";
    out << "**\n";
    out << "**   Result result;\n";
    out << "**   vector<double> time_points;\n";
    out << "**   vector<double> species_initial_values;\n";
    out << "**   vector<double> parameters;\n";
    out << "**   result = simulate(timepoints, species_initial_values, parameters);\n";
    out << "**\n";
    out << "**   result.status: is the simulation status\n";
    out << "**   result.species: is the time series for each species, result.species[N][t]\n";
    out << "**      is the value of species N at time t\n";
    out << "**   result.observables: is the time series for each observable, result.observables[N][t]\n";
    out << "**      is the value of observable N at time t\n";
    out << "*/\n\n";

    // ===== Library headers =====
    out << "/* Library headers */\n";
    out << "#include <stdlib.h>\n";
    out << "#include <math.h>\n";
    out << "#include <iostream>\n";
    out << "#include <vector>\n\n";
    out << R"(#include <cvode/cvode.h>             /* prototypes for CVODE  */
#include <nvector/nvector_serial.h>  /* serial N_Vector       */
#include <sundials/sundials_iterative.h>
#include <sundials/sundials_linearsolver.h>
#include <sunmatrix/sunmatrix_dense.h>
#include <sunlinsol/sunlinsol_dense.h>
#include <sunlinsol/sunlinsol_spgmr.h>

#include <sunnonlinsol/sunnonlinsol_fixedpoint.h>

using namespace std;

)";

    // ===== Problem dimensions =====
    out << "/* Problem Dimensions */\n";
    out << "#define __N_PARAMETERS__   " << nParams << "\n";
    out << "#define __N_EXPRESSIONS__  " << nParams << "\n";
    out << "#define __N_OBSERVABLES__  " << groups.size() << "\n";
    out << "#define __N_RATELAWS__     " << nRxns << "\n";
    out << "#define __N_SPECIES__      " << nSpecies << "\n\n";

    // ===== calc_expressions =====
    out << "/* Calculate expressions */\n";
    out << "void\n";
    out << "calc_expressions ( N_Vector expressions, double * parameters )\n";
    out << "{\n";
    for (std::size_t i = 0; i < nParams; ++i) {
        out << "    NV_Ith_S(expressions," << i << ") = parameters[" << i << "];";
        out << "   /* " << paramNames[i] << " */\n";
    }
    out << "}\n\n";

    // ===== calc_observables =====
    out << "/* Calculate observables */\n";
    out << "void\n";
    out << "calc_observables ( N_Vector observables, N_Vector species, N_Vector expressions )\n";
    out << "{\n";
    for (std::size_t g = 0; g < groups.size(); ++g) {
        if (groups[g].entries.empty()) {
            out << "    NV_Ith_S(observables," << g << ") = 0;";
        } else {
            out << "    NV_Ith_S(observables," << g << ") = ";
            bool first = true;
            for (const auto& [specIdx, weight] : groups[g].entries) {
                if (!first) out << " + ";
                if (weight > 1) {
                    out << weight << "*";
                }
                out << "NV_Ith_S(species," << specIdx << ")";
                first = false;
            }
            out << ";";
        }
        out << "   /* " << groups[g].name << " */\n";
    }
    out << "}\n\n";

    // ===== calc_ratelaws =====
    out << "/* Calculate ratelaws */\n";
    out << "void\n";
    out << "calc_ratelaws ( N_Vector ratelaws, N_Vector species, N_Vector expressions, N_Vector observables )\n";
    out << "{\n";
    for (std::size_t r = 0; r < nRxns; ++r) {
        const auto& rxn = network.reactions.all()[r];
        out << "    NV_Ith_S(ratelaws," << r << ") = ";

        const std::string& rateLaw = rxn.getRateLaw();
        std::string cleanRate = rateLaw;
        auto localPos = cleanRate.find("|local:");
        if (localPos != std::string::npos) {
            cleanRate = cleanRate.substr(0, localPos);
        }

        double statFactor = rxn.getFactor();

        bool isNumeric = false;
        double rateVal = 0.0;
        try {
            std::size_t pos = 0;
            rateVal = std::stod(cleanRate, &pos);
            if (pos == cleanRate.size()) isNumeric = true;
        } catch (...) {}

        if (isNumeric) {
            double combined = statFactor * rateVal;
            out << combined;
        } else {
            std::string rateRef = convertRateToCVode(cleanRate, paramNames);
            if (std::abs(statFactor - 1.0) > 1e-12) {
                out << statFactor << "*" << rateRef;
            } else {
                out << rateRef;
            }
        }

        // Multiply by reactant concentrations
        for (const auto idx : rxn.getReactants()) {
            out << "*NV_Ith_S(species," << idx << ")";
        }

        out << ";\n";
    }
    out << "}\n\n\n";

    // ===== calc_species_deriv =====
    out << "/* Calculate species derivatives */\n";
    out << "int\n";
    out << "calc_species_deriv ( sunrealtype time, N_Vector species, N_Vector Dspecies, void * f_data )\n";
    out << "{\n";
    out << "    int         return_val;\n";
    out << "    N_Vector *  temp_data;\n";
    out << "\n";
    out << "    N_Vector    expressions;\n";
    out << "    N_Vector    observables;\n";
    out << "    N_Vector    ratelaws;\n";
    out << "\n";
    out << "    /* cast temp_data */\n";
    out << "    temp_data = (N_Vector*)f_data;\n";
    out << "\n";
    out << "    /* sget ratelaws Vector */\n";
    out << "    expressions = temp_data[0];\n";
    out << "    observables = temp_data[1];\n";
    out << "    ratelaws    = temp_data[2];\n";
    out << "\n";
    out << "    /* calculate observables */\n";
    out << "    calc_observables( observables, species, expressions );\n";
    out << "\n";
    out << "    /* calculate ratelaws */\n";
    out << "    calc_ratelaws( ratelaws, species, expressions, observables );\n";
    out << "\n";
    out << "    /* calculate derivatives */\n";

    // Build derivative expressions from stoichiometry
    // First initialize all to zero
    for (std::size_t i = 0; i < nSpecies; ++i) {
        out << "    NV_Ith_S(Dspecies," << i << ") = ";
        if (fixedSpecies[i]) {
            out << "0; /* fixed species */\n";
            continue;
        }

        // Find stoich entry for this species
        bool found = false;
        for (const auto& entry : stoich) {
            if (entry.speciesIndex == i) {
                found = true;
                bool first = true;
                for (const auto& [rxnIdx, coeff] : entry.rxnCoeffs) {
                    if (first) {
                        if (coeff == 1) {
                            out << "NV_Ith_S(ratelaws," << rxnIdx << ")";
                        } else if (coeff == -1) {
                            out << "-NV_Ith_S(ratelaws," << rxnIdx << ")";
                        } else {
                            out << coeff << "*NV_Ith_S(ratelaws," << rxnIdx << ")";
                        }
                    } else {
                        if (coeff == 1) {
                            out << " + NV_Ith_S(ratelaws," << rxnIdx << ")";
                        } else if (coeff == -1) {
                            out << " - NV_Ith_S(ratelaws," << rxnIdx << ")";
                        } else if (coeff > 0) {
                            out << " + " << coeff << "*NV_Ith_S(ratelaws," << rxnIdx << ")";
                        } else {
                            out << " - " << (-coeff) << "*NV_Ith_S(ratelaws," << rxnIdx << ")";
                        }
                    }
                    first = false;
                }
                break;
            }
        }
        if (!found) {
            out << "0";
        }
        out << ";\n";
    }

    out << "\n";
    out << "    return(0);\n";
    out << "}\n\n";

    // ===== check_flag =====
    out << "/*  Check function return value...\n";
    out << " *   opt == 0 means SUNDIALS function allocates memory so check if\n";
    out << " *            returned NULL pointer\n";
    out << " *   opt == 1 means SUNDIALS function returns a flag so check if\n";
    out << " *            flag >= 0\n";
    out << " *   opt == 2 means function allocates memory so check if returned\n";
    out << " *            NULL pointer\n";
    out << " */\n";
    out << "int check_flag(void *flagvalue, char *funcname, int opt)\n";
    out << "{\n";
    out << "    int *errflag;\n";
    out << "\n";
    out << "    /* Check if SUNDIALS function returned NULL pointer - no memory allocated */\n";
    out << "    if (opt == 0 && flagvalue == NULL)\n";
    out << "    {\n";
    out << "        cout << \"\\nSUNDIALS_ERROR: \" << funcname << \"() failed - returned NULL pointer\" << endl;\n";
    out << "        return(1);\n";
    out << "    }\n";
    out << "\n";
    out << "    /* Check if flag < 0 */\n";
    out << "    else if (opt == 1)\n";
    out << "    {\n";
    out << "        errflag = (int *) flagvalue;\n";
    out << "        if (*errflag < 0)\n";
    out << "        {\n";
    out << "            cout << \"\\nSUNDIALS_ERROR: \" << funcname << \"() failed with flag = \" << errflag << endl;\n";
    out << "            return(1);\n";
    out << "        }\n";
    out << "    }\n";
    out << "\n";
    out << "    /* Check if function returned NULL pointer - no memory allocated */\n";
    out << "    else if (opt == 2 && flagvalue == NULL)\n";
    out << "    {\n";
    out << "        cout << \"\\nMEMORY_ERROR: \" << funcname << \"() failed - returned NULL pointer\" << endl;\n";
    out << "        return(1);\n";
    out << "    }\n";
    out << "\n";
    out << "    return(0);\n";
    out << "}\n\n";

    // ===== Result struct =====
    out << "/*\n";
    out << "**   ========\n";
    out << "**   result structure\n";
    out << "**   ========\n";
    out << "*/\n\n";
    out << "struct Result {\n";
    out << "    int status;\n";
    out << "    vector< vector<double> > species;\n";
    out << "    vector< vector<double> > observables;\n";
    out << "};\n\n";

    // ===== simulate function =====
    out << "/*\n";
    out << "**   ========\n";
    out << "**   main simulate command\n";
    out << "**   ========\n";
    out << "*/\n";
    out << "Result simulate( vector<double> timepoints, vector<double> species_init, vector<double> parameters)\n";
    out << "{\n";
    out << "    int       n_timepoints;\n";
    out << "    size_t    i;\n";
    out << "    size_t    j;\n";
    out << "\n";
    out << R"(    struct SolverResources {
        SUNContext context = nullptr;
        SUNMatrix matrix = nullptr;
        SUNLinearSolver linear = nullptr;
        SUNNonlinearSolver nonlinear = nullptr;
        void* cvode = nullptr;
        N_Vector expressions = nullptr;
        N_Vector observables = nullptr;
        N_Vector ratelaws = nullptr;
        N_Vector species = nullptr;

        ~SolverResources() {
            if (cvode) CVodeFree(&cvode);
            if (nonlinear) SUNNonlinSolFree(nonlinear);
            if (linear) SUNLinSolFree(linear);
            if (matrix) SUNMatDestroy(matrix);
            if (species) N_VDestroy(species);
            if (ratelaws) N_VDestroy(ratelaws);
            if (observables) N_VDestroy(observables);
            if (expressions) N_VDestroy(expressions);
            if (context) SUNContext_Free(&context);
        }
    } resources;
    auto& expressions = resources.expressions;
    auto& observables = resources.observables;
    auto& ratelaws = resources.ratelaws;
    auto& species = resources.species;
    auto& cvode_mem = resources.cvode;
    N_Vector temp_data[3];
    sunrealtype reltol, abstol, time;
    int flag;

)";

    out << "    /* make sure timepoints has correct dimensions */\n";
    out << "    if ( (timepoints.size() < 2) )\n";
    out << "    {  cout << \"TIMEPOINTS must be a vector with 2 or more elements.\" <<endl;  }\n";
    out << "\n";
    out << "    /* make sure species_init has correct dimensions */\n";
    out << "    if ( (species_init.size() != __N_SPECIES__) )\n";
    out << "    {  cout << \"SPECIES_INIT must be a vector with " << nSpecies << " elements.\" << endl;  }\n";
    out << "\n";
    out << "    /* make sure params has correct dimensions */\n";
    out << "    if ( (parameters.size() != __N_PARAMETERS__) )\n";
    out << "    {  cout << \"PARAMS must be a column vector with " << nParams << " elements.\" << endl;  }\n";
    out << "\n";
    out << "    /* get number of timepoints */\n";
    out << "    n_timepoints = timepoints.size();\n";
    out << "\n";
    out << "    /* Create output arrays */\n";
    out << "    vector< vector<double> > species_out( __N_SPECIES__ , vector<double> (n_timepoints, 0));\n";
    out << "    vector< vector<double> > observables_out( __N_OBSERVABLES__ , vector<double> (n_timepoints, 0));\n";
    out << "\n";
    out << "    double * ptr_parameters = parameters.data();\n";
    out << "\n";

    out << R"(    const auto failure = [&] {
        return Result {1, species_out, observables_out};
    };
    flag = SUNContext_Create(SUN_COMM_NULL, &resources.context);
    if (flag != SUN_SUCCESS) return failure();

    expressions = N_VNew_Serial(__N_EXPRESSIONS__, resources.context);
    observables = N_VNew_Serial(__N_OBSERVABLES__, resources.context);
    ratelaws = N_VNew_Serial(__N_RATELAWS__, resources.context);
    species = N_VNew_Serial(__N_SPECIES__, resources.context);
    if (!expressions || !observables || !ratelaws || !species) return failure();

)";
    out << "    temp_data[0] = expressions;\n";
    out << "    temp_data[1] = observables;\n";
    out << "    temp_data[2] = ratelaws;\n";
    out << "\n";
    out << "    /* calculate expressions (expressions are constant, so only do this once!) */\n";
    out << "    calc_expressions( expressions, ptr_parameters );\n";
    out << "\n";
    out << "    /* SOLVE model equations! */\n";
    out << "\n";
    out << "    /* Set the scalar relative tolerance */\n";
    out << "    reltol = " << std::scientific << opts.rtol << ";\n";
    out << "    abstol = " << std::scientific << opts.atol << ";\n";
    out << std::defaultfloat;
    out << "\n";
    out << "    /* Initialize the species vector */\n";
    out << "    for ( i = 0; i < __N_SPECIES__; i++ )\n";
    out << "    {   NV_Ith_S(species,i) = species_init[i];   }\n";
    out << "\n";
    out << "    /* write initial species populations into species_out */\n";
    out << "    for ( i = 0; i < __N_SPECIES__; i++ )\n";
    out << "    {   species_out[i][0] = species_init[i];   }\n";
    out << "\n";
    out << "    /* write initial observables populations into species_out */\n";
    out << "    calc_observables( observables, species, expressions );\n";
    out << "    for ( i = 0; i < __N_OBSERVABLES__; i++ )\n";
    out << "    {   observables_out[i][0] = NV_Ith_S(observables,i);   }\n";
    out << "\n";

    // CVodeCreate
    out << "    /*   Call CVodeCreate to create the solver memory:\n";
    out << "     *   CV_ADAMS or CV_BDF is the linear multistep method\n";
    out << "     *   A pointer to the integrator problem memory is returned and stored in cvode_mem.\n";
    out << "     */\n";
    out << "    cvode_mem = CVodeCreate(" << linearMultistep << ", resources.context);\n";
    out << "    if (check_flag((void *)cvode_mem, \"CVodeCreate\", 0))\n";
    out << "        return failure();\n\n";

    // CVodeInit
    out << "    /*   Call CVodeInit to initialize the integrator memory:\n";
    out << "     *   cvode_mem is the pointer to the integrator memory returned by CVodeCreate\n";
    out << "     *   rhs_func  is the user's right hand side function in y'=f(t,y)\n";
    out << "     *   T0        is the initial time\n";
    out << "     *   y         is the initial dependent variable vector\n";
    out << "     */\n";
    out << "    flag = CVodeInit(cvode_mem, calc_species_deriv, timepoints[0], species);\n";
    out << "    if (check_flag(&flag, \"CVodeInit\", 1))\n";
    out << "        return failure();\n\n";

    // Tolerances
    out << "    /* Set scalar relative and absolute tolerances */\n";
    out << "    flag = CVodeSStolerances(cvode_mem, reltol, abstol);\n";
    out << "    if (check_flag(&flag, \"CVodeSStolerances\", 1))\n";
    out << "        return failure();\n\n";

    // User data
    out << "    /* pass params to rhs_func */\n";
    out << "    flag = CVodeSetUserData(cvode_mem, &temp_data);\n";
    out << "    if (check_flag(&flag, \"CVodeSetFdata\", 1))\n";
    out << "        return failure();\n\n";

    // CVODE v7 uses explicit solver objects. Adams uses fixed-point
    // iteration and sparse BDF uses matrix-free SPGMR.
    out << solverSetup;
    out << "    if (check_flag(&flag, \"CVODE solver setup\", 1))\n";
    out << "        return failure();\n\n";

    // Solver options
    out << "    flag = CVodeSetMaxNumSteps(cvode_mem, " << opts.maxNumSteps << ");\n";
    out << "    if (check_flag(&flag, \"CVodeSetMaxNumSteps\", 1))\n";
    out << "        return failure();\n\n";

    out << "    flag = CVodeSetMaxErrTestFails(cvode_mem, " << opts.maxErrTestFails << ");\n";
    out << "    if (check_flag(&flag, \"CVodeSetMaxErrTestFails\", 1))\n";
    out << "        return failure();\n\n";

    out << "    flag = CVodeSetMaxConvFails(cvode_mem, " << opts.maxConvFails << ");\n";
    out << "    if (check_flag(&flag, \"CVodeSetMaxConvFails\", 1))\n";
    out << "        return failure();\n\n";

    out << "    flag = CVodeSetMaxStep(cvode_mem, " << opts.maxStep << ");\n";
    out << "    if (check_flag(&flag, \"CVodeSetMaxStep\", 1))\n";
    out << "        return failure();\n\n";

    // Integration loop
    out << "    /* integrate to each timepoint */\n";
    out << "    for ( i=1;  i < n_timepoints;  i++ )\n";
    out << "    {\n";
    out << "        flag = CVode(cvode_mem, timepoints[i], species, &time, CV_NORMAL);\n";
    out << "        if (check_flag(&flag, \"CVode\", 1)) return failure();\n";
    out << "        for ( j = 0; j < __N_SPECIES__; j++ )\n";
    out << "        {   species_out[j][i] = NV_Ith_S(species,j);   }\n";
    out << "\n";
    out << "        /* copy observables output from nvector to output array */\n";
    out << "        calc_observables( observables, species, expressions );\n";
    out << "        for ( j = 0; j < __N_OBSERVABLES__; j++ )\n";
    out << "        {   observables_out[j][i] = NV_Ith_S(observables,j);   }\n";
    out << "    }\n\n";

    out << "    return Result {0, species_out, observables_out};\n";
    out << "}\n";

    return out.str();
}

std::string CppExportWriter::convertRateToCVode(const std::string& rate, const std::vector<std::string>& paramNames) {
    std::string result = rate;

    // Replace parameter names with NV_Ith_S(expressions,i) - longer names first
    std::vector<std::pair<std::size_t, std::string>> sorted;
    for (std::size_t i = 0; i < paramNames.size(); ++i) {
        sorted.push_back({i, paramNames[i]});
    }
    std::sort(sorted.begin(), sorted.end(), [](const auto& a, const auto& b) {
        return a.second.size() > b.second.size();
    });

    for (const auto& [idx, name] : sorted) {
        std::string paramRef = "NV_Ith_S(expressions," + std::to_string(idx) + ")";
        std::size_t pos = 0;
        while ((pos = result.find(name, pos)) != std::string::npos) {
            bool validStart = (pos == 0 || (!std::isalnum(static_cast<unsigned char>(result[pos - 1])) && result[pos - 1] != '_'));
            bool validEnd = (pos + name.length() >= result.length() ||
                           (!std::isalnum(static_cast<unsigned char>(result[pos + name.length()])) && result[pos + name.length()] != '_'));
            if (validStart && validEnd) {
                result.replace(pos, name.length(), paramRef);
                pos += paramRef.length();
            } else {
                pos += name.length();
            }
        }
    }

    return result;
}

std::vector<CppExportWriter::ObservableGroup> CppExportWriter::computeObservableGroups(
    const ast::Model& model, const engine::GeneratedNetwork& network) {
    std::vector<ObservableGroup> groups;
    const compile::CompiledModel compiledModel(model);
    const engine::ObservableProjection projection(compiledModel);
    groups.reserve(projection.size());

    for (std::size_t observableIndex = 0;
         observableIndex < projection.size(); ++observableIndex) {
        ObservableGroup group;
        group.name = projection.name(observableIndex);
        group.type = compiledModel.observables().at(observableIndex).type;

        for (std::size_t speciesIndex = 0; speciesIndex < network.species.size(); ++speciesIndex) {
            const auto& species = network.species.get(speciesIndex);
            const auto weight = projection.weight(
                observableIndex,
                species.getSpeciesGraph().getGraph(), species.getCompartment());
            if (weight > 0) {
                group.entries.push_back(
                    {speciesIndex, static_cast<std::size_t>(weight)});
            }
        }

        groups.push_back(std::move(group));
    }

    return groups;
}

std::vector<CppExportWriter::StoichEntry> CppExportWriter::computeStoichiometry(
    const engine::GeneratedNetwork& network, std::size_t nSpecies) {
    std::map<std::size_t, std::map<std::size_t, int>> stoichMap;

    for (std::size_t r = 0; r < network.reactions.size(); ++r) {
        const auto& rxn = network.reactions.all()[r];
        for (const auto idx : rxn.getReactants()) {
            stoichMap[idx][r] -= 1;
        }
        for (const auto idx : rxn.getProducts()) {
            stoichMap[idx][r] += 1;
        }
    }

    std::vector<StoichEntry> result;
    for (auto& [specIdx, rxnMap] : stoichMap) {
        StoichEntry entry;
        entry.speciesIndex = specIdx;
        for (auto& [rxnIdx, coeff] : rxnMap) {
            if (coeff != 0) {
                entry.rxnCoeffs.push_back({rxnIdx, coeff});
            }
        }
        if (!entry.rxnCoeffs.empty()) {
            result.push_back(std::move(entry));
        }
    }

    return result;
}

} // namespace bng::io
