import {DropdownMenu as AstryxMenu, DropdownMenuItem as AstryxItem, DropdownMenuDivider} from "@astryxdesign/core/DropdownMenu";
import {Stack} from "@astryxdesign/core/Stack";
import {AstryxSlot} from "./astryx-slot";
import * as React from "react";

type MenuItemBaseProps = React.ComponentProps<"div"> & {asChild?: boolean; disabled?: boolean; onSelect?: (event: Event) => void};
type MenuTriggerProps = React.ComponentProps<"button"> & {asChild?: boolean};
type MenuContentProps = React.ComponentProps<"div"> & {side?: "top" | "bottom" | "left" | "right"; align?: "start" | "center" | "end"};
type MenuRootProps = {children?: React.ReactNode; open?: boolean; defaultOpen?: boolean; onOpenChange?: (open: boolean) => void; modal?: boolean};
type ItemProps = MenuItemBaseProps & {inset?: boolean; variant?: "default" | "destructive"};
function DropdownMenuTrigger({children}: MenuTriggerProps) { return <>{children}</>; }
function DropdownMenuContent(_props: MenuContentProps) { return null; }
function DropdownMenuItem(_props: ItemProps) { return null; }
function DropdownMenuLabel({inset: _inset, ...props}: React.ComponentProps<"div"> & {inset?: boolean}) { return <Stack {...props} data-slot="dropdown-menu-label" />; }
function DropdownMenuSeparator(_props: React.ComponentProps<"div">) { return null; }
// 2026-11-11: SDK compound 메뉴로 행의 아이콘, DOM 속성과 ref를 그대로 전달한다.
function DropdownMenu({children, open, defaultOpen, onOpenChange}: MenuRootProps) {
 const [internal, setInternal] = React.useState(defaultOpen ?? false);
 const setOpen = (next: boolean) => {if (open === undefined) setInternal(next); onOpenChange?.(next);};
 const parts = React.Children.toArray(children).filter(React.isValidElement);
 const trigger = parts.find(part => part.type === DropdownMenuTrigger) as React.ReactElement<MenuTriggerProps> | undefined;
 const content = parts.find(part => part.type === DropdownMenuContent) as React.ReactElement<MenuContentProps> | undefined;
 const marker = React.useId();
 const contentRef = content?.props.ref;
 React.useLayoutEffect(() => {
   if (!(open ?? internal)) return;
   // 2026-11-11: SDK는 메뉴 ref prop을 제공하지 않아 공개 data 속성으로 실제 메뉴 행 컨테이너를 연결한다.
   const element = [...document.querySelectorAll<HTMLElement>("[data-magi-menu]")].find(node => node.dataset.magiMenu === marker) as HTMLDivElement | undefined;
   if (!element) return;
   const testId = (content?.props as (MenuContentProps & {"data-testid"?: string}) | undefined)?.["data-testid"];
   if (testId) element.setAttribute("data-testid", testId);
   if (!contentRef) return;
   const cleanup = typeof contentRef === "function" ? contentRef(element) : (contentRef.current = element, undefined);
   return () => { if (typeof cleanup === "function") cleanup(); else if (typeof contentRef === "function") contentRef(null); else contentRef.current = null; };
 }, [open, internal, marker, contentRef, content?.props]);
 if (!trigger || !React.isValidElement(trigger.props.children)) return null;
 const child = trigger.props.children as React.ReactElement<Record<string, unknown>>;
 const childrenParts = React.Children.toArray(content?.props.children).filter(React.isValidElement);
 const header = childrenParts.filter(part => part.type !== DropdownMenuItem && part.type !== DropdownMenuSeparator);
 const rows = childrenParts.flatMap(part => {
   if (part.type === DropdownMenuSeparator) return [<DropdownMenuDivider key={part.key} />];
   if (part.type !== DropdownMenuItem) return [];
   const item = part as React.ReactElement<ItemProps>;
   const {children: itemChildren, asChild, disabled, onSelect, inset: _inset, variant, onClick, ref, ...itemProps} = item.props;
   const link = asChild && React.isValidElement<React.ComponentProps<"a">>(itemChildren) ? itemChildren : undefined;
   const {children: _linkChildren, onClick: linkClick, ref: linkRef, ...linkProps} = link?.props ?? {};
   const assignRef = (target: React.Ref<HTMLElement> | undefined, element: HTMLElement | null) => { if (typeof target === "function") return target(element); if (target) target.current = element; };
   const combined: Record<string, unknown> = {...itemProps, ...linkProps};
   for (const [key, outer] of Object.entries(itemProps)) {
     const inner = (linkProps as Record<string, unknown>)[key];
     if (/^on[A-Z]/.test(key) && typeof outer === "function" && typeof inner === "function") combined[key] = (event: {defaultPrevented?: boolean}) => {inner(event); if (!event.defaultPrevented) outer(event);};
   }
   const rowChildren = React.Children.toArray(link?.props.children ?? itemChildren);
   const icon = rowChildren.find(node => React.isValidElement(node) && typeof node.type !== "string");
   const label = rowChildren.filter(node => node !== icon);
   return [<AstryxItem {...combined as unknown as React.ComponentProps<typeof AstryxItem>} className={[itemProps.className, linkProps.className].filter(Boolean).join(" ")} style={{...itemProps.style, ...linkProps.style}} data-slot="dropdown-menu-item" key={part.key} ref={element => { const refs = [ref, linkRef] as (React.Ref<HTMLElement> | undefined)[]; const cleanups = refs.map(target => assignRef(target, element)); if (element) return () => refs.forEach((target, index) => {const cleanup = cleanups[index]; if (typeof cleanup === "function") cleanup(); else assignRef(target, null);}); }} label={label} icon={icon} href={linkProps.href} target={linkProps.target as "_blank" | "_self" | undefined} rel={linkProps.rel} isDisabled={disabled} variant={variant} hasCloseOnSelect={false} onClick={event => { linkClick?.(event as React.MouseEvent<HTMLAnchorElement>); if (!event.defaultPrevented) onClick?.(event as React.MouseEvent<HTMLDivElement>); const selection = new Event("select", {cancelable: true}); if (!event.defaultPrevented) onSelect?.(selection); if (!event.defaultPrevented && !selection.defaultPrevented) setOpen(false); }} />];
 });
 const side = content?.props.side;
 const {children: _children, side: _side, align: _align, ref: _ref, ...contentProps} = content?.props ?? {};
 return <AstryxMenu {...contentProps as Pick<React.ComponentProps<typeof AstryxMenu>, "className" | "style">} presentation="popover" data-magi-menu={marker} isMenuOpen={open ?? internal} onOpenChange={setOpen} menuWidth={280} menuMaxHeight={1200} header={header.length ? <Stack className="magi-menu-header" gap={2}>{header}</Stack> : undefined} placement={side === "right" ? "end" : side === "left" ? "start" : side === "top" ? "above" : "below"} alignment={content?.props.align} renderTrigger={props => <AstryxSlot {...props}>{child}</AstryxSlot>}>{rows}</AstryxMenu>;
}
export {DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger};
