import { useCollapsible } from "@astryxdesign/core/Collapsible";
import { Stack } from "@astryxdesign/core/Stack";
import { AstryxSlot as Slot } from "./astryx-slot";
import * as React from "react";

type CollapsibleRootProps = React.ComponentProps<"div"> & { open?: boolean; defaultOpen?: boolean; onOpenChange?: (open: boolean) => void; disabled?: boolean; asChild?: boolean };
type CollapsibleTriggerProps = React.ComponentProps<"button"> & { asChild?: boolean };
type CollapsibleContentProps = React.ComponentProps<"div"> & { forceMount?: true };
import { Button } from "./button";

type State = { open: boolean; disabled?: boolean; toggle: () => void; contentId: string };
const Context = React.createContext<State | null>(null);
function useStateContext() { const value = React.useContext(Context); if (!value) throw new Error("Collapsible composition requires Collapsible"); return value; }
function Collapsible({ children, open, defaultOpen = false, onOpenChange, disabled, asChild, ...props }: CollapsibleRootProps) {
  const state = useCollapsible({ isCollapsible: { isOpen: open, defaultIsOpen: defaultOpen, onOpenChange } });
  const contentId = React.useId();
  // 2026-11-11: 기존 중첩 컴포지션과 비제어 기본 닫힘을 유지하면서 Astryx 상태를 사용한다.
  return <Context.Provider value={{ open: state.isOpen, toggle: state.toggle, disabled, contentId }}><Stack {...props}>{children}</Stack></Context.Provider>;
}
function CollapsibleTrigger({ children, asChild, onClick, disabled, ...props }: CollapsibleTriggerProps) {
  const state = useStateContext(); const Component = asChild ? Slot : Button;
  return <Component {...props} type="button" disabled={disabled || state.disabled} aria-expanded={state.open} aria-controls={state.contentId}
    onClick={event => { onClick?.(event); if (!event.defaultPrevented && !state.disabled) state.toggle(); }}>{children}</Component>;
}
function CollapsibleContent({ children, forceMount, ...props }: CollapsibleContentProps) {
  const state = useStateContext();
  return state.open || forceMount ? <Stack {...props} id={state.contentId} hidden={!state.open}>{children}</Stack> : null;
}
export { Collapsible, CollapsibleContent, CollapsibleTrigger };
