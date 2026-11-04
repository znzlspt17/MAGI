import {
  useLayoutEffect2
} from "./chunk-M4L4BMTB.js";
import {
  require_react
} from "./chunk-2JUH4I7N.js";
import {
  __toESM
} from "./chunk-QKQ6FTX6.js";

// node_modules/.pnpm/@radix-ui+react-use-callbac_69a3fb791ef61c6e6ef64d5483eb0094/node_modules/@radix-ui/react-use-callback-ref/dist/index.mjs
var React = __toESM(require_react(), 1);
var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
var useReactInsertionEffect = React[" useInsertionEffect ".trim().toString()];
function useCallbackRef(callback) {
  const callbackRef = React.useRef(callback);
  if (typeof useReactInsertionEffect === "function") {
    useReactInsertionEffect(() => {
      callbackRef.current = callback;
    });
  } else {
    useLayoutEffect2(() => {
      callbackRef.current = callback;
    });
  }
  return React.useMemo(() => ((...args) => callbackRef.current?.(...args)), []);
}
__name(useCallbackRef, "useCallbackRef");

export {
  useCallbackRef
};
//# sourceMappingURL=chunk-DWRS74ET.js.map
