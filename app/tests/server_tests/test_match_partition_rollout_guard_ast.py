from pathlib import Path


def test_partition_rollout_command_exists() -> None:
    cmd = Path("server/api/management/commands/immoapp_match_partition_rollout.py")
    assert cmd.exists()
    text = cmd.read_text(encoding="utf-8")
    assert "--apply" in text
    assert "rollout_match_partitions" in text
