from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENTRY_FILES = (
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "start.sh",
    "README.md",
    "DEPLOY.md",
)


def test_every_default_entry_targets_guide_runtime() -> None:
    for relative_path in DEFAULT_ENTRY_FILES:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")

        assert "app.guide_runtime.app:app" in text, relative_path
        assert "app.main:app" not in text, relative_path
