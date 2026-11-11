import * as React from "react";
import {VStack} from "@astryxdesign/core/VStack";
import {HStack} from "@astryxdesign/core/HStack";
import {Button} from "./button";
import {Input} from "./input";
import {Textarea} from "./textarea";

const ComposerContext = React.createContext(false);
// 2026-11-11: 단일 행 그룹과 여러 줄 작성창은 다른 배치와 경계를 사용한다.
function InputGroup({mode = "inline", children, ...props}: React.ComponentProps<"div"> & {mode?: "inline" | "composer"}) {
  const Group = mode === "composer" ? VStack : HStack;
  return <ComposerContext.Provider value={mode === "composer"}><Group {...props} data-slot="input-group" data-mode={mode} role="group">{children}</Group></ComposerContext.Provider>;
}
function InputGroupAddon({align = "inline-start", ...props}: React.ComponentProps<"div"> & {align?: "inline-start" | "inline-end" | "block-start" | "block-end"}) { return <HStack {...props} data-slot="input-group-addon" data-align={align} />; }
function InputGroupButton({type = "button", variant = "ghost", size = "xs", ...props}: React.ComponentProps<typeof Button>) { return <Button {...props} type={type} variant={variant} size={size} />; }
function InputGroupInput({className, ...props}: React.ComponentProps<"input">) { return <Input {...props} className={["magi-inline-input", className].filter(Boolean).join(" ")} data-slot="input-group-control" />; }
function InputGroupTextarea({embedded, ...props}: React.ComponentProps<"textarea"> & {embedded?: boolean}) { const composer = React.useContext(ComposerContext); return <Textarea {...props} embedded={embedded ?? composer} data-slot="input-group-control" />; }
export {InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput, InputGroupTextarea};
