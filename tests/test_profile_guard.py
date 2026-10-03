"""The guard's refusal must carry the line that fixes it (T185)."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from integral.identity import (
    create_profile,
    hook_main,
    read_active_handle,
    write_active_handle,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def _payload(tool: str, tool_input: dict[str, str], session: str = "s1") -> str:
    return json.dumps({"session_id": session, "tool_name": tool, "tool_input": tool_input})


def _command_from(message: str) -> str:
    return message.split("with: ", 1)[1].splitlines()[0]


def test_refusal_names_the_restore_command(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    ada = create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    target = root / ada.handle / "profile" / "evidence.jsonl"
    code, message = hook_main(_payload("Edit", {"file_path": str(target)}), root=root)
    assert code == 2
    words = shlex.split(_command_from(message))
    # runnable, not a spec reference: it names the handle and the session
    assert words[:4] == ["uv", "run", "python", "-c"]
    assert f"'{ada.handle}'" in words[4]
    assert "session_id='s1'" in words[4]
    # and executing the Python it names really does restore the handle
    python = words[4].replace("default_profiles_root()", "Path(R)")
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


def test_an_unsafe_session_id_gets_no_command_but_is_still_refused(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    ada = create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    target = root / ada.handle / "profile" / "evidence.jsonl"
    code, message = hook_main(
        _payload("Edit", {"file_path": str(target)}, session="s'; rm -rf ~; '"), root=root
    )
    assert code == 2
    assert "write_active_handle" not in message


def test_the_shell_wrapper_prints_the_restore_command(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    ada = create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    guard = Path(__file__).resolve().parents[1] / "tools" / "profile_guard.sh"
    result = subprocess.run(
        ["bash", str(guard)],
        input=_payload("Edit", {"file_path": str(root / ada.handle / "x.json")}),
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        env={**os.environ, "INTEGRAL_HOME": str(tmp_path)},
    )
    assert result.returncode == 2
    assert "write_active_handle" in result.stderr
