"""The guard's refusal must carry the line that fixes it (T185)."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from integral import identity
from integral.identity import (
    _RESERVED_HANDLES,
    create_profile,
    hook_main,
    read_active_handle,
    write_active_handle,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)
GUARD = Path(__file__).resolve().parents[1] / "tools" / "profile_guard.sh"


def _payload(tool: str, tool_input: dict[str, str], session: str = "s1") -> str:
    return json.dumps({"session_id": session, "tool_name": tool, "tool_input": tool_input})


def _command_from(message: str) -> str:
    return message.split("): ", 1)[1].splitlines()[0]


def _guard(payload: str, home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(GUARD)],
        input=payload,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        env={**os.environ, "INTEGRAL_HOME": str(home)},
    )


def test_refusal_names_the_restore_command(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    ada = create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    target = root / ada.handle / "profile" / "evidence.jsonl"
    code, message = hook_main(_payload("Edit", {"file_path": str(target)}), root=root)
    assert code == 2
    words = shlex.split(_command_from(message))
    # runnable, not a spec reference: it names the session
    assert words[:4] == ["uv", "run", "python", "-c"]
    assert "session_id='s1'" in words[4]
    # the handle is a placeholder, never the refused call's handle
    assert "'<handle>'" in words[4]
    assert ada.handle not in words[4]
    # and executing the Python it names, handle filled in, really restores it
    python = words[4].replace("default_profiles_root()", "Path(R)").replace("<handle>", ada.handle)
    exec(python, {"R": str(root), "Path": Path})
    assert read_active_handle(root, session_id="s1") == ada.handle
    assert hook_main(_payload("Edit", {"file_path": str(target)}), root=root)[0] == 0


def test_no_restore_command_is_offered_when_another_candidate_is_active(tmp_path: Path) -> None:
    """Fail-open direction: never hand out an identity switch on a wrong-profile refusal."""
    root = tmp_path / "profiles"
    ada = create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    nuria = create_profile(root, "Núria Puig", language="ca", now=FIXED)
    write_active_handle(root, ada.handle, session_id="s1", now=FIXED)
    target = root / nuria.handle / "profile" / "evidence.jsonl"
    code, message = hook_main(_payload("Edit", {"file_path": str(target)}), root=root)
    assert code == 2
    assert "write_active_handle" not in message


def test_compound_command_refusal_is_explained(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    ada = create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    command = (
        'uv run python -c "from integral.identity import write_active_handle; '
        f"write_active_handle(root, '{ada.handle}', session_id='s1')\" "
        f"&& echo x >> profiles/{ada.handle}/profile/evidence.jsonl"
    )
    code, message = hook_main(_payload("Bash", {"command": command}), root=root)
    assert code == 2  # still refused as a unit
    assert "as its own call" in message
    assert read_active_handle(root, session_id="s1") is None


# The fullwidth id passes `\w`, which is what the first version used.
@pytest.mark.parametrize(
    "session",
    ["s1\n", "ｓ１", "s'; rm -rf ~; '", "a;b", "a b"],  # noqa: RUF001
)
def test_an_unsafe_session_id_gets_no_command_but_is_still_refused(
    tmp_path: Path, session: str
) -> None:
    root = tmp_path / "profiles"
    ada = create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    target = root / ada.handle / "profile" / "evidence.jsonl"
    payload = _payload("Edit", {"file_path": str(target)}, session=session)
    code, message = hook_main(payload, root=root)
    assert code == 2
    assert "write_active_handle" not in message


def test_a_failure_building_the_hint_cannot_change_the_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(identity, "restore_command", boom)
    root = tmp_path / "profiles"
    code, message = hook_main(_payload("Edit", {"file_path": str(root / "ada" / "x")}), root=root)
    assert code == 2
    assert message.startswith("profile guard refused this call")


@pytest.mark.parametrize("name", sorted(_RESERVED_HANDLES))
def test_reserved_handles_are_refused_with_exit_2_by_the_real_script(
    tmp_path: Path, name: str
) -> None:
    """A reserved name must never crash the hook: exit 1 lets the call run."""
    root = tmp_path / "profiles"
    root.mkdir()
    calls = [
        ("Write", {"file_path": str(root / name / "x.json")}),
        ("Bash", {"command": f"echo x > profiles/{name}/x.json"}),
        ("Bash", {"command": f"python step.py --id {name}"}),
    ]
    for tool, tool_input in calls:
        result = _guard(_payload(tool, tool_input), tmp_path)
        assert result.returncode == 2, (tool, tool_input, result.stderr)


def test_the_shell_wrapper_prints_the_restore_command(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    ada = create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    result = _guard(_payload("Edit", {"file_path": str(root / ada.handle / "x.json")}), tmp_path)
    assert result.returncode == 2
    assert "write_active_handle" in result.stderr
