/*
**   _cvode.h
**
**   Cvode-C++ implementation of BioNetGen model ''.
**
**   Code Adapted from templates provided by Mathworks and Sundials.
**
**   Requires the CVODE libraries:  sundials_cvode and sundials_nvecserial.
**   https://computation.llnl.gov/casc/sundials/main.html
**
**-----------------------------------------------------------------------------
**
**   Compilation notes:
**
**   include the model in your C++ file with
**
**   #include <.h>
**
**   and compile with
**
**   g++ -I/path/to/.h -c your_script.cpp
**   g++  your_script.o -L/path/to/sundials/lib -lsundials_cvode -lsundials_nvecserial -o run_model
**   ./run_model
**
**   note1: if cvode is in your library path, you can omit path specifications.
**
**-----------------------------------------------------------------------------
**
**   Usage in C++ :
**
**   Result result;
**   vector<double> time_points;
**   vector<double> species_initial_values;
**   vector<double> parameters;
**   result = simulate(timepoints, species_initial_values, parameters);
**
**   result.status: is the simulation status
**   result.species: is the time series for each species, result.species[N][t]
**      is the value of species N at time t
**   result.observables: is the time series for each observable, result.observables[N][t]
**      is the value of observable N at time t
*/

/* Library headers */
#include <stdlib.h>
#include <math.h>
#include <iostream>
#include <vector>

#include <cvode/cvode.h>             /* prototypes for CVODE  */
#include <nvector/nvector_serial.h>  /* serial N_Vector       */
#include <cvode/cvode_dense.h>       /* prototype for CVDense */
#include <cvode/cvode_spgmr.h>       /* prototype for CVSpgmr */

using namespace std;

/* Problem Dimensions */
#define __N_PARAMETERS__   4
#define __N_EXPRESSIONS__  4
#define __N_OBSERVABLES__  2
#define __N_RATELAWS__     1
#define __N_SPECIES__      2

/* Calculate expressions */
void
calc_expressions ( N_Vector expressions, double * parameters )
{
    NV_Ith_S(expressions,0) = parameters[0];   /* k */
    NV_Ith_S(expressions,1) = parameters[1];   /* kr */
    NV_Ith_S(expressions,2) = parameters[2];   /* N */
    NV_Ith_S(expressions,3) = parameters[3];   /* V */
}

/* Calculate observables */
void
calc_observables ( N_Vector observables, N_Vector species, N_Vector expressions )
{
    NV_Ith_S(observables,0) = NV_Ith_S(species,0);   /* A */
    NV_Ith_S(observables,1) = NV_Ith_S(species,1);   /* B */
}

/* Calculate ratelaws */
void
calc_ratelaws ( N_Vector ratelaws, N_Vector species, N_Vector expressions, N_Vector observables )
{
    NV_Ith_S(ratelaws,0) = rate()*NV_Ith_S(species,0);
}


/* Calculate species derivatives */
int
calc_species_deriv ( realtype time, N_Vector species, N_Vector Dspecies, void * f_data )
{
    int         return_val;
    N_Vector *  temp_data;

    N_Vector    expressions;
    N_Vector    observables;
    N_Vector    ratelaws;

    /* cast temp_data */
    temp_data = (N_Vector*)f_data;

    /* sget ratelaws Vector */
    expressions = temp_data[0];
    observables = temp_data[1];
    ratelaws    = temp_data[2];

    /* calculate observables */
    calc_observables( observables, species, expressions );

    /* calculate ratelaws */
    calc_ratelaws( ratelaws, species, expressions, observables );

    /* calculate derivatives */
    NV_Ith_S(Dspecies,0) = -NV_Ith_S(ratelaws,0);
    NV_Ith_S(Dspecies,1) = NV_Ith_S(ratelaws,0);

    return(0);
}

/*  Check function return value...
 *   opt == 0 means SUNDIALS function allocates memory so check if
 *            returned NULL pointer
 *   opt == 1 means SUNDIALS function returns a flag so check if
 *            flag >= 0
 *   opt == 2 means function allocates memory so check if returned
 *            NULL pointer
 */
int check_flag(void *flagvalue, char *funcname, int opt)
{
    int *errflag;

    /* Check if SUNDIALS function returned NULL pointer - no memory allocated */
    if (opt == 0 && flagvalue == NULL)
    {
        cout << "\nSUNDIALS_ERROR: " << funcname << "() failed - returned NULL pointer" << endl;
        return(1);
    }

    /* Check if flag < 0 */
    else if (opt == 1)
    {
        errflag = (int *) flagvalue;
        if (*errflag < 0)
        {
            cout << "\nSUNDIALS_ERROR: " << funcname << "() failed with flag = " << errflag << endl;
            return(1);
        }
    }

    /* Check if function returned NULL pointer - no memory allocated */
    else if (opt == 2 && flagvalue == NULL)
    {
        cout << "\nMEMORY_ERROR: " << funcname << "() failed - returned NULL pointer" << endl;
        return(1);
    }

    return(0);
}

