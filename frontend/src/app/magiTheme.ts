import {defineTheme} from "@astryxdesign/core/theme";
import {neutralTheme} from "@astryxdesign/theme-neutral";

// 2026-11-11: Neutral의 컴포넌트를 유지하면서 MAGI 라벤더 팔레트를 적용한다.
export const magiTheme = defineTheme({
  name: "magi",
  extends: neutralTheme,
  color: {accent: "#776095", neutralStyle: "neutral"},
  typography: {
    scale: {base: 14, ratio: 1.2},
    body: {family: "Segoe UI", fallbacks: '"Malgun Gothic", system-ui, sans-serif'},
    heading: {family: "Segoe UI", fallbacks: '"Malgun Gothic", system-ui, sans-serif'},
  },
  components: {
    button: {
      base: {whiteSpace: "normal"},
      "size:sm": {height: "auto", minHeight: "var(--size-element-sm)"},
      "size:md": {height: "auto", minHeight: "var(--size-element-md)"},
      "size:lg": {height: "auto", minHeight: "var(--size-element-lg)"},
      "variant:primary": {
        ":hover": {backgroundColor: "#665080", backgroundImage: "none"},
      },
    },
  },
  adaptations: {rules: [{when: {width: {below: "md"}}, value: {tokens: {"--size-element-sm": "44px", "--size-element-md": "44px", "--size-element-lg": "44px"}}}]},
  tokens: {
    "--size-element-sm": "36px",
    "--size-element-md": "36px",
    "--size-element-lg": "40px",
    "--radius-element": "8px",
    "--radius-container": "12px",
    "--radius-page": "18px",
    "--radius-chat": "12px",
    "--text-heading-1-size": "24px",
    "--text-heading-2-size": "18px",
    "--color-accent": "#776095",
    "--color-accent-muted": "#E9E1F5",
    "--color-text-accent": "#5F467D",
    "--color-icon-accent": "#5F467D",
    "--color-on-accent": "#FFFFFF",
    "--color-neutral": "#F1EEF8",
    "--color-background-body": "#F8F7FC",
    "--color-background-surface": "#FFFFFF",
    "--color-background-card": "#FFFFFF",
    "--color-background-popover": "#FFFFFF",
    "--color-background-muted": "#F1EEF8",
    "--color-text-primary": "#2E2936",
    "--color-text-secondary": "#6D6578",
    "--color-border": "#DDD6E8",
  },
});
