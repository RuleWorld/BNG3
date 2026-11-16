import ctypes
import os
import tempfile

import numpy as np

from .bngsimulator import BNGSimulator
from bionetgen.core.exc import (
    BNGCompileError,
    BNGFormatError,
    BNGSimError,
    BNGSimulatorError,
)
from bionetgen.core.utils.logging import BNGLogger


def _new_ccompiler():
    try:
        from setuptools._distutils import ccompiler
    except ImportError as exc:
        raise BNGCompileError(
            None,
            "CSimulator requires setuptools to provide the distutils ccompiler API.",
        ) from exc
    return ccompiler.new_compiler()


logger = BNGLogger()


class RESULT(ctypes.Structure):
    _fields_ = [
        ("status", ctypes.c_int),
        ("n_observables", ctypes.c_int),
        ("n_species", ctypes.c_int),
        ("n_tpts", ctypes.c_int),
        ("obs_name_len", ctypes.c_int),
        ("spcs_name_len", ctypes.c_int),
        ("observables", ctypes.POINTER(ctypes.c_double)),
        ("species", ctypes.POINTER(ctypes.c_double)),
        ("obs_names", ctypes.POINTER(ctypes.c_char)),
        ("spcs_names", ctypes.POINTER(ctypes.c_char)),
    ]


class CSimWrapper:
    def __init__(self, lib_path, num_params=None, num_spec_init=None):
        self.logger = BNGLogger()
        self.return_struct = RESULT
        self.lib = ctypes.CDLL(lib_path)
        self.lib.simulate.restype = ctypes.c_void_p
        self.num_params = num_params
        self.num_spec_init = num_spec_init

    def set_species_init(self, arr):
        if len(arr) != self.num_spec_init:
            raise BNGSimulatorError(
                f"Expected {self.num_spec_init} initial species, but got {len(arr)}"
            )
        self.species_init = np.array(arr, dtype=np.float64)

    def set_parameters(self, arr):
        if len(arr) != self.num_params:
            raise BNGSimulatorError(
                f"Expected {self.num_params} parameters, but got {len(arr)}"
            )
        self.parameters = np.array(arr, dtype=np.float64)

    def simulate(self, t_start=0, t_end=100, n_steps=100):
        del_t = (t_end - t_start) / float(n_steps)
        timepoints = np.arange(t_start, t_end + 1, del_t)
        ntpts = len(timepoints)
        self.result = self.return_struct.from_address(
            self.lib.simulate(
                ntpts,
                ctypes.c_void_p(timepoints.ctypes.data),
                self.num_spec_init,
                ctypes.c_void_p(self.species_init.ctypes.data),
                self.num_params,
                ctypes.c_void_p(self.parameters.ctypes.data),
            )
        )
        obs_names = ctypes.cast(
            self.result.obs_names,
            ctypes.POINTER(ctypes.c_char * self.result.obs_name_len),
        )[0].value.decode()
        obs_names = obs_names.split("/")[:-1]
        spcs_names = ctypes.cast(
            self.result.spcs_names,
            ctypes.POINTER(ctypes.c_char * self.result.spcs_name_len),
        )[0].value.decode()
        spcs_names = spcs_names.split("/")[:-1]
        buffer_as_ctypes_arr_obs = ctypes.cast(
            self.result.observables,
            ctypes.POINTER(ctypes.c_double * ntpts * self.result.n_observables),
        )[0]
        observables = np.frombuffer(buffer_as_ctypes_arr_obs, np.float64)
        fmt = ["f8"] * len(obs_names)
        obs_all = np.reshape(observables, (self.result.n_observables, ntpts))
        obs_all = np.core.records.fromarrays(obs_all, names=obs_names, formats=fmt)
        buffer_as_ctypes_arr_spc = ctypes.cast(
            self.result.species,
            ctypes.POINTER(ctypes.c_double * ntpts * self.result.n_species),
        )[0]
        species = np.frombuffer(buffer_as_ctypes_arr_spc, np.float64)
        fmt = ["f8"] * len(spcs_names)
        spcs_all = np.reshape(species, (self.result.n_species, ntpts))
        spcs_all = np.core.records.fromarrays(spcs_all, names=spcs_names, formats=fmt)
        self.lib.free_result(ctypes.byref(self.result))
        del self.result
        return (timepoints, obs_all, spcs_all)


class CSimulator(BNGSimulator):
    def __init__(self, model_input, generate_network=False):
        try:
            import bionetgen
            from bionetgen.core.defaults import BNGDefaults
        except Exception as exc:
            raise BNGCompileError(
                None, f"CSimulator unavailable in this environment: {exc}"
            ) from exc
        try:
            conf = BNGDefaults().config.get("bionetgen", {})
        except Exception:
            conf = {}
        if isinstance(model_input, str):
            self.model = bionetgen.bngmodel(
                model_input, generate_network=generate_network
            )
        elif isinstance(model_input, bionetgen.bngmodel):
            self.model = model_input
            cd = os.getcwd()
            import shutil

            tmpdirname = tempfile.mkdtemp(prefix="bngsim_")
            try:
                os.chdir(tmpdirname)
                self.model.actions.clear_actions()
                copy_label = getattr(self.model, "model_" + "name", "model")
                self.model.write_model(f"{copy_label}_cpy.bngl")
                self.model = bionetgen.bngmodel(
                    f"{copy_label}_cpy.bngl", generate_network=generate_network
                )
            finally:
                os.chdir(cd)
                try:
                    shutil.rmtree(tmpdirname)
                except Exception:
                    pass
        else:
            raise BNGFormatError(
                message=f"CSimulator model input must be a BNGL path or bngmodel instance, got {type(model_input).__name__}"
            )
        self.compiler = _new_ccompiler()
        cvode_include = conf.get("cvode_include") if hasattr(conf, "get") else None
        cvode_lib = conf.get("cvode_lib") if hasattr(conf, "get") else None
        if cvode_include:
            self.compiler.add_include_dir(cvode_include)
        if cvode_lib:
            self.compiler.add_library_dir(cvode_lib)
        self.compile_shared_lib()
        self.simulator = self.lib_file

    def compile_shared_lib(self):
        raise BNGCompileError(
            self.model,
            "CSimulator compilation is not supported in BNG3's native environment",
        )

    @property
    def simulator(self):
        return self._simulator

    @simulator.setter
    def simulator(self, lib_file):
        raise BNGCompileError(
            self.model, "CSimulator is not supported in BNG3's native environment"
        )

    def simulate(self, t_start=0, t_end=10, n_steps=10):
        raise BNGSimError(
            "CSimulator simulation is not supported in BNG3's native environment"
        )
