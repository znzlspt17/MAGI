import * as React from "react";
import {Item as AstryxItem} from "@astryxdesign/core/Item";
import {VStack} from "@astryxdesign/core/VStack";
import {HStack} from "@astryxdesign/core/HStack";
import {Text} from "@astryxdesign/core/Text";
// 2026-11-11: 항목의 내부 구성을 유지하면서 Astryx 행과 스택으로 렌더링한다.
function Item({children, variant: _variant, size: _size, asChild: _asChild, ...props}: React.ComponentProps<"div"> & {variant?: "default" | "outline" | "muted"; size?: "default" | "sm"; asChild?: boolean}) { return <AstryxItem {...(props as unknown as React.ComponentProps<typeof AstryxItem>)} data-slot="item" label={children} />; }
function ItemGroup(props: React.ComponentProps<"div">) { return <VStack {...props} data-slot="item-group" />; }
function ItemContent(props: React.ComponentProps<"div">) { return <VStack {...props} data-slot="item-content" />; }
function ItemTitle({children, color: _color, ...props}: React.ComponentProps<"div">) { return <Text {...props} data-slot="item-title" weight="bold">{children}</Text>; }
function ItemDescription({children, color: _color, ...props}: React.ComponentProps<"p">) { return <Text {...props} data-slot="item-description" type="supporting">{children}</Text>; }
function ItemActions(props: React.ComponentProps<"div">) { return <HStack {...props} data-slot="item-actions" />; }
export {Item, ItemGroup, ItemContent, ItemTitle, ItemDescription, ItemActions};
