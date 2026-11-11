import { Tooltip as AstryxTooltip } from "@astryxdesign/core/Tooltip";
import * as React from "react";

type TooltipProviderProps = { children?: React.ReactNode; delayDuration?: number };
type TooltipTriggerProps = React.ComponentProps<"button"> & { asChild?: boolean };
type TooltipContentProps = React.ComponentProps<"div"> & { side?: "top" | "bottom" | "left" | "right"; align?: "start" | "center" | "end"; sideOffset?: number };
type TooltipRootProps = { children?: React.ReactNode; open?: boolean; defaultOpen?: boolean; onOpenChange?: (open: boolean) => void };

const DelayContext = React.createContext(0);
function TooltipProvider({ delayDuration = 0, children }: TooltipProviderProps) {
  return <DelayContext.Provider value={delayDuration}>{children}</DelayContext.Provider>;
}
function TooltipTrigger({ children }: TooltipTriggerProps) {
  return <>{children}</>;
}
function TooltipContent(_props: TooltipContentProps) { return null; }
function Tooltip({ children, open, defaultOpen, onOpenChange }: TooltipRootProps) {
  const delay = React.useContext(DelayContext);
  const parts = React.Children.toArray(children).filter(React.isValidElement);
  const trigger = parts.find(part => part.type === TooltipTrigger) as React.ReactElement<React.ComponentProps<typeof TooltipTrigger>> | undefined;
  const content = parts.find(part => part.type === TooltipContent) as React.ReactElement<React.ComponentProps<typeof TooltipContent>> | undefined;
  if (!trigger) return null;
  const side = content?.props.side;
  const placement = side === "top" ? "above" : side === "bottom" ? "below" : side === "left" ? "start" : side === "right" ? "end" : undefined;
  // 2026-11-11: 기존 조합 API를 유지해 호출부의 실제 trigger와 비활성 툴팁 조건을 보존한다.
  return <AstryxTooltip content={content?.props.children} placement={placement} alignment={content?.props.align}
    delay={delay} isEnabled={!content?.props.hidden} isOpen={open} isDefaultOpen={defaultOpen} onOpenChange={onOpenChange}>
    {trigger.props.children}
  </AstryxTooltip>;
}
export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger };
