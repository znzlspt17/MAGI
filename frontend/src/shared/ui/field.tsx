import * as React from "react";
import {VStack} from "@astryxdesign/core/VStack";
import {HStack} from "@astryxdesign/core/HStack";
import {Text} from "@astryxdesign/core/Text";
import {Label} from "./label";
function FieldSet(props: React.ComponentProps<"fieldset">) { return <fieldset {...props} data-slot="field-set" />; }
function FieldLegend({variant = "legend", ...props}: React.ComponentProps<"legend"> & {variant?: "legend" | "label"}) { return <legend {...props} data-slot="field-legend" data-variant={variant} />; }
function Field({orientation = "vertical", ...props}: React.ComponentProps<"div"> & {orientation?: "vertical" | "horizontal" | "responsive"}) { const Stack = orientation === "horizontal" ? HStack : VStack; return <Stack {...props} role="group" data-slot="field" data-orientation={orientation} />; }
function FieldLabel(props: React.ComponentProps<typeof Label>) { return <Label {...props} data-slot="field-label" />; }
function FieldDescription({children, color: _color, ...props}: React.ComponentProps<"p">) { return <Text {...props} data-slot="field-description" type="supporting">{children}</Text>; }
function FieldError({children, errors, ...props}: React.ComponentProps<"div"> & {errors?: Array<{message?: string} | undefined>}) { const messages = [...new Set(errors?.map(error => error?.message).filter(Boolean))]; const content = children || messages.join(", "); return content ? <VStack {...props} role="alert" data-slot="field-error">{content}</VStack> : null; }
export {Field, FieldDescription, FieldError, FieldLabel, FieldLegend, FieldSet};
