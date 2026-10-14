"""Scaffold boundaries only; no application acceptance or provider evaluation."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class PackageScaffoldTests(unittest.TestCase):
    def invoke(self, source: Path, cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        # Explicitly avoid carrying provider keys or a workspace path into the detached process.
        environment = {"PYTHONPATH": str(source), "PYTHONIOENCODING": "utf-8"}
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            if name in os.environ:
                environment[name] = os.environ[name]
        return subprocess.run(
            [sys.executable, "-m", "content_strategy", *arguments],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_status_is_explicitly_unfinished_without_creating_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            cwd = Path(folder)
            result = self.invoke(REPO / "src", cwd, "--status-json")
            self.assertEqual(result.returncode, 0, result.stderr)
            status = json.loads(result.stdout)
            self.assertEqual(status["stage"], "contracts-only")
            self.assertFalse(status["schema_validation_is_authorization"])
            self.assertEqual(status["implemented_workflows"], [])
            self.assertFalse(status["provider_calls"])
            self.assertFalse(status["approval_export_available"])
            self.assertEqual(list(cwd.iterdir()), [])

    def test_detached_package_import_has_no_workspace_or_test_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            cwd = Path(folder)
            source = cwd / "detached source"
            shutil.copytree(REPO / "src", source)
            result = self.invoke(source, cwd, "--status-json")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["implemented_workflows"], [])

    def test_unimplemented_workflow_is_rejected_instead_of_faked(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke(REPO / "src", Path(folder), "export", "--approve")
            self.assertEqual(result.returncode, 2)
            self.assertIn("unrecognized arguments", result.stderr)
            self.assertNotIn("approved", result.stdout)

    def test_version_matches_package_metadata(self) -> None:
        import tomllib

        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke(REPO / "src", Path(folder), "--version")
        with (REPO / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), project["version"])


if __name__ == "__main__":
    unittest.main()
