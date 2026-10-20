import copy
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ragleap_voice.coverage import COLUMNS, CoverageError, check_rows, load_rows  # noqa: E402
from ragleap_voice.manifest import load_manifest  # noqa: E402

REPO = ROOT.parents[1] if (ROOT.parents[1] / "benchmarks" / "voice").is_dir() else None
KNOWN = {e.name for e in load_manifest()[0]}
GOOD = dict.fromkeys(COLUMNS, "")
GOOD.update(language="sw", engine="whisper-large-v3", tier="2", metric="WER", value="10", ci_low="8", ci_high="12",
            test_set="t", n_clips="60", raw_committed="no", evidence="benchmarks/voice/README.md")


@pytest.mark.parametrize("name", ["stt", "tts"])
def test_shipped_files_follow_the_rules(name):
    rows = load_rows(ROOT / "coverage" / (name + ".csv"))
    assert rows
    assert check_rows(rows, KNOWN, REPO) == []


def test_good_row_passes():
    assert check_rows([GOOD], KNOWN) == []


def mutated(**kw):
    row = copy.deepcopy(GOOD)
    row.update(kw)
    return check_rows([row], KNOWN)


@pytest.mark.parametrize("kw,word", [
    ({"tier": "2", "evidence": ""}, "evidence"),
    ({"tier": "2", "value": ""}, "numeric value"),
    ({"tier": "2", "n_clips": "0"}, "n_clips"),
    ({"tier": "9"}, "tier"),
    ({"language": "Swahili"}, "language"),
    ({"engine": "made-up"}, "engine"),
    ({"engine": "candidate:"}, "engine"),
    ({"value": "50"}, "outside"),
    ({"raw_committed": "maybe"}, "raw_committed"),
])
def test_bad_rows_are_reported(kw, word):
    assert any(word in p for p in mutated(**kw))


def test_candidate_prefix_is_allowed():
    assert mutated(engine="candidate:some-model") == []


def test_tier_one_needs_no_evidence():
    assert mutated(tier="1", evidence="", value="", ci_low="", ci_high="", metric="", test_set="", n_clips="") == []


def test_duplicate_is_reported():
    assert any("duplicate" in p for p in check_rows([GOOD, dict(GOOD)], KNOWN))


def test_missing_evidence_file_is_reported(tmp_path):
    assert any("evidence file not found" in p for p in check_rows([GOOD], KNOWN, tmp_path))
    (tmp_path / "benchmarks" / "voice").mkdir(parents=True)
    (tmp_path / "benchmarks" / "voice" / "README.md").write_text("x", encoding="utf-8")
    assert check_rows([GOOD], KNOWN, tmp_path) == []


def test_wrong_columns_are_refused(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("language,engine\nsw,x\n", encoding="utf-8")
    with pytest.raises(CoverageError):
        load_rows(p)
