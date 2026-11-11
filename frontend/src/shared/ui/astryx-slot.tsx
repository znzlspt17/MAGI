import * as React from "react";

type SlotProps = React.HTMLAttributes<any> & { children?: React.ReactNode; ref?: React.Ref<any> };
function assignRef(ref: React.Ref<HTMLElement> | undefined, node: HTMLElement | null) {
  if (typeof ref === "function") return ref(node);
  if (ref) ref.current = node;
}
// 2026-11-11: asChild의 이벤트 우선순위와 React 19 ref 정리를 보존하며 단일 실제 요소를 공유한다.
export function AstryxSlot({ children, ref, ...props }: SlotProps) {
  const child = React.Children.only(children) as React.ReactElement<Record<string, unknown>>;
  const childProps = child.props;
  const combined: Record<string, unknown> = { ...props, ...childProps };
  for (const key of Object.keys(props)) {
    const outer = props[key as keyof typeof props], inner = childProps[key];
    if (/^on[A-Z]/.test(key) && typeof outer === "function" && typeof inner === "function") {
      combined[key] = (event: { defaultPrevented?: boolean }) => { inner(event); if (!event.defaultPrevented) outer(event); };
    }
  }
  combined.className = [props.className, childProps.className].filter(Boolean).join(" ") || undefined;
  combined.style = { ...props.style, ...(childProps.style as React.CSSProperties | undefined) };
  const childRef = childProps.ref as React.Ref<HTMLElement> | undefined;
  combined.ref = (node: HTMLElement | null) => {
    const childCleanup = assignRef(childRef, node), parentCleanup = assignRef(ref, node);
    if (node) return () => {
      if (typeof childCleanup === "function") childCleanup(); else assignRef(childRef, null);
      if (typeof parentCleanup === "function") parentCleanup(); else assignRef(ref, null);
    };
  };
  return React.cloneElement(child, combined);
}
