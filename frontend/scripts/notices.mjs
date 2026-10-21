import { readFile, readdir, realpath, mkdir, writeFile, copyFile } from "node:fs/promises";
import { dirname, join, resolve, basename } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const revision = "ba1503c64472b82256d9de95e2e62c5901a38e8b";

export function sourceUrl(value = "") {
  const url = value.replace(/^git\+/, "").replace(/\.git$/, "");
  if (/^[\w.-]+\/[\w.-]+$/.test(url)) return `https://github.com/${url}`;
  return url.replace(/^git@github\.com:/, "https://github.com/").replace(/^git:\/\//, "https://");
}

export async function packageNotice(directory) {
  const pkg = JSON.parse(await readFile(join(directory, "package.json"), "utf8"));
  const license = typeof pkg.license === "string" ? pkg.license : pkg.license?.type;
  if (!license || /unknown|unlicensed/i.test(license)) throw new Error(`라이선스 종류 누락: ${pkg.name}`);
  const names = await readdir(directory);
  const licenses = names.filter((name) => /^(licen[sc]e|copying)([.-]|$)/i.test(name));
  const notices = names.filter((name) => /^notice([.-]|$)/i.test(name));
  if (!licenses.length) {
    // npm 배포에 원문이 빠진 패키지는 버전별로 검토한 upstream 고지만 사용한다.
    const sources = JSON.parse(await readFile(join(root, "../resources/licenses/sources.json"), "utf8"));
    const source = sources[`${pkg.name}@${pkg.version}`];
    if (!source) throw new Error(`라이선스 원문 누락: ${pkg.name}`);
    const text = (await readFile(join(root, "../resources/licenses", source.file), "utf8")).trim();
    if (!text) throw new Error(`빈 라이선스 원문: ${pkg.name}`);
    const additions = await Promise.all(notices.map(async (name) => `${name}\n${await readFile(join(directory, name), "utf8")}`));
    return { name: pkg.name, version: pkg.version, license, url: source.url, text: [text, ...additions].join("\n\n") };
  }
  const files = [...licenses, ...notices];
  const texts = await Promise.all(files.sort().map(async (name) => {
    const text = (await readFile(join(directory, name), "utf8")).trim();
    if (!text) throw new Error(`빈 라이선스 원문: ${pkg.name}/${name}`);
    return `${name}\n${text}`;
  }));
  const repository = typeof pkg.repository === "string" ? pkg.repository : pkg.repository?.url;
  return { name: pkg.name, version: pkg.version, license, url: sourceUrl(repository || pkg.homepage), text: texts.join("\n\n") };
}

async function findPackage(id) {
  let directory = dirname(await realpath(id));
  while (directory !== dirname(directory)) {
    try {
      const pkg = JSON.parse(await readFile(join(directory, "package.json"), "utf8"));
      if (pkg.name) return directory;
    } catch (error) { if (error.code !== "ENOENT") throw error; }
    directory = dirname(directory);
  }
  throw new Error(`배포 모듈의 패키지를 찾을 수 없습니다: ${basename(id)}`);
}

export function resourcesAndNotices() {
  return {
    name: "resources-and-notices",
    async writeBundle(_options, bundle) {
      const packageDirectories = new Set();
      for (const chunk of Object.values(bundle)) {
        if (chunk.type !== "chunk") continue;
        for (const raw of Object.keys(chunk.modules)) {
          const id = raw.replace(/^\0/, "").split("?")[0];
          if (!id.includes("node_modules") || !/\.[cm]?[jt]sx?$/.test(id)) continue;
          packageDirectories.add(await findPackage(id));
        }
      }
      // 생성한 utility CSS에도 Tailwind의 라이선스를 보존한다.
      packageDirectories.add(await realpath(join(root, "node_modules/tailwindcss")));
      const results = await Promise.allSettled([...packageDirectories].map(packageNotice));
      const failures = results.filter((r) => r.status === "rejected");
      if (failures.length) throw new Error(failures.map((r) => r.reason.message).join("; "));
      const entries = results.map((r) => r.value);
      entries.push({ name: "shadcn/ui", version: revision, license: "MIT", url: `https://github.com/shadcn-ui/ui/tree/${revision}`, text: await readFile(join(root, "src/components/ui/LICENSE.txt"), "utf8") });
      const vendor = join(root, "static/vendor");
      // 기존 vendored 에셋의 고지도 배포 내역에서 빠뜨리지 않는다.
      for (const filename of (await readdir(vendor)).filter((name) => /-LICENSE\.txt$/.test(name))) {
        const name = filename.replace("-LICENSE.txt", "");
        const url = name === "cytoscape" ? "https://github.com/cytoscape/cytoscape.js" : `https://github.com/d3/${name}`;
        entries.push({ name: name + " (vendored)", version: "기존 배포 에셋", license: "원문 참조", url, text: await readFile(join(vendor, filename), "utf8") });
      }
      entries.sort((a, b) => a.name.localeCompare(b.name));
      await mkdir(vendor, { recursive: true });
      await writeFile(join(vendor, "third-party-licenses.json"), JSON.stringify(entries, null, 2) + "\n");
      await writeFile(join(vendor, "THIRD_PARTY_NOTICES.txt"), "MAGI — Third-party notices\n배포 코드·에셋의 필수 고지 및 라이선스 원문\n\n" + entries.map((e) => `${e.name} — ${e.version}\n${e.license}\n${e.url}\n\n${e.text}\n`).join("\n" + "=".repeat(72) + "\n\n"));
      const assets = join(root, "static/dist/assets");
      await mkdir(assets, { recursive: true });
      await copyFile(join(root, "../resources/favicon-120.png"), join(assets, "favicon-120.png"));
    },
  };
}
