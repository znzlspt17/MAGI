import { HStack } from "@astryxdesign/core/HStack";
// shadcn/ui sidebar-07/nav-user layout, adapted for MAGI's identifier-only accounts.
import { UserCircleIcon, CaretUpDownIcon, SignOutIcon, SignInIcon, CopyIcon, GearIcon, ShieldCheckIcon, CopyrightIcon, BookOpenIcon } from "@phosphor-icons/react";
import { useAuth } from "./Auth";
import { formatTime } from "../../shared/ui/UI";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "../../shared/ui/dropdown-menu";
import { SidebarMenu, SidebarMenuItem, SidebarMenuButton, useSidebar } from "../../shared/ui/sidebar";

export function NavUser() {
  const auth = useAuth();
  const { isMobile } = useSidebar();
  if (!auth.user) return <><HStack gap={2} wrap="wrap" className="sidebar-local-account"><UserCircleIcon weight="duotone" size={20} aria-hidden /><span>로컬 작업 공간</span></HStack><a href="/privacy">정보 처리 안내</a><a href="/licenses">오픈소스 라이선스</a><a href="/research">연구 출처 및 적용 방식</a></>;
  const guest = auth.user.identity_kind === "guest";
  return <SidebarMenu>
    {guest && auth.loginAvailable && <SidebarMenuItem><SidebarMenuButton asChild className="min-h-11 px-2"><a href="/auth/google/start" onClick={auth.rememberLink}><SignInIcon size={18} aria-hidden /><span>로그인해서 기록 이어가기</span></a></SidebarMenuButton></SidebarMenuItem>}
    <SidebarMenuItem><DropdownMenu>
    <DropdownMenuTrigger asChild><SidebarMenuButton size="lg" className="sidebar-account-trigger" aria-label="내 계정">
      <UserCircleIcon weight="duotone" size={20} aria-hidden /><span className="sidebar-account-name"><strong>{guest ? "익명 작업 공간" : "내 계정"}</strong></span><CaretUpDownIcon size={16} aria-hidden />
    </SidebarMenuButton></DropdownMenuTrigger>
    <DropdownMenuContent className="account-menu-content" side={isMobile ? "bottom" : "right"} align="end">
      <DropdownMenuLabel><HStack className="account-menu-heading" gap={2} hAlign="between" vAlign="center"><strong>{guest ? "익명 작업 공간" : "내 계정"}</strong><span className="account-role">{guest ? "익명 사용자" : auth.user.role === "admin" ? "관리자" : "일반 사용자"}</span></HStack></DropdownMenuLabel>
      {guest && <p className="account-details">작업 기록은 서버에 저장되며 이 브라우저에서 30일간 이어갈 수 있습니다. 계정을 연결하면 다른 기기에서도 이어갈 수 있습니다.</p>}
      {auth.usage && <HStack gap={2} wrap="wrap" className="account-usage"><span>오늘 실행 {auth.usage.runs}회</span><span>제한 없음</span>{(auth.usage.limit_reached || auth.usage.runs_exceeded) && <span>관측 기준 초과</span>}</HStack>}
      <details className="account-details"><summary>계정 상세</summary><p>사용자 ID: {auth.user.id}</p>{auth.usage && <p>사용량 갱신: {auth.usage.resets_at ? formatTime(auth.usage.resets_at) : "확인 중"}</p>}</details>
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={() => void navigator.clipboard.writeText(auth.user!.id).then(() => auth.setNotice("사용자 ID를 복사했습니다.")).catch(() => auth.setNotice("표시된 ID를 직접 복사하세요."))}><CopyIcon size={18} aria-hidden />사용자 ID 복사</DropdownMenuItem>
      {auth.user.role === "admin" && <DropdownMenuItem asChild><a href="/admin"><GearIcon size={18} aria-hidden />관리자 페이지</a></DropdownMenuItem>}
      <DropdownMenuItem asChild><a href="/settings/mcp"><GearIcon size={18} aria-hidden />MCP 연결</a></DropdownMenuItem>
      <DropdownMenuItem asChild><a href="/privacy"><ShieldCheckIcon size={18} aria-hidden />정보 처리 안내</a></DropdownMenuItem>
      <DropdownMenuItem asChild><a href="/licenses"><CopyrightIcon size={18} aria-hidden />오픈소스 라이선스</a></DropdownMenuItem>
      <DropdownMenuItem asChild><a href="/research"><BookOpenIcon size={18} aria-hidden />연구 출처 및 적용 방식</a></DropdownMenuItem>
      {!guest && <DropdownMenuItem onSelect={() => void auth.logout()}><SignOutIcon size={18} aria-hidden />로그아웃</DropdownMenuItem>}
    </DropdownMenuContent>
  </DropdownMenu></SidebarMenuItem></SidebarMenu>;
}
