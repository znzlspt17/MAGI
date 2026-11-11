import { TabList, Tab } from "@astryxdesign/core/TabList";
import { Stack } from "@astryxdesign/core/Stack";
import * as React from "react";

type TabsRootProps = React.ComponentProps<"div"> & { value?: string; defaultValue?: string; onValueChange?: (value: string) => void; orientation?: "horizontal" | "vertical" };
type TabsTriggerProps = React.ComponentProps<"button"> & { value: string };
type TabsContentProps = React.ComponentProps<"div"> & { value: string; forceMount?: true };

type State = { value: string; setValue: (value: string) => void; baseId: string };
const Context = React.createContext<State | null>(null);
function useTabs() { const value = React.useContext(Context); if (!value) throw new Error("Tabs composition requires Tabs"); return value; }
function textOf(node: React.ReactNode): string { return React.Children.toArray(node).map(child => typeof child === "string" || typeof child === "number" ? String(child) : React.isValidElement<{ children?: React.ReactNode }>(child) ? textOf(child.props.children) : "").join(""); }
function Tabs({ children, value, defaultValue = "", onValueChange, orientation: _orientation, ...props }: TabsRootProps) {
  const [internal, setInternal] = React.useState(defaultValue);
  const baseId = React.useId();
  // 2026-11-11: 기존 제어형 탭의 값과 패널을 유지하고 Astryx가 키보드 이동을 담당한다.
  return <Context.Provider value={{ baseId, value: value ?? internal, setValue: next => { if (value === undefined) setInternal(next); onValueChange?.(next); } }}><Stack {...props} data-slot="tabs">{children}</Stack></Context.Provider>;
}
function TabsList({ children, className, variant: _variant, ...props }: React.ComponentProps<"div"> & { variant?: "default" | "line" }) {
  const { value, setValue } = useTabs();
  return <TabList {...props} value={value} onChange={setValue} role="tablist" className={className}>{children}</TabList>;
}
function TabsTrigger({ children, value, className, disabled, ...props }: TabsTriggerProps) {
  const { baseId } = useTabs();
  const label = props["aria-label"] || textOf(children);
  const icon = React.Children.toArray(children).find(child => React.isValidElement(child) && typeof child.type !== "string");
  return <Tab {...props} value={value} label={label} icon={icon} className={className} aria-disabled={disabled || props["aria-disabled"]} id={props.id || `${baseId}-tab-${value}`} panelId={props["aria-controls"] || `${baseId}-panel-${value}`} />;
}
function TabsContent({ children, value, forceMount, className, ...props }: TabsContentProps) {
  const state = useTabs(), selected = state.value === value;
  return selected || forceMount ? <Stack as="div" role="tabpanel" hidden={!selected} className={className} id={`${state.baseId}-panel-${value}`} aria-labelledby={`${state.baseId}-tab-${value}`} {...props}>{children}</Stack> : null;
}
const tabsListVariants = () => "";
export { Tabs, TabsContent, TabsList, tabsListVariants, TabsTrigger };
