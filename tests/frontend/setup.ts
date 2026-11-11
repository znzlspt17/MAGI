// 2026-11-11: jsdom에 없는 CSS 식별자 이스케이프를 보완해 실제 Astryx 레이어를 검사한다.
if (!globalThis.CSS) Object.defineProperty(globalThis, "CSS", {value: {}, configurable: true});
if (!CSS.escape) {
  CSS.escape = (value: string): string => {
    const text = String(value);
    return Array.from(text, (character, index) => {
      const point = character.codePointAt(0)!;
      if (point === 0) return "\uFFFD";
      if (point < 32 || point === 127 || (index === 0 && /[0-9]/.test(character)) ||
        (index === 1 && text[0] === "-" && /[0-9]/.test(character))) return `\\${point.toString(16)} `;
      if (index === 0 && text.length === 1 && character === "-") return "\\-";
      return point >= 128 || /[a-zA-Z0-9_-]/.test(character) ? character : `\\${character}`;
    }).join("");
  };
}

// 2026-11-11: 단위 테스트에는 열림 상태와 close 이벤트만 제공한다. 네이티브 포커스 가두기는 E2E에서 검사한다.
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
}
if (!HTMLDialogElement.prototype.close) {
  HTMLDialogElement.prototype.close = function (returnValue = "") {
    this.returnValue = returnValue;
    this.open = false;
    this.dispatchEvent(new Event("close"));
  };
}

// 2026-11-11: Chromium에서 확인한 auto popover의 숨김·외부 클릭 동작을 jsdom에도 제공한다.
// 위치 계산·포커스 가두기·실제 최상위 레이어는 브라우저 검증으로 별도 확인한다.
if (!HTMLElement.prototype.showPopover) {
  const nativePopoverStyle = document.createElement("style");
  nativePopoverStyle.textContent = "[popover] { display: none; }";
  document.head.append(nativePopoverStyle);
  const opened = new Set<HTMLElement>();
  const sources = new WeakMap<HTMLElement, HTMLElement>();
  function toggleEvent(type: string, opening: boolean) {
    const event = new Event(type, {cancelable: type === "beforetoggle" && opening});
    Object.defineProperties(event, {oldState: {value: opening ? "closed" : "open"}, newState: {value: opening ? "open" : "closed"}});
    return event;
  }
  HTMLElement.prototype.showPopover = function (options?: {source?: HTMLElement}) {
    if (opened.has(this)) return;
    if (!this.dispatchEvent(toggleEvent("beforetoggle", true))) return;
    if (this.getAttribute("popover") !== "manual") {
      for (const other of [...opened]) if (other !== this && other.getAttribute("popover") !== "manual" && !other.contains(this)) other.hidePopover();
    }
    if (options?.source) sources.set(this, options.source);
    opened.add(this);
    this.style.display = "block";
    this.dispatchEvent(toggleEvent("toggle", true));
  };
  HTMLElement.prototype.hidePopover = function () {
    if (!opened.has(this)) { this.style.display = "none"; return; }
    this.dispatchEvent(toggleEvent("beforetoggle", false));
    opened.delete(this);
    this.style.display = "none";
    this.dispatchEvent(toggleEvent("toggle", false));
  };
  HTMLElement.prototype.togglePopover = function (options?: boolean | {force?: boolean}) {
    const force = typeof options === "boolean" ? options : options?.force;
    const show = force ?? !opened.has(this);
    if (show) this.showPopover(); else this.hidePopover();
    return show;
  };
  Object.defineProperty(HTMLElement.prototype, "popover", {
    configurable: true,
    get() { return this.getAttribute("popover"); },
    set(value: string | null) {
      if (value === null) this.removeAttribute("popover"); else this.setAttribute("popover", value);
      if (!opened.has(this)) this.style.display = "none";
    },
  });
  document.addEventListener("click", event => {
    for (const element of [...opened]) {
      if (!element.isConnected) { opened.delete(element); continue; }
      const target = event.target;
      if (element.getAttribute("popover") !== "manual" && target instanceof Node && !element.contains(target) && !sources.get(element)?.contains(target)) element.hidePopover();
    }
  }, true);
}
