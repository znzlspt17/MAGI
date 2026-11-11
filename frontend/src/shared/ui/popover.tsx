import { Stack } from "@astryxdesign/core/Stack";
import { Popover as AstryxPopover } from "@astryxdesign/core/Popover";
import * as React from "react";

type PopoverTriggerProps = React.ComponentProps<"button"> & { asChild?: boolean };
type PopoverContentProps = React.ComponentProps<"div"> & { side?: "top" | "bottom" | "left" | "right"; align?: "start" | "center" | "end"; sideOffset?: number; onEscapeKeyDown?: (event: KeyboardEvent) => void };
type PopoverRootProps = { children?: React.ReactNode; open?: boolean; defaultOpen?: boolean; onOpenChange?: (open: boolean) => void; modal?: boolean };

function PopoverTrigger({ children }: PopoverTriggerProps) { return <>{children}</>; }
function PopoverContent(_props: PopoverContentProps) { return null; }
function Popover({ children, open, defaultOpen, onOpenChange, modal }: PopoverRootProps) {
  const [internal, setInternal] = React.useState(defaultOpen ?? false);
  const parts = React.Children.toArray(children).filter(React.isValidElement);
  const trigger = parts.find(part => part.type === PopoverTrigger) as React.ReactElement<React.ComponentProps<typeof PopoverTrigger>> | undefined;
  const content = parts.find(part => part.type === PopoverContent) as React.ReactElement<React.ComponentProps<typeof PopoverContent>> | undefined;
  if (!trigger) return null;
  const side = content?.props.side;
  const placement = side === "top" ? "above" : side === "bottom" ? "below" : side === "left" ? "start" : side === "right" ? "end" : undefined;
  // 2026-11-11: 기존 제어형 및 비제어형 공개 API를 Astryx 팝오버에 연결한다.
  return <Stack onKeyDown={event => {
    content?.props.onKeyDown?.(event as React.KeyboardEvent<HTMLDivElement>);
    if (event.key === "Escape" && (open ?? internal)) {
      content?.props.onEscapeKeyDown?.(event.nativeEvent);
      // 2026-11-11: 열린 팝오버가 Escape를 먼저 처리해 상위 대화상자까지 닫히지 않게 한다.
      event.stopPropagation();
      if (!event.defaultPrevented && !event.nativeEvent.defaultPrevented) { event.preventDefault(); if (open === undefined) setInternal(false); onOpenChange?.(false); }
    }
  }}><AstryxPopover label="상세 정보" content={content?.props.children} className={content?.props.className} placement={placement}
    alignment={content?.props.align} isOpen={open ?? internal} isModal={modal ?? false}
    onOpenChange={value => { if (open === undefined) setInternal(value); onOpenChange?.(value); }}>
    {trigger.props.children}
  </AstryxPopover></Stack>;
}
export { Popover, PopoverContent, PopoverTrigger };
