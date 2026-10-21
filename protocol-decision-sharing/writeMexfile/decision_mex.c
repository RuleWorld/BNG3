/*
**   _mex.c
**
**   MATLAB MEX implementation of BioNetGen model ''.
**
**   Compile in MATLAB with:
**     mex _mex.c
**
**   Usage in MATLAB:
**     [species_out, observables_out] = _mex(timepoints, species_init, parameters)
**
**   Uses a built-in RK4 integrator (no external solver dependencies).
*/

#include "mex.h"
#include <math.h>
#include <string.h>
#include <stdlib.h>

/* Problem Dimensions */
#define N_PARAMETERS   4
#define N_EXPRESSIONS  4
#define N_OBSERVABLES  2
#define N_RATELAWS     1
#define N_SPECIES      2

/* Calculate expressions */
static void calc_expressions(double *expressions, const double *parameters)
{
    expressions[0] = parameters[0];   /* k */
    expressions[1] = parameters[1];   /* kr */
    expressions[2] = parameters[2];   /* N */
    expressions[3] = parameters[3];   /* V */
}

/* Calculate observables */
static void calc_observables(double *observables, const double *species, const double *expressions)
{
    observables[0] = species[0];   /* A */
    observables[1] = species[1];   /* B */
}

/* Calculate ratelaws */
static void calc_ratelaws(double *ratelaws, const double *species, const double *expressions, const double *observables)
{
    ratelaws[0] = rate()*species[0];
}

/* Calculate species derivatives */
static void calc_species_deriv(double t, const double *species, double *dydt,
                               const double *expressions)
{
    double observables[N_OBSERVABLES];
    double ratelaws[N_RATELAWS];

    /* calculate observables */
    calc_observables(observables, species, expressions);

    /* calculate ratelaws */
    calc_ratelaws(ratelaws, species, expressions, observables);

    /* calculate derivatives */
    dydt[0] = -ratelaws[0];
    dydt[1] = ratelaws[0];
}

/* Built-in RK4 integrator */
static void rk4_step(double t, double dt, double *y, double *y_out,
                     int n, const double *expressions)
{
    int i;
    double *k1, *k2, *k3, *k4, *ytmp;

    k1   = (double *)mxMalloc(n * sizeof(double));
    k2   = (double *)mxMalloc(n * sizeof(double));
    k3   = (double *)mxMalloc(n * sizeof(double));
    k4   = (double *)mxMalloc(n * sizeof(double));
    ytmp = (double *)mxMalloc(n * sizeof(double));

    /* k1 */
    calc_species_deriv(t, y, k1, expressions);

    /* k2 */
    for (i = 0; i < n; i++) ytmp[i] = y[i] + 0.5 * dt * k1[i];
    calc_species_deriv(t + 0.5 * dt, ytmp, k2, expressions);

    /* k3 */
    for (i = 0; i < n; i++) ytmp[i] = y[i] + 0.5 * dt * k2[i];
    calc_species_deriv(t + 0.5 * dt, ytmp, k3, expressions);

    /* k4 */
    for (i = 0; i < n; i++) ytmp[i] = y[i] + dt * k3[i];
    calc_species_deriv(t + dt, ytmp, k4, expressions);

    /* combine */
    for (i = 0; i < n; i++)
        y_out[i] = y[i] + (dt / 6.0) * (k1[i] + 2.0*k2[i] + 2.0*k3[i] + k4[i]);

    mxFree(k1);
    mxFree(k2);
    mxFree(k3);
    mxFree(k4);
    mxFree(ytmp);
}

/* Adaptive RK4 driver: integrate from t0 to tf with sub-stepping */
static void integrate_rk4(double t0, double tf, double *y, int n,
                          const double *expressions, int max_steps)
{
    double dt = (tf - t0) / (double)max_steps;
    double t  = t0;
    double *y_new = (double *)mxMalloc(n * sizeof(double));
    int step;

    for (step = 0; step < max_steps; step++) {
        if (t + dt > tf) dt = tf - t;
        rk4_step(t, dt, y, y_new, n, expressions);
        memcpy(y, y_new, n * sizeof(double));
        t += dt;
        if (t >= tf) break;
    }

    mxFree(y_new);
}

/*
** Gateway function
**   [species_out, observables_out] = _mex(timepoints, species_init, parameters)
**
**   timepoints   : 1 x T or T x 1 double array
**   species_init : 1 x 2 or 2 x 1 double array
**   parameters   : 1 x 4 or 4 x 1 double array
**
**   species_out     : 2 x T double array
**   observables_out : 2 x T double array
*/
void mexFunction(int nlhs, mxArray *plhs[], int nrhs, const mxArray *prhs[])
{
    int i, j, n_timepoints, n_substeps;
    double *timepoints, *species_init, *parameters;
    double *species_out, *observables_out;
    double *y;
    double expressions[N_EXPRESSIONS];
    double observables[N_OBSERVABLES];

    /* Validate inputs */
    if (nrhs < 3)
        mexErrMsgTxt("Three inputs required: timepoints, species_init, parameters.");
    if (nlhs > 2)
        mexErrMsgTxt("Too many output arguments (max 2).");

    /* Get input pointers */
    timepoints   = mxGetPr(prhs[0]);
    species_init = mxGetPr(prhs[1]);
    parameters   = mxGetPr(prhs[2]);

    n_timepoints = (int)mxGetNumberOfElements(prhs[0]);

    /* Validate dimensions */
    if (mxGetNumberOfElements(prhs[1]) != N_SPECIES)
        mexErrMsgTxt("species_init must have 2 elements.");
    if (mxGetNumberOfElements(prhs[2]) != N_PARAMETERS)
        mexErrMsgTxt("parameters must have 4 elements.");
    if (n_timepoints < 2)
        mexErrMsgTxt("timepoints must have at least 2 elements.");

    /* Create output arrays */
    plhs[0] = mxCreateDoubleMatrix(N_SPECIES, n_timepoints, mxREAL);
    species_out = mxGetPr(plhs[0]);
    if (nlhs > 1) {
        plhs[1] = mxCreateDoubleMatrix(N_OBSERVABLES, n_timepoints, mxREAL);
        observables_out = mxGetPr(plhs[1]);
    } else {
        observables_out = NULL;
    }

    /* Calculate expressions (constant, do once) */
    calc_expressions(expressions, parameters);

    /* Copy initial conditions */
    y = (double *)mxMalloc(N_SPECIES * sizeof(double));
    for (i = 0; i < N_SPECIES; i++) y[i] = species_init[i];

    /* Store initial state */
    for (i = 0; i < N_SPECIES; i++)
        species_out[i] = y[i];  /* column 0 */
    if (observables_out) {
        calc_observables(observables, y, expressions);
        for (i = 0; i < N_OBSERVABLES; i++)
            observables_out[i] = observables[i];
    }

    /* Number of RK4 sub-steps per output interval */
    n_substeps = 2000;

    /* Integrate to each timepoint */
    for (j = 1; j < n_timepoints; j++) {
        integrate_rk4(timepoints[j-1], timepoints[j], y, N_SPECIES,
                      expressions, n_substeps);

        /* Store species (column-major: row i, col j -> index j*N_SPECIES + i) */
        for (i = 0; i < N_SPECIES; i++)
            species_out[j * N_SPECIES + i] = y[i];

        /* Store observables */
        if (observables_out) {
            calc_observables(observables, y, expressions);
            for (i = 0; i < N_OBSERVABLES; i++)
                observables_out[j * N_OBSERVABLES + i] = observables[i];
        }
    }

    mxFree(y);
}
