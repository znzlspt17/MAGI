import {
  useCallbackRef
} from "./chunk-DWRS74ET.js";
import {
  Primitive,
  composeEventHandlers,
  createContextScope,
  useControllableState,
  useId,
  useLayoutEffect2
} from "./chunk-M4L4BMTB.js";
import {
  require_jsx_runtime
} from "./chunk-4YUEB2SN.js";
import {
  createSlot,
  useComposedRefs
} from "./chunk-JSWZMOYI.js";
import {
  require_react
} from "./chunk-2JUH4I7N.js";
import {
  __privateAdd,
  __privateGet,
  __privateSet,
  __toESM
} from "./chunk-QKQ6FTX6.js";

// node_modules/.pnpm/@radix-ui+react-direction@1_527de58341a1b41b1117c799ae82b79a/node_modules/@radix-ui/react-direction/dist/index.mjs
var React = __toESM(require_react(), 1);
var import_jsx_runtime = __toESM(require_jsx_runtime(), 1);
var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });
var Direction = {
  LTR: "ltr",
  RTL: "rtl"
};
var DirectionContext = React.createContext(void 0);
var DirectionProvider = __name((props) => {
  const { dir, children } = props;
  return (0, import_jsx_runtime.jsx)(DirectionContext.Provider, { value: dir, children });
}, "DirectionProvider");
function useDirection(localDir) {
  const globalDir = React.useContext(DirectionContext);
  return localDir || globalDir || Direction.LTR;
}
__name(useDirection, "useDirection");

// node_modules/.pnpm/@radix-ui+react-roving-focu_bed290ae4c554285fceef8952991064b/node_modules/@radix-ui/react-roving-focus/dist/index.mjs
var React4 = __toESM(require_react(), 1);

