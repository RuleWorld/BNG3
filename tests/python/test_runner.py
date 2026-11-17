"""modelapi runner delegation contract.

The legacy in-process/BNGCLI fallback was removed; ``run`` now delegates the
action workflow to ``bionetgen.compat.runner.run`` and keeps only an in-memory
single-simulation override path. These cases retain their historical IDs while
checking the current delegation surface instead of removed internals.
"""

from unittest.mock import patch, MagicMock

import pytest

from bionetgen.modelapi.runner import run


@patch("bionetgen.compat.runner.run", return_value="mock_result")
def test_runner_with_out(mock_compat_run):
    result = run("test.bngl", out="test_out", suppress=True, timeout=10)
    assert result == "mock_result"
    mock_compat_run.assert_called_once()
    kwargs = mock_compat_run.call_args.kwargs
    assert kwargs["out"] == "test_out"
    assert kwargs["suppress"] is True
    assert kwargs["timeout"] == 10


@patch("bionetgen.compat.runner.run", return_value="mock_result")
def test_runner_without_out(mock_compat_run):
    result = run("test.bngl", suppress=False, timeout=None)
    assert result == "mock_result"
    mock_compat_run.assert_called_once()
    kwargs = mock_compat_run.call_args.kwargs
    assert kwargs["out"] is None
    assert kwargs["suppress"] is False
    assert kwargs["timeout"] is None


@patch("bionetgen.compat.runner.run", side_effect=RuntimeError("Test Exception"))
def test_runner_exception(mock_compat_run):
    with pytest.raises(RuntimeError, match="Test Exception"):
        run("test.bngl", out="test_out")
    mock_compat_run.assert_called_once()


@patch("bionetgen.compat.runner.run", side_effect=RuntimeError("backend parse failure"))
def test_runner_does_not_fallback_after_cpp_failure(mock_compat_run):
    # No silent fallback: a compat runner failure propagates unchanged.
    with pytest.raises(RuntimeError, match="backend parse failure"):
        run("test.bngl", out="test_out")
    mock_compat_run.assert_called_once()
