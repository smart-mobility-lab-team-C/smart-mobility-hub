"""Check package Python style through the colcon pytest runner."""
from pathlib import Path

from ament_flake8.main import main_with_errors
from ament_pep257.main import main as pep257


def test_flake8():
    """Validate all Python source in this package."""
    code, errors = main_with_errors(argv=[str(Path(__file__).resolve().parents[1])])
    assert code == 0, '\n'.join(errors)


def test_pep257():
    """Validate package docstrings."""
    assert pep257(argv=[str(Path(__file__).resolve().parents[1])]) == 0
