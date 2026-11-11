import {createRef} from "react";
import {cleanup, fireEvent, render, screen} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {Tabs,TabsList,TabsTrigger} from "@/shared/ui/tabs";
afterEach(cleanup);
it("탭은 전달된 ref와 이벤트, 비활성 상태를 보존한다", () => {
 const ref=createRef<HTMLButtonElement>(); const onClick=vi.fn();
 render(<Tabs defaultValue="a"><TabsList aria-label="보기"><TabsTrigger value="a" ref={ref} onClick={onClick}>첫 번째</TabsTrigger><TabsTrigger value="b" disabled>두 번째</TabsTrigger></TabsList></Tabs>);
 const first=screen.getByRole("tab",{name:"첫 번째"}); expect(ref.current).toBe(first); fireEvent.click(first); expect(onClick).toHaveBeenCalledOnce();
 expect(screen.getByRole("tab",{name:"두 번째"}).getAttribute("aria-disabled")).toBe("true");
});