// node_modules/.pnpm/@radix-ui+react-collection@_6acb2d8ed0d1a5e2d86fa68fa86b38fc/node_modules/@radix-ui/react-collection/dist/index.mjs
var React2 = __toESM(require_react(), 1);
var import_jsx_runtime2 = __toESM(require_jsx_runtime(), 1);
var React22 = __toESM(require_react(), 1);
var import_jsx_runtime3 = __toESM(require_jsx_runtime(), 1);
var __defProp2 = Object.defineProperty;
var __name2 = (target, value) => __defProp2(target, "name", { value, configurable: true });
function createCollection(name) {
  const PROVIDER_NAME = name + "CollectionProvider";
  const [createCollectionContext, createCollectionScope2] = createContextScope(PROVIDER_NAME);
  const [CollectionProviderImpl, useCollectionContext] = createCollectionContext(
    PROVIDER_NAME,
    { collectionRef: { current: null }, itemMap: /* @__PURE__ */ new Map() }
  );
  const CollectionProvider = __name2((props) => {
    const { scope, children } = props;
    const ref = React2.useRef(null);
    const itemMap = React2.useRef(/* @__PURE__ */ new Map()).current;
    return (0, import_jsx_runtime2.jsx)(CollectionProviderImpl, { scope, itemMap, collectionRef: ref, children });
  }, "CollectionProvider");
  CollectionProvider.displayName = PROVIDER_NAME;
  const COLLECTION_SLOT_NAME = name + "CollectionSlot";
  const CollectionSlotImpl = createSlot(COLLECTION_SLOT_NAME);
  const CollectionSlot = React2.forwardRef(
    (props, forwardedRef) => {
      const { scope, children } = props;
      const context = useCollectionContext(COLLECTION_SLOT_NAME, scope);
      const composedRefs = useComposedRefs(forwardedRef, context.collectionRef);
      return (0, import_jsx_runtime2.jsx)(CollectionSlotImpl, { ref: composedRefs, children });
    }
  );
  CollectionSlot.displayName = COLLECTION_SLOT_NAME;
  const ITEM_SLOT_NAME = name + "CollectionItemSlot";
  const ITEM_DATA_ATTR = "data-radix-collection-item";
  const CollectionItemSlotImpl = createSlot(ITEM_SLOT_NAME);
  const CollectionItemSlot = React2.forwardRef(
    (props, forwardedRef) => {
      const { scope, children, ...itemData } = props;
      const ref = React2.useRef(null);
      const composedRefs = useComposedRefs(forwardedRef, ref);
      const context = useCollectionContext(ITEM_SLOT_NAME, scope);
      React2.useEffect(() => {
        context.itemMap.set(ref, { ref, ...itemData });
        return () => void context.itemMap.delete(ref);
      });
      return (0, import_jsx_runtime2.jsx)(CollectionItemSlotImpl, { ...{ [ITEM_DATA_ATTR]: "" }, ref: composedRefs, children });
    }
  );
  CollectionItemSlot.displayName = ITEM_SLOT_NAME;
  function useCollection2(scope) {
    const context = useCollectionContext(name + "CollectionConsumer", scope);
    const getItems = React2.useCallback(() => {
      const collectionNode = context.collectionRef.current;
      if (!collectionNode) return [];
      const orderedNodes = Array.from(collectionNode.querySelectorAll(`[${ITEM_DATA_ATTR}]`));
      const items = Array.from(context.itemMap.values());
      const orderedItems = items.sort(
        (a, b) => orderedNodes.indexOf(a.ref.current) - orderedNodes.indexOf(b.ref.current)
      );
      return orderedItems;
    }, [context.collectionRef, context.itemMap]);
    return getItems;
  }
  __name2(useCollection2, "useCollection");
  return [
    { Provider: CollectionProvider, Slot: CollectionSlot, ItemSlot: CollectionItemSlot },
    useCollection2,
    createCollectionScope2
  ];
}
__name2(createCollection, "createCollection");
var __instanciated = /* @__PURE__ */ new WeakMap();
var _keys, _a;
var OrderedDict = (_a = class extends Map {
  constructor(entries) {
    super(entries);
    __privateAdd(this, _keys);
    __privateSet(this, _keys, [...super.keys()]);
    __instanciated.set(this, true);
  }
  set(key, value) {
    if (__instanciated.get(this) && !this.has(key)) {
      __privateGet(this, _keys).push(key);
    }
    super.set(key, value);
    return this;
  }
  /**
   * Sets a key-value pair so that it ends up at the given index.
   * - Existing keys are moved
   * - Negative indices count from the end of the resulting dictionary, so
   *   inserting at -1 makes the item the last one, -2 the second to last, etc.
   * - Out-of-range indices are clamped
   */
  insert(index, key, value) {
    const has = this.has(key);
    const finalSize = has ? this.size : this.size + 1;
    const relativeIndex = toSafeInteger(index);
    const targetIndex = relativeIndex >= 0 ? Math.min(relativeIndex, finalSize - 1) : Math.max(finalSize + relativeIndex, 0);
    if (has ? __privateGet(this, _keys).indexOf(key) === targetIndex : targetIndex === this.size) {
      this.set(key, value);
      return this;
    }
    const keys = __privateGet(this, _keys).filter((existingKey) => existingKey !== key);
    keys.splice(targetIndex, 0, key);
    const entries = keys.map((entryKey) => [
      entryKey,
      entryKey === key ? value : this.get(entryKey)
    ]);
    this.clear();
    for (const [entryKey, entryValue] of entries) {
      this.set(entryKey, entryValue);
    }
    return this;
  }
  with(index, key, value) {
    const copy = new _a(this);
    copy.insert(index, key, value);
    return copy;
  }
  before(key) {
    const index = __privateGet(this, _keys).indexOf(key) - 1;
    if (index < 0) {
      return void 0;
    }
    return this.entryAt(index);
  }
  /**
   * Sets a new key-value pair at the position before the given key.
   */
  setBefore(key, newKey, value) {
    const index = __privateGet(this, _keys).indexOf(key);
    if (index === -1) {
      return this;
    }
    const currentIndex = __privateGet(this, _keys).indexOf(newKey);
    const targetIndex = currentIndex !== -1 && currentIndex < index ? index - 1 : index;
    return this.insert(targetIndex, newKey, value);
  }
  after(key) {
    let index = __privateGet(this, _keys).indexOf(key);
    index = index === -1 || index === this.size - 1 ? -1 : index + 1;
    if (index === -1) {
      return void 0;
    }
    return this.entryAt(index);
  }
  /**
   * Sets a new key-value pair at the position after the given key.
   */
  setAfter(key, newKey, value) {
    const index = __privateGet(this, _keys).indexOf(key);
    if (index === -1) {
      return this;
    }
    const currentIndex = __privateGet(this, _keys).indexOf(newKey);
    const targetIndex = currentIndex !== -1 && currentIndex <= index ? index : index + 1;
    return this.insert(targetIndex, newKey, value);
  }
  first() {
    return this.entryAt(0);
  }
  last() {
    return this.entryAt(-1);
  }
  clear() {
    __privateSet(this, _keys, []);
    return super.clear();
  }
  delete(key) {
    const deleted = super.delete(key);
    if (deleted) {
      __privateGet(this, _keys).splice(__privateGet(this, _keys).indexOf(key), 1);
    }
    return deleted;
  }
  deleteAt(index) {
    const key = this.keyAt(index);
    if (key !== void 0) {
      return this.delete(key);
    }
    return false;
  }
  at(index) {
    const key = at(__privateGet(this, _keys), index);
    if (key !== void 0) {
      return this.get(key);
    }
  }
  entryAt(index) {
    const key = at(__privateGet(this, _keys), index);
    if (key !== void 0) {
      return [key, this.get(key)];
    }
  }
  indexOf(key) {
    return __privateGet(this, _keys).indexOf(key);
  }
  keyAt(index) {
    return at(__privateGet(this, _keys), index);
  }
  from(key, offset) {
    const index = this.indexOf(key);
    if (index === -1) {
      return void 0;
    }
    let dest = index + offset;
    if (dest < 0) dest = 0;
    if (dest >= this.size) dest = this.size - 1;
    return this.at(dest);
  }
  keyFrom(key, offset) {
    const index = this.indexOf(key);
    if (index === -1) {
      return void 0;
    }
    let dest = index + offset;
    if (dest < 0) dest = 0;
    if (dest >= this.size) dest = this.size - 1;
    return this.keyAt(dest);
  }
  find(predicate, thisArg) {
    let index = 0;
    for (const entry of this) {
      if (Reflect.apply(predicate, thisArg, [entry, index, this])) {
        return entry;
      }
      index++;
    }
    return void 0;
  }
  findIndex(predicate, thisArg) {
    let index = 0;
    for (const entry of this) {
      if (Reflect.apply(predicate, thisArg, [entry, index, this])) {
        return index;
      }
      index++;
    }
    return -1;
  }
  filter(predicate, thisArg) {
    const entries = [];
    let index = 0;
    for (const entry of this) {
      if (Reflect.apply(predicate, thisArg, [entry, index, this])) {
        entries.push(entry);
      }
      index++;
    }
    return new _a(entries);
  }
  map(callbackfn, thisArg) {
    const entries = [];
    let index = 0;
    for (const entry of this) {
      entries.push([entry[0], Reflect.apply(callbackfn, thisArg, [entry, index, this])]);
      index++;
    }
    return new _a(entries);
  }
  reduce(...args) {
    const [callbackfn, initialValue] = args;
    const hasInitialValue = args.length > 1;
    if (!hasInitialValue && this.size === 0) {
      throw new TypeError("Reduce of empty OrderedDict with no initial value");
    }
    let index = 0;
    let accumulator = initialValue;
    for (const entry of this) {
      if (index === 0 && !hasInitialValue) {
        accumulator = entry;
      } else {
        accumulator = Reflect.apply(callbackfn, this, [accumulator, entry, index, this]);
      }
      index++;
    }
    return accumulator;
  }
  reduceRight(...args) {
    const [callbackfn, initialValue] = args;
    const hasInitialValue = args.length > 1;
    if (!hasInitialValue && this.size === 0) {
      throw new TypeError("Reduce of empty OrderedDict with no initial value");
    }
    let accumulator = initialValue;
    for (let index = this.size - 1; index >= 0; index--) {
      const entry = this.entryAt(index);
      if (index === this.size - 1 && !hasInitialValue) {
        accumulator = entry;
      } else {
        accumulator = Reflect.apply(callbackfn, this, [accumulator, entry, index, this]);
      }
    }
    return accumulator;
  }
  /**
   * Sorts the dictionary in place. This method mutates the dictionary and
   * returns a reference to the same object
   *
   * @param compareFn Function used to determine the order of the elements. It
   * is expected to return a negative value if the first argument is less than
   * the second argument, zero if they're equal, and a positive value otherwise.
   */
  sort(compareFn) {
    if (typeof compareFn !== "function") {
      throw new TypeError(`OrderedDict.sort requires a compare function`);
    }
    const entries = [...this.entries()].sort(compareFn);
    this.clear();
    for (const [key, value] of entries) {
      this.set(key, value);
    }
    return this;
  }
  /**
   * Returns a copy of the dictionary with its elements sorted.
   *
   * @param compareFn Function used to determine the order of the elements. It
   * is expected to return a negative value if the first argument is less than
   * the second argument, zero if they're equal, and a positive value otherwise.
   */
  toSorted(compareFn) {
    if (typeof compareFn !== "function") {
      throw new TypeError(`OrderedDict.toSorted requires a compare function`);
    }
    const entries = [...this.entries()].sort(compareFn);
    return new _a(entries);
  }
  toReversed() {
    const reversed = new _a();
    for (let index = this.size - 1; index >= 0; index--) {
      const key = this.keyAt(index);
      const element = this.get(key);
      reversed.set(key, element);
    }
    return reversed;
  }
  toSpliced(...args) {
    const entries = [...this.entries()];
    entries.splice(...args);
    return new _a(entries);
  }
  slice(start, end) {
    const result = new _a();
    for (const key of __privateGet(this, _keys).slice(start, end)) {
      result.set(key, this.get(key));
    }
    return result;
  }
  every(predicate, thisArg) {
    let index = 0;
    for (const entry of this) {
      if (!Reflect.apply(predicate, thisArg, [entry, index, this])) {
        return false;
      }
      index++;
    }
    return true;
  }
  some(predicate, thisArg) {
    let index = 0;
    for (const entry of this) {
      if (Reflect.apply(predicate, thisArg, [entry, index, this])) {
        return true;
      }
      index++;
    }
    return false;
  }
}, _keys = new WeakMap(), __name2(_a, "OrderedDict"), _a);
function at(array, index) {
  if ("at" in Array.prototype) {
    return Array.prototype.at.call(array, index);
  }
  const actualIndex = toSafeIndex(array, index);
  return actualIndex === -1 ? void 0 : array[actualIndex];
}
__name2(at, "at");
function toSafeIndex(array, index) {
  const length = array.length;
  const relativeIndex = toSafeInteger(index);
  const actualIndex = relativeIndex >= 0 ? relativeIndex : length + relativeIndex;
  return actualIndex < 0 || actualIndex >= length ? -1 : actualIndex;
}
__name2(toSafeIndex, "toSafeIndex");
function toSafeInteger(number) {
  return number !== number || number === 0 ? 0 : Math.trunc(number);
}
__name2(toSafeInteger, "toSafeInteger");
function createCollection2(name) {
  const PROVIDER_NAME = name + "CollectionProvider";
  const [createCollectionContext, createCollectionScope2] = createContextScope(PROVIDER_NAME);
  const [CollectionStableContextProvider, useStableCollectionContext] = createCollectionContext(PROVIDER_NAME);
  CollectionStableContextProvider.displayName = name + "CollectionStableContextProvider";
  const [CollectionStatefulContextProvider, useStatefulCollectionContext] = createCollectionContext(PROVIDER_NAME);
  CollectionStatefulContextProvider.displayName = name + "CollectionStatefulContextProvider";
  const CollectionProvider = __name2(({ state, ...props }) => {
    return state ? (0, import_jsx_runtime3.jsx)(CollectionProviderImpl, { ...props, state }) : (0, import_jsx_runtime3.jsx)(CollectionInit, { ...props });
  }, "CollectionProvider");
  CollectionProvider.displayName = PROVIDER_NAME;
  const CollectionInit = __name2((props) => {
    const state = useInitCollection();
    return (0, import_jsx_runtime3.jsx)(CollectionProviderImpl, { ...props, state });
  }, "CollectionInit");
  CollectionInit.displayName = name + "CollectionInit";
  const CollectionProviderImpl = __name2((props) => {
    const { scope, children, state } = props;
    const ref = React22.useRef(null);
    const [collectionElement, setCollectionElement] = React22.useState(
      null
    );
    const composeRefs = useComposedRefs(ref, setCollectionElement);
    const [collection, setCollection] = state;
    const registryRef = React22.useRef(
      new OrderedDict()
    );
    const getCollection = React22.useCallback(() => {
      const registry = registryRef.current;
      if (!isInDocumentOrder(registry)) {
        registry.sort(sortByDocumentPosition);
      }
      return registry;
    }, []);
    React22.useEffect(() => {
      if (!collectionElement) {
        return;
      }
      const observer = getChildListObserver(() => {
        setCollection((map) => {
          const sorted = map.toSorted(sortByDocumentPosition);
          const orderChanged = sorted.some(([key], index) => map.keyAt(index) !== key);
          return orderChanged ? sorted : map;
        });
      });
      observer.observe(collectionElement, {
        childList: true,
        subtree: true
      });
      return () => {
        observer.disconnect();
      };
    }, [collectionElement, setCollection]);
    return (0, import_jsx_runtime3.jsx)(
      CollectionStableContextProvider,
      {
        scope,
        collectionElementRef: composeRefs,
        collectionElementRefObject: ref,
        getCollection,
        setCollection,
        registryRef,
        children: (0, import_jsx_runtime3.jsx)(
          CollectionStatefulContextProvider,
          {
            scope,
            collectionElement,
            collection,
            children
          }
        )
      }
    );
  }, "CollectionProviderImpl");
  CollectionProviderImpl.displayName = name + "CollectionProviderImpl";
  const COLLECTION_SLOT_NAME = name + "CollectionSlot";
  const CollectionSlotImpl = createSlot(COLLECTION_SLOT_NAME);
  const CollectionSlot = React22.forwardRef(
    (props, forwardedRef) => {
      const { scope, children } = props;
      const context = useStableCollectionContext(COLLECTION_SLOT_NAME, scope);
      const composedRefs = useComposedRefs(forwardedRef, context.collectionElementRef);
      return (0, import_jsx_runtime3.jsx)(CollectionSlotImpl, { ref: composedRefs, children });
    }
  );
  CollectionSlot.displayName = COLLECTION_SLOT_NAME;
  const ITEM_SLOT_NAME = name + "CollectionItemSlot";
  const ITEM_DATA_ATTR = "data-radix-collection-item";
  const CollectionItemSlotImpl = createSlot(ITEM_SLOT_NAME);
  const CollectionItemSlot = React22.forwardRef(
    (props, forwardedRef) => {
      const { scope, children, ...itemData } = props;
      const ref = React22.useRef(null);
      const context = useStableCollectionContext(ITEM_SLOT_NAME, scope);
      const { setCollection, registryRef } = context;
      const itemDataRef = React22.useRef(itemData);
      if (!shallowEqual(itemDataRef.current, itemData)) {
        itemDataRef.current = itemData;
      }
      const memoizedItemData = itemDataRef.current;
      const registerElement = React22.useCallback(
        (node) => {
          const registry = registryRef.current;
          if (node) {
            registry.set(node, {
              ...itemDataRef.current,
              element: node
            });
          } else if (ref.current) {
            registry.delete(ref.current);
          }
        },
        [registryRef]
      );
      const composedRefs = useComposedRefs(forwardedRef, registerElement, ref);
      useLayoutEffect2(() => {
        const node = ref.current;
        const registry = registryRef.current;
        if (node && registry.has(node)) {
          registry.set(node, { ...memoizedItemData, element: node });
        }
      }, [memoizedItemData, registryRef]);
      const registeredRef = React22.useRef(null);
      React22.useEffect(() => {
        const element = ref.current;
        const registered = registeredRef.current;
        if ((registered?.element ?? null) === element && (!element || registered?.itemData === memoizedItemData)) {
          return;
        }
        registeredRef.current = element ? { element, itemData: memoizedItemData } : null;
        setCollection((map) => {
          const next = new OrderedDict(map);
          if (registered && registered.element !== element) {
            next.delete(registered.element);
          }
          if (element) {
            next.set(element, { ...memoizedItemData, element });
          }
          return next.sort(sortByDocumentPosition);
        });
      });
      React22.useEffect(() => {
        return () => {
          const registered = registeredRef.current;
          registeredRef.current = null;
          if (!registered) {
            return;
          }
          setCollection((map) => {
            if (!map.has(registered.element)) {
              return map;
            }
            const next = new OrderedDict(map);
            next.delete(registered.element);
            return next;
          });
        };
      }, [setCollection]);
      return (0, import_jsx_runtime3.jsx)(CollectionItemSlotImpl, { ...{ [ITEM_DATA_ATTR]: "" }, ref: composedRefs, children });
    }
  );
  CollectionItemSlot.displayName = ITEM_SLOT_NAME;
  function useInitCollection() {
    return React22.useState(new OrderedDict());
  }
  __name2(useInitCollection, "useInitCollection");
  function useCollection2(scope) {
    const { collection } = useStatefulCollectionContext(name + "CollectionConsumer", scope);
    return collection;
  }
  __name2(useCollection2, "useCollection");
  function useGetCollection(scope) {
    const { getCollection } = useStableCollectionContext(name + "CollectionConsumer", scope);
    return getCollection;
  }
  __name2(useGetCollection, "useGetCollection");
  const functions = {
    createCollectionScope: createCollectionScope2,
    useCollection: useCollection2,
    useGetCollection,
    useInitCollection
  };
  return [
    { Provider: CollectionProvider, Slot: CollectionSlot, ItemSlot: CollectionItemSlot },
    functions
  ];
}
__name2(createCollection2, "createCollection");
function shallowEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object") return false;
  if (a == null || b == null) return false;
  const keysA = Object.keys(a);
  const keysB = Object.keys(b);
  if (keysA.length !== keysB.length) return false;
  for (const key of keysA) {
    if (!Object.prototype.hasOwnProperty.call(b, key)) return false;
    if (a[key] !== b[key]) return false;
  }
  return true;
}
__name2(shallowEqual, "shallowEqual");
function isElementPreceding(a, b) {
  return !!(b.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_PRECEDING);
}
__name2(isElementPreceding, "isElementPreceding");
function isInDocumentOrder(dict) {
  let previous;
  for (const element of dict.keys()) {
    if (previous) {
      const position = previous.compareDocumentPosition(element);
      if (!(position & Node.DOCUMENT_POSITION_DISCONNECTED) && position & Node.DOCUMENT_POSITION_PRECEDING) {
        return false;
      }
    }
    previous = element;
  }
  return true;
}
__name2(isInDocumentOrder, "isInDocumentOrder");
function sortByDocumentPosition(a, b) {
  return !a[1].element || !b[1].element ? 0 : isElementPreceding(a[1].element, b[1].element) ? -1 : 1;
}
__name2(sortByDocumentPosition, "sortByDocumentPosition");
function getChildListObserver(callback) {
  const observer = new MutationObserver((mutationsList) => {
    for (const mutation of mutationsList) {
      if (mutation.type === "childList") {
        callback();
        return;
      }
    }
  });
  return observer;
}
__name2(getChildListObserver, "getChildListObserver");

