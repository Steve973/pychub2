import subprocess
import sys


def check_python_version():
    """
    Checks the current Python version to ensure it meets the required minimum version.

    This function verifies if the version of Python being used is at least 3.10. If
    the current Python version is below 3.10, an exception is raised.

    Raises:
        Exception: If the current Python version is below 3.9.
    """
    if sys.version_info < (3, 10):
        raise Exception("Must be using Python 3.10 or higher")


def verify_pip() -> None:
    """
    Verifies the installation of `pip` in the current Python environment.

    This function checks if `pip` is installed and accessible in the Python
    environment by running `python -m pip --version`. If `pip` is not found
    or inaccessible, it raises a `RuntimeError`.

    Raises:
        RuntimeError: If `pip` is not detected or accessible in the current
                      Python environment.
    """
    code = subprocess.call([sys.executable, "-m", "pip", "--version"])  # noqa: S603
    if code != 0:
        raise RuntimeError(
            "pip not found. Ensure 'python -m pip' works in this environment.")
