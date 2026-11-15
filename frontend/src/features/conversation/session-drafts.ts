export function clearAccountDrafts(storage: Storage, owner: string): void {
  const prefix = `draft:${owner}`;
  for (const key of Object.keys(storage)) {
    if (key === prefix || key.startsWith(prefix + ":") || key === `draft-backup:${prefix}` || key.startsWith(`draft-backup:${prefix}:`)) {
      storage.removeItem(key);
    }
  }
}

// 2026-11-13: 계정 연결로 식별자가 바뀌어도 탭에서 작성하던 내용을 복구한다.
export function copyAccountDrafts(storage: Storage, source: string, destination: string): void {
  if (!source || !destination || source === destination) return;
  const from = `draft:${source}`;
  const to = `draft:${destination}`;
  for (const key of Object.keys(storage)) {
    if (key !== from && !key.startsWith(from + ":")) continue;
    const destinationKey = to + key.slice(from.length);
    const value = storage.getItem(key);
    if (value === null) continue;
    const existing = storage.getItem(destinationKey);
    if (existing !== null && existing !== value) {
      // 원래 계정의 초안과 겹쳐도 어느 쪽도 버리지 않는다.
      let backup = `draft-backup:${destinationKey}`, suffix = 0;
      while (storage.getItem(backup) !== null) backup = `draft-backup:${destinationKey}:${++suffix}`;
      storage.setItem(backup, existing);
    }
    storage.setItem(destinationKey, value);
    storage.removeItem(key);
  }
}
