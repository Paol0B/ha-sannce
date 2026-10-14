from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "protocol-examples.json"
COPY = ROOT / "lib" / "tests" / "data" / "protocol-examples.json"


def test_library_copy_matches_the_docs_file():
    assert COPY.read_bytes() == SOURCE.read_bytes(), (
        f"{COPY.relative_to(ROOT)} differs from {SOURCE.relative_to(ROOT)}: "
        f"run cp {SOURCE.relative_to(ROOT)} {COPY.relative_to(ROOT)}"
    )
