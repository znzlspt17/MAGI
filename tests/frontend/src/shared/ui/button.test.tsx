import {createRef} from "react";
import {cleanup, fireEvent, render, screen} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {Button} from "@/shared/ui/button";
import {Button as LegacyButton} from "@/shared/ui/UI";
import {SidebarSimpleIcon} from "@phosphor-icons/react";
afterEach(cleanup);
it("링크 버튼은 원래 링크의 다운로드 속성과 이벤트 및 ref를 보존한다", () => {
  const clicked = vi.fn();
  const ref = createRef<HTMLAnchorElement>();
  render(<Button asChild><a href="/notice.txt" download="notice.txt" target="_blank" onClick={clicked} ref={ref}>고지 다운로드</a></Button>);
  const link = screen.getByRole("link", {name: "고지 다운로드"});
  expect(link.getAttribute("href")).toBe("/notice.txt");
  expect(link.getAttribute("download")).toBe("notice.txt");
  expect(link.getAttribute("target")).toBe("_blank");
  expect(ref.current).toBe(link);
  fireEvent.click(link);
  expect(clicked).toHaveBeenCalledOnce();
});
it("인접 텍스트의 접근성 이름은 원래 문자열을 유지한다", () => {
  render(<Button><span>architecture </span>{3}행</Button>);
  expect(screen.getByRole("button", {name: "architecture 3행"})).toBeTruthy();
});

it("asChild는 부모와 자식 키 이벤트를 모두 보존한다", () => {
  const outer = vi.fn(); const inner = vi.fn();
  render(<Button asChild onKeyDown={outer}><a href="/" onKeyDown={inner}>열기</a></Button>);
  fireEvent.keyDown(screen.getByRole("link", {name: "열기"}), {key: "Enter"});
  expect(inner).toHaveBeenCalledOnce(); expect(outer).toHaveBeenCalledOnce();
});
it("호출자가 지정한 data-slot을 보존한다", () => {
  render(<Button data-slot="sidebar-trigger">메뉴</Button>);
  expect(screen.getByRole("button", {name: "메뉴"}).getAttribute("data-slot")).toBe("sidebar-trigger");
});
it("아이콘 전용 버튼은 접근성 이름과 Astryx 아이콘 크기를 보존한다", () => {
  render(<Button size="icon" aria-label="메뉴 열기"><SidebarSimpleIcon aria-hidden="true" /><span className="sr-only">메뉴 열기</span></Button>);
  const button = screen.getByRole("button", {name: "메뉴 열기"});
  expect(button.querySelector(".astryx-icon")).toBeTruthy();
});
it("기본 버튼은 보조 동작이며 명시적 default만 주요 동작이다", () => {
  render(<><Button>취소</Button><Button variant="default">저장</Button></>);
  expect(screen.getByRole("button", {name:"취소"}).getAttribute("data-variant")).toBe("secondary");
  expect(screen.getByRole("button", {name:"저장"}).getAttribute("data-variant")).toBe("primary");
});
it("레거시 클래스만으로 주요 동작을 암묵 지정하지 않는다", () => {
 render(<LegacyButton className="primary">보조</LegacyButton>);
 expect(screen.getByRole("button", {name:"보조"}).getAttribute("data-variant")).toBe("secondary");
});
