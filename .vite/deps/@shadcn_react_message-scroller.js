"use client";
import {
  require_jsx_runtime
} from "./chunk-4YUEB2SN.js";
import {
  require_react
} from "./chunk-2JUH4I7N.js";
import {
  __toESM
} from "./chunk-QKQ6FTX6.js";

// node_modules/.pnpm/@shadcn+react@0.3.1_@types+react@19.3.0_react@19.3.1/node_modules/@shadcn/react/dist/chunk-HBS6WEDP.js
var i = __toESM(require_react(), 1);
function S({ defaultTagName: a, props: r, render: t, state: n = {}, stateAttributesMapping: e }) {
  let o = d(R(n, e), r);
  if (!t) return i.createElement(a, o);
  if (typeof t == "function") return t(o, n);
  if (!i.isValidElement(t)) return null;
  let s = t.props, u = { ...d(o, s), ref: f(o.ref, s.ref) };
  return i.cloneElement(t, u);
}
function d(...a) {
  let r = {};
  for (let t of a) {
    if (!t) continue;
    let n = t;
    for (let e of Object.keys(n)) {
      let o = n[e];
      if (o === void 0) continue;
      let s = r[e];
      e === "className" ? r[e] = [s, o].filter(Boolean).join(" ") : e === "style" ? r[e] = { ...s, ...o } : e === "ref" ? r[e] = f(s, o) : l(e) && typeof s == "function" && typeof o == "function" ? r[e] = p(o, s) : r[e] = o;
    }
  }
  return r;
}
function R(a, r) {
  let t = {};
  for (let n of Object.keys(a)) {
    let e = a[n], o = r?.[n]?.(e);
    if (o) {
      Object.assign(t, o);
      continue;
    }
    if (n === "slot") {
      t["data-slot"] = e;
      continue;
    }
    let s = `data-${String(n).replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`;
    typeof e == "boolean" ? t[s] = e ? "" : void 0 : e != null && (t[s] = String(e));
  }
  return t;
}
function p(a, r) {
  return function(n) {
    a(n), n.defaultPrevented || r(n);
  };
}
function l(a) {
  return /^on[A-Z]/.test(a);
}
function f(...a) {
  let r = a.filter(Boolean);
  if (r.length !== 0) return (t) => {
    for (let n of r) typeof n == "function" ? n(t) : n && (n.current = t);
  };
}

