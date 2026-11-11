import * as React from "react";
import {Divider} from "@astryxdesign/core/Divider";

function Separator({orientation = "horizontal", decorative = true, ...props}: React.ComponentProps<"div"> & {orientation?: "horizontal" | "vertical"; decorative?: boolean}) {
  return <Divider {...props} data-slot="separator" orientation={orientation} aria-hidden={decorative || undefined} />;
}
export {Separator};
