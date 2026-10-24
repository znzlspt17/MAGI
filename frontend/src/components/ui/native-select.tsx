// shadcn/ui MIT; adapted from ba1503c64472b82256d9de95e2e62c5901a38e8b
import * as React from "react"
import { cn } from "../../lib/utils"

import { CaretDownIcon } from "@phosphor-icons/react"

type NativeSelectProps = Omit<React.ComponentProps<"select">, "size"> & {
  size?: "sm" | "default"
}

function NativeSelect({
  className,
  size = "default",
  ...props
}: NativeSelectProps) {
  return (
    <div
      className={cn(
        "cn-native-select-wrapper group/native-select relative w-fit has-[select:disabled]:opacity-50",
        className
      )}
      data-slot="native-select-wrapper"
      data-size={size}
    >
      <select
        data-slot="native-select"
        data-size={size}
        className="cn-native-select outline-none disabled:pointer-events-none disabled:cursor-not-allowed"
        {...props}
      />
      <CaretDownIcon
        className="cn-native-select-icon pointer-events-none absolute select-none"
        aria-hidden="true"
        data-slot="native-select-icon"
      />
    </div>
  )
}

function NativeSelectOption({
  className,
  ...props
}: React.ComponentProps<"option">) {
  return (
    <option
      data-slot="native-select-option"
      className={cn("bg-[Canvas] text-[CanvasText]", className)}
      {...props}
    />
  )
}



export {
NativeSelect,
NativeSelectOption
}