// node_modules/.pnpm/@shadcn+react@0.3.1_@types+react@19.3.0_react@19.3.1/node_modules/@shadcn/react/dist/message-scroller/index.js
var f2 = __toESM(require_react());
var import_jsx_runtime = __toESM(require_jsx_runtime());
var _e = 8;
var Be = 64;
var Fe = 0;
var J = 0.5;
var je = 180;
var Ge = /* @__PURE__ */ new Set(["ArrowDown", "ArrowUp", "End", "Home", "PageDown", "PageUp", " "]);
var ge = { start: false, end: false };
var vt = [];
var Q = { currentAnchorId: null, visibleMessageIds: vt };
function Ne({ content: e, scrollEdgeThreshold: t, spacer: r, viewport: n }) {
  if (!n || !e) return ge;
  let l2 = Re({ content: e, spacer: r, viewport: n });
  return { start: n.scrollTop > t, end: l2 - n.scrollTop - n.clientHeight > t };
}
function Ue({ content: e, scrollMargin: t, scrollPreviousItemPeek: r, spacer: n, viewport: l2, visibleMessageIds: c }) {
  if (!e || !l2) return Q;
  let S2 = l2.getBoundingClientRect(), o = S2.top + t + r, b = typeof IntersectionObserver > "u", v = [], m = null;
  for (let L of ee(e, n)) {
    let R2 = L.dataset.messageId;
    if (!R2) continue;
    let E = L.dataset.scrollAnchor === "true", h = E || b ? L.getBoundingClientRect() : null;
    (b && h ? h.bottom > o && h.top < S2.bottom : c.has(R2)) && v.push(R2), E && h && h.top <= o + J && (m = R2);
  }
  return v.length === 0 && m === null ? Q : { currentAnchorId: m, visibleMessageIds: v };
}
function ee(e, t) {
  return Array.from(e.children).filter((r) => r instanceof HTMLElement && r !== t);
}
function Ye(e, t) {
  for (let r = t; r < e.length; r++) {
    let n = e[r];
    if (n?.dataset.scrollAnchor === "true") return n;
  }
  return null;
}
function ze(e, t) {
  for (let r of e) if (r.dataset.scrollAnchor === "true" && !t.has(r)) return r;
  return null;
}
function qe(e, t) {
  let r = 0;
  for (let n = t; n < e.length; n++) if (e[n]?.dataset.scrollAnchor === "true" && (r += 1, r > 1)) return true;
  return false;
}
function Ke(e) {
  for (let t = e.length - 1; t >= 0; t--) {
    let r = e[t];
    if (r?.dataset.scrollAnchor === "true") return r;
  }
  return null;
}
function We({ content: e, spacer: t, viewport: r }) {
  let n = r.getBoundingClientRect();
  for (let l2 of ee(e, t)) {
    if (!l2.dataset.messageId) continue;
    let c = l2.getBoundingClientRect();
    if (c.bottom > n.top && c.top < n.bottom) return l2;
  }
  return null;
}
function $e({ align: e, element: t, scrollMargin: r, spacer: n, viewport: l2 }) {
  let c = me(t, l2), S2 = t.getBoundingClientRect().height, o = ht(n);
  if (e === "center") {
    let b = Math.max(0, l2.clientHeight - o.start - o.end);
    return c - o.start - (b - S2) / 2 - r;
  }
  if (e === "end") return c - l2.clientHeight + S2 + o.end + r;
  if (e === "nearest") {
    let b = c + S2, v = l2.scrollTop + o.start, m = l2.scrollTop + l2.clientHeight - o.end;
    return c >= v && b <= m ? l2.scrollTop : c < v ? c - o.start - r : b - l2.clientHeight + o.end + r;
  }
  return c - o.start - r;
}
function me(e, t) {
  let r = e.getBoundingClientRect(), n = t.getBoundingClientRect();
  return r.top - n.top + t.scrollTop;
}
function te(e, t) {
  return e.getBoundingClientRect().top - t.getBoundingClientRect().top;
}
function Je({ content: e, scrollTop: t, spacer: r, viewport: n }) {
  let l2 = Re({ content: e, spacer: r, viewport: n });
  return t + n.clientHeight - l2;
}
function Re({ content: e, spacer: t, viewport: r }) {
  let n = ee(e, t), l2 = Xe(e), c = r.getBoundingClientRect(), S2 = r.scrollTop, o = l2.start + l2.end;
  for (let b of n) {
    let v = b.getBoundingClientRect();
    o = Math.max(o, v.bottom - c.top + S2 + l2.end);
  }
  return o;
}
function Qe(e) {
  return Math.max(0, e.scrollHeight - e.clientHeight);
}
function Xe(e) {
  let t = window.getComputedStyle(e);
  return { end: pe(t.paddingBlockEnd || t.paddingBottom), start: pe(t.paddingBlockStart || t.paddingTop) };
}
function ht(e) {
  let t = e?.parentElement;
  return t ? Xe(t) : { end: 0, start: 0 };
}
function Ze(e) {
  if (!e) return 0;
  let t = window.getComputedStyle(e), r = t.rowGap === "normal" ? t.gap : t.rowGap;
  return pe(r);
}
function pe(e) {
  if (!e) return 0;
  let t = Number.parseFloat(e);
  return Number.isFinite(t) ? t : 0;
}
function et(e, t) {
  let r = e, n = /* @__PURE__ */ new Set();
  return { getSnapshot: () => r, hasListeners: () => n.size > 0, setSnapshot: (l2) => {
    t(r, l2) || (r = l2, n.forEach((c) => c()));
  }, subscribe: (l2, c, S2) => {
    let o = n.size === 0;
    return n.add(l2), o && c?.(), () => {
      n.delete(l2), n.size === 0 && S2?.();
    };
  } };
}
function de(e, t) {
  return et(e, t);
}
function tt() {
  return et(Q, Lt);
}
function rt(e, t) {
  return e.start === t.start && e.end === t.end;
}
function Lt(e, t) {
  return e.currentAnchorId !== t.currentAnchorId || e.visibleMessageIds.length !== t.visibleMessageIds.length ? false : e.visibleMessageIds.every((r, n) => r === t.visibleMessageIds[n]);
}
function nt({ autoScroll: e, defaultScrollPosition: t, scrollEdgeThreshold: r, scrollMargin: n, scrollPreviousItemPeek: l2 }) {
  let c = f2.useRef(e), S2 = f2.useRef(false), o = f2.useRef(null), b = f2.useRef(false), v = f2.useRef(r), m = f2.useRef(0), L = f2.useRef(null), R2 = f2.useRef(0), E = f2.useRef(e ? "following-bottom" : "free-scrolling"), h = f2.useRef(/* @__PURE__ */ new Map()), I = f2.useRef(null), u = f2.useRef(null), k = f2.useRef(null), j = f2.useRef(l2), _ = f2.useRef(true), Y = f2.useRef(null), x = f2.useRef(n), V = f2.useRef(null), P = f2.useRef(0), G = f2.useRef(0), A = f2.useRef(null), le = f2.useRef(null), z = f2.useRef(null), B = f2.useRef(null), i2 = f2.useRef(null), d2 = f2.useRef(null), T = f2.useRef(null), w = f2.useRef(null), C = f2.useRef(null), y = f2.useRef(/* @__PURE__ */ new Set()), F = f2.useRef(/* @__PURE__ */ new WeakSet());
  return z.current === null && (z.current = de(t === "end" || t === "last-anchor", (q, X) => q === X)), B.current === null && (B.current = de(ge, rt)), C.current === null && (C.current = tt()), c.current = e, v.current = r, x.current = n, j.current = l2, { autoScrollRef: c, autoscrollingRef: S2, autoscrollingTimeoutRef: i2, streamingTurnRef: k, contentRef: o, defaultScrollPositionAppliedRef: b, firstItemRef: L, itemCountRef: m, lastScrollTopRef: R2, messageElementsRef: h, modeRef: E, pendingScrollFrameRef: V, pendingScrollToMessageRef: I, prependRestoreRef: u, preserveScrollOnPrependRef: _, pendingDefaultScrollStore: z.current, rootRef: Y, scrollEdgeThresholdRef: v, scrollMarginRef: x, scrollPreviousItemPeekRef: j, spacerGapRef: P, spacerHeightRef: G, spacerRef: A, stateFrameRef: le, stateStore: B.current, viewportRef: d2, visibilityFrameRef: T, visibilityObserverRef: w, visibilityStore: C.current, visibleMessageIdsRef: y, handledScrollAnchorsRef: F };
}
function Me(e) {
  e.pendingDefaultScrollStore.setSnapshot(false);
}
function re(e) {
  e.defaultScrollPositionAppliedRef.current = true, Me(e);
}
function lt({ refs: e, commitScrollState: t, scheduleStateCommit: r, scheduleVisibilitySync: n }) {
  let { streamingTurnRef: l2, autoScrollRef: c, autoscrollingRef: S2, autoscrollingTimeoutRef: o, contentRef: b, itemCountRef: v, messageElementsRef: m, modeRef: L, pendingScrollToMessageRef: R2, prependRestoreRef: E, scrollMarginRef: h, scrollPreviousItemPeekRef: I, spacerGapRef: u, spacerHeightRef: k, spacerRef: j, viewportRef: _ } = e, Y = f2.useCallback((i2) => {
    o.current !== null && (window.clearTimeout(o.current), o.current = null), S2.current !== i2 && (S2.current = i2, t()), i2 && (o.current = window.setTimeout(() => {
      o.current = null, S2.current = false, t();
    }, je));
  }, [t]), x = f2.useCallback((i2) => {
    let d2 = j.current;
    if (!d2) return;
    let T = Math.max(0, Math.ceil(i2));
    k.current !== T && (k.current = T, d2.hidden = T === 0, d2.style.height = `${T}px`, d2.style.marginTop = T > 0 ? `${-u.current}px` : "");
  }, []), V = f2.useCallback((i2, { behavior: d2 = "auto", autoscrolling: T = false } = {}) => {
    let w = _.current;
    if (!w) return;
    let C = Math.max(0, i2);
    if (Math.abs(w.scrollTop - C) <= J) {
      w.scrollTop = C, t();
      return;
    }
    T && Y(true), w.scrollTo({ top: C, behavior: d2 }), r();
  }, [t, r, Y]), P = f2.useCallback(({ behavior: i2 = "auto" } = {}) => _.current ? (x(0), l2.current = null, L.current = "free-scrolling", V(0, { behavior: i2 }), n(), true) : false, [n, V, x]), G = f2.useCallback(({ behavior: i2 = "auto" } = {}) => {
    let d2 = _.current;
    return d2 ? (x(0), l2.current = null, L.current = c.current ? "following-bottom" : "free-scrolling", V(Qe(d2), { autoscrolling: true, behavior: i2 }), n(), true) : false;
  }, [n, V, x]), A = f2.useCallback((i2, { align: d2 = "start", behavior: T = "auto", scrollMargin: w = h.current } = {}, { keepPreviousPeek: C = false } = {}) => {
    let y = b.current, F = _.current;
    if (!y || !F || !y.contains(i2)) return false;
    let q = $e({ align: d2, element: i2, scrollMargin: C ? w + I.current : w, spacer: j.current, viewport: F }), X = Je({ content: y, scrollTop: q, spacer: j.current, viewport: F });
    return x(X), E.current = { element: i2, viewportTop: te(i2, F) }, L.current = C ? "anchored-to-message" : "settling-jump", l2.current = C ? i2 : null, V(q, { behavior: T }), n(), true;
  }, [n, V, x]), le = f2.useCallback(() => {
    let i2 = l2.current;
    return !i2 || !i2.isConnected || L.current !== "anchored-to-message" ? false : A(i2, { align: "start" }, { keepPreviousPeek: true });
  }, [A]), z = f2.useCallback((i2, d2) => {
    let T = m.current.get(i2);
    return T ? (re(e), A(T, d2) ? (R2.current = null, true) : (R2.current = { messageId: i2, options: d2 }, true)) : v.current === 0 ? (R2.current = { messageId: i2, options: d2 }, re(e), true) : false;
  }, [A]);
  return { flushPendingScrollToMessage: f2.useCallback(() => {
    let i2 = R2.current;
    if (!i2) return false;
    let d2 = m.current.get(i2.messageId);
    return !d2 || !A(d2, i2.options) ? false : (R2.current = null, re(e), true);
  }, [A]), reanchorToAnchoredMessage: le, scrollToElement: A, scrollToEnd: G, scrollToMessage: z, scrollToStart: P };
}
function ot(e, t) {
  return f2.useCallback((r) => {
    e.current = r, r && t();
  }, [e, t]);
}
function st({ autoScroll: e = false, defaultScrollPosition: t = "end", scrollEdgeThreshold: r = _e, scrollPreviousItemPeek: n = Be, scrollMargin: l2 = Fe }) {
  let c = nt({ autoScroll: e, defaultScrollPosition: t, scrollEdgeThreshold: r, scrollMargin: l2, scrollPreviousItemPeek: n }), { streamingTurnRef: S2, autoScrollRef: o, autoscrollingRef: b, autoscrollingTimeoutRef: v, contentRef: m, defaultScrollPositionAppliedRef: L, firstItemRef: R2, itemCountRef: E, lastScrollTopRef: h, messageElementsRef: I, modeRef: u, pendingScrollFrameRef: k, pendingScrollToMessageRef: j, prependRestoreRef: _, preserveScrollOnPrependRef: Y, pendingDefaultScrollStore: x, rootRef: V, scrollEdgeThresholdRef: P, scrollMarginRef: G, scrollPreviousItemPeekRef: A, spacerGapRef: le, spacerHeightRef: z, spacerRef: B, stateFrameRef: i2, stateStore: d2, viewportRef: T, visibilityFrameRef: w, visibilityObserverRef: C, visibilityStore: y, visibleMessageIdsRef: F, handledScrollAnchorsRef: q } = c, X = f2.useRef(t);
  X.current !== t && (X.current = t, L.current = false);
  let ce = f2.useCallback((s) => {
    let a = V.current, M = T.current, H = [s.start && "start", s.end && "end"].filter(Boolean).join(" "), fe = b.current;
    for (let W of [a, M]) W && (H ? W.setAttribute("data-scrollable", H) : W.removeAttribute("data-scrollable"), W.toggleAttribute("data-autoscrolling", fe));
  }, []), be = f2.useCallback((s) => {
    let a = T.current?.scrollTop ?? 0, M = a < h.current - J;
    h.current = a, o.current && !s.end && u.current !== "settling-jump" && u.current !== "anchored-to-message" ? u.current = "following-bottom" : u.current === "following-bottom" && s.end && M && !b.current && (u.current = "free-scrolling");
  }, []), N = f2.useCallback(() => {
    let s = Ne({ content: m.current, scrollEdgeThreshold: P.current, spacer: B.current, viewport: T.current });
    be(s);
    let a = u.current === "following-bottom" ? { ...s, end: false } : s;
    ce(a), d2.setSnapshot(a);
  }, [be, d2, ce]), oe = f2.useCallback(() => {
    i2.current === null && (i2.current = window.requestAnimationFrame(() => {
      i2.current = null, N();
    }));
  }, [N]), O = f2.useCallback(() => {
    y.hasListeners() && w.current === null && (w.current = window.requestAnimationFrame(() => {
      w.current = null, y.hasListeners() && y.setSnapshot(Ue({ content: m.current, scrollMargin: G.current, scrollPreviousItemPeek: A.current, spacer: B.current, viewport: T.current, visibleMessageIds: F.current }));
    }));
  }, [y]), { flushPendingScrollToMessage: ae, reanchorToAnchoredMessage: Te, scrollToElement: se, scrollToEnd: D, scrollToMessage: Ee, scrollToStart: ie } = lt({ refs: c, commitScrollState: N, scheduleStateCommit: oe, scheduleVisibilitySync: O }), ve = f2.useCallback(() => {
    let s = _.current, a = T.current;
    if (!s || !a || !s.element.isConnected) return false;
    let H = te(s.element, a) - s.viewportTop;
    return Math.abs(H) <= J ? false : (a.scrollTop += H, s.viewportTop = te(s.element, a), oe(), O(), true);
  }, [oe, O]), Z = f2.useCallback(() => {
    let s = m.current, a = T.current;
    if (!s || !a) {
      _.current = null;
      return;
    }
    let M = We({ content: s, spacer: B.current, viewport: a });
    _.current = M ? { element: M, viewportTop: te(M, a) } : null;
  }, []), he = f2.useCallback(() => {
    k.current === null && (k.current = window.requestAnimationFrame(() => {
      k.current = null, ae() && Z();
    }));
  }, [Z, ae]), ue = f2.useCallback(() => {
    if (!t || L.current || E.current === 0) return false;
    let s = false;
    if (t === "last-anchor") {
      let a = m.current, M = T.current, H = a && M ? Ke(ee(a, B.current)) : null;
      if (!a || !M || !H) s = D({ behavior: "auto" });
      else {
        let fe = me(H, M);
        s = Re({ content: a, spacer: B.current, viewport: M }) - fe <= M.clientHeight ? D({ behavior: "auto" }) : se(H, { align: "start" }, { keepPreviousPeek: true });
      }
    } else s = t === "end" ? D({ behavior: "auto" }) : ie({ behavior: "auto" });
    return s ? (re(c), true) : false;
  }, [t, se, D, ie]), Le = f2.useCallback(() => {
    let s = m.current;
    if (!s) return;
    let a = ee(s, B.current), M = E.current, H = R2.current;
    E.current = a.length, R2.current = a[0] ?? null, (() => {
      if (ae()) return;
      if (M === 0) {
        if (ue() || a.length > 0 && o.current && D({ behavior: "auto" })) return;
        N(), O();
        return;
      }
      let W = H ? a.indexOf(H) : -1;
      if (Y.current && W > 0) {
        ve();
        return;
      }
      if (a.length > M) {
        let $ = Ye(a, M);
        if ($) {
          if (o.current && u.current === "following-bottom" && qe(a, M)) {
            D({ behavior: "auto" });
            return;
          }
          se($, { align: "start" }, { keepPreviousPeek: true }), q.current.add($);
          return;
        }
      }
      if (a.length === M) {
        let $ = ze(a, q.current);
        if ($) {
          se($, { align: "start" }, { keepPreviousPeek: true }), q.current.add($);
          return;
        }
      }
      u.current === "following-bottom" && o.current ? D({ behavior: "auto" }) : (N(), O());
    })(), Z();
  }, [ue, Z, N, ae, ve, O, se, D]), Ce = f2.useCallback(() => {
    if (u.current === "following-bottom" && o.current) {
      D({ behavior: "auto" });
      return;
    }
    let s = z.current;
    if (Te()) {
      o.current && s > 0 && z.current === 0 && D({ behavior: "auto" });
      return;
    }
    oe(), O();
  }, [Te, oe, O, D]), Pe = f2.useCallback(() => {
    let s = T.current;
    if (!(!s || !y.hasListeners())) {
      if (typeof IntersectionObserver > "u") {
        O();
        return;
      }
      C.current || (C.current = new IntersectionObserver((a) => {
        for (let M of a) {
          let H = M.target.dataset.messageId;
          H && (M.isIntersecting ? F.current.add(H) : F.current.delete(H));
        }
        O();
      }, { root: s, rootMargin: `${-(G.current + A.current)}px 0px 0px 0px`, threshold: [0, 0.01, 0.5, 1] })), I.current.forEach((a) => {
        C.current?.observe(a);
      }), O();
    }
  }, [O, y]), we = f2.useCallback(() => {
    w.current !== null && (window.cancelAnimationFrame(w.current), w.current = null), C.current?.disconnect(), C.current = null, F.current.clear(), y.setSnapshot(Q);
  }, [y]), bt = f2.useCallback((s, a, M) => {
    if (a) {
      I.current.set(s, a), C.current?.observe(a), O(), j.current?.messageId === s && he();
      return;
    }
    M && I.current.get(s) === M && (I.current.delete(s), F.current.delete(s), C.current?.unobserve(M), O());
  }, [he, O]), Oe = f2.useCallback(() => {
    (u.current === "following-bottom" || u.current === "anchored-to-message" || u.current === "settling-jump") && (S2.current = null, u.current = "free-scrolling");
  }, []), ye = f2.useCallback(() => ce(d2.getSnapshot()), [d2, ce]), He = ot(V, ye), Ie = ot(T, ye), Ae = f2.useCallback((s) => {
    m.current = s;
  }, []), De = f2.useCallback((s) => {
    B.current = s, le.current = Ze(s?.parentElement ?? null);
  }, []), xe = f2.useCallback(() => {
    N(), O(), Z();
  }, [Z, N, O]), Tt = f2.useMemo(() => ({ handleContentChange: Le, handleResize: Ce, observeVisibility: Pe, pendingDefaultScrollStore: x, preserveScrollOnPrependRef: Y, scrollToEnd: D, scrollToMessage: Ee, scrollToStart: ie, setContentElement: Ae, setRootElement: He, setSpacerElement: De, setViewportElement: Ie, stateStore: d2, syncAfterScroll: xe, unobserveVisibility: we, userScrollIntent: Oe, viewportRef: T, visibilityStore: y }), [Le, Ce, Pe, x, D, Ee, ie, Ae, He, De, Ie, d2, xe, we, Oe, y]);
  return f2.useLayoutEffect(() => {
    ue() || E.current === 0 && Me(c);
  }, [ue]), f2.useEffect(() => () => {
    i2.current !== null && (window.cancelAnimationFrame(i2.current), i2.current = null), w.current !== null && (window.cancelAnimationFrame(w.current), w.current = null), v.current !== null && (window.clearTimeout(v.current), v.current = null), k.current !== null && (window.cancelAnimationFrame(k.current), k.current = null), C.current?.disconnect(), C.current = null;
  }, []), f2.useLayoutEffect(() => {
    if (e && u.current === "following-bottom" && E.current > 0) {
      D({ behavior: "auto" });
      return;
    }
    N();
  }, [e, N, D]), { context: Tt, registerMessage: bt };
}
function at(e) {
  let t = f2.useRef(e);
  return t.current = e, t;
}
var it = f2.createContext(null);
var ut = f2.createContext(null);
function K() {
  let e = f2.useContext(it);
  if (!e) throw new Error("useMessageScroller must be used within a MessageScroller.");
  return e;
}
function Ct() {
  let e = f2.useContext(ut);
  if (!e) throw new Error("MessageScrollerItem must be used within a MessageScroller.");
  return e;
}
function Pt() {
  let { scrollToEnd: e, scrollToMessage: t, scrollToStart: r } = K();
  return f2.useMemo(() => ({ scrollToEnd: e, scrollToMessage: t, scrollToStart: r }), [e, t, r]);
}
function wt() {
  let { stateStore: e } = K();
  return f2.useSyncExternalStore(e.subscribe, e.getSnapshot, e.getSnapshot);
}
function Ot() {
  let { observeVisibility: e, unobserveVisibility: t, visibilityStore: r } = K(), n = f2.useCallback((l2) => r.subscribe(l2, e, t), [e, t, r]);
  return f2.useSyncExternalStore(n, r.getSnapshot, r.getSnapshot);
}
function ft({ autoScroll: e = false, children: t, defaultScrollPosition: r = "end", scrollEdgeThreshold: n, scrollPreviousItemPeek: l2, scrollMargin: c }) {
  let { context: S2, registerMessage: o } = st({ autoScroll: e, defaultScrollPosition: r, scrollEdgeThreshold: n, scrollPreviousItemPeek: l2, scrollMargin: c });
  return (0, import_jsx_runtime.jsx)(it.Provider, { value: S2, children: (0, import_jsx_runtime.jsx)(ut.Provider, { value: o, children: t }) });
}
function St() {
  let { pendingDefaultScrollStore: e } = K();
  return f2.useSyncExternalStore(e.subscribe, e.getSnapshot, e.getSnapshot);
}
function gt({ children: e, ...t }) {
  let { setRootElement: r } = K(), n = St();
  return (0, import_jsx_runtime.jsx)("div", { ref: r, ...t, ...n ? { "data-pending-scroll": "" } : null, children: e });
}
function Rt({ "aria-label": e, children: t, onKeyDown: r, onScroll: n, onTouchMove: l2, onWheel: c$1, preserveScrollOnPrepend: S2 = true, ref: o, role: b, tabIndex: v, ...m }) {
  let { handleResize: L, preserveScrollOnPrependRef: R2, setViewportElement: E, syncAfterScroll: h, userScrollIntent: I, viewportRef: u } = K(), k = St();
  R2.current = S2;
  let j = f2.useCallback((P) => {
    E(P), f(o)?.(P);
  }, [o, E]);
  function _(P) {
    h(), n?.(P);
  }
  function Y(P) {
    I(), c$1?.(P);
  }
  function x(P) {
    I(), l2?.(P);
  }
  function V(P) {
    Ge.has(P.key) && I(), r?.(P);
  }
  return f2.useEffect(() => {
    let P = u.current;
    if (!P || typeof ResizeObserver > "u") return;
    let G = 0, A = new ResizeObserver(() => {
      window.cancelAnimationFrame(G), G = window.requestAnimationFrame(L);
    });
    return A.observe(P), () => {
      window.cancelAnimationFrame(G), A.disconnect();
    };
  }, [L, u]), (0, import_jsx_runtime.jsx)("div", { ref: j, role: b ?? "region", "aria-label": e ?? "Messages", tabIndex: v ?? 0, onKeyDown: V, onScroll: _, onTouchMove: x, onWheel: Y, ...m, ...k ? { "data-pending-scroll": "" } : null, children: t });
}
function pt({ "aria-relevant": e, children: t, ref: r, role: n, spacerClassName: l2, ...c$1 }) {
  let { handleContentChange: S2, handleResize: o, setContentElement: b, setSpacerElement: v } = K(), m = f2.useRef(null), L = f2.useCallback((R2) => {
    m.current = R2, b(R2), f(r)?.(R2);
  }, [r, b]);
  return f2.useLayoutEffect(() => {
    let R2 = m.current;
    if (!R2 || (S2(), typeof MutationObserver > "u")) return;
    let E = new MutationObserver(() => {
      S2();
    });
    return E.observe(R2, { childList: true }), () => E.disconnect();
  }, [S2]), f2.useEffect(() => {
    let R2 = m.current;
    if (!R2 || typeof ResizeObserver > "u") return;
    let E = 0, h = new ResizeObserver(() => {
      window.cancelAnimationFrame(E), E = window.requestAnimationFrame(o);
    });
    return h.observe(R2), () => {
      window.cancelAnimationFrame(E), h.disconnect();
    };
  }, [o]), (0, import_jsx_runtime.jsxs)("div", { ref: L, role: n ?? "log", "aria-relevant": e ?? "additions", ...c$1, children: [t, (0, import_jsx_runtime.jsx)("div", { ref: v, "aria-hidden": "true", "data-message-scroller-spacer": "", hidden: true, className: l2 })] });
}
function mt({ messageId: e, ref: t, scrollAnchor: r = false, ...n }) {
  let l2 = Ct(), c$1 = f2.useRef(null), S2 = f2.useCallback((o) => {
    let b = c$1.current;
    c$1.current = o, e && l2(e, o, b), f(t)?.(o);
  }, [e, t, l2]);
  return (0, import_jsx_runtime.jsx)("div", { ref: S2, "data-message-id": e, "data-scroll-anchor": r ? "true" : "false", ...n });
}
function dt({ behavior: e = "smooth", children: t, direction: r = "end", onClick: n, render: l2, tabIndex: c, type: S2 = "button", ...o }) {
  let { scrollToEnd: b$1, scrollToStart: v, stateStore: m } = K(), L = at(n), R2 = f2.useCallback((u) => m.subscribe(u), [m]), E = f2.useCallback(() => {
    let u = m.getSnapshot();
    return r === "start" ? u.start : u.end;
  }, [r, m]), h = f2.useSyncExternalStore(R2, E, E), I = f2.useCallback((u) => {
    h && (L.current?.(u), u.defaultPrevented || (u.currentTarget.blur(), r === "start" ? v({ behavior: e }) : b$1({ behavior: e })));
  }, [e, r, h, L, b$1, v]);
  return S({ defaultTagName: "button", props: d({ type: S2, inert: !h, tabIndex: h ? c : -1, children: t ?? (0, import_jsx_runtime.jsxs)("span", { children: ["Scroll to ", r] }), onClick: I }, o), render: l2, state: { active: h, direction: r }, stateAttributesMapping: { active: (u) => ({ "data-active": u ? "true" : "false" }) } });
}
var er = { Provider: ft, Root: gt, Viewport: Rt, Content: pt, Item: mt, Button: dt };
export {
  er as MessageScroller,
  Pt as useMessageScroller,
  wt as useMessageScrollerScrollable,
  Ot as useMessageScrollerVisibility
};
//# sourceMappingURL=@shadcn_react_message-scroller.js.map
