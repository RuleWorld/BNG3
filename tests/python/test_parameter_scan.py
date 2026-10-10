from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
import sys

import numpy as np
import pytest

pytest.importorskip("bionetgen._bionetgen_cpp")

import bionetgen
import bionetgen.scan as scan


def _write_decay_model(path):
    path.write_text("""
begin model
begin parameters
    k 0.1
    X0 100
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() X0
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")


def test_parameter_scan_1d_and_dataframe(tmp_path):
    model_path = tmp_path / "decay.bngl"
    _write_decay_model(model_path)

    model = bionetgen.load(str(model_path))
    scan = model.parameter_scan(
        parameter="k",
        values=np.array([0.01, 0.1, 0.2]),
        method="ode",
        t_end=20,
        n_steps=40,
    )

    final = scan.final("Xtot")
    assert final.shape == (3,)
    assert final[0] > final[-1]
    assert scan.at_time(10.0, "Xtot").shape == (3,)

    pandas = pytest.importorskip("pandas")
    frame = scan.to_dataframe()
    assert isinstance(frame, pandas.DataFrame)
    assert set(["k", "time", "Xtot"]).issubset(frame.columns)


def test_parameter_scan_log_and_linear_spacing(tmp_path):
    model_path = tmp_path / "decay.bngl"
    _write_decay_model(model_path)
    model = bionetgen.load(str(model_path))

    log_scan = model.parameter_scan(
        parameter="k", min=1e-2, max=1e2, n_points=4, log_scale=True
    )
    assert np.allclose(log_scan.parameter_values, np.logspace(-2, 2, 4))

    lin_scan = model.parameter_scan(
        parameter="k", min=0.0, max=1.0, n_points=5, log_scale=False
    )
    assert np.allclose(lin_scan.parameter_values, np.linspace(0.0, 1.0, 5))


def test_seed_parameter_override_does_not_reuse_stale_network(tmp_path):
    model_path = tmp_path / "decay.bngl"
    _write_decay_model(model_path)
    model = bionetgen.load(str(model_path))
    original_network = model.generate_network()

    model.set_parameter("X0", 250.0)
    assert model.get_parameter("X0").value == pytest.approx(250.0)
    result = model.simulate(method="ode", t_end=1.0, n_steps=2, sample_times=[0.0, 1.0])

    assert result.observables["Xtot"][0] == pytest.approx(250.0)
    assert model._network is not original_network


def test_parameter_override_recomputes_dependent_parameter_values(tmp_path):
    model_path = tmp_path / "dependent_decay.bngl"
    model_path.write_text("""
begin model
begin parameters
    k 0.1
    k2 2*k
    X0 100
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() X0
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k2
end reaction rules
end model
""")
    model = bionetgen.load(str(model_path))
    assert model.get_parameter("k2").value == pytest.approx(0.2)

    model.set_parameter("k", 0.3)
    assert model.get_parameter("k2").value == pytest.approx(0.6)
    result = model.simulate(method="ode", t_end=2.0, n_steps=2, sample_times=[0.0, 2.0])
    assert result.observables["Xtot"][1] == pytest.approx(
        100.0 * np.exp(-1.2), rel=1e-6
    )


def test_parallel_scan_workers_match_fresh_analytic_trajectories(tmp_path):
    model_path = tmp_path / "decay.bngl"
    _write_decay_model(model_path)
    model = bionetgen.load(str(model_path))
    original_network = model.generate_network()
    original_k = model.get_parameter("k").value
    values = [0.01, 0.1, 0.2]
    options = dict(method="ode", t_end=5.0, n_steps=25)

    serial = model.parameter_scan(parameter="k", values=values, **options)
    expected_identity = scan._scan_runtime_identity()
    wrong_native_identity = dict(expected_identity)
    wrong_native_identity["native"] = expected_identity["native"] + ".other"
    with pytest.raises(RuntimeError, match="already loaded a different BNG3 native"):
        scan._initialize_scan_worker(wrong_native_identity)

    source_python = str(Path(__file__).resolve().parents[2] / "python")
    original_sys_path = sys.path[:]
    # Simulate a second checkout shadowing the installed wheel in a spawned
    # worker. The worker must rebind both Python modules and the native module
    # to the exact files loaded by this parent process.
    sys.path.insert(0, source_python)
    try:
        with ProcessPoolExecutor(
            max_workers=1,
            initializer=scan._initialize_scan_worker,
            initargs=(expected_identity,),
        ) as executor:
            worker_identity = executor.submit(scan._scan_runtime_identity).result()
        parallel = model.parameter_scan(
            parameter="k", values=values, parallel=2, **options
        )
    finally:
        sys.path[:] = original_sys_path
    expected = 100.0 * np.exp(-np.asarray(values) * options["t_end"])

    assert worker_identity == expected_identity
    np.testing.assert_allclose(serial.final("Xtot"), expected, rtol=1e-6, atol=1e-8)
    np.testing.assert_allclose(parallel.final("Xtot"), expected, rtol=1e-6, atol=1e-8)
    np.testing.assert_allclose(
        parallel.final("Xtot"), serial.final("Xtot"), rtol=1e-12, atol=1e-12
    )
    assert model.get_parameter("k").value == pytest.approx(original_k)
    assert model._network is original_network


def test_concurrent_ssa_runs_reuse_network_without_sharing_rng_state(tmp_path):
    model_path = tmp_path / "ssa_decay.bngl"
    model_path.write_text("""
begin model
begin parameters
    k 0.5
    X0 1000
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() X0
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k
end reaction rules
end model
""")
    model = bionetgen.load(str(model_path))
    network = model.generate_network()
    kwargs = dict(method="ssa", t_end=4.0, n_steps=40)
    seeds = [17, 29]
    serial = [model.simulate(seed=seed, **kwargs) for seed in seeds]

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent = list(
            executor.map(lambda seed: model.simulate(seed=seed, **kwargs), seeds)
        )

    assert model._network is network
    for expected, observed in zip(serial, concurrent):
        np.testing.assert_array_equal(observed.concentrations, expected.concentrations)
    assert not np.array_equal(serial[0].concentrations, serial[1].concentrations)


def test_failed_serial_scan_restores_parameters_and_network(tmp_path):
    model_path = tmp_path / "dependent_decay.bngl"
    model_path.write_text("""
begin model
begin parameters
    k 0.1
    k2 2*k
    X0 100
end parameters
begin molecule types
    X()
end molecule types
begin seed species
    X() X0
end seed species
begin observables
    Molecules Xtot X()
end observables
begin reaction rules
    X() -> 0 k2
end reaction rules
end model
""")
    model = bionetgen.load(str(model_path))
    original_network = model.generate_network()
    original_k = model.get_parameter("k").value
    original_k2 = model.get_parameter("k2").value

    with pytest.raises(RuntimeError, match="Failed to evaluate stop_if expression"):
        model.parameter_scan(
            parameter="k",
            values=[0.25],
            method="ode",
            t_end=1.0,
            n_steps=2,
            stop_if="missing > 0",
        )

    assert model.get_parameter("k").value == pytest.approx(original_k)
    assert model.get_parameter("k2").value == pytest.approx(original_k2)
    assert model._network is original_network

    options = dict(t_end=2.0, n_steps=4, sample_times=[0.0, 1.0, 2.0])
    recovered = model.simulate(method="ode", **options)
    fresh = bionetgen.load(str(model_path)).simulate(method="ode", **options)
    expected = 100.0 * np.exp(-original_k2 * np.asarray(options["sample_times"]))
    np.testing.assert_allclose(
        recovered.observables["Xtot"], expected, rtol=1e-6, atol=1e-8
    )
    np.testing.assert_allclose(
        recovered.observables["Xtot"],
        fresh.observables["Xtot"],
        rtol=1e-12,
        atol=1e-12,
    )


def test_concurrent_ode_instances_reuse_network_with_independent_parameters(tmp_path):
    model_path = tmp_path / "ode_decay.bngl"
    _write_decay_model(model_path)
    topology_model = bionetgen.load(str(model_path))
    shared_network = topology_model.generate_network()

    rates = [0.07, 0.31]
    models = [bionetgen.load(str(model_path)) for _ in rates]
    for model, rate in zip(models, rates):
        model.set_parameter("k", rate)
        # A rate-only override does not change this generated topology. Each
        # model snapshot gets its own OdeIntegrator while sharing the network.
        model._network = shared_network

    options = dict(
        method="ode",
        t_end=12.0,
        n_steps=120,
        sample_times=[0.0, 0.3, 1.0, 4.0, 12.0],
    )
    serial = [model.simulate(**options) for model in models]

    with ThreadPoolExecutor(max_workers=len(models)) as executor:
        concurrent = list(executor.map(lambda model: model.simulate(**options), models))

    expected_times = options["sample_times"]
    for model, rate, expected_result, observed_result in zip(
        models, rates, serial, concurrent
    ):
        assert model._network is shared_network
        np.testing.assert_allclose(
            observed_result.observables["Xtot"],
            expected_result.observables["Xtot"],
            rtol=1e-12,
            atol=1e-12,
        )
        np.testing.assert_allclose(
            observed_result.observables["Xtot"],
            100.0 * np.exp(-rate * np.asarray(expected_times)),
            rtol=1e-6,
            atol=1e-8,
        )


def test_parameter_scan_forwards_advanced_simulation_controls(tmp_path):
    model_path = tmp_path / "decay.bngl"
    _write_decay_model(model_path)
    model = bionetgen.load(str(model_path))

    scan = model.parameter_scan(
        parameter="k",
        values=[0.1],
        method="ode",
        t_end=1.0,
        n_steps=0,
        sample_times=[0.0, 0.25, 1.0],
        max_step=0.1,
        stop_if="Xtot < 0",
        sparse=False,
        check_product_scale=1000.0,
    )

    assert scan.results[0].time.tolist() == [0.0, 0.25, 1.0]


def test_parameter_scan_2d_shape_and_standalone(tmp_path):
    model_path = tmp_path / "decay.bngl"
    _write_decay_model(model_path)

    scan = bionetgen.parameter_scan(
        str(model_path),
        parameter="k",
        values=[0.01, 0.05, 0.1],
        method="ode",
        t_end=10,
        n_steps=20,
    )
    assert scan.final("Xtot").shape == (3,)

    model = bionetgen.load(str(model_path))
    scan2d = model.parameter_scan_2d(
        parameter1="k",
        values1=[0.01, 0.1],
        parameter2="X0",
        values2=[50, 100, 150],
        method="ode",
        t_end=10,
        n_steps=20,
        parallel=2,
    )

    assert scan2d.final("Xtot").shape == (2, 3)
    assert scan2d.at_time(5.0, "Xtot").shape == (2, 3)

    pandas = pytest.importorskip("pandas")
    frame = scan2d.to_dataframe()
    assert isinstance(frame, pandas.DataFrame)
    assert set(["k", "X0", "time", "Xtot"]).issubset(frame.columns)


def test_parameter_scan_rejects_invalid_inputs(tmp_path):
    model_path = tmp_path / "decay.bngl"
    _write_decay_model(model_path)
    model = bionetgen.load(str(model_path))

    with pytest.raises(ValueError, match="Unknown parameter"):
        model.parameter_scan(parameter="missing", values=[1.0])
    with pytest.raises(ValueError, match="positive"):
        model.parameter_scan(parameter="k", min=0.0, max=1.0, n_points=0)
    with pytest.raises(ValueError, match="positive"):
        model.parameter_scan(
            parameter="k", min=0.0, max=1.0, n_points=3, log_scale=True
        )
    with pytest.raises(ValueError, match="must not be empty"):
        model.parameter_scan(parameter="k", values=[])
