"""분할 파일을 모두 검증한 뒤에만 ZIP 응답을 완성한다."""
import base64
import hashlib
import io
import json
import zipfile

CHUNK = 48 * 1024
NAMES = {"README.ko.md", "SPEC.en.md", "SPEC.ko.md", "TASKS.md", "CONSTRAINTS.md", "VERIFICATION.md", "manifest.json"}


def download_package(client, ident, completed_id, bundle_id):
    metadata = client.call("implementation.package", {"id": ident, "completed_id": completed_id, "bundle_id": bundle_id})
    if metadata.get("bundle_id") != bundle_id or not metadata.get("available"):
        raise ValueError("묶음 자료가 변경되었거나 크기 제한을 초과했습니다. 다시 조회하세요.")
    entries = metadata.get("files", [])
    names = [e["name"] for e in entries]
    if len(names) != len(set(names)) or set(names) - NAMES or not NAMES - {"SPEC.ko.md"} <= set(names):
        raise ValueError("묶음 파일 목록을 확인할 수 없습니다.")
    if any(type(e["size"]) is not int or not 0 < e["size"] <= 4 * 1024 * 1024 for e in entries) or sum(e["size"] for e in entries) > 16 * 1024 * 1024:
        raise ValueError("묶음 크기 제한을 초과했습니다.")
    bodies = {}
    for entry in entries:
        body = bytearray()
        while len(body) < entry["size"]:
            offset = len(body)
            chunk = client.call("implementation.package.file", {"id": ident, "completed_id": metadata["completed_id"],
                "bundle_id": bundle_id, "file_id": entry["name"], "offset": offset})
            raw = base64.b64decode(chunk.get("content", ""), validate=True)
            expected = min(CHUNK, entry["size"] - offset)
            if (len(raw) != expected or chunk.get("offset") != offset or chunk.get("name") != entry["name"]
                    or chunk.get("bundle_id") != bundle_id or chunk.get("size") != entry["size"]
                    or chunk.get("sha256") != entry["sha256"] or chunk.get("eof") != (offset + expected == entry["size"])):
                raise ValueError("묶음 전송을 확인하지 못했습니다.")
            body.extend(raw)
        if hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError("묶음 파일의 해시가 일치하지 않습니다.")
        bodies[entry["name"]] = bytes(body)
    manifest = json.loads(bodies["manifest.json"])
    expected = [e for e in entries if e["name"] != "manifest.json"]
    identity = {k: v for k, v in manifest.items() if k not in {"bundle_id", "test_status"}}
    calculated_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")).hexdigest()
    if (manifest.get("files") != expected or manifest.get("bundle_id") != bundle_id
            or calculated_id != bundle_id or metadata.get("source_hash") != manifest.get("source_hash")
            or manifest.get("completed_id") != metadata["completed_id"]
            or manifest.get("source_hash") != hashlib.sha256(bodies["SPEC.en.md"]).hexdigest()):
        raise ValueError("묶음 기준 정보를 확인할 수 없습니다.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in bodies.items():
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, body)
    output.seek(0)
    return output, metadata["filename"]
