import { Drawer } from "@astryxdesign/core/Drawer";
import { Stack } from "@astryxdesign/core/Stack";
import * as React from "react";

type SheetRootProps = { children?: React.ReactNode; open?: boolean; defaultOpen?: boolean; onOpenChange?: (open: boolean) => void; modal?: boolean };
type SheetContentProps = React.ComponentProps<"div"> & { onCloseAutoFocus?: (event: Event) => void };
import { Button } from "./button";
import { XIcon } from "./icons";

type SheetState = { open: boolean; setOpen: (open: boolean) => void; titleId: string; descriptionId: string };
const Context = React.createContext<SheetState | null>(null);
function useSheet() { const value = React.useContext(Context); if (!value) throw new Error("Sheet composition requires Sheet"); return value; }
function Sheet({ open, defaultOpen, onOpenChange, children }: SheetRootProps) {
  const [internal, setInternal] = React.useState(defaultOpen ?? false);
  const titleId = React.useId(), descriptionId = React.useId();
  return <Context.Provider value={{ open: open ?? internal, setOpen: value => { if (open === undefined) setInternal(value); onOpenChange?.(value); }, titleId, descriptionId }}>{children}</Context.Provider>;
}
function SheetContent({ children, className, side = "right", showCloseButton = true, onCloseAutoFocus, onKeyDown, ref, ...props }: SheetContentProps & { side?: "top" | "right" | "bottom" | "left"; showCloseButton?: boolean }) {
  const { open, setOpen, titleId, descriptionId } = useSheet();
  const previous = React.useRef(open), onCloseRef = React.useRef(onCloseAutoFocus); onCloseRef.current = onCloseAutoFocus;
  React.useEffect(() => {
    if (previous.current && !open) onCloseRef.current?.(new Event("closeAutoFocus", { cancelable: true }));
    previous.current = open;
  }, [open]);
  // 2026-11-11: 관리자 상세와 모바일 탐색은 같은 modal 포커스 복귀 계약을 공유한다.
  return <Drawer {...props as unknown as React.ComponentProps<typeof Drawer>} ref={ref as unknown as React.Ref<HTMLDialogElement>} width={side === "left" ? "18rem" : undefined} isOpen={open} onOpenChange={setOpen} label="상세 패널" side={side === "left" ? "start" : "end"} className={className}
    aria-labelledby={titleId} aria-describedby={descriptionId} onKeyDown={onKeyDown as unknown as React.KeyboardEventHandler<HTMLDialogElement>}>
    {open && children}{open && showCloseButton && <Button variant="ghost" size="icon-sm" aria-label="닫기" onClick={() => setOpen(false)}><XIcon aria-hidden /></Button>}
  </Drawer>;
}
function SheetHeader({ children, className }: React.ComponentProps<"div">) { return <Stack gap={2} className={className}>{children}</Stack>; }
function SheetTitle({ children, ...props }: React.ComponentProps<"h2">) { const { titleId } = useSheet(); return <h2 {...props} id={titleId}>{children}</h2>; }
function SheetDescription({ children, ...props }: React.ComponentProps<"p">) { const { descriptionId } = useSheet(); return <p {...props} id={descriptionId}>{children}</p>; }
export { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle };
