import { Dialog as AstryxDialog } from "@astryxdesign/core/Dialog";
import { Stack } from "@astryxdesign/core/Stack";
import { AstryxSlot as Slot } from "./astryx-slot";
import * as React from "react";

type DialogRootProps = { children?: React.ReactNode; open?: boolean; defaultOpen?: boolean; onOpenChange?: (open: boolean) => void; modal?: boolean };
type DialogTriggerProps = React.ComponentProps<"button"> & { asChild?: boolean };
type DialogContentProps = React.ComponentProps<"div"> & { onCloseAutoFocus?: (event: Event) => void };
import { Button } from "./button";
import { XIcon } from "./icons";

type DialogContextValue = { open: boolean; setOpen: (value: boolean) => void; titleId: string; descriptionId: string };
const DialogContext = React.createContext<DialogContextValue | null>(null);
function useDialog() { const context = React.useContext(DialogContext); if (!context) throw new Error("Dialog composition requires Dialog"); return context; }
function Dialog({ children, open, defaultOpen, onOpenChange }: DialogRootProps) {
  const [internal, setInternal] = React.useState(defaultOpen ?? false);
  const titleId = React.useId(), descriptionId = React.useId();
  const setOpen = (value: boolean) => { if (open === undefined) setInternal(value); onOpenChange?.(value); };
  return <DialogContext.Provider value={{ open: open ?? internal, setOpen, titleId, descriptionId }}>{children}</DialogContext.Provider>;
}
function DialogTrigger({ children, asChild, onClick, ...props }: DialogTriggerProps) {
  const { setOpen } = useDialog(); const Component = asChild ? Slot : "button";
  return <Component {...props} onClick={event => { onClick?.(event); if (!event.defaultPrevented) setOpen(true); }}>{children}</Component>;
}
function DialogPortal({ children }: { children?: React.ReactNode }) { return <>{children}</>; }
function DialogOverlay(_props: React.ComponentProps<"div">) { return null; }
function DialogContent({ children, className, showCloseButton = true, onCloseAutoFocus, onKeyDown, ref, ...props }: DialogContentProps & { showCloseButton?: boolean }) {
  const { open, setOpen, titleId, descriptionId } = useDialog();
  const previousOpen = React.useRef(open), onCloseRef = React.useRef(onCloseAutoFocus); onCloseRef.current = onCloseAutoFocus;
  React.useEffect(() => {
    if (previousOpen.current && !open && onCloseRef.current) {
      // 2026-11-11: 원래 입력란 등 명시적인 복귀 대상이 있는 호출부의 포커스 정책을 보존한다.
      onCloseRef.current?.(new Event("closeAutoFocus", { cancelable: true }));
    }
    previousOpen.current = open;
  }, [open]);
  return <AstryxDialog {...props as unknown as React.ComponentProps<typeof AstryxDialog>} ref={ref as unknown as React.Ref<HTMLDialogElement>} isOpen={open} onOpenChange={setOpen} className={className} aria-labelledby={props["aria-labelledby"] ?? titleId} aria-describedby={props["aria-describedby"] ?? descriptionId} onKeyDown={event => { onKeyDown?.(event as unknown as React.KeyboardEvent<HTMLDivElement>); if (event.key === "Escape" && !event.defaultPrevented) { event.preventDefault(); setOpen(false); } }}>
    {open && children}
    {open && showCloseButton && <Button className="magi-dialog-close" variant="ghost" size="icon-sm" aria-label="닫기" onClick={() => setOpen(false)}><XIcon aria-hidden /></Button>}
  </AstryxDialog>;
}
function DialogHeader({ children, className }: React.ComponentProps<"div">) { return <Stack className={className} gap={2}>{children}</Stack>; }
function DialogFooter({ children, className, showCloseButton = false }: React.ComponentProps<"div"> & { showCloseButton?: boolean }) { const { setOpen } = useDialog(); return <Stack direction="horizontal" wrap="wrap" gap={2} className={className}>{children}{showCloseButton && <Button onClick={() => setOpen(false)}>닫기</Button>}</Stack>; }
function DialogTitle({ children, ...props }: React.ComponentProps<"h2">) { const { titleId } = useDialog(); return <h2 {...props} id={titleId}>{children}</h2>; }
function DialogDescription({ children, ...props }: React.ComponentProps<"p">) { const { descriptionId } = useDialog(); return <p {...props} id={descriptionId}>{children}</p>; }
export { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogOverlay, DialogPortal, DialogTitle, DialogTrigger };
