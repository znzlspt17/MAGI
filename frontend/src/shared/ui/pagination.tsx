import * as React from "react";
import {HStack} from "@astryxdesign/core/HStack";
function Pagination(props: React.ComponentProps<"nav">) { return <HStack {...(props as unknown as React.ComponentProps<typeof HStack>)} as="nav" aria-label={props["aria-label"] || "페이지"} data-slot="pagination" />; }
function PaginationContent(props: React.ComponentProps<"ul">) { return <HStack {...(props as unknown as React.ComponentProps<typeof HStack>)} as="ul" data-slot="pagination-content" />; }
function PaginationItem(props: React.ComponentProps<"li">) { return <HStack {...(props as unknown as React.ComponentProps<typeof HStack>)} as="li" data-slot="pagination-item" />; }
export {Pagination, PaginationContent, PaginationItem};
