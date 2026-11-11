import * as React from "react";
import {Button as AstryxButton} from "@astryxdesign/core/Button";
import {HStack} from "@astryxdesign/core/HStack";
import {IconButton} from "@astryxdesign/core/IconButton";
import {Icon} from "@astryxdesign/core/Icon";
type ButtonVariant = "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
type ButtonSize = "default" | "xs" | "sm" | "lg" | "icon" | "icon-xs" | "icon-sm" | "icon-lg";

function textOf(node: React.ReactNode): string {
  return React.Children.toArray(node).map(child => {
    if (typeof child === "string" || typeof child === "number") return String(child);
    if (React.isValidElement<{children?: React.ReactNode}>(child)) return textOf(child.props.children);
    return "";
  }).join("");
}

// 2026-11-11: 기존 버튼 계약을 Astryx에 연결해 호출부의 링크와 접근성 이름을 보존한다.
function Button({variant = "secondary", size = "default", asChild = false, children, disabled, ...props}: Omit<React.ComponentProps<"button">, "size"> & {variant?: ButtonVariant; size?: ButtonSize; asChild?: boolean}) {
  const child = asChild && React.isValidElement<React.ComponentProps<"a">>(children) ? children : undefined;
  const content = child ? child.props.children : children;
  const label = props["aria-label"] || textOf(content).trim() || "버튼";
  const mappedVariant = variant === "default" ? "primary" : variant === "destructive" ? "destructive" : variant === "ghost" || variant === "link" ? "ghost" : "secondary";
  const mappedSize = size === "lg" || size === "icon-lg" ? "lg" : size === "sm" || size === "xs" || size === "icon-sm" || size === "icon-xs" ? "sm" : "md";
  const childProps = child?.props;
  const merged: Record<string, unknown> = {...props, ...childProps};
  if (childProps) {
    for (const [key, outer] of Object.entries(props)) {
      const inner = (childProps as Record<string, unknown>)[key];
      if (/^on[A-Z]/.test(key) && typeof outer === "function" && typeof inner === "function") {
        merged[key] = (event: {defaultPrevented?: boolean}) => { inner(event); if (!event.defaultPrevented) outer(event); };
      }
    }
    merged.className = [props.className, childProps.className].filter(Boolean).join(" ");
    merged.style = {...props.style, ...childProps.style};
    const refs = [props.ref, childProps.ref] as React.Ref<HTMLElement>[];
    merged.ref = (node: HTMLElement | null) => {
      const cleanups = refs.map(ref => { if (typeof ref === "function") return ref(node); if (ref) ref.current = node; });
      if (node) return () => refs.forEach((ref, index) => { const cleanup = cleanups[index]; if (typeof cleanup === "function") cleanup(); else if (typeof ref === "function") ref(null); else if (ref) ref.current = null; });
    };
  }
  const iconElement = size.startsWith("icon") ? React.Children.toArray(content).find(node => React.isValidElement(node) && typeof node.type !== "string") : undefined;
  if (React.isValidElement(iconElement)) {
    const IconComponent = iconElement.type as React.ComponentType<React.SVGProps<SVGSVGElement>>;
    return <IconButton {...(merged as unknown as React.ComponentProps<typeof IconButton>)} type={props.type ?? "submit"} data-slot={(merged["data-slot"] as string | undefined) ?? "button"} label={label} variant={mappedVariant} size={mappedSize} isDisabled={disabled} icon={<Icon icon={IconComponent} />} />;
  }
  return <AstryxButton {...(merged as unknown as React.ComponentProps<typeof AstryxButton>)} type={props.type ?? "submit"} data-slot={(merged["data-slot"] as string | undefined) ?? "button"} label={label} variant={mappedVariant} size={mappedSize} isDisabled={disabled}><HStack gap={2} vAlign="center">{content}</HStack></AstryxButton>;
}

export {Button};
