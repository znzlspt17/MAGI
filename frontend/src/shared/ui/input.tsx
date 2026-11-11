import * as React from "react";
import {TextInput} from "@astryxdesign/core/TextInput";

// 2026-11-11: 기존 이벤트와 ref 계약을 유지하며 Astryx 필드에 연결한다.
function Input({value, defaultValue, onChange, disabled, readOnly, required, name, autoFocus, className, type, ref, ...props}: React.ComponentProps<"input">) {
  const [uncontrolled, setUncontrolled] = React.useState(String(defaultValue ?? ""));
  const label = props["aria-label"] || props.placeholder || "입력";
  const inputType = (type === "password" || type === "email" || type === "search" || type === "tel" || type === "url" ? type : "text") as React.ComponentProps<typeof TextInput>["type"];
  return <TextInput {...(props as unknown as React.ComponentProps<typeof TextInput>)} ref={element => { if (element) { element.disabled = !!disabled; element.required = !!required; } if (typeof ref === "function") ref(element); else if (ref) ref.current = element; }} aria-label={label} data-slot="input" type={inputType} label={label} isLabelHidden value={String(value ?? uncontrolled)} onChange={(next, event) => { if (value === undefined) setUncontrolled(next); onChange?.(event); }} isDisabled={disabled} isReadOnly={readOnly} isRequired={required} htmlName={name} hasAutoFocus={autoFocus} containerClassName={className} />;
}
export {Input};
