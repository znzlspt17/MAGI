import * as React from "react";
import {Selector} from "@astryxdesign/core/Selector";

type NativeSelectProps = Omit<React.ComponentProps<"select">, "size"> & {size?: "sm" | "default"};
type OptionProps = React.ComponentProps<"option">;
function optionsOf(children: React.ReactNode): {value: string; label: string; disabled?: boolean}[] {
  return React.Children.toArray(children).flatMap(child => {
    if (!React.isValidElement<OptionProps & {children?: React.ReactNode}>(child)) return [];
    if (child.type === React.Fragment) return optionsOf(child.props.children);
    const label = React.Children.toArray(child.props.children).join("");
    return [{value: String(child.props.value ?? label), label, disabled: child.props.disabled}];
  });
}
// 2026-11-11: Selector의 값 콜백을 기존 화면의 선택 이벤트 계약에 연결한다.
function NativeSelect({children, value, defaultValue, onChange, disabled, required, name, size, className, ref: _ref, ...props}: NativeSelectProps) {
  const options = optionsOf(children);
  const [selected, setSelected] = React.useState(String(defaultValue ?? options[0]?.value ?? ""));
  const label = props["aria-label"] || "선택";
  return <Selector id={props.id} aria-label={props["aria-label"]} data-slot="native-select" label={label} isLabelHidden options={options} value={String(value ?? selected)} htmlName={name} isDisabled={disabled} isRequired={required} size={size === "sm" ? "sm" : "md"} containerClassName={className} onChange={next => {
    if (value === undefined) setSelected(next);
    const target = {value: next} as HTMLSelectElement;
    onChange?.({target, currentTarget: target} as React.ChangeEvent<HTMLSelectElement>);
  }} />;
}
function NativeSelectOption(props: OptionProps) { return <option {...props} />; }
export {NativeSelect, NativeSelectOption};
