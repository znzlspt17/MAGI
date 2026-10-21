import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { packageNotice, sourceUrl } from "./notices.mjs";

test("npm 저장소 shorthand와 Git URL을 공식 소스 링크로 정규화한다", () => {
  assert.equal(sourceUrl("phosphor-icons/react"), "https://github.com/phosphor-icons/react");
  assert.equal(sourceUrl("git+https://github.com/org/repo.git"), "https://github.com/org/repo");
  assert.equal(sourceUrl("git@github.com:org/repo.git"), "https://github.com/org/repo");
});

test("원문 또는 라이선스 종류를 알 수 없는 패키지는 배포 고지 생성을 중단한다", async () => {
  const directory = await mkdtemp(join(tmpdir(), "notices-"));
  try {
    await writeFile(join(directory, "package.json"), JSON.stringify({ name: "fixture", version: "1", license: "UNKNOWN" }));
    await assert.rejects(packageNotice(directory), /종류 누락/);
    await writeFile(join(directory, "package.json"), JSON.stringify({ name: "fixture", version: "1", license: "MIT" }));
    await assert.rejects(packageNotice(directory), /원문 누락/);
    await writeFile(join(directory, "NOTICE"), "Copyright fixture — notice only");
    await assert.rejects(packageNotice(directory), /원문 누락/);
    await writeFile(join(directory, "LICENSE"), "Copyright fixture\nMIT permission text");
    const result = await packageNotice(directory);
    assert.match(result.text, /MIT permission text/);
    assert.match(result.text, /notice only/);
  } finally { await rm(directory, { recursive: true, force: true }); }
});
