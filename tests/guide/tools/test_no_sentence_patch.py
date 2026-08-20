from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = (
    "app/guide/intent",
    "app/guide/application",
)


def test_release_change_does_not_add_sentence_owned_action_rules() -> None:
    diff = subprocess.run(
        ["git", "diff", "-U0", "HEAD", "--", *PRODUCTION],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    prohibited = (
        "第一款和第二款",
        "第一张和第二张",
        "哪个更适合",
        "product_id ==",
    )
    added = "\n".join(
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    assert not any(token in added for token in prohibited)
