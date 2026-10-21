let csrf = "",
  publicMode = false,
  authGeneration = 0;
const pending = new Map<string, string>();
export function configureAuth(value: { csrf?: string; publicMode: boolean }) {
  authGeneration++;
  csrf = value.csrf || "";
  publicMode = value.publicMode;
}
export function clearRequests() {
  pending.clear();
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const generation = authGeneration,
    method = (options.method || "GET").toUpperCase(),
    headers = new Headers(options.headers),
    signature = `${method}:${path}:${options.body || ""}`;
  if (publicMode && csrf) {
    headers.set("X-CSRF-Token", csrf);
  }
  if (publicMode && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    if (!pending.has(signature)) pending.set(signature, crypto.randomUUID());
    headers.set("Idempotency-Key", pending.get(signature)!);
  }
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
  });
  if (generation === authGeneration && (response.ok || response.status < 500))
    pending.delete(signature);
  if (publicMode && generation === authGeneration && response.status === 401)
    window.dispatchEvent(new Event("signed-out"));
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new ApiError(
      `${data.error || "요청을 처리하지 못했습니다."}${data.request_id ? ` (문의 번호 ${data.request_id})` : ""}`,
      response.status,
    );
  return data as T;
}
export function post<T = any>(
  path: string,
  payload: unknown,
  options: RequestInit = {},
) {
  return api<T>(path, {
    ...options,
    method: "POST",
    headers: { "Content-Type": "application/json", ...options.headers },
    body: JSON.stringify(payload),
  });
}
