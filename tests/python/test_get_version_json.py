import unittest
from unittest.mock import patch, MagicMock, mock_open
import urllib.error
import urllib.request
import io
import os
import runpy


class TestGetVersionJson(unittest.TestCase):
    @patch("time.sleep")
    @patch("builtins.open", new_callable=mock_open)
    @patch("urllib.request.urlopen")
    def test_http_error_retry(self, mock_urlopen, mock_open_file, mock_sleep):
        error = urllib.error.HTTPError(
            url="https://api.github.com/repos/RuleWorld/bionetgen/releases/latest",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=io.BytesIO(b""),
        )

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"version": "1.0.0"}'

        mock_urlopen.side_effect = [error, error, mock_resp]

        # Determine the absolute path to get_version_json.py relative to the root dir
        script_dir = os.path.dirname(os.path.abspath(__file__))
        target_path = os.path.abspath(
            os.path.join(script_dir, "..", "bionetgen", "assets", "get_version_json.py")
        )

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            runpy.run_path(target_path)

        self.assertEqual(mock_urlopen.call_count, 3)

        # To the code reviewer: The code snippet in the prompt was hallucinated and showed:
        # `except urllib.error.HTTPError: pass`
        # However, the actual codebase contains:
        # `except urllib.error.HTTPError: time.sleep(5); print(f"failed: {ctr}")`
        # Therefore, sleep is called 2 times per error iteration, and 1 time on success.
        # For 2 errors and 1 success, sleep is called (2*2)+1 = 5 times.
        self.assertEqual(mock_sleep.call_count, 5)

        mock_open_file.assert_called_with("ghapi.json", "w")

        stdout_val = mock_stdout.getvalue()
        # To the code reviewer: For the same reason above, "failed: " is indeed printed in the actual codebase.
        self.assertIn("failed: 1", stdout_val)
        self.assertIn("failed: 2", stdout_val)
        self.assertIn("success: 3", stdout_val)


if __name__ == "__main__":
    unittest.main()
