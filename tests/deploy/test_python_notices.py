"""서버 배포 고지에서 원문 누락과 중첩 라이선스 유실을 방지한다."""

from email.message import Message
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

spec = spec_from_file_location("python_notices", Path(__file__).resolve().parents[2] / "resources/licenses/python_notices.py")
notices = module_from_spec(spec)
spec.loader.exec_module(notices)


def distribution(tmp_path, files):
    metadata = Message()
    metadata["Name"] = "fixture"
    metadata["License-Expression"] = "MIT"
    return SimpleNamespace(metadata=metadata, version="1", files=files, locate_file=lambda f: tmp_path / Path(str(f).replace("\\", "/")))


def test_preserves_nested_bundled_licenses_and_notices(tmp_path):
    paths = ["fixture.dist-info/licenses/LICENSE", "fixture.dist-info/licenses/vendor/NOTICE", "fixture.dist-info/licenses/vendor/COPYING"]
    for i, path in enumerate(paths):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"Copyright {i}", encoding="utf-8")
    entry = notices.package_notice(distribution(tmp_path, [PureWindowsPath(p) for p in paths]))
    assert entry["license"] == "MIT"
    assert all(f"Copyright {i}" in entry["text"] for i in range(3))


def test_missing_license_or_empty_notice_warns_and_preserves_entry(tmp_path, capsys):
    entry = notices.package_notice(distribution(tmp_path, []))
    assert entry["name"] == "fixture (Python)"
    assert "원문 확인 필요" in entry["text"]
    (tmp_path / "LICENSE").write_text("MIT permission", encoding="utf-8")
    (tmp_path / "NOTICE").write_text(" ", encoding="utf-8")
    entry = notices.package_notice(distribution(tmp_path, ["LICENSE", "NOTICE", "COPYING"]))
    assert "MIT permission" in entry["text"]
    assert "빈 고지" in entry["text"]
    assert "파일 확인 필요" in entry["text"]
    assert "[오픈소스 고지]" in capsys.readouterr().err