// node_modules/.pnpm/@radix-ui+react-use-is-hydr_d5f02d66173c49c68cbede894417d34b/node_modules/@radix-ui/react-use-is-hydrated/dist/index.mjs
var React23 = __toESM(require_react(), 1);
var React3 = __toESM(require_react(), 1);
var __defProp3 = Object.defineProperty;
var __name3 = (target, value) => __defProp3(target, "name", { value, configurable: true });
var _isHydrated = false;
function useIsHydrated() {
  const [isHydrated, setIsHydrated] = React3.useState(_isHydrated);
  React3.useEffect(() => {
    if (!_isHydrated) {
      _isHydrated = true;
      setIsHydrated(true);
    }
  }, []);
  return isHydrated;
}
__name3(useIsHydrated, "useIsHydrated");
var useReactSyncExternalStore = React23[" useSyncExternalStore ".trim().toString()];
function subscribe() {
  return () => {
  };
}
__name3(subscribe, "subscribe");
function useIsHydratedModern() {
  return useReactSyncExternalStore(
    subscribe,
    () => true,
    () => false
  );
}
__name3(useIsHydratedModern, "useIsHydratedModern");
var useIsHydrated2 = typeof useReactSyncExternalStore === "function" ? useIsHydratedModern : useIsHydrated;

