// 기존 초안의 값을 바꾸지 않고 알려진 키만 한 번 옮긴다.
export function migrateSessionKeys(storage: Storage): void {
  try {
    if (storage.getItem("session-key-format") === "1") return;
    const keys = Array.from({ length: storage.length }, (_, i) => storage.key(i));
    for (const key of keys) {
      if (!key || !(key === "magi:return-path" || key.startsWith("magi:draft:"))) continue;
      const target = key.slice(5), value = storage.getItem(key);
      if (value === null) continue;
      const existing = storage.getItem(target);
      if (existing !== null && existing !== value) continue;
      if (existing === null) storage.setItem(target, value);
      storage.removeItem(key);
    }
    storage.setItem("session-key-format", "1");
  } catch {
    // 저장소 접근·용량 오류가 나면 남은 이전 값을 보존한다.
  }
}

export function clearAccountDrafts(storage: Storage, owner: string): void {
  const prefix = `draft:${owner}`;
  // 충돌로 남긴 이전 초안도 지워 로그아웃 후 다시 이관되지 않게 한다.
  const prefixes = [prefix, `magi:${prefix}`];
  for (const key of Object.keys(storage)) {
    if (prefixes.some((value) => key === value || key.startsWith(value + ":"))) {
      storage.removeItem(key);
    }
  }
}
