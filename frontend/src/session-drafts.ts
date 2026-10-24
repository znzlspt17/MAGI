export function clearAccountDrafts(storage: Storage, owner: string): void {
  const prefix = `draft:${owner}`;
  for (const key of Object.keys(storage)) {
    if (key === prefix || key.startsWith(prefix + ":")) {
      storage.removeItem(key);
    }
  }
}
