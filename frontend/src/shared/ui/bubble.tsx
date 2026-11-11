import * as React from "react";
import {ChatMessageBubble} from "@astryxdesign/core/Chat";
import {VStack} from "@astryxdesign/core/VStack";
function Bubble({children, variant, align: _align, ...props}: React.ComponentProps<"div"> & {variant?: "default" | "secondary" | "muted" | "tinted" | "outline" | "ghost" | "destructive"; align?: "start" | "end"}) { return <ChatMessageBubble {...props} data-slot="bubble" variant={variant === "ghost" ? "ghost" : "filled"}>{children}</ChatMessageBubble>; }
function BubbleContent({asChild: _asChild, ...props}: React.ComponentProps<"div"> & {asChild?: boolean}) { return <VStack {...props} data-slot="bubble-content" />; }
export {Bubble, BubbleContent};
