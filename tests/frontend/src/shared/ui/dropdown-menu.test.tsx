import {createRef} from "react";
import {cleanup, fireEvent, render, screen} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {CopyIcon} from "@phosphor-icons/react";
import {DropdownMenu,DropdownMenuTrigger,DropdownMenuContent,DropdownMenuLabel,DropdownMenuItem} from "@/shared/ui/dropdown-menu";
afterEach(cleanup);
it("메뉴는 콘텐츠 클래스와 정보 영역 및 아이콘·행 ref와 이벤트를 보존한다", async () => {
 const ref=createRef<HTMLDivElement>(); const select=vi.fn();
 render(<DropdownMenu><DropdownMenuTrigger><button>계정</button></DropdownMenuTrigger><DropdownMenuContent className="account-menu-content"><DropdownMenuLabel className="account-menu-heading">내 계정</DropdownMenuLabel><DropdownMenuItem className="copy-row" ref={ref} onSelect={select}><CopyIcon aria-hidden />복사</DropdownMenuItem></DropdownMenuContent></DropdownMenu>);
 fireEvent.click(screen.getByRole("button",{name:"계정"}));
 const item=await screen.findByRole("menuitem",{name:"복사"});
 expect(document.querySelector(".account-menu-content")).toBeTruthy(); expect(document.querySelector(".account-menu-heading")).toBeTruthy();
 expect(item.classList.contains("copy-row")).toBe(true); expect(item.querySelector("svg")).toBeTruthy(); expect(ref.current).toBe(item);
 fireEvent.click(item); expect(select).toHaveBeenCalledOnce();
});
it("메뉴 콘텐츠의 data 속성과 ref를 열린 메뉴에 전달한다", async () => {
 const ref=createRef<HTMLDivElement>();
 render(<DropdownMenu><DropdownMenuTrigger><button>설정</button></DropdownMenuTrigger><DropdownMenuContent ref={ref} data-testid="my-menu"><DropdownMenuItem>항목</DropdownMenuItem></DropdownMenuContent></DropdownMenu>);
 fireEvent.click(screen.getByRole("button", {name:"설정"}));
 const menu=await screen.findByRole("menu"); expect(ref.current).toBe(menu); expect(menu.getAttribute("data-testid")).toBe("my-menu");
});

it("선택 취소 이벤트는 메뉴를 열린 상태로 둔다", async () => {
 render(<DropdownMenu><DropdownMenuTrigger><button>선택</button></DropdownMenuTrigger><DropdownMenuContent><DropdownMenuItem onSelect={event => event.preventDefault()}>계속 편집</DropdownMenuItem></DropdownMenuContent></DropdownMenu>);
 fireEvent.click(screen.getByRole("button",{name:"선택"})); fireEvent.click(await screen.findByRole("menuitem",{name:"계속 편집"}));
 expect(screen.getByRole("menu")).toBeTruthy();
});
it("메뉴 링크의 클래스·data·ref와 이벤트를 보존한다", async () => {
 const ref=createRef<HTMLAnchorElement>(); const click=vi.fn();
 render(<DropdownMenu><DropdownMenuTrigger><button>이동</button></DropdownMenuTrigger><DropdownMenuContent><DropdownMenuItem asChild><a href="#privacy" className="menu-link" data-source="account" ref={ref} onClick={click}>안내</a></DropdownMenuItem></DropdownMenuContent></DropdownMenu>);
 fireEvent.click(screen.getByRole("button",{name:"이동"})); const item=await screen.findByRole("menuitem",{name:"안내"});
 expect(item.classList.contains("menu-link")).toBe(true); expect(item.getAttribute("data-source")).toBe("account"); expect(ref.current).toBe(item); fireEvent.click(item); expect(click).toHaveBeenCalledOnce();
});
it("메뉴 링크의 부모와 자식 키 이벤트를 함께 전달한다", async () => {
 const parent=vi.fn(), child=vi.fn();
 render(<DropdownMenu><DropdownMenuTrigger><button>메뉴</button></DropdownMenuTrigger><DropdownMenuContent><DropdownMenuItem asChild onKeyDown={parent}><a href="#help" onKeyDown={child}>도움말</a></DropdownMenuItem></DropdownMenuContent></DropdownMenu>);
 fireEvent.click(screen.getByRole("button",{name:"메뉴"})); fireEvent.keyDown(await screen.findByRole("menuitem",{name:"도움말"}), {key:"a"}); expect(child).toHaveBeenCalledOnce(); expect(parent).toHaveBeenCalledOnce();
});
