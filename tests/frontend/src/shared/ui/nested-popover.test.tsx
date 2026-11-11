import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/shared/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/shared/ui/popover";
import { Button } from "@/shared/ui/button";
afterEach(cleanup);
it("중첩 팝오버에서 Escape 한 번은 팝오버만 닫고 다음 Escape가 대화상자를 닫는다", () => {
  function Example() {
    const [open, setOpen] = useState(false);
    return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button>대화상자 열기</Button></DialogTrigger><DialogContent><DialogTitle>등록 확인</DialogTitle><Popover><PopoverTrigger asChild><Button>출처 확인</Button></PopoverTrigger><PopoverContent><Button>출처 내용</Button></PopoverContent></Popover></DialogContent></Dialog>;
  }
  render(<Example />);
  fireEvent.click(screen.getByRole("button", { name: "대화상자 열기" }));
  const dialog = screen.getByRole("dialog", { name: "등록 확인" });
  fireEvent.click(within(dialog).getByRole("button", { name: "출처 확인" }));
  const source = screen.getByRole("button", { name: "출처 내용" });
  fireEvent.keyDown(source, { key: "Escape" });
  expect(screen.getByRole("dialog", { name: "등록 확인" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "출처 내용" })).toBeNull();
  fireEvent.keyDown(screen.getByRole("dialog", { name: "등록 확인" }), { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "등록 확인" })).toBeNull();
});
