// shadcn/ui MIT; adapted from ba1503c64472b82256d9de95e2e62c5901a38e8b
"use client"

import * as React from "react"
import { cn } from "../../lib/utils"

function Label({
  className,
  ...props
}: React.ComponentProps<"label">) {
  return (
    <label
      data-slot="label"
      className={cn(
        "cn-label flex items-center select-none group-data-[disabled=true]:pointer-events-none peer-disabled:cursor-not-allowed",
        className
      )}
      {...props}
    />
  )
}

export { Label }