/*
**   ========
**   result structure
**   ========
*/

struct Result {
    int status;
    vector< vector<double> > species;
    vector< vector<double> > observables;
};

/*
**   ========
**   main simulate command
**   ========
*/
Result simulate( vector<double> timepoints, vector<double> species_init, vector<double> parameters)
{
    int       n_timepoints;
    size_t    i;
    size_t    j;

    /* intermediate data vectors */
    N_Vector  expressions;
    N_Vector  observables;
    N_Vector  ratelaws;

    /* array to hold pointers to data vectors */
    N_Vector  temp_data[3];

    /* CVODE specific variables */
    realtype  reltol;
    realtype  abstol;
    realtype  time;
    N_Vector  species;
    void *    cvode_mem;
    int       flag;

    /* make sure timepoints has correct dimensions */
    if ( (timepoints.size() < 2) )
    {  cout << "TIMEPOINTS must be a vector with 2 or more elements." <<endl;  }

    /* make sure species_init has correct dimensions */
    if ( (species_init.size() != __N_SPECIES__) )
    {  cout << "SPECIES_INIT must be a vector with 2 elements." << endl;  }

    /* make sure params has correct dimensions */
    if ( (parameters.size() != __N_PARAMETERS__) )
    {  cout << "PARAMS must be a column vector with 4 elements." << endl;  }

    /* get number of timepoints */
    n_timepoints = timepoints.size();

    /* Create output arrays */
    int return_status;
    vector< vector<double> > species_out( __N_SPECIES__ , vector<double> (n_timepoints, 0));
    vector< vector<double> > observables_out( __N_OBSERVABLES__ , vector<double> (n_timepoints, 0));

    double * ptr_parameters = &parameters[0];
    double * ptr_timepoints = &timepoints[0];
    double * ptr_species_init = &species_init[0];

    /* initialize intermediate data vectors */
    expressions  = NULL;
    expressions = N_VNew_Serial(__N_EXPRESSIONS__);
    if (check_flag((void *)expressions, "N_VNew_Serial", 0))
    {
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }

    observables = NULL;
    observables = N_VNew_Serial(__N_OBSERVABLES__);
    if (check_flag((void *)observables, "N_VNew_Serial", 0))
    {
        N_VDestroy_Serial(expressions);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }

    ratelaws    = NULL;
    ratelaws = N_VNew_Serial(__N_RATELAWS__);
    if (check_flag((void *)ratelaws, "N_VNew_Serial", 0))
    {
        N_VDestroy_Serial(expressions);
        N_VDestroy_Serial(observables);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }

    /* set up pointers to intermediate data vectors */
    temp_data[0] = expressions;
    temp_data[1] = observables;
    temp_data[2] = ratelaws;

    /* calculate expressions (expressions are constant, so only do this once!) */
    calc_expressions( expressions, ptr_parameters );

    /* SOLVE model equations! */
    species   = NULL;
    cvode_mem = NULL;

    /* Set the scalar relative tolerance */
    reltol = 1.000000e-08;
    abstol = 1.000000e-09;

    /* Create serial vector for Species */
    species = N_VNew_Serial(__N_SPECIES__);
    if (check_flag((void *)species, "N_VNew_Serial", 0))
    {
        N_VDestroy_Serial(expressions);
        N_VDestroy_Serial(observables);
        N_VDestroy_Serial(ratelaws);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }
    for ( i = 0; i < __N_SPECIES__; i++ )
    {   NV_Ith_S(species,i) = species_init[i];   }

    /* write initial species populations into species_out */
    for ( i = 0; i < __N_SPECIES__; i++ )
    {   species_out[i][0] = species_init[i];   }

    /* write initial observables populations into species_out */
    calc_observables( observables, species, expressions );
    for ( i = 0; i < __N_OBSERVABLES__; i++ )
    {   observables_out[i][0] = NV_Ith_S(observables,i);   }

    /*   Call CVodeCreate to create the solver memory:
     *   CV_ADAMS or CV_BDF is the linear multistep method
     *   CV_FUNCTIONAL or CV_NEWTON is the nonlinear solver iteration
     *   A pointer to the integrator problem memory is returned and stored in cvode_mem.
     */
    cvode_mem = CVodeCreate(CV_BDF, CV_NEWTON);
    if (check_flag((void *)cvode_mem, "CVodeCreate", 0))
    {
        N_VDestroy_Serial(expressions);
        N_VDestroy_Serial(observables);
        N_VDestroy_Serial(ratelaws);
        N_VDestroy_Serial(species);
        CVodeFree(&cvode_mem);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }


    /*   Call CVodeInit to initialize the integrator memory:
     *   cvode_mem is the pointer to the integrator memory returned by CVodeCreate
     *   rhs_func  is the user's right hand side function in y'=f(t,y)
     *   T0        is the initial time
     *   y         is the initial dependent variable vector
     */
    flag = CVodeInit(cvode_mem, calc_species_deriv, timepoints[0], species);
    if (check_flag(&flag, "CVodeInit", 1))
    {
        N_VDestroy_Serial(expressions);
        N_VDestroy_Serial(observables);
        N_VDestroy_Serial(ratelaws);
        N_VDestroy_Serial(species);
        CVodeFree(&cvode_mem);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }

    /* Set scalar relative and absolute tolerances */
    flag = CVodeSStolerances(cvode_mem, reltol, abstol);
    if (check_flag(&flag, "CVodeSStolerances", 1))
    {
        N_VDestroy_Serial(expressions);
        N_VDestroy_Serial(observables);
        N_VDestroy_Serial(ratelaws);
        N_VDestroy_Serial(species);
        CVodeFree(&cvode_mem);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }

    /* pass params to rhs_func */
    flag = CVodeSetUserData(cvode_mem, &temp_data);
    if (check_flag(&flag, "CVodeSetFdata", 1))
    {
        N_VDestroy_Serial(expressions);
        N_VDestroy_Serial(observables);
        N_VDestroy_Serial(ratelaws);
        N_VDestroy_Serial(species);
        CVodeFree(&cvode_mem);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }

    /* select linear solver */
    flag = CVDense(cvode_mem, __N_SPECIES__);
    if (check_flag(&flag, "CVDense", 1))
    {
        N_VDestroy_Serial(expressions);
        N_VDestroy_Serial(observables);
        N_VDestroy_Serial(ratelaws);
        N_VDestroy_Serial(species);
        CVodeFree(&cvode_mem);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }

    flag = CVodeSetMaxNumSteps(cvode_mem, 2000);
    if (check_flag(&flag, "CVodeSetMaxNumSteps", 1))
    {
        N_VDestroy_Serial(expressions);
        N_VDestroy_Serial(observables);
        N_VDestroy_Serial(ratelaws);
        N_VDestroy_Serial(species);
        CVodeFree(&cvode_mem);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }

    flag = CVodeSetMaxErrTestFails(cvode_mem, 7);
    if (check_flag(&flag, "CVodeSetMaxErrTestFails", 1))
    {
        N_VDestroy_Serial(expressions);
        N_VDestroy_Serial(observables);
        N_VDestroy_Serial(ratelaws);
        N_VDestroy_Serial(species);
        CVodeFree(&cvode_mem);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }

    flag = CVodeSetMaxConvFails(cvode_mem, 10);
    if (check_flag(&flag, "CVodeSetMaxConvFails", 1))
    {
        N_VDestroy_Serial(expressions);
        N_VDestroy_Serial(observables);
        N_VDestroy_Serial(ratelaws);
        N_VDestroy_Serial(species);
        CVodeFree(&cvode_mem);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }

    flag = CVodeSetMaxStep(cvode_mem, 0);
    if (check_flag(&flag, "CVodeSetMaxStep", 1))
    {
        N_VDestroy_Serial(expressions);
        N_VDestroy_Serial(observables);
        N_VDestroy_Serial(ratelaws);
        N_VDestroy_Serial(species);
        CVodeFree(&cvode_mem);
        return_status = 1;
        return Result {return_status, species_out, observables_out};
    }

    /* integrate to each timepoint */
    for ( i=1;  i < n_timepoints;  i++ )
    {
        flag = CVode(cvode_mem, timepoints[i], species, &time, CV_NORMAL);
        if (check_flag(&flag, "CVode", 1))
        {
            N_VDestroy_Serial(expressions);
            N_VDestroy_Serial(observables);
            N_VDestroy_Serial(ratelaws);
            N_VDestroy_Serial(species);
            CVodeFree(&cvode_mem);
            return_status = 1;
            return Result {return_status, species_out, observables_out} ;
        }

        /* copy species output from nvector to output array */
        for ( j = 0; j < __N_SPECIES__; j++ )
        {   species_out[j][i] = NV_Ith_S(species,j);   }

        /* copy observables output from nvector to output array */
        calc_observables( observables, species, expressions );
        for ( j = 0; j < __N_OBSERVABLES__; j++ )
        {   observables_out[j][i] = NV_Ith_S(observables,j);   }
    }

    /* Free vectors */
    N_VDestroy_Serial(expressions);
    N_VDestroy_Serial(observables);
    N_VDestroy_Serial(ratelaws);
    N_VDestroy_Serial(species);

    /* Free integrator memory */
    CVodeFree(&cvode_mem);

    /* return status, species and observables */
    return Result {return_status, species_out, observables_out};
}