// node_modules/.pnpm/@radix-ui+react-roving-focu_bed290ae4c554285fceef8952991064b/node_modules/@radix-ui/react-roving-focus/dist/index.mjs
var import_jsx_runtime4 = __toESM(require_jsx_runtime(), 1);
var __defProp4 = Object.defineProperty;
var __name4 = (target, value) => __defProp4(target, "name", { value, configurable: true });
var ENTRY_FOCUS = "rovingFocusGroup.onEntryFocus";
var EVENT_OPTIONS = { bubbles: false, cancelable: true };
var GROUP_NAME = "RovingFocusGroup";
var [Collection, useCollection, createCollectionScope] = createCollection(GROUP_NAME);
var [createRovingFocusGroupContext, createRovingFocusGroupScope] = createContextScope(
  GROUP_NAME,
  [createCollectionScope]
);
var Orientation = {
  Vertical: "vertical",
  Horizontal: "horizontal"
};
var Direction2 = {
  LTR: "ltr",
  RTL: "rtl"
};
var [RovingFocusProvider, useRovingFocusContext] = createRovingFocusGroupContext(GROUP_NAME);
var RovingFocusGroup = React4.forwardRef(
  // blank line to reduce diff noise
  __name4(function RovingFocusGroup2(props, forwardedRef) {
    return (0, import_jsx_runtime4.jsx)(Collection.Provider, { scope: props.__scopeRovingFocusGroup, children: (0, import_jsx_runtime4.jsx)(Collection.Slot, { scope: props.__scopeRovingFocusGroup, children: (0, import_jsx_runtime4.jsx)(RovingFocusGroupImpl, { ...props, ref: forwardedRef }) }) });
  }, "RovingFocusGroup")
);
var RovingFocusGroupImpl = React4.forwardRef(__name4(function RovingFocusGroupImpl2(props, forwardedRef) {
  const {
    __scopeRovingFocusGroup,
    orientation,
    loop = false,
    dir,
    currentTabStopId: currentTabStopIdProp,
    defaultCurrentTabStopId,
    onCurrentTabStopIdChange,
    onEntryFocus,
    preventScrollOnEntryFocus = false,
    ...groupProps
  } = props;
  const ref = React4.useRef(null);
  const composedRefs = useComposedRefs(forwardedRef, ref);
  const direction = useDirection(dir);
  const [currentTabStopId, setCurrentTabStopId] = useControllableState({
    prop: currentTabStopIdProp,
    defaultProp: defaultCurrentTabStopId ?? null,
    onChange: onCurrentTabStopIdChange,
    caller: GROUP_NAME
  });
  const [isTabbingBackOut, setIsTabbingBackOut] = React4.useState(false);
  const handleEntryFocus = useCallbackRef(onEntryFocus);
  const getItems = useCollection(__scopeRovingFocusGroup);
  const isClickFocusRef = React4.useRef(false);
  const [focusableItemsCount, setFocusableItemsCount] = React4.useState(0);
  React4.useEffect(() => {
    const node = ref.current;
    if (node) {
      node.addEventListener(ENTRY_FOCUS, handleEntryFocus);
      return () => node.removeEventListener(ENTRY_FOCUS, handleEntryFocus);
    }
  }, [handleEntryFocus]);
  return (0, import_jsx_runtime4.jsx)(
    RovingFocusProvider,
    {
      scope: __scopeRovingFocusGroup,
      orientation,
      dir: direction,
      loop,
      currentTabStopId,
      onItemFocus: React4.useCallback(
        (tabStopId) => setCurrentTabStopId(tabStopId),
        [setCurrentTabStopId]
      ),
      onItemShiftTab: React4.useCallback(() => setIsTabbingBackOut(true), []),
      onFocusableItemAdd: React4.useCallback(
        () => setFocusableItemsCount((prevCount) => prevCount + 1),
        []
      ),
      onFocusableItemRemove: React4.useCallback(
        () => setFocusableItemsCount((prevCount) => prevCount - 1),
        []
      ),
      children: (0, import_jsx_runtime4.jsx)(
        Primitive.div,
        {
          tabIndex: isTabbingBackOut || focusableItemsCount === 0 ? -1 : 0,
          "data-orientation": orientation,
          ...groupProps,
          ref: composedRefs,
          style: { outline: "none", ...props.style },
          onMouseDown: composeEventHandlers(props.onMouseDown, () => {
            isClickFocusRef.current = true;
          }),
          onFocus: composeEventHandlers(props.onFocus, (event) => {
            const isKeyboardFocus = !isClickFocusRef.current;
            if (event.target === event.currentTarget && isKeyboardFocus && !isTabbingBackOut) {
              const entryFocusEvent = new CustomEvent(ENTRY_FOCUS, EVENT_OPTIONS);
              event.currentTarget.dispatchEvent(entryFocusEvent);
              if (!entryFocusEvent.defaultPrevented) {
                const items = getItems().filter((item) => item.focusable);
                const activeItem = items.find((item) => item.active);
                const currentItem = items.find((item) => item.id === currentTabStopId);
                const candidateItems = [activeItem, currentItem, ...items].filter(
                  Boolean
                );
                const candidateNodes = candidateItems.map((item) => item.ref.current);
                focusFirst(candidateNodes, preventScrollOnEntryFocus);
              }
            }
            isClickFocusRef.current = false;
          }),
          onBlur: composeEventHandlers(props.onBlur, () => setIsTabbingBackOut(false))
        }
      )
    }
  );
}, "RovingFocusGroupImpl"));
var ITEM_NAME = "RovingFocusGroupItem";
var RovingFocusGroupItem = React4.forwardRef(
  // blank line to reduce diff noise
  __name4(function RovingFocusGroupItem2(props, forwardedRef) {
    const {
      __scopeRovingFocusGroup,
      focusable = true,
      active = false,
      tabStopId,
      children,
      ...itemProps
    } = props;
    const autoId = useId();
    const id = tabStopId || autoId;
    const context = useRovingFocusContext(ITEM_NAME, __scopeRovingFocusGroup);
    const isCurrentTabStop = context.currentTabStopId === id;
    const getItems = useCollection(__scopeRovingFocusGroup);
    const { onFocusableItemAdd, onFocusableItemRemove, currentTabStopId } = context;
    const isHydrated = useIsHydrated2();
    useLayoutEffect2(() => {
      if (!isHydrated || !focusable) {
        return;
      }
      onFocusableItemAdd();
      return () => onFocusableItemRemove();
    }, [isHydrated, focusable, onFocusableItemAdd, onFocusableItemRemove]);
    React4.useEffect(() => {
      if (isHydrated || !focusable) {
        return;
      }
      onFocusableItemAdd();
      return () => onFocusableItemRemove();
    }, [isHydrated, focusable, onFocusableItemAdd, onFocusableItemRemove]);
    return (0, import_jsx_runtime4.jsx)(
      Collection.ItemSlot,
      {
        scope: __scopeRovingFocusGroup,
        id,
        focusable,
        active,
        children: (0, import_jsx_runtime4.jsx)(
          Primitive.span,
          {
            tabIndex: isCurrentTabStop ? 0 : -1,
            "data-orientation": context.orientation,
            ...itemProps,
            ref: forwardedRef,
            onMouseDown: composeEventHandlers(props.onMouseDown, (event) => {
              if (!focusable) event.preventDefault();
              else context.onItemFocus(id);
            }),
            onFocus: composeEventHandlers(props.onFocus, () => context.onItemFocus(id)),
            onKeyDown: composeEventHandlers(props.onKeyDown, (event) => {
              if (event.key === "Tab" && event.shiftKey) {
                context.onItemShiftTab();
                return;
              }
              if (event.target !== event.currentTarget) return;
              const focusIntent = getFocusIntent(event, context.orientation, context.dir);
              if (focusIntent !== void 0) {
                if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
                event.preventDefault();
                const items = getItems().filter((item) => item.focusable);
                let candidateNodes = items.map((item) => item.ref.current);
                if (focusIntent === "last") candidateNodes.reverse();
                else if (focusIntent === "prev" || focusIntent === "next") {
                  if (focusIntent === "prev") candidateNodes.reverse();
                  const currentIndex = candidateNodes.indexOf(event.currentTarget);
                  candidateNodes = context.loop ? wrapArray(candidateNodes, currentIndex + 1) : candidateNodes.slice(currentIndex + 1);
                }
                setTimeout(() => focusFirst(candidateNodes));
              }
            }),
            children: typeof children === "function" ? children({ isCurrentTabStop, hasTabStop: currentTabStopId != null }) : children
          }
        )
      }
    );
  }, "RovingFocusGroupItem")
);
var MAP_KEY_TO_FOCUS_INTENT = {
  ArrowLeft: "prev",
  ArrowUp: "prev",
  ArrowRight: "next",
  ArrowDown: "next",
  PageUp: "first",
  Home: "first",
  PageDown: "last",
  End: "last"
};
function getDirectionAwareKey(key, dir) {
  if (dir !== Direction2.RTL) return key;
  return key === "ArrowLeft" ? "ArrowRight" : key === "ArrowRight" ? "ArrowLeft" : key;
}
__name4(getDirectionAwareKey, "getDirectionAwareKey");
function getFocusIntent(event, orientation, dir) {
  const key = getDirectionAwareKey(event.key, dir);
  if (orientation === Orientation.Vertical && ["ArrowLeft", "ArrowRight"].includes(key)) {
    return void 0;
  }
  if (orientation === Orientation.Horizontal && ["ArrowUp", "ArrowDown"].includes(key)) {
    return void 0;
  }
  return MAP_KEY_TO_FOCUS_INTENT[key];
}
__name4(getFocusIntent, "getFocusIntent");
function focusFirst(candidates, preventScroll = false) {
  const PREVIOUSLY_FOCUSED_ELEMENT = document.activeElement;
  for (const candidate of candidates) {
    if (candidate === PREVIOUSLY_FOCUSED_ELEMENT) return;
    candidate.focus({ preventScroll });
    if (document.activeElement !== PREVIOUSLY_FOCUSED_ELEMENT) return;
  }
}
__name4(focusFirst, "focusFirst");
function wrapArray(array, startIndex) {
  return array.map((_, index) => array[(startIndex + index) % array.length]);
}
__name4(wrapArray, "wrapArray");

export {
  createCollection,
  useDirection,
  createRovingFocusGroupScope,
  RovingFocusGroup,
  RovingFocusGroupItem
};
//# sourceMappingURL=chunk-OS6QBPFW.js.map
