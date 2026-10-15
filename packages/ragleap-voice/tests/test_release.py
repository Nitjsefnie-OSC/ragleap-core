import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import ragleap_voice  # noqa: E402


def test_version_matches_pyproject():
    m = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert m and m.group(1) == ragleap_voice.__version__


def test_package_has_its_own_licence_file():
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").lstrip().startswith("MIT License")


def test_readme_links_are_absolute():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)]+)\)", text):
        assert target.startswith(("https://", "http://", "#")), target
