import * as React from "react";
import {ScrollableArea} from "@astryxdesign/core/ScrollableArea";
import {VStack} from "@astryxdesign/core/VStack";
import {Button} from "./button";

type ScrollContext = {viewport: React.RefObject<HTMLDivElement | null>; autoScroll: boolean; threshold: number; atEnd: boolean; setAtEnd: (value: boolean) => void};
const Context = React.createContext<ScrollContext | null>(null);
function useMessageScroller() { const context = React.useContext(Context); if (!context) throw new Error("MessageScrollerProvider가 필요합니다."); return context; }
function useMessageScrollerScrollable() { return useMessageScroller(); }
function useMessageScrollerVisibility() { return useMessageScroller(); }
function MessageScrollerProvider({children, autoScroll = true, scrollEdgeThreshold = 48, defaultScrollPosition = "end"}: {children: React.ReactNode; autoScroll?: boolean; scrollEdgeThreshold?: number; defaultScrollPosition?: "start" | "end"}) {
  const viewport = React.useRef<HTMLDivElement>(null);
  const [atEnd, setAtEnd] = React.useState(defaultScrollPosition === "end");
  return <Context.Provider value={{viewport, autoScroll, threshold: scrollEdgeThreshold, atEnd, setAtEnd}}>{children}</Context.Provider>;
}
function MessageScroller(props: React.ComponentProps<"div">) { return <VStack {...props} data-slot="message-scroller" />; }
// 2026-11-11: 사용자가 이전 메시지를 읽는 동안 자동 스크롤하지 않고 끝에 있을 때만 새 내용을 따라간다.
function MessageScrollerViewport({children, role: _role, ...props}: React.ComponentProps<"div">) {
  const {viewport, autoScroll, threshold, atEnd, setAtEnd} = useMessageScroller();
  const follow = React.useRef(atEnd);
  follow.current = atEnd;
  React.useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const update = () => { if (autoScroll && follow.current) element.scrollTop = element.scrollHeight; };
    update();
    const mutation = new MutationObserver(update);
    mutation.observe(element, {childList: true, subtree: true, characterData: true});
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    if (element.firstElementChild) resize?.observe(element.firstElementChild);
    return () => { mutation.disconnect(); resize?.disconnect(); };
  }, [autoScroll, viewport]);
  return <ScrollableArea {...props} ref={viewport} label={props["aria-label"] || "대화 이력"} data-slot="message-scroller-viewport" overscroll="contain" onScroll={event => { const el = event.currentTarget; setAtEnd(el.scrollHeight - el.clientHeight - el.scrollTop <= threshold); props.onScroll?.(event); }}>{children}</ScrollableArea>;
}
function MessageScrollerContent(props: React.ComponentProps<"div">) { return <VStack {...props} data-slot="message-scroller-content" />; }
function MessageScrollerItem({messageId: _messageId, scrollAnchor: _scrollAnchor, ...props}: React.ComponentProps<"div"> & {messageId?: string; scrollAnchor?: boolean}) { return <VStack {...props} data-slot="message-scroller-item" />; }
function MessageScrollerButton({children, direction = "end", ...props}: React.ComponentProps<typeof Button> & {direction?: "start" | "end"}) {
  const {viewport, atEnd, setAtEnd} = useMessageScroller();
  return <Button {...props} type="button" data-slot="message-scroller-button" hidden={direction === "end" && atEnd} onClick={event => { viewport.current?.scrollTo({top: direction === "end" ? viewport.current.scrollHeight : 0, behavior: "smooth"}); setAtEnd(direction === "end"); props.onClick?.(event); }}>{children || "최신 메시지로 이동"}</Button>;
}
export {MessageScroller, MessageScrollerButton, MessageScrollerContent, MessageScrollerItem, MessageScrollerProvider, MessageScrollerViewport, useMessageScroller, useMessageScrollerScrollable, useMessageScrollerVisibility};
