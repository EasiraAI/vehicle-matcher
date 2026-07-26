"""The CLI's output contract is part of the challenge spec: Input / Vehicle ID /
Confidence, blank line between results, one block per description."""

import re

import pytest

from vehicle_matcher import cli

pytestmark = pytest.mark.integration

BLOCK = re.compile(
    r"Input: (?P<input>.+)\nVehicle ID: (?P<id>\d+|null)\nConfidence: (?P<conf>\d+)\n"
)


def test_cli_output_format(db_conn, capsys, monkeypatch):
    monkeypatch.setenv("MATCHER_LLM_ENABLED", "false")
    exit_code = cli.main(["data/inputs.txt"])
    out = capsys.readouterr().out

    assert exit_code == 0
    blocks = BLOCK.findall(out)
    assert len(blocks) == 20
    for _text, vehicle_id, confidence in blocks:
        assert vehicle_id == "null" or vehicle_id.isdigit()
        assert 0 <= int(confidence) <= 10
    # blank line between result blocks
    assert "\n\n" in out
