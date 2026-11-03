// Adapted from shadcn/ui sidebar-07 (MIT), revision ba1503c64472b82256d9de95e2e62c5901a38e8b.
import type { ReactNode } from "react";
import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarRail, useSidebar } from "../../shared/ui/sidebar";
import { NavUser } from "../auth/NavUser";
import { ScalesIcon } from "@phosphor-icons/react";

export function AppSidebar({ children }: { children: ReactNode }) {
  const { setOpenMobile } = useSidebar();
  return (
    <Sidebar variant="sidebar" className="sidebar">
      <SidebarHeader className="sidebar-brand">
        <a href="/" className="brand"><span className="brand-mark"><ScalesIcon weight="duotone" size={20} aria-hidden /></span><span>MAGI</span></a>
      </SidebarHeader>
      <SidebarContent className="navigation" onClick={(event) => {
        const target = event.target as HTMLElement;
        if (target.closest("a, .primary-nav button, .new-job")) setOpenMobile(false);
      }}>{children}</SidebarContent>
      <SidebarFooter className="sidebar-footer">
        <NavUser />
      </SidebarFooter>
      <SidebarRail aria-label="작업 메뉴 접기 또는 펼치기" />
    </Sidebar>
  );
}
