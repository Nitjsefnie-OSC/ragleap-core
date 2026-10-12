import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ragleap_voice import _toml  # noqa: E402

SAMPLE = r'''
# comment
top = 3
[[model]]
name = "a#b"   # trailing comment
url = "https://x.example/p?q=1#frag"
quote = "say \"hi\""
flag = true
off = false
n = -7
langs = ["hi", "ta", ]
empty = []
[[model]]
name = "second"
'''


def test_subset_parses_sample():
    data = _toml._loads_subset(SAMPLE)
    assert data["top"] == 3
    first, second = data["model"]
    assert first == {"name": "a#b", "url": "https://x.example/p?q=1#frag", "quote": 'say "hi"',
                     "flag": True, "off": False, "n": -7, "langs": ["hi", "ta"], "empty": []}
    assert second == {"name": "second"}


def test_subset_matches_tomllib_on_sample():
    tomllib = pytest.importorskip("tomllib")
    assert _toml._loads_subset(SAMPLE) == tomllib.loads(SAMPLE)


def test_real_manifest_parses_and_matches_tomllib():
    text = (ROOT / "models.toml").read_text(encoding="utf-8")
    data = _toml._loads_subset(text)
    assert len(data["model"]) >= 4
    assert _toml.loads(text) == data
    tomllib = pytest.importorskip("tomllib")
    assert tomllib.loads(text) == data


@pytest.mark.parametrize("text", [
    "[table]\n", "[[a.b]]\n", "x = 1.5\n", "x = 'lit'\n", 'x = """a"""\n', "x = {a = 1}\n",
    "x = [1, 2]\n", 'x = ["a"\n', 'x = "abc\n', 'x = "a" junk\n', "a.b = 1\n", "x = 1\nx = 2\n",
    'x = "bad \\q"\n', "no equals sign\n",
])
def test_subset_rejects_unsupported_syntax(text):
    with pytest.raises(ValueError):
        _toml._loads_subset(text)
