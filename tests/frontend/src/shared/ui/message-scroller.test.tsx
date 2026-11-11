import {act, cleanup, fireEvent, render, screen} from "@testing-library/react";
import {afterEach, expect, it} from "vitest";
import {MessageScrollerProvider, MessageScroller, MessageScrollerViewport, MessageScrollerContent} from "@/shared/ui/message-scroller";
afterEach(cleanup);
it("과거 메시지를 읽는 중에는 새 메시지가 추가돼도 스크롤 위치를 유지한다", async () => {
  const view = render(<MessageScrollerProvider><MessageScroller><MessageScrollerViewport aria-label="대화 이력"><MessageScrollerContent>첫 메시지</MessageScrollerContent></MessageScrollerViewport></MessageScroller></MessageScrollerProvider>);
  const viewport = screen.getByLabelText("대화 이력");
  Object.defineProperty(viewport, "scrollHeight", {configurable: true, value: 1000});
  Object.defineProperty(viewport, "clientHeight", {configurable: true, value: 200});
  viewport.scrollTop = 100; fireEvent.scroll(viewport);
  view.rerender(<MessageScrollerProvider><MessageScroller><MessageScrollerViewport aria-label="대화 이력"><MessageScrollerContent>첫 메시지와 새 메시지</MessageScrollerContent></MessageScrollerViewport></MessageScroller></MessageScrollerProvider>);
  await act(async () => { await Promise.resolve(); });
  expect(viewport.scrollTop).toBe(100);
});
it("최신 위치를 따라가는 중에는 새 메시지로 이동한다", async () => {
  const view = render(<MessageScrollerProvider><MessageScroller><MessageScrollerViewport aria-label="대화 이력"><MessageScrollerContent>첫 메시지</MessageScrollerContent></MessageScrollerViewport></MessageScroller></MessageScrollerProvider>);
  const viewport = screen.getByLabelText("대화 이력");
  Object.defineProperty(viewport, "scrollHeight", {configurable: true, value: 1000});
  Object.defineProperty(viewport, "clientHeight", {configurable: true, value: 200});
  view.rerender(<MessageScrollerProvider><MessageScroller><MessageScrollerViewport aria-label="대화 이력"><MessageScrollerContent>첫 메시지와 새 메시지</MessageScrollerContent></MessageScrollerViewport></MessageScroller></MessageScrollerProvider>);
  await act(async () => { await Promise.resolve(); });
  expect(viewport.scrollTop).toBe(1000);
});
