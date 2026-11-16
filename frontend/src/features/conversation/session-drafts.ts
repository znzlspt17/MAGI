// 2026-11-15: 브라우저가 저장소를 차단해도 작성 화면은 계속 사용할 수 있다.
export const draftStorage = {
  getItem(key: string): string | null { try { return sessionStorage.getItem(key); } catch { return null; } },
  setItem(key: string, value: string): void { try { sessionStorage.setItem(key, value); } catch { /* 작성 내용은 화면에 유지한다. */ } },
  removeItem(key: string): void { try { sessionStorage.removeItem(key); } catch { /* 화면 전환은 계속한다. */ } },
};

export function clearAccountDrafts(storage: Storage, owner: string): void {
  const prefix = `draft:${owner}`;
  for (const key of Object.keys(storage)) {
    if (key === prefix || key.startsWith(prefix + ":") || key === `draft-backup:${prefix}` || key.startsWith(`draft-backup:${prefix}:`)) {
      storage.removeItem(key);
    }
  }
}

export function clearJobDrafts(storage: Storage, owner: string, job: string): void {
  const prefix = `draft:${owner}:${job}:`;
  for (const key of Object.keys(storage)) {
    if (key.startsWith(prefix) || key.startsWith(`draft-backup:${prefix}`)) storage.removeItem(key);
  }
}

// 2026-11-15: 복원 전 현재 내용을 별도 백업으로 남겨 어느 초안도 버리지 않는다.
export function restoreDraft(storage: Storage, key: string, backup: string): string {
  const prefix = `draft-backup:${key}`;
  if (backup !== prefix && !(backup.startsWith(prefix + ":") && /^\d+(?::\d+)*$/.test(backup.slice(prefix.length + 1)))) throw new Error("초안 백업을 확인할 수 없습니다.");
  const selected = storage.getItem(backup);
  if (selected === null) throw new Error("초안 백업이 없습니다.");
  const current = storage.getItem(key);
  if (current !== null && current !== selected) {
    let spare = prefix, suffix = 0;
    while (storage.getItem(spare) !== null) spare = `${prefix}:${++suffix}`;
    storage.setItem(spare, current);
  }
  storage.setItem(key, selected);
  storage.removeItem(backup);
  return selected;
}

// 2026-11-13: 계정 연결로 식별자가 바뀌어도 탭에서 작성하던 내용을 복구한다.
export function copyAccountDrafts(storage: Storage, source: string, destination: string): void {
  if (!source || !destination || source === destination) return;
  const from = `draft:${source}`;
  const to = `draft:${destination}`;
  // 백업은 먼저 옮겨 충돌 시 생성되는 새 백업과 모두 보존한다.
  for (const key of Object.keys(storage)) {
    const prefix = `draft-backup:${from}`;
    if (key !== prefix && !key.startsWith(prefix + ":")) continue;
    const value = storage.getItem(key);
    if (value === null) continue;
    const base = `draft-backup:${to}${key.slice(prefix.length)}`;
    let target = base, suffix = 0;
    while (storage.getItem(target) !== null) target = `${base}:${++suffix}`;
    storage.setItem(target, value);
    storage.removeItem(key);
  }
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
