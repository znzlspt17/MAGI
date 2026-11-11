import {cleanup, render, screen} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {afterEach, expect, it, vi} from "vitest";
import {NativeSelect, NativeSelectOption} from "@/shared/ui/native-select";
afterEach(cleanup);
it("선택 옵션을 바꾸면 기존 콜백에 선택 값을 전달한다", async () => {
  const user = userEvent.setup(); const change = vi.fn();
  render(<NativeSelect aria-label="상태" defaultValue="a" onChange={change}><NativeSelectOption value="a">전체</NativeSelectOption><NativeSelectOption value="b">완료</NativeSelectOption></NativeSelect>);
  await user.click(screen.getByRole("combobox", {name: "상태"}));
  await user.click(await screen.findByRole("option", {name: "완료"}));
  expect(change.mock.calls[0][0].target.value).toBe("b");
});
