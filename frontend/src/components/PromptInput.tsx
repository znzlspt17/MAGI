// shadcn/ui Radix AI Elements Prompt Input composition (MIT), revision ba1503c64472b82256d9de95e2e62c5901a38e8b.
import { useLayoutEffect, useRef, useState, type ComponentProps, type KeyboardEvent } from "react";
import { ArrowUpIcon, ArrowsOutSimpleIcon } from "@phosphor-icons/react";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from "./ui/input-group";
import { Dialog, DialogTrigger, DialogContent, DialogTitle, DialogDescription } from "./ui/dialog";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "./ui/tooltip";
import { Button } from "./ui/button";

export function ExpandableTextarea({ label, disabled, maxLength = 20000, ...props }: ComponentProps<"textarea"> & { label: string }) {
  const input = useRef<HTMLTextAreaElement>(null);
  const [expanded, setExpanded] = useState(false);
  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    const resize = () => {
      const style = getComputedStyle(element);
      const line = parseFloat(style.lineHeight) || 27;
      const padding = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
      const maximum = Math.min(line * 6 + padding, Math.max(line + padding, (window.visualViewport?.height || window.innerHeight) * .3));
      element.style.height = "0px";
      element.style.height = `${Math.min(Math.max(element.scrollHeight, line + padding), maximum)}px`;
      element.style.overflowY = element.scrollHeight > maximum ? "auto" : "hidden";
    };
    resize();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(element);
    window.visualViewport?.addEventListener("resize", resize);
    return () => { observer?.disconnect(); window.visualViewport?.removeEventListener("resize", resize); };
  }, [props.value]);
  return <div className="expandable-input">
    <InputGroupTextarea {...props} ref={input} rows={1} disabled={disabled} aria-label={label} maxLength={maxLength} />
    <Dialog open={expanded} onOpenChange={setExpanded}>
      <TooltipProvider><Tooltip><TooltipTrigger asChild><DialogTrigger asChild><Button type="button" variant="ghost" size="icon-sm" className="expand-input" disabled={disabled} aria-label={`${label} 크게 쓰기`}><ArrowsOutSimpleIcon size={17} aria-hidden /></Button></DialogTrigger></TooltipTrigger><TooltipContent>크게 쓰기</TooltipContent></Tooltip></TooltipProvider>
      <DialogContent className="expanded-editor" onKeyDown={event => event.stopPropagation()} onCloseAutoFocus={event => { event.preventDefault(); input.current?.focus(); }}>
        <DialogTitle>{label} 크게 쓰기</DialogTitle>
        <DialogDescription>작성 내용은 자동으로 반영됩니다. 닫은 뒤 원래 화면에서 제출하세요.</DialogDescription>
        <InputGroupTextarea value={props.value} onChange={props.onChange} disabled={disabled} maxLength={maxLength} aria-label={`${label} 전체 편집`} autoFocus />
      </DialogContent>
    </Dialog>
  </div>;
}

export function isSubmitShortcut(event: KeyboardEvent): boolean {
  return event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229;
}

export function PromptInput({ onSend, disabled, label, buttonLabel, maxLength = 20000, ...props }: Omit<ComponentProps<"textarea">, "onSubmit"> & {
  onSend: () => void;
  label: string;
  buttonLabel: string;
}) {
  return <InputGroup className="chat-prompt" data-disabled={disabled || undefined}>
    <ExpandableTextarea {...props} label={label} maxLength={maxLength} onKeyDown={(event) => {
      props.onKeyDown?.(event);
      if (!event.defaultPrevented && isSubmitShortcut(event)) { event.preventDefault(); if (!disabled) onSend(); }
    }} />
    <InputGroupAddon align="block-end" className="chat-prompt-footer"><span>Enter로 줄바꿈 · Ctrl/⌘ + Enter로 전송</span><InputGroupButton variant="default" size="sm" disabled={disabled} onClick={onSend} aria-label={buttonLabel}>{buttonLabel}<ArrowUpIcon size={17} aria-hidden /></InputGroupButton></InputGroupAddon>
  </InputGroup>;
}
