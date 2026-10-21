// shadcn/ui MIT; adapted from ba1503c64472b82256d9de95e2e62c5901a38e8b
import { cn } from "../../lib/utils"

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("animate-pulse rounded-md bg-accent", className)}
      {...props}
    />
  )
}

export { Skeleton }
