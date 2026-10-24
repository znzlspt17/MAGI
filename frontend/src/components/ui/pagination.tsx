// shadcn/ui MIT; adapted from ba1503c64472b82256d9de95e2e62c5901a38e8b
import * as React from "react"
import { cn } from "../../lib/utils"

import { Button } from "./button"

function Pagination({ className, ...props }: React.ComponentProps<"nav">) {
  return (
    <nav
      role="navigation"
      aria-label="pagination"
      data-slot="pagination"
      className={cn(
        "cn-pagination mx-auto flex w-full justify-center",
        className
      )}
      {...props}
    />
  )
}

function PaginationContent({
  className,
  ...props
}: React.ComponentProps<"ul">) {
  return (
    <ul
      data-slot="pagination-content"
      className={cn("cn-pagination-content flex items-center", className)}
      {...props}
    />
  )
}

function PaginationItem({ ...props }: React.ComponentProps<"li">) {
  return <li data-slot="pagination-item" {...props} />
}

type PaginationLinkProps = {
  isActive?: boolean
} & Pick<React.ComponentProps<typeof Button>, "size"> &
  React.ComponentProps<"a">









export {
Pagination,
PaginationContent,
PaginationItem
}
