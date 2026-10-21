// Adapted from shadcn/ui sidebar-07 (MIT), revision ba1503c64472b82256d9de95e2e62c5901a38e8b.
import type { ReactNode } from "react";
import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarRail, useSidebar } from "./ui/sidebar";
import { NavUser } from "./NavUser";
import { ScalesIcon, ShieldCheckIcon, CopyrightIcon } from "@phosphor-icons/react";

export function AppSidebar({ children }: { children: ReactNode }) {
  const { setOpenMobile } = useSidebar();
  return (
    <Sidebar variant="inset" className="sidebar">
      <SidebarHeader className="sidebar-brand">
        <a href="/" className="brand"><span className="brand-mark"><ScalesIcon weight="duotone" size={25} aria-hidden /></span><span>MAGI<small>생각을 명세로 연결하는 공간</small></span></a>
      </SidebarHeader>
      <SidebarContent className="navigation" onClick={(event) => {
        const target = event.target as HTMLElement;
        if (target.closest("a, .primary-nav button, .new-job")) setOpenMobile(false);
      }}>{children}</SidebarContent>
      <SidebarFooter className="sidebar-footer">
        <NavUser />
        <p>요청과 답변은 AI 제공자에게 전송됩니다. 민감한 정보는 입력하지 마세요.</p>
        <a href="/privacy"><ShieldCheckIcon size={16} aria-hidden />정보 처리 안내</a>
        <a href="/licenses"><CopyrightIcon size={16} aria-hidden />오픈소스 라이선스</a>
      </SidebarFooter>
      <SidebarRail aria-label="작업 메뉴 접기 또는 펼치기" />
    </Sidebar>
  );
}
