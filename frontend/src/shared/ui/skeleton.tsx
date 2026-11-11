import * as React from "react";
import {Skeleton as AstryxSkeleton} from "@astryxdesign/core/Skeleton";
function Skeleton(props: React.ComponentProps<"div">) { return <AstryxSkeleton {...props} data-slot="skeleton" />; }
export {Skeleton};
