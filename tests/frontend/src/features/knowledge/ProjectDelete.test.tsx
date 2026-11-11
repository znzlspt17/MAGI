import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { ProjectDelete } from "@/features/knowledge/Knowledge";

afterEach(cleanup);

it("빈 프로젝트 삭제 확인은 취소에 포커스하고 처리 중 Escape를 막는다", async () => {
  const execute = vi.fn();
  function Harness() {
    const [open, setOpen] = useState(false), [busy, setBusy] = useState(false);
    return <><button onClick={() => setOpen(true)}>미리보기</button>{open && <ProjectDelete
      operation={{ id: "preview", scope: "projects", counts: { jobs: 0 }, project_id: "project" }}
      busy={busy} onCancel={() => setOpen(false)} onExecute={() => { execute(); setBusy(true); }} />}</>;
  }
  render(<Harness />);
  const opener = screen.getByRole("button", { name: "미리보기" });
  opener.focus(); fireEvent.click(opener);
  let dialog = screen.getByRole("dialog", { name: "빈 프로젝트 영구 삭제 확인" });
  await waitFor(() => expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "취소" })));
  fireEvent.click(within(dialog).getByRole("button", { name: "취소" }));
  await waitFor(() => expect(document.activeElement).toBe(opener));
  fireEvent.click(opener); dialog = screen.getByRole("dialog", { name: "빈 프로젝트 영구 삭제 확인" });
  fireEvent.click(within(dialog).getByRole("button", { name: "영구 삭제" }));
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(screen.getByRole("dialog", { name: "빈 프로젝트 영구 삭제 확인" })).toBeTruthy();
  expect(within(dialog).getByRole<HTMLButtonElement>("button", { name: "영구 삭제" }).disabled).toBe(true);
  expect(execute).toHaveBeenCalledTimes(1);
});
