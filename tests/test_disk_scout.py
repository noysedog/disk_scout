import importlib.util
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "disk_scout.py"
)

spec = importlib.util.spec_from_file_location(
    "disk_scout_module", SCRIPT_PATH
)

if spec is None or spec.loader is None:
    raise ImportError(f"Impossibile caricare {SCRIPT_PATH}")

disk_scout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(disk_scout)

fmt_size = disk_scout.fmt_size
size_key = disk_scout.size_key


def test_fmt_size_bytes():
    assert fmt_size(0) == "0.00 B"


def test_fmt_size_kib():
    assert fmt_size(1024) == "1.00 KiB"


def test_fmt_size_mib():
    assert fmt_size(1024 ** 2) == "1.00 MiB"


def test_fmt_size_gib():
    assert fmt_size(1024 ** 3) == "1.00 GiB"


def test_size_key_decimal_comma():
    assert size_key("4,1G") > size_key("900M")


def test_size_key_ordering():
    sizes = ["512K", "900M", "4,1G", "14G", "1,5T"]
    ordered = sorted(sizes, key=size_key, reverse=True)

    assert ordered == ["1,5T", "14G", "4,1G", "900M", "512K"]
