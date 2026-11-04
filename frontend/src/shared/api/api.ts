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
async function responseData(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  try { return await response.json(); }
  catch {
    if (response.ok) throw new ApiError("서버 응답 형식이 올바르지 않습니다.", response.status);
    return null;
  }
}
function responseError(data: unknown, fallback: string): string {
  if (data === null || typeof data !== "object" || Array.isArray(data)) return fallback;
  const message = "error" in data && typeof data.error === "string" ? data.error : fallback;
  const requestId = "request_id" in data && typeof data.request_id === "string" ? data.request_id : "";
  return `${message}${requestId ? ` (문의 번호 ${requestId})` : ""}`;
}
export async function api(
  path: string,
  options: RequestInit = {},
): Promise<unknown> {
  return request(path, options);
}

async function request(path: string, options: RequestInit, sensitiveOperationId?: string): Promise<unknown> {
  const generation = authGeneration,
    method = (options.method || "GET").toUpperCase(),
    headers = new Headers(options.headers),
    // 2026-11-03: 인증정보 요청은 본문을 재시도 식별자나 Map에 남기지 않는다.
    signature = sensitiveOperationId ? null : `${method}:${path}:${options.body || ""}`;
  if (publicMode && csrf) {
    headers.set("X-CSRF-Token", csrf);
  }
  if (publicMode && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    if (signature !== null) {
      if (!pending.has(signature)) pending.set(signature, crypto.randomUUID());
      headers.set("Idempotency-Key", pending.get(signature)!);
    } else headers.set("Idempotency-Key", sensitiveOperationId!);
  }
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
  });
  if (signature !== null && generation === authGeneration && (response.ok || response.status < 500))
    pending.delete(signature);
  if (publicMode && generation === authGeneration && response.status === 401)
    window.dispatchEvent(new Event("signed-out"));
  const data = await responseData(response);
  if (!response.ok)
    throw new ApiError(
      responseError(data, "요청을 처리하지 못했습니다."),
      response.status,
    );
  return data;
}

// 호출자는 같은 조작을 재시도할 때만 이 불투명 ID를 재사용한다.
export function sensitiveMutation(path: string, method: "POST" | "PATCH", payload: unknown, operationId: string) {
  if (!operationId) throw new Error("요청 식별자가 필요합니다.");
  return request(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, operationId);
}
export function post(
  path: string,
  payload: unknown,
  options: RequestInit = {},
) {
  return api(path, {
    ...options,
    method: "POST",
    headers: { "Content-Type": "application/json", ...options.headers },
    body: JSON.stringify(payload),
  });
}

export async function apiBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const generation = authGeneration;
  const headers = new Headers();
  if (publicMode && csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(path, { method: "GET", credentials: "same-origin", headers, signal });
  if (generation !== authGeneration) throw new Error("접속 계정이 변경되었습니다. 다시 조회하세요.");
  if (publicMode && response.status === 401) window.dispatchEvent(new Event("signed-out"));
  if (!response.ok) {
    const data = await responseData(response);
    throw new ApiError(responseError(data, "파일을 받지 못했습니다."), response.status);
  }
  if (!response.headers.get("Content-Type")?.includes("application/zip")) throw new Error("ZIP 응답을 확인할 수 없습니다.");
  const blob = await response.blob();
  if (generation !== authGeneration) throw new Error("접속 계정이 변경되었습니다. 다시 조회하세요.");
  return blob;
}
