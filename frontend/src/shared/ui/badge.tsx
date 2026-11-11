import * as React from "react";
import {Badge as AstryxBadge} from "@astryxdesign/core/Badge";

// 2026-11-11: 기존 상태 표기의 내용을 Astryx 배지로 전달한다.
function Badge({variant, children, asChild: _asChild, ...props}: React.ComponentProps<"span"> & {variant?: "default" | "secondary" | "destructive" | "outline" | "ghost" | "link"; asChild?: boolean}) {
  return <AstryxBadge {...props} data-slot="badge" variant={variant === "destructive" ? "error" : "neutral"} label={children} />;
}
export {Badge};
