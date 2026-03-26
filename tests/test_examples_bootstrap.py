import subprocess
import sys
from pathlib import Path


def test_examples_bootstrap_runs_successfully() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, str(repo_root / "examples" / "bootstrap.py")],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Registered tools:" in result.stdout
    assert "Registered workers:" in result.stdout
