export type AuthType = "none" | "api_key" | "bearer" | "oauth";
export interface McpTool {
  name: string;
  description: string;
  read_only_hint: boolean;
  destructive_hint: boolean;
  enabled: boolean;
  schema_changed: boolean;
  available: boolean;
  disabled_reason: string | null;
}
export interface McpConnection {
  id: string;
  name: string;
  url: string;
  auth_type: AuthType;
  enabled: boolean;
  status: "disconnected" | "ready" | "auth_required" | "error";
  tools: McpTool[];
  has_credential: boolean;
  api_key_header?: string;
  oauth_client_id?: string;
  error: string | null;
}

const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("MCP 응답 형식이 올바르지 않습니다.");
  return value as Record<string, unknown>;
};
const str = (value: unknown): string => {
  if (typeof value !== "string") throw new Error("MCP 응답 형식이 올바르지 않습니다.");
  return value;
};
const bool = (value: unknown): boolean => {
  if (typeof value !== "boolean") throw new Error("MCP 응답 형식이 올바르지 않습니다.");
  return value;
};

// 2026-11-03: 외부 서버에서 온 도구 설명은 문자열로만 취급하고 인증정보는 보관하지 않는다.
export function decodeConnection(value: unknown): McpConnection {
  const v = object(value);
  const auth = str(v.auth_type), status = str(v.status);
  if (!["none", "api_key", "bearer", "oauth"].includes(auth) ||
      !["disconnected", "ready", "auth_required", "error"].includes(status) ||
      !Array.isArray(v.tools)) throw new Error("MCP 응답 형식이 올바르지 않습니다.");
  return {
    id: str(v.id), name: str(v.name), url: str(v.url), auth_type: auth as AuthType,
    status: status as McpConnection["status"], enabled: bool(v.enabled),
    has_credential: bool(v.has_credential),
    error: v.error == null ? null : str(v.error),
    api_key_header: v.api_key_header == null ? undefined : str(v.api_key_header),
    oauth_client_id: v.oauth_client_id == null ? undefined : str(v.oauth_client_id),
    tools: v.tools.map((value): McpTool => {
      const tool = object(value);
      return { name: str(tool.name), description: str(tool.description), read_only_hint: bool(tool.read_only_hint),
        destructive_hint: bool(tool.destructive_hint), enabled: bool(tool.enabled), schema_changed: bool(tool.schema_changed),
        available: tool.available === undefined ? false : bool(tool.available),
        disabled_reason: tool.disabled_reason == null ? null : str(tool.disabled_reason) };
    }),
  };
}

export function decodeConnections(value: unknown): McpConnection[] {
  const list = object(value).connections;
  if (!Array.isArray(list)) throw new Error("MCP 응답 형식이 올바르지 않습니다.");
  return list.map(decodeConnection);
}

export function decodeAuthorizationUrl(value: unknown): string {
  const url = new URL(str(object(value).url));
  if (url.protocol !== "https:" || url.username || url.password) throw new Error("인증 주소가 올바르지 않습니다.");
  return url.href;
}
