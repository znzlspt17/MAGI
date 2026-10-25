// shadcn/ui sidebar-07/nav-user layout, adapted for MAGI's identifier-only accounts.
import { UserCircleIcon, CaretUpDownIcon, SignOutIcon, CopyIcon } from "@phosphor-icons/react";
import { useAuth } from "../Auth";
import { formatTime } from "../UI";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "./ui/dropdown-menu";
import { SidebarMenu, SidebarMenuItem, SidebarMenuButton, useSidebar } from "./ui/sidebar";

export function NavUser() {
  const auth = useAuth();
  const { isMobile } = useSidebar();
  if (!auth.user) return <div className="sidebar-local-account"><UserCircleIcon weight="duotone" size={22} aria-hidden /><span>로컬 작업 공간</span></div>;
  return <SidebarMenu><SidebarMenuItem><DropdownMenu>
    <DropdownMenuTrigger asChild><SidebarMenuButton size="lg" className="sidebar-account-trigger" aria-label="내 계정">
      <UserCircleIcon weight="duotone" size={30} aria-hidden /><span className="sidebar-account-name"><strong>내 작업 공간</strong><small>{auth.user.role === "admin" ? "관리자" : "일반 사용자"}</small></span><CaretUpDownIcon size={16} aria-hidden />
    </SidebarMenuButton></DropdownMenuTrigger>
    <DropdownMenuContent className="account-menu-content" side={isMobile ? "bottom" : "right"} align="end" sideOffset={8}>
      <DropdownMenuLabel>내 계정</DropdownMenuLabel>
      <p>사용자 ID: {auth.user.id}</p>
      <p>권한: {auth.user.role === "admin" ? "관리자" : "일반 사용자"}</p>
      {auth.usage && <p>오늘 실행 {auth.usage.runs}회 · 실행 제한 없음{auth.usage.limit_reached || auth.usage.runs_exceeded ? " · 관측 기준 초과" : ""} · 갱신 {auth.usage.resets_at ? formatTime(auth.usage.resets_at) : "확인 중"}</p>}
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={() => void navigator.clipboard.writeText(auth.user!.id).then(() => auth.setNotice("사용자 ID를 복사했습니다.")).catch(() => auth.setNotice("표시된 ID를 직접 복사하세요."))}><CopyIcon size={18} aria-hidden />사용자 ID 복사</DropdownMenuItem>
      {auth.user.role === "admin" && <DropdownMenuItem asChild><a href="/admin">관리자 페이지</a></DropdownMenuItem>}
      <DropdownMenuItem onSelect={() => void auth.logout()}><SignOutIcon size={18} aria-hidden />로그아웃</DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu></SidebarMenuItem></SidebarMenu>;
}
