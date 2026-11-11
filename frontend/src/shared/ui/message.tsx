import * as React from "react";
import {VStack} from "@astryxdesign/core/VStack";
import {ChatMessage} from "@astryxdesign/core/Chat";
import {Text} from "@astryxdesign/core/Text";
function Message({align = "start", children, ...props}: React.ComponentProps<"div"> & {align?: "start" | "end"}) { return <ChatMessage {...props} sender={align === "end" ? "user" : "assistant"} data-slot="message" data-align={align}>{children}</ChatMessage>; }
function MessageContent(props: React.ComponentProps<"div">) { return <VStack {...props} data-slot="message-content" />; }
function MessageHeader({children, color: _color, ...props}: React.ComponentProps<"div">) { return <Text {...props} data-slot="message-header" type="supporting">{children}</Text>; }
function MessageFooter({children, color: _color, ...props}: React.ComponentProps<"div">) { return <Text {...props} data-slot="message-footer" type="supporting">{children}</Text>; }
export {Message, MessageContent, MessageHeader, MessageFooter};
