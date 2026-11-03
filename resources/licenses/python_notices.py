"""설치된 Python 배포판의 원문 고지를 수집하고 누락은 경고로 알린다."""

import argparse
from importlib.metadata import distributions
import json
from pathlib import Path
import re
import sys


def package_notice(dist):
    name = dist.metadata["Name"]
    warnings = []
    files = sorted(
        (f for f in dist.files or [] if re.search(
            r"(^|/)(licen[sc]e|copying|notice)([./_-]|$)", str(f).replace("\\", "/"), re.I
        )), key=str,
    )
    if not any(re.search(r"(^|/)(licen[sc]e|copying)([./_-]|$)", str(f).replace("\\", "/"), re.I) for f in files):
        warnings.append(f"라이선스 원문 확인 필요: {name}=={dist.version}")
    texts = []
    for file in files:
        try:
            text = "\n".join(line.rstrip() for line in Path(dist.locate_file(file)).read_text(encoding="utf-8").splitlines()).strip()
        except FileNotFoundError:
            warnings.append(f"고지 원문 파일 확인 필요: {name}/{file}")
            continue
        if not text:
            warnings.append(f"빈 고지 원문 확인 필요: {name}/{file}")
            continue
        texts.append(f"{file}\n{text}")
    for warning in warnings:
        print(f"[오픈소스 고지] {warning}", file=sys.stderr)
    texts.extend(warnings)
    license_name = dist.metadata.get("License-Expression") or " / ".join(
        c.split(" :: ")[-1] for c in dist.metadata.get_all("Classifier", []) if c.startswith("License ::")
    ) or "원문 참조"
    urls = dist.metadata.get_all("Project-URL", [])
    url = next((u.split(",", 1)[1].strip() for u in urls if u.lower().startswith(("source,", "repository,", "source code,"))), dist.metadata.get("Home-page", ""))
    return dict(name=f"{name} (Python)", version=dist.version, license=license_name, url=url, text="\n\n".join(texts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--merge", type=Path, action="append", default=[])
    args = parser.parse_args()
    entries = [package_notice(dist) for dist in distributions()]
    for path in args.merge:
        entries.extend(json.loads(path.read_text(encoding="utf-8")))
    unique = {}
    for entry in entries:
        key = (entry["name"], entry["version"])
        if key in unique and unique[key] != entry:
            print(f"[오픈소스 고지] 동일 버전의 고지 원문 불일치: {key}", file=sys.stderr)
            entry = dict(entry, text=unique[key]["text"] + "\n\n" + entry["text"])
        unique[key] = entry
    entries = sorted(unique.values(), key=lambda e: (e["name"].lower(), e["version"]))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "third-party-licenses.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "THIRD_PARTY_NOTICES.txt").write_text(
        "MAGI — Third-party notices\n배포 코드·에셋의 필수 고지 및 라이선스 원문\n\n" +
        ("\n" + "=" * 72 + "\n\n").join(
            f'{e["name"]} — {e["version"]}\n{e["license"]}\n{e["url"]}\n\n{e["text"]}\n' for e in entries
        ), encoding="utf-8",
    )
    print(f"오픈소스 고지 {len(entries)}개 생성: {args.output}")


if __name__ == "__main__":
    main()
