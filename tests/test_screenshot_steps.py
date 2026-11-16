import pytest

from godot_common import SetupError
from screenshot import parse_steps


def test_parse_steps_ok():
    assert parse_steps(" click:Start ; wait:30;shot:menu; ") == ["click:Start", "wait:30", "shot:menu"]


@pytest.mark.parametrize("bad", ["jump:x", "wait:soon", "click:", "shot:has space", "hover"])
def test_parse_steps_rejects(bad):
    with pytest.raises(SetupError):
        parse_steps(bad)
