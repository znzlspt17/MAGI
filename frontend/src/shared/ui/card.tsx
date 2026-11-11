import * as React from "react";
import {Card as AstryxCard} from "@astryxdesign/core/Card";
import {VStack} from "@astryxdesign/core/VStack";
import {Text} from "@astryxdesign/core/Text";

// 2026-11-11: 공통 카드 외형과 내부 간격을 Astryx 컴포넌트가 담당한다.
function Card(props: React.ComponentProps<"div">) { return <AstryxCard {...props} data-slot="card" />; }
function CardHeader(props: React.ComponentProps<"div">) { return <VStack {...props} data-slot="card-header" gap={2} />; }
function CardTitle({color: _color, children, ...props}: React.ComponentProps<"div">) { return <Text {...props} data-slot="card-title" weight="bold">{children}</Text>; }
function CardDescription({color: _color, children, ...props}: React.ComponentProps<"div">) { return <Text {...props} data-slot="card-description" type="supporting">{children}</Text>; }
function CardContent(props: React.ComponentProps<"div">) { return <VStack {...props} data-slot="card-content" />; }
export {Card, CardContent, CardDescription, CardHeader, CardTitle};
