// shadcn/ui MIT; adapted from ba1503c64472b82256d9de95e2e62c5901a38e8b
import { cva } from "class-variance-authority"
import { cn } from "../../lib/utils"

function Empty({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="empty"
      className={cn(
        "cn-empty flex w-full min-w-0 flex-1 flex-col items-center justify-center text-center text-balance",
        className
      )}
      {...props}
    />
  )
}

function EmptyHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="empty-header"
      className={cn(
        "cn-empty-header flex max-w-sm flex-col items-center",
        className
      )}
      {...props}
    />
  )
}

const emptyMediaVariants = cva(
  "cn-empty-media flex shrink-0 items-center justify-center [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "cn-empty-media-default",
        icon: "cn-empty-media-icon",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)



function EmptyTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="empty-title"
      className={cn("cn-empty-title cn-font-heading", className)}
      {...props}
    />
  )
}

function EmptyDescription({ className, ...props }: React.ComponentProps<"p">) {
  return (
    <div
      data-slot="empty-description"
      className={cn(
        "cn-empty-description text-muted-foreground [&>a]:underline [&>a]:underline-offset-4 [&>a:hover]:text-primary",
        className
      )}
      {...props}
    />
  )
}



export {
Empty,EmptyDescription,EmptyHeader,
EmptyTitle
}
