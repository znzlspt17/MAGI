// 외부 JSON을 검증하는 경계. 검증 실패의 원문 값은 오류에 포함하지 않는다.
export type Decoder<T> = (value: unknown) => T;
export function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("응답 형식이 올바르지 않습니다.");
  return value as Record<string, unknown>;
}
export const text: Decoder<string> = value => {
  if (typeof value !== "string") throw new Error("문자열 응답이 필요합니다.");
  return value;
};
export const number: Decoder<number> = value => {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error("숫자 응답이 필요합니다.");
  return value;
};
export const boolean: Decoder<boolean> = value => {
  if (typeof value !== "boolean") throw new Error("참거짓 응답이 필요합니다.");
  return value;
};
export function array<T>(decode: Decoder<T>): Decoder<T[]> {
  return value => { if (!Array.isArray(value)) throw new Error("목록 응답이 필요합니다."); return value.map(decode); };
}
export function optional<T>(decode: Decoder<T>): Decoder<T | undefined> {
  return value => value == null ? undefined : decode(value);
}
type Shape = Record<string, Decoder<unknown>>;
type Parsed<S extends Shape> = { [K in keyof S]?: ReturnType<S[K]> };
export function object<S extends Shape>(shape: S): Decoder<Parsed<S>> {
  return value => {
    const source = record(value), result: Record<string, unknown> = {};
    for (const [key, decode] of Object.entries(shape)) {
      if (source[key] !== undefined) result[key] = decode(source[key]);
    }
    // 모든 값은 해당 키의 decoder를 통과했다. 동적 키 순회를 타입으로 연결한다.
    return result as Parsed<S>;
  };
}

type RequiredParsed<S extends Shape> = {
  [K in keyof S as undefined extends ReturnType<S[K]> ? never : K]: ReturnType<S[K]>
} & {
  [K in keyof S as undefined extends ReturnType<S[K]> ? K : never]?: ReturnType<S[K]>
};
export function requiredObject<S extends Shape>(shape: S): Decoder<RequiredParsed<S>> {
  return value => {
    const source = record(value), result: Record<string, unknown> = {};
    for (const [key, decode] of Object.entries(shape)) result[key] = decode(source[key]);
    return result as RequiredParsed<S>;
  };
}
export function literal<const T extends readonly string[]>(...values: T): Decoder<T[number]> {
  return value => {
    const parsed = text(value);
    if (!values.includes(parsed)) throw new Error("알 수 없는 응답 상태입니다.");
    return parsed;
  };
}
export function nullable<T>(decode: Decoder<T>): Decoder<T | null> {
  return value => value === null ? null : decode(value);
}
export function dictionary<T>(decode: Decoder<T>): Decoder<Record<string, T>> {
  return value => Object.fromEntries(Object.entries(record(value)).map(([key, item]) => [key, decode(item)]));
}
