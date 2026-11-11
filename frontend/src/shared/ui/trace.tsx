import * as React from "react";
import {VStack} from "@astryxdesign/core/VStack";
import {HStack} from "@astryxdesign/core/HStack";
import {Text} from "@astryxdesign/core/Text";
import {CaretRightIcon} from "@phosphor-icons/react";
import {Collapsible, CollapsibleContent, CollapsibleTrigger} from "./collapsible";
function Trace(props: React.ComponentProps<"div">) { return <VStack {...props} data-slot="trace" />; }
function TraceLine({status, ...props}: React.ComponentProps<"span"> & {status?: "running" | "error" | "pending"}) { return <HStack {...(props as unknown as React.ComponentProps<typeof HStack>)} as="span" data-slot="trace-line" data-status={status} />; }
function TraceIcon(props: React.ComponentProps<"span">) { return <HStack {...(props as unknown as React.ComponentProps<typeof HStack>)} as="span" data-slot="trace-icon" aria-hidden="true" />; }
function TraceTitle({children, color: _color, ...props}: React.ComponentProps<"span">) { return <Text {...props} as="span" data-slot="trace-title">{children}</Text>; }
function TraceCollapsible(props: React.ComponentProps<typeof Collapsible>) { return <Collapsible {...props} data-slot="trace-collapsible" />; }
function TraceCollapsibleTrigger({children, ...props}: React.ComponentProps<typeof CollapsibleTrigger>) { return <CollapsibleTrigger {...props} data-slot="trace-collapsible-trigger">{children}<TraceIcon><CaretRightIcon size={16} aria-hidden /></TraceIcon></CollapsibleTrigger>; }
function TraceCollapsibleContent({children, ...props}: React.ComponentProps<typeof CollapsibleContent>) { return <CollapsibleContent {...props} data-slot="trace-collapsible-content"><VStack data-slot="trace-collapsible-content-inner">{children}</VStack></CollapsibleContent>; }
export {Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle};
