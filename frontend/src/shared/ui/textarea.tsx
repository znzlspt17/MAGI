import * as React from "react";
import {TextArea} from "@astryxdesign/core/TextArea";

// 2026-11-11: 편집기 ref와 입력 이벤트를 유지해 자동 높이와 포커스 복귀가 동작한다.
function Textarea({value, defaultValue, onChange, disabled, readOnly, required, name, autoFocus, className, maxLength, ref, embedded = false, ...props}: React.ComponentProps<"textarea"> & {embedded?: boolean}) {
  const [uncontrolled, setUncontrolled] = React.useState(String(defaultValue ?? ""));
  const label = props["aria-label"] || props.placeholder || "입력";
  return <TextArea {...(props as unknown as React.ComponentProps<typeof TextArea>)} ref={element => { if (element) { if (maxLength !== undefined) element.maxLength = maxLength; element.disabled = !!disabled; element.required = !!required; } if (typeof ref === "function") ref(element); else if (ref) ref.current = element; }} data-slot="textarea" label={label} isLabelHidden value={String(value ?? uncontrolled)} onChange={(next, event) => { if (value === undefined) setUncontrolled(next); onChange?.(event); }} isDisabled={disabled} isReadOnly={readOnly} isRequired={required} htmlName={name} hasAutoFocus={autoFocus} containerClassName={className} controlClassName={embedded ? "magi-composer-control" : undefined} />;
}
export {Textarea};
