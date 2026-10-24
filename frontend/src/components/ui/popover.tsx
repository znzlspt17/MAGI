// shadcn/ui MIT; adapted from ba1503c64472b82256d9de95e2e62c5901a38e8b
"use client"

import * as PopoverPrimitive from "@radix-ui/react-popover"
import * as React from "react"
import { cn } from "../../lib/utils"

function Popover({
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

function PopoverContent({
  className,
  align = "center",
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        data-slot="popover-content"
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "cn-popover-content z-50 w-72 origin-(--radix-popover-content-transform-origin) outline-hidden",
          className
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
}









export {
Popover,
PopoverContent,
PopoverTrigger
}
