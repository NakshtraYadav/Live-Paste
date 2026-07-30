{
  "product": {
    "name": "LinkPad",
    "one_liner": "Anonymous real-time text/code pads with a shareable link.",
    "brand_attributes": [
      "fast",
      "developer-friendly",
      "quietly premium",
      "trustworthy",
      "distraction-free"
    ],
    "design_personality": {
      "keywords": [
        "editor-first",
        "low-chrome",
        "high-contrast",
        "soft-industrial",
        "calm dark mode"
      ],
      "avoid": [
        "centered marketing-page layouts",
        "heavy gradients",
        "glass/transparent cards",
        "purple accents",
        "busy backgrounds behind text"
      ]
    }
  },
  "typography": {
    "google_fonts_import": "@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');",
    "font_families": {
      "ui": "'Space Grotesk', ui-sans-serif, system-ui",
      "mono": "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace"
    },
    "scale": {
      "h1": "text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight",
      "h2": "text-base md:text-lg font-medium text-muted-foreground",
      "body": "text-sm md:text-base",
      "small": "text-xs text-muted-foreground",
      "code": "font-mono text-[13px] sm:text-sm leading-6"
    },
    "usage_rules": [
      "Use UI font for navigation, labels, buttons.",
      "Use mono font for editor, slug/link, counts, connection status, timestamps.",
      "Avoid ultra-light weights; prefer 400/500 for readability on dark surfaces."
    ]
  },
  "color_system": {
    "notes": [
      "Dark mode is primary; light mode is equally polished.",
      "No purple accents (per requirement).",
      "Avoid transparent backgrounds; use solid surfaces with subtle borders.",
      "Gradients only as decorative section background accents (<=20% viewport)."
    ],
    "tokens_css": ":root {\n  /* Light (paper + ink) */\n  --background: 36 33% 98%;          /* paper */\n  --foreground: 222 22% 12%;         /* ink */\n\n  --card: 36 33% 99%;\n  --card-foreground: 222 22% 12%;\n\n  --popover: 36 33% 99%;\n  --popover-foreground: 222 22% 12%;\n\n  /* Brand accent: ocean-teal */\n  --primary: 173 58% 34%;            /* teal */\n  --primary-foreground: 36 33% 98%;\n\n  /* Secondary: sand */\n  --secondary: 38 45% 92%;\n  --secondary-foreground: 222 22% 12%;\n\n  --muted: 36 20% 94%;\n  --muted-foreground: 222 10% 40%;\n\n  --accent: 38 55% 88%;\n  --accent-foreground: 222 22% 12%;\n\n  --destructive: 12 85% 55%;\n  --destructive-foreground: 36 33% 98%;\n\n  --border: 222 12% 86%;\n  --input: 222 12% 86%;\n  --ring: 173 58% 34%;\n\n  --radius: 0.75rem;\n\n  /* Editor-specific */\n  --editor-bg: 36 33% 99%;\n  --editor-fg: 222 22% 12%;\n  --editor-gutter: 36 20% 94%;\n  --editor-selection: 173 58% 34% / 0.18;\n  --editor-caret: 173 58% 34%;\n}\n\n.dark {\n  /* Dark (graphite + off-white) */\n  --background: 210 14% 7%;          /* #0F1214 */\n  --foreground: 36 33% 96%;          /* off-white */\n\n  --card: 210 14% 10%;               /* #161A1D */\n  --card-foreground: 36 33% 96%;\n\n  --popover: 210 14% 10%;\n  --popover-foreground: 36 33% 96%;\n\n  --primary: 173 58% 45%;            /* teal accent */\n  --primary-foreground: 210 14% 7%;\n\n  --secondary: 210 12% 14%;          /* #1F2326 */\n  --secondary-foreground: 36 33% 96%;\n\n  --muted: 210 12% 14%;\n  --muted-foreground: 215 16% 72%;   /* cool gray */\n\n  --accent: 38 45% 70%;              /* sand accent */\n  --accent-foreground: 210 14% 7%;\n\n  --destructive: 12 85% 62%;         /* coral */\n  --destructive-foreground: 210 14% 7%;\n\n  --border: 215 14% 20%;             /* #2A2F35 */\n  --input: 215 14% 20%;\n  --ring: 173 58% 45%;\n\n  /* Editor-specific */\n  --editor-bg: 210 14% 9%;\n  --editor-fg: 210 20% 92%;\n  --editor-gutter: 210 12% 14%;\n  --editor-selection: 173 58% 45% / 0.22;\n  --editor-caret: 173 58% 45%;\n}\n",
    "semantic_usage": {
      "primary_actions": "teal",
      "secondary_actions": "sand/neutral",
      "status_connected": "teal",
      "status_reconnecting": "sand",
      "status_disconnected": "destructive/coral",
      "badges": "solid surfaces with border; avoid gradients"
    },
    "syntax_highlighting": {
      "notes": [
        "Prism theme should be tuned to match tokens; keep background solid.",
        "Selection highlight uses --editor-selection.",
        "Prefer subtle, readable colors (no neon rainbow)."
      ],
      "suggested_dark": {
        "comment": "#7E8A97",
        "string": "#A7D7C5",
        "keyword": "#7CC7FF",
        "function": "#D8C59A",
        "number": "#FFB38A",
        "punctuation": "#C9D1D9"
      }
    }
  },
  "layout": {
    "grid_and_spacing": {
      "container": "max-w-6xl mx-auto px-4 sm:px-6",
      "vertical_rhythm": "Use 2–4x more spacing than default: section py-10 sm:py-14; card gaps gap-4 sm:gap-6",
      "editor_page": "Full-bleed editor; constrain only the top toolbar with px-3 sm:px-4"
    },
    "page_structures": {
      "home": {
        "pattern": "Z-pattern hero + create form",
        "sections": [
          "Top nav (minimal)",
          "Hero: headline + short explainer + create form",
          "How it works (3 steps)",
          "Privacy/expiry note + footer"
        ]
      },
      "paste": {
        "pattern": "Editor-first full screen",
        "regions": [
          "Sticky top toolbar (single row on desktop, wraps on mobile)",
          "Editor canvas (fills remaining height)",
          "Optional bottom status strip on mobile (connection + saved)"
        ]
      },
      "not_found_or_expired": {
        "pattern": "Centered message within readable container (not full centered app)",
        "cta": "Create new paste"
      }
    }
  },
  "components": {
    "component_path": {
      "button": "/app/frontend/src/components/ui/button.jsx",
      "input": "/app/frontend/src/components/ui/input.jsx",
      "textarea": "/app/frontend/src/components/ui/textarea.jsx",
      "select": "/app/frontend/src/components/ui/select.jsx",
      "badge": "/app/frontend/src/components/ui/badge.jsx",
      "card": "/app/frontend/src/components/ui/card.jsx",
      "separator": "/app/frontend/src/components/ui/separator.jsx",
      "tooltip": "/app/frontend/src/components/ui/tooltip.jsx",
      "switch": "/app/frontend/src/components/ui/switch.jsx",
      "dropdown_menu": "/app/frontend/src/components/ui/dropdown-menu.jsx",
      "popover": "/app/frontend/src/components/ui/popover.jsx",
      "scroll_area": "/app/frontend/src/components/ui/scroll-area.jsx",
      "sonner_toast": "/app/frontend/src/components/ui/sonner.jsx",
      "dialog": "/app/frontend/src/components/ui/dialog.jsx"
    },
    "home_create_form": {
      "structure": [
        "Card (subtle border)",
        "Editor-like textarea (monospace, min-h)",
        "Row: custom slug input + language select + expiry select",
        "Primary CTA: Create link",
        "Secondary: Random link toggle (optional)"
      ],
      "tailwind_classes": {
        "card": "bg-card text-card-foreground border border-border rounded-[var(--radius)] shadow-sm",
        "textarea": "font-mono text-[13px] sm:text-sm leading-6 min-h-[220px] sm:min-h-[280px] bg-[hsl(var(--editor-bg))] text-[hsl(var(--editor-fg))] border border-border rounded-lg px-3 py-3 focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]",
        "form_row": "grid grid-cols-1 sm:grid-cols-12 gap-3",
        "slug": "sm:col-span-4",
        "language": "sm:col-span-4",
        "expiry": "sm:col-span-4",
        "cta": "w-full sm:w-auto"
      },
      "data_testids": {
        "content": "create-paste-content-textarea",
        "slug": "create-paste-custom-slug-input",
        "language": "create-paste-language-select",
        "expiry": "create-paste-expiry-select",
        "submit": "create-paste-submit-button",
        "result_link": "create-paste-result-link",
        "copy_link": "create-paste-copy-link-button"
      }
    },
    "paste_toolbar": {
      "behavior": [
        "Sticky top bar with subtle border; no heavy shadows.",
        "On mobile: wrap into two rows; keep primary actions visible.",
        "Presence cluster collapses into a dropdown when >6 viewers."
      ],
      "slots": [
        "Slug/link display (mono)",
        "Copy link button",
        "Copy content button",
        "Language select",
        "Viewer count badge (live)",
        "Total view count (muted)",
        "Connection status pill",
        "Expiry badge/countdown",
        "Dark mode toggle"
      ],
      "tailwind_classes": {
        "bar": "sticky top-0 z-40 bg-background/100 border-b border-border",
        "inner": "flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2",
        "left": "flex items-center gap-2 min-w-0",
        "right": "flex flex-wrap items-center gap-2 sm:justify-end",
        "slug": "font-mono text-xs sm:text-sm truncate max-w-[52vw] sm:max-w-[420px]",
        "status_pill": "inline-flex items-center gap-2 rounded-full border border-border bg-card px-2.5 py-1 text-xs font-medium",
        "viewer_badge": "rounded-full"
      },
      "data_testids": {
        "slug": "paste-toolbar-slug-text",
        "copy_link": "paste-toolbar-copy-link-button",
        "copy_content": "paste-toolbar-copy-content-button",
        "language": "paste-toolbar-language-select",
        "viewer_count": "paste-toolbar-viewer-count",
        "view_count": "paste-toolbar-total-view-count",
        "connection": "paste-toolbar-connection-status",
        "expiry": "paste-toolbar-expiry-badge",
        "theme_toggle": "paste-toolbar-theme-toggle"
      }
    },
    "editor_surface": {
      "notes": [
        "Use react-simple-code-editor + Prism; keep editor background solid.",
        "Add a subtle inset border to separate editor from page background.",
        "Use ScrollArea for long content; avoid nested scroll traps."
      ],
      "tailwind_classes": {
        "wrapper": "h-[calc(100vh-56px)] sm:h-[calc(100vh-52px)]",
        "editor_shell": "h-full bg-[hsl(var(--editor-bg))] text-[hsl(var(--editor-fg))]",
        "editor_inner": "h-full px-3 sm:px-6 py-4",
        "editor": "font-mono text-[13px] sm:text-sm leading-6 outline-none",
        "focus_ring": "focus-within:ring-2 focus-within:ring-[hsl(var(--ring))]"
      },
      "data_testids": {
        "editor": "paste-live-editor",
        "viewer_count_inline": "paste-live-viewer-count-inline",
        "expired_banner": "paste-expired-banner"
      }
    },
    "empty_states": {
      "expired": {
        "title": "This link expired",
        "body": "Create a new paste to keep sharing.",
        "cta": "Create new paste"
      },
      "not_found": {
        "title": "Nothing at this link",
        "body": "The paste may have been deleted or the URL is wrong.",
        "cta": "Create new paste"
      },
      "tailwind_classes": {
        "wrap": "max-w-xl mx-auto px-4 sm:px-6 py-14",
        "card": "border border-border bg-card rounded-xl p-6 sm:p-8",
        "title": "text-xl sm:text-2xl font-semibold",
        "body": "mt-2 text-sm text-muted-foreground",
        "cta": "mt-6"
      },
      "data_testids": {
        "state": "not-found-state",
        "cta": "not-found-create-new-button"
      }
    }
  },
  "motion_and_microinteractions": {
    "principles": [
      "Motion should communicate state: connected/reconnecting, copied, saved.",
      "Keep durations short (120–180ms) and easing natural.",
      "Never use transition: all. Transition only color, background-color, border-color, opacity, box-shadow."
    ],
    "recommended_library": {
      "name": "framer-motion",
      "install": "npm i framer-motion",
      "use_cases": [
        "Toolbar entrance on paste page (subtle slide/fade)",
        "Copy-to-clipboard feedback (scale 0.98 on press)",
        "Connection status pulse when reconnecting"
      ]
    },
    "interaction_specs": {
      "buttons": {
        "hover": "hover:bg-accent hover:text-accent-foreground",
        "press": "active:scale-[0.98]",
        "focus": "focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      },
      "copy_feedback": [
        "On copy link/content: show Sonner toast 'Copied' and briefly swap icon/text for 900ms.",
        "Also animate the button background to accent for 180ms (no transform transitions)."
      ],
      "connection_status": [
        "Connected: solid teal dot.",
        "Reconnecting: sand dot with subtle pulse (opacity only).",
        "Disconnected: coral dot; show tooltip with last error."
      ]
    }
  },
  "accessibility": {
    "requirements": [
      "WCAG AA contrast for text and interactive controls.",
      "Visible focus rings on all interactive elements.",
      "Keyboard navigation: toolbar actions reachable in logical order.",
      "Respect prefers-reduced-motion: disable pulses and entrance animations.",
      "Editor: ensure caret and selection are visible in both themes."
    ],
    "aria_and_labels": [
      "All icon-only buttons must have aria-label.",
      "Connection status pill should include sr-only text describing state.",
      "Language select should announce current language."
    ]
  },
  "libraries_and_icons": {
    "icons": {
      "library": "lucide-react",
      "usage": "Use Lucide icons for copy/link/moon/sun/users/wifi. No emoji icons.",
      "common_icons": [
        "Link",
        "Copy",
        "Moon",
        "Sun",
        "Users",
        "Wifi",
        "WifiOff",
        "Clock"
      ]
    },
    "editor": {
      "packages": [
        "react-simple-code-editor",
        "prismjs"
      ],
      "notes": [
        "Keep Prism CSS minimal; override token colors to match the palette.",
        "Use IBM Plex Mono for editor font."
      ]
    }
  },
  "image_urls": {
    "decorative_backgrounds": [
      {
        "url": "https://images.unsplash.com/photo-1709877769536-20bf1043b210?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2NDJ8MHwxfHNlYXJjaHwzfHxhYnN0cmFjdCUyMHN1YnRsZSUyMGdyYWluJTIwdGV4dHVyZSUyMGRhcmslMjB0ZWFsJTIwYmFja2dyb3VuZHxlbnwwfHx8dGVhbHwxNzg1Mzc1MzY5fDA&ixlib=rb-4.1.0&q=85",
        "category": "home-hero-background",
        "description": "Optional subtle grain/texture image used as a low-opacity overlay behind the hero only (<=20% viewport)."
      },
      {
        "url": "https://images.unsplash.com/photo-1616763880410-744958efc093?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2NDJ8MHwxfHNlYXJjaHwxfHxhYnN0cmFjdCUyMHN1YnRsZSUyMGdyYWluJTIwdGV4dHVyZSUyMGRhcmslMjB0ZWFsJTIwYmFja2dyb3VuZHxlbnwwfHx8dGVhbHwxNzg1Mzc1MzY5fDA&ixlib=rb-4.1.0&q=85",
        "category": "noise-overlay",
        "description": "Fallback texture for subtle noise overlay (use opacity 0.06–0.10)."
      }
    ]
  },
  "instructions_to_main_agent": [
    "Update /app/frontend/src/index.css tokens to match tokens_css above; remove default centered App styles (do not add text-align:center).",
    "Replace App.css demo styles; keep App.css minimal or delete unused rules.",
    "Implement theme toggle by toggling 'dark' class on <html> or <body> and persist to localStorage; default to prefers-color-scheme.",
    "Home page: use Card + Textarea (monospace) to feel like an editor immediately; keep hero copy short.",
    "Paste page: sticky toolbar + full-height editor; toolbar wraps on mobile; keep editor as the star.",
    "Use shadcn Select for language/expiry; use Badge for viewer count and expiry; use Tooltip for icon buttons.",
    "All interactive and key informational elements MUST include data-testid (kebab-case) per mappings above.",
    "Use Sonner for copy notifications and connection state changes.",
    "Do not use gradients except a subtle hero background accent (<=20% viewport). No gradients on buttons or small elements.",
    "Ensure Prism token colors are overridden to match syntax_highlighting.suggested_dark and remain readable in light mode too."
  ],
  "general_ui_ux_design_guidelines_appendix": "<General UI UX Design Guidelines>\n    - You must **not** apply universal transition. Eg: `transition: all`. This results in breaking transforms. Always add transitions for specific interactive elements like button, input excluding transforms\n    - You must **not** center align the app container, ie do not add `.App { text-align: center; }` in the css file. This disrupts the human natural reading flow of text\n   - NEVER: use AI assistant Emoji characters like`🤖🧠💭💡🔮🎯📚🎭🎬🎪🎉🎊🎁🎀🎂🍰🎈🎨🎰💰💵💳🏦💎🪙💸🤑📊📈📉💹🔢🏆🥇 etc for icons. Always use **FontAwesome cdn** or **lucid-react** library already installed in the package.json\n\n **GRADIENT RESTRICTION RULE**\nNEVER use dark/saturated gradient combos (e.g., purple/pink) on any UI element.  Prohibited gradients: blue-500 to purple 600, purple 500 to pink-500, green-500 to blue-500, red to pink etc\nNEVER use dark gradients for logo, testimonial, footer etc\nNEVER let gradients cover more than 20% of the viewport.\nNEVER apply gradients to text-heavy content or reading areas.\nNEVER use gradients on small UI elements (<100px width).\nNEVER stack multiple gradient layers in the same viewport.\n\n**ENFORCEMENT RULE:**\n    • Id gradient area exceeds 20% of viewport OR affects readability, **THEN** use solid colors\n\n**How and where to use:**\n   • Section backgrounds (not content backgrounds)\n   • Hero section header content. Eg: dark to light to dark color\n   • Decorative overlays and accent elements only\n   • Hero section with 2-3 mild color\n   • Gradients creation can be done for any angle say horizontal, vertical or diagonal\n\n- For AI chat, voice application, **do not use purple color. Use color like light green, ocean blue, peach orange etc**\n\n</Font Guidelines>\n\n- Every interaction needs micro-animations - hover states, transitions, parallax effects, and entrance animations. Static = dead. \n   \n- Use 2-3x more spacing than feels comfortable. Cramped designs look cheap.\n\n- Subtle grain textures, noise overlays, custom cursors, selection states, and loading animations: separates good from extraordinary.\n   \n- Before generating UI, infer the visual style from the problem statement (palette, contrast, mood, motion) and immediately instantiate it by setting global design tokens (primary, secondary/accent, background, foreground, ring, state colors), rather than relying on any library defaults. Don't make the background dark as a default step, always understand problem first and define colors accordingly\n    Eg: - if it implies playful/energetic, choose a colorful scheme\n           - if it implies monochrome/minimal, choose a black–white/neutral scheme\n\n**Component Reuse:**\n\t- Prioritize using pre-existing components from src/components/ui when applicable\n\t- Create new components that match the style and conventions of existing components when needed\n\t- Examine existing components to understand the project's component patterns before creating new ones\n\n**IMPORTANT**: Do not use HTML based component like dropdown, calendar, toast etc. You **MUST** always use `/app/frontend/src/components/ui/ ` only as a primary components as these are modern and stylish component\n\n**Best Practices:**\n\t- Use Shadcn/UI as the primary component library for consistency and accessibility\n\t- Import path: ./components/[component-name]\n\n**Export Conventions:**\n\t- Components MUST use named exports (export const ComponentName = ...)\n\t- Pages MUST use default exports (export default function PageName() {...})\n\n**Toasts:**\n  - Use `sonner` for toasts\"\n  - Sonner component are located in `/app/src/components/ui/sonner.tsx`\n\nUse 2–4 color gradients, subtle textures/noise overlays, or CSS-based noise to avoid flat visuals.\n</General UI UX Design Guidelines>"
}
