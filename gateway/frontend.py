"""같은 릴리스의 Vite manifest와 정적 자산을 함께 제공한다."""

import json
from pathlib import Path

from flask import current_app, render_template


def frontend_assets():
    root = Path(current_app.static_folder) / "dist"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["src/main.tsx"]
    assets = [entry["file"], *entry.get("css", [])]
    for item in assets:
        target = (root / item).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            raise ValueError("missing frontend asset")
    return entry


def render_frontend():
    try:
        entry = frontend_assets()
    except (OSError, ValueError, KeyError, TypeError):
        current_app.logger.error("React frontend build is unavailable")
        return "프론트엔드 빌드가 준비되지 않았습니다. 운영자에게 문의하세요.", 503
    return render_template("react.html", react_assets=entry)
