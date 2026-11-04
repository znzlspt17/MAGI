import { expect, it } from "vitest";
import { decodeAuthInfo, decodeServiceStatus, decodeUser } from "@/features/auth/account-response";

it("인증 여부와 실행 수는 잘못된 타입을 허용하지 않는다", () => {
  expect(() => decodeAuthInfo({ public: "false" })).toThrow();
  expect(() => decodeServiceStatus({ active_count: [] })).toThrow();
  expect(() => decodeUser({ id: "user", role: {} })).toThrow();
});
it("과거 로컬 모드 응답의 로그인 설정 누락을 허용한다", () => {
  expect(decodeAuthInfo({ public: false })).toMatchObject({ public: false });
});
