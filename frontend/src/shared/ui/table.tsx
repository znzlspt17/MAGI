import * as React from "react";
import {Table as AstryxTable, TableHeader as AstryxTableHeader, TableBody as AstryxTableBody, TableRow as AstryxTableRow, TableCell as AstryxTableCell, TableHeaderCell} from "@astryxdesign/core/Table";

// 2026-11-11: Astryx의 스크롤 가능한 의미론적 표를 기존 합성 인터페이스에 연결한다.
function Table(props: React.ComponentProps<"table">) { return <AstryxTable {...props} data-slot="table" />; }
function TableHeader({children, ...props}: React.ComponentProps<"thead">) { return <AstryxTableHeader {...props} data-slot="table-header">{children}</AstryxTableHeader>; }
function TableBody({children, ...props}: React.ComponentProps<"tbody">) { return <AstryxTableBody {...props} data-slot="table-body">{children}</AstryxTableBody>; }
function TableRow({children, ...props}: React.ComponentProps<"tr">) { return <AstryxTableRow {...props} data-slot="table-row">{children}</AstryxTableRow>; }
type Scope = "col" | "colgroup" | "row" | "rowgroup";
function TableHead({children, scope, ...props}: React.ComponentProps<"th">) { return <TableHeaderCell {...props} scope={scope as Scope | undefined} data-slot="table-head">{children}</TableHeaderCell>; }
function TableCell({children, scope, ...props}: React.ComponentProps<"td">) { return <AstryxTableCell {...props} scope={scope as Scope | undefined} data-slot="table-cell">{children}</AstryxTableCell>; }
function TableCaption(props: React.ComponentProps<"caption">) { return <caption {...props} data-slot="table-caption" />; }
export {Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow};
