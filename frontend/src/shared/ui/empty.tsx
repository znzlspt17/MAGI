import * as React from "react";
import {VStack} from "@astryxdesign/core/VStack";
import {Text} from "@astryxdesign/core/Text";
function Empty(props: React.ComponentProps<"div">) { return <VStack {...props} data-slot="empty" />; }
function EmptyHeader(props: React.ComponentProps<"div">) { return <VStack {...props} data-slot="empty-header" />; }
function EmptyTitle({children, color: _color, ...props}: React.ComponentProps<"div">) { return <Text {...props} data-slot="empty-title" weight="bold">{children}</Text>; }
function EmptyDescription({children, color: _color, ...props}: React.ComponentProps<"p">) { return <Text {...props} data-slot="empty-description" type="supporting">{children}</Text>; }
export {Empty, EmptyHeader, EmptyTitle, EmptyDescription};
