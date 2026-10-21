// shadcn/ui Radix AI Elements Prompt Input composition (MIT), revision ba1503c64472b82256d9de95e2e62c5901a38e8b.
import type { ComponentProps, KeyboardEvent } from "react";
import { ArrowUpIcon } from "@phosphor-icons/react";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from "./ui/input-group";

export function isSubmitShortcut(event: KeyboardEvent): boolean {
  return event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229;
}

export function PromptInput({ onSend, disabled, label, buttonLabel, ...props }: Omit<ComponentProps<"textarea">, "onSubmit"> & {
  onSend: () => void;
  label: string;
  buttonLabel: string;
}) {
  return <InputGroup className="chat-prompt" data-disabled={disabled || undefined}>
    <InputGroupTextarea {...props} aria-label={label} disabled={disabled} maxLength={20000} onKeyDown={(event) => {
      props.onKeyDown?.(event);
      if (!event.defaultPrevented && isSubmitShortcut(event)) { event.preventDefault(); if (!disabled) onSend(); }
    }} />
    <InputGroupAddon align="block-end" className="chat-prompt-footer"><span>Enter로 줄바꿈 · Ctrl/⌘ + Enter로 전송</span><InputGroupButton variant="default" size="sm" disabled={disabled} onClick={onSend} aria-label={buttonLabel}>{buttonLabel}<ArrowUpIcon size={17} aria-hidden /></InputGroupButton></InputGroupAddon>
  </InputGroup>;
}
