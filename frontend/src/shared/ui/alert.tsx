import * as React from "react";
import {Banner} from "@astryxdesign/core/Banner";
import {VStack} from "@astryxdesign/core/VStack";
import {Text} from "@astryxdesign/core/Text";
function Alert({children, variant, role = "alert", ...props}: React.ComponentProps<"div"> & {variant?: "default" | "destructive"}) { return <Banner {...props} data-slot="alert" role={role} status={variant === "destructive" ? "error" : "info"} title={children} />; }
function AlertTitle(props: React.ComponentProps<"div">) { return <VStack {...props} data-slot="alert-title" />; }
function AlertDescription({children, color: _color, ...props}: React.ComponentProps<"div">) { return <Text {...props} data-slot="alert-description">{children}</Text>; }
export {Alert, AlertTitle, AlertDescription};
