import {cleanup, fireEvent, render, screen} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {Sidebar, SidebarProvider, SidebarTrigger} from "@/shared/ui/sidebar";
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
it("사이드바 안에서 Ctrl+B로 접으면 메뉴 버튼으로 초점이 돌아간다", () => {
 vi.stubGlobal("innerWidth", 1440);
 vi.stubGlobal("matchMedia", vi.fn(() => ({matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn()})));
 render(<SidebarProvider><Sidebar><a href="#session">대화 기록</a></Sidebar><SidebarTrigger /></SidebarProvider>);
 const link=screen.getByRole("link", {name:"대화 기록"}); link.focus();
 fireEvent.keyDown(link, {key:"b", ctrlKey:true});
 expect(document.activeElement).toBe(screen.getByRole("button", {name:"메뉴 열기"}));
});
