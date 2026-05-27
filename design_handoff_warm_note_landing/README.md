# Handoff: MyPinkAssistant Landing Page — "Warm Note" direction

## Overview

A refreshed landing page for **mypinkassistant.com**, an AI assistant for Mary Kay consultants. The page repositions the product around two modes — **Do things** (add customers, place orders) and **Know things** (ask who hasn't reordered, who's enrolled in PCP, whose birthday is this month) — and replaces the old desktop screen recording with an iPhone demo.

This is the **"Warm Note"** design direction. (Project also contains an alternate "Refined Rose" direction which is **not** being shipped — only Warm Note should be recreated.)

## About the Design Files

The files in this bundle (`landing-warm.jsx`, `shared.jsx`, `demo.mp4`, and the wrapper HTML) are **design references created as React+Babel-in-the-browser prototypes**. They demonstrate the intended look, layout, copy, and behavior — they are **not** production code to ship as-is.

Your job is to **recreate this design in the target codebase's existing environment** using its established patterns (component library, styling solution, build system, etc.). If no codebase environment exists yet, choose the most appropriate framework (Next.js + React + Tailwind would be a natural fit) and implement there.

Key things to translate, not literally copy:
- Inline-style React → CSS modules / Tailwind / styled-components (whatever the target uses)
- The custom `Reveal` component → use the codebase's preferred scroll-reveal pattern (Framer Motion, react-intersection-observer, native CSS `@starting-style` + IntersectionObserver, etc.)
- Container queries on a `.mpa-landing` wrapper → in production, switch to ordinary viewport media queries (the container-query approach was only needed because the prototype renders the same page at both desktop and mobile widths inside a design canvas)
- The `darken(hex, amount)` helper → port to whatever color-manipulation tool the codebase uses (or just hand-code derived shadow colors)

## Fidelity

**High-fidelity.** Treat colors, typography, spacing, copy, and component structure as authoritative. The look-and-feel decisions have been settled with the founder. Minor adjustments are fine (e.g., snapping to an 8px grid if a value reads as 7px) but no major restyling.

## Page Structure (top to bottom)

The page is a single scrolling landing page with these sections in order:

1. **Top nav** — logo + Log in (outlined button) + Start free trial (pink button)
2. **Hero** — two-column: headline + sub + CTAs on the left, iPhone bezel playing demo video on the right. On mobile, the bezel is hidden; instead the video appears full-width (no bezel) below the CTAs.
3. **Trust strip** — three pills with icons, full-width band
4. **How it works** — three numbered tilted cards
5. **Two modes (Do / Know)** — two side-by-side cards with chat-bubble examples
6. **Day-one import callout** — single wide card with "<2 min automated setup"
7. **Testimonials** — three slightly tilted star-rated quote cards (placeholder content — see "Outstanding work" below)
8. **CTA card** — full-width pink gradient card with $5.99/month pricing and Start free trial button
9. **Footer** — logo + copyright + nav links

---

## Design Tokens

### Colors

| Token | Value | Use |
|---|---|---|
| `cream` | `#FFF6F0` | Page background |
| `cream2` | `#FCEAE0` | Alt section bg / testimonial card variant |
| `cream3` | `#F8DDD0` | Card hard-shadow color |
| `ink` | `#3A1F25` | Body text / headlines |
| `ink2` | `#6B4751` | Secondary text |
| `pink` (primary) | `#C2185B` | Primary accent (buttons, links, italic emphasis) |
| `pinkDeep` (derived) | ~`#8C115E` | Hard-shadow under pink buttons (= `darken(pink, 0.28)`) |
| `blush` | `#FFE0E9` | "Know" mode card background; one testimonial variant |
| `hairline` | `rgba(58,31,37,.10)` | Borders and dividers |

The pink is intentionally configurable in the prototype's Tweaks panel (options include `#F08CA8`, `#E76A8B`, `#C84A6F`, `#C2185B`, `#A93860`). **Ship with `#C2185B`** unless directed otherwise.

### Typography

- **Serif (headlines, italic emphasis, logo wordmark):** `Lora` (Google Fonts), fallbacks `"Cormorant Garamond", Georgia, serif`
- **Sans (body, UI, buttons):** `Nunito` (Google Fonts), fallbacks `-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
- Italic-styled emphasis spans inside h1/h2 use `<em>` with the pink color applied inline.

| Element | Font | Size | Weight | Line-height | Letter-spacing |
|---|---|---|---|---|---|
| Hero h1 | Lora | 68px | 500 | 1.05 | -0.015em |
| Section h2 | Lora | 48–60px | 500 | 1.02–1.05 | -0.01em |
| Section h3 (cards) | Lora | 24–28px | 500–600 | 1.1 | — |
| Body | Nunito | 15–18px | 400 | 1.55 | — |
| Eyebrow / pill / trust strip | Nunito | 12–13.5px | 600–700 | — | 0.04–0.08em uppercase |
| Buttons | Nunito | 14–16px | 700–800 | — | — |
| Logo wordmark | Lora | 22px | 600 | — | -0.01em |

Hero h1 should use `text-wrap: balance`; long body paragraphs use `text-wrap: pretty`.

### Spacing & radii

- **Section padding:** 64px horizontal, varies 40–96px vertical between sections
- **Card padding:** 28–36px
- **Card radius:** 18–28px (testimonials 18, content cards 20–22, callouts 24–28)
- **Button radius:** 12–14px (rounded rect, not pill — pills are reserved for the eyebrow/trust chips at 999px)
- **Eyebrow pill:** 6px vertical / 12px horizontal padding, 999px radius

### Shadows

- **Pink primary button:** `0 6px 0 0 ${pinkDeep}, 0 14px 30px -10px ${pink}80` (two-layer: hard offset + soft glow)
- **Outlined secondary button:** `0 3px 0 ${ink}1a` (subtle hard offset only)
- **Cards (How it works, Do/Know, testimonials, day-one callout):** `0 6px 0 ${cream3}` (cream hard offset, no soft shadow — this is the "lifted note" aesthetic)
- **iPhone hero bezel (desktop):** `0 30px 60px -20px rgba(40,10,25,.35), 0 8px 20px -8px rgba(40,10,25,.2), inset 0 0 0 1px rgba(255,255,255,.08)`
- **Mobile video card:** `0 18px 40px -16px ${pink}55, 0 4px 12px -4px rgba(0,0,0,.15)`

The "hard-shadow" pattern (solid colored offset, no blur) is the signature lift effect throughout the page. Don't replace it with conventional drop shadows.

---

## Screens / Sections in detail

### 1. Top nav

```
[logo: pink circle "mpa" + wordmark]              [Log in]  [Start free trial]
```

- 20px vertical / 64px horizontal padding
- Logo on left, nav buttons on right with 28px gap between them
- **Log in:** white background, `1.5px solid rgba(58,31,37,.15)` border, 12px radius, ink text, 8px/18px padding, 14px Nunito 700, `0 3px 0 rgba(58,31,37,.10)` hard shadow
- **Start free trial:** pink (`#C2185B`) background, white text, same 12px radius, 10px/18px padding, hard shadow `0 3px 0 ${pinkDeep}`

#### Logo composition
- Pink filled circle, 38×38px, with **"mpa"** rendered in Lora italic 600, 16px, white, slight letter-spacing -0.02em. Circle has the same hard pink shadow as the trial button.
- Wordmark to the right (12px gap): Lora 22px, **"MyPink"** in pink + **"Assistant"** in ink italic.

### 2. Hero section

Two-column grid (`1.15fr .85fr`), 56px gap, 64px horizontal padding, 56px top / 72px bottom padding.

**Left column:**
- Eyebrow pill: `For Mary Kay consultants` in uppercase 12px 700, white bg with hairline border, pink dot on the left, 999px radius, 22px bottom margin
- H1: **Run your business *by chat.*** (italic word in pink)
- Sub: "Add a customer. Take an order. Find who hasn't reordered in 3 months. Your whole business, by message — like texting an assistant who already knows everyone." — 18px ink2, 500px max-width
- Buttons row (vertical-aligned center, 8px+ gap):
  - **Start free trial →** — pink primary button, 15px/28px padding, 14px radius, 800 weight, 15px size, both shadows
  - **I already have an account →** — outlined secondary (matches top-nav Log in style at slightly larger size: 13px/22px padding)
- "$5.99 / month. 7-day free trial. Cancel anytime." — 13.5px ink2, ink-colored "$5.99 / month" bolded

**Right column (`data-hero-phone` — hidden on mobile):**
- iPhone bezel playing `demo.mp4` autoplay/muted/loop/playsInline/preload=auto, 280×568 base size scaled 0.86×
- Bezel: dark gradient outer (`linear-gradient(160deg, #1f1a1c → #3a2f33)`), 42px radius, 7px inner padding
- Inner screen: rounded inset, video fills `object-fit: cover`, dynamic island pill (92×26, `#0e0a0c`, centered at top 10px) overlays the video
- Soft pink halo behind: `radial-gradient(60% 60% at 50% 50%, ${blush}, transparent 70%)` filling a wider area

**Mobile-only video block (`data-show-mobile` — appears only at narrow widths):**
- Sits below the buttons + pricing line, 28px top margin
- Rounded card 22px radius, dark bg `#0e0a0c`, `aspect-ratio: 9 / 19.5`, max-width 360px, centered
- Same video, full-bleed, `object-fit: cover`
- No bezel chrome — the device frame is the device

### 3. Trust strip

Full-width band, white bg, dashed hairline top + bottom borders, 18px/64px padding. Center-justified flex row with 36px gap.

Three items, each: small accent-colored icon (SVG, 16px, 2px stroke) + label in 13.5px Nunito 700 ink2:

1. 🔄 sync icon — "Syncs directly with MyCustomers"
2. ✨ sparkle (4-point burst) icon — "Personal inventory tracked automatically"
3. 📱 phone icon — "Works on every device"

4px dots between items (rgba(0,0,0,.18), 50% radius), hidden on mobile.

### 4. How it works

Section: 88px top / 80px bottom padding, 64px horizontal. Position relative, z-index 1.

H2: **From chat to *MyCustomers* in under a minute.** (italic word in pink, with explicit `<br/>` between "MyCustomers" and "in"). 48px Lora 500, 12px top margin / 56px bottom margin, ink color, 720px max-width.

Three-column grid below (24px gap):

Each card:
- White bg, 20px radius, hairline border, `0 4px 0 ${cream3}` hard shadow
- 28px vertical / 26px horizontal padding, 210px min-height
- **Tilted:** card 1 `rotate(-1.5deg)`, card 2 `rotate(1deg)`, card 3 `rotate(-.5deg)` (mobile resets to 0deg)
- Numbered badge: 36×36px pink circle absolutely positioned `top: -16px, left: 20px`, white "1"/"2"/"3" in Lora 600 18px, hard pink shadow
- H3: Lora 26px 500, 12px top / 10px bottom margin, ink color
- Body: 15px Nunito ink2 line-height 1.55

Content:
1. **Chat it** — "New order for Jane Doe, Satin Lips Set and Lash Love Mascara."
2. **Confirm it** — "Quick glance — products matched, totals look right? Tap confirm."
3. **Done.** — "Securely sent to MyCustomers. On hand inventory updated. Ready for what's next."

### 5. Two modes — Do / Know

Section: 32px top / 64px bottom padding, 64px horizontal.

H2: **Do things. Know things.** Both verbs italic in pink. 52px Lora 500, 720px max-width.

Sub: "MyPinkAssistant doesn't just do the work. It tells you what work matters." 18px ink2, 560px max-width, 48px bottom margin.

Two-column grid (24px gap), each card 32px padding, 22px radius, hairline border, `0 6px 0 ${cream3}` hard shadow, 460px min-height, slight tilts (`-.6deg`, `.5deg`).

#### Do card (left, white bg)
- Header row: 32px pink-filled circle with white "1" in Lora 600 16px, then h3 "Do things." Lora 28px 600 ink
- Body line: "Add a customer, place an order, update inventory — without ever opening MyCustomers."
- **Two ChatSnippet exchanges** (see ChatSnippet spec below):

**Exchange 1:**
- User: "New customer Jane Doe, 214-555-0188, birthday Aug 3"
- App: "Added Jane Doe. Sent to MyCustomers <GreenCheck>"

**Exchange 2:**
- User: "Mary ordered a CC cream light to medium and a charcoal mask"
- App (multi-line):
  ```
  Okay — I have this order for Mary:
  • Mary Kay CC Cream Sunscreen Broad Spectrum SPF 15 — Light to Medium **$22.00**
  • Clear Proof Deep-Cleansing Charcoal Mask **$26.00**
  Estimated retail total: **$48.00**
  Does that sound right?
  ```
  Bullet items render as `•` glyphs, prices in `<strong>`.

#### Know card (right, blush #FFE0E9 bg)
- Same header pattern with "2"
- Body line: "Ask anything about your business. She already knows."
- **Three ChatSnippet exchanges:**

1. **User:** "Who hasn't reordered in 3 months?" → **App:** "7 customers: Linda P., Sarah K., Mary J., Tasha R., Aisha N., Brittany M., Diane S. *Want to message them?*"
2. **User:** "Who has a birthday this month?" → **App:** "3 birthdays: **Jane Doe** Jun 8 · **Mary J.** Jun 14 · **Aisha N.** Jun 22 🎉"
3. **User:** "Who's enrolled in PCP this quarter?" → **App:** "42 customers active in Q2 PCP. **11** haven't engaged yet — want the list?"

#### ChatSnippet spec
- Vertical flex, 10px gap
- **Ask (user) bubble:** right-aligned. Pink (`#C2185B`) bg, white text, 16px radius with **top-right corner = 4px** (tail-style), 10/14px padding, 14.5px Nunito line-height 1.4, max 85% width, soft pink shadow `0 2px 8px ${pink}33`
- **Answer (app) bubble:** left-aligned. White bg, ink text, 16px radius with **top-left corner = 4px**, 12/16px padding, 14.5px Nunito line-height 1.5, max 92% width, hairline border

#### GreenCheck spec
A small filled green circle (`#22c55e`) with a white checkmark inside. 16×16px, inline-flex, vertical-align -3px, 4px left margin. SVG check uses 3.5px stroke, currentColor (white), `path d="M5 13l4 4L19 7"` in a `0 0 24 24` viewbox.

### 6. Day-one import callout

32px top / 64px bottom padding, 64px horizontal.

Single card: white bg, 24px radius, 40/44px padding, hairline border, `0 8px 0 ${cream3}` hard shadow. Two-column grid (1fr auto), 32px gap, center-aligned.

Soft pink decoration: absolutely-positioned 220×220px circle, `${pink}1a`, 40px blur, top -40px right -60px.

Left column:
- H3: **Your whole customer base, *already here.*** (italic part pink). Lora 34px 500.
- Body: "The day you sign up, your full MyCustomers customer base and order history imports automatically. No exports, no spreadsheets — just sign in and ask away." — 15.5px ink2, 540px max-width.

Right column:
- "<2 min" in Lora 72px 500, pink, line-height 0.95, letter-spacing -0.02em
- "automated setup" below in 13.5px Nunito 700 ink2, uppercase, letter-spacing 0.06em, 4px top margin

### 7. Testimonials

64px top / 88px bottom padding, 64px horizontal, white section bg.

H2: **Consultants are *obsessed*.** Centered, 48px Lora 500, italic word in pink.

Three-column grid (22px gap). Each card:
- 28px padding, 18px radius, hairline border, `0 6px 0 ${cream3}` hard shadow, 260px min-height
- Backgrounds rotate per index: `[cream, blush, cream2]`
- Tilts: `[-1.5deg, 1deg, -.5deg]`
- 5 pink filled stars (SVG, 18×18px), 2px gap
- Blockquote in Lora 18px 400 line-height 1.4 ink, with `"` open/close quotes around the text
- Figcaption: 38×38px pink-bg avatar with white initials in Nunito 700 13px, + name (Nunito 800 14px ink) + role (Nunito 12.5px ink2). Border-top dashed hairline, 14px top padding.

**Placeholder testimonial content** (in `shared.jsx` as `TESTIMONIALS`) — replace with real quotes before launch:

```js
[
  {
    quote: "I used to dread Sunday order entry. Now I knock it out from the school pickup line — three orders in the time it takes to find my pen.",
    name: "Brittany M.", role: "Senior Consultant · 9 yrs", initials: "BM",
  },
  {
    quote: "It feels like texting an assistant who actually knows my customers. 'Who hasn't reordered foundation in 60 days?' — and there's my list.",
    name: "Tasha R.", role: "Director · Atlanta unit", initials: "TR",
  },
  {
    quote: "I stopped keeping a separate inventory spreadsheet last month. That alone is worth it. The sync to MyCustomers is the cherry on top.",
    name: "Linda P.", role: "Consultant · 4 yrs", initials: "LP",
  },
]
```

### 8. Final CTA card

88px top / 80px bottom padding, 64px horizontal.

Card: 28px radius, 64px vertical / 56px horizontal padding, centered text, white text on `linear-gradient(135deg, ${pink} 0%, ${pinkDeep} 100%)` background.

Decorative scattered white dots at 35% opacity (7 dots at specific %-positions and varying small radii — see source for coords).

Content:
- H2: "Try it free for 7 days." Lora 60px 500 white, -0.01em letter-spacing
- Sub: "$5.99/month after trial · cancel anytime" — 18px white at 92% opacity
- Button: "Start free trial →" — white bg, `${pinkDeep}` text, 17/32px padding, 14px radius, Nunito 800 16px, hard shadow `0 6px 0 rgba(0,0,0,.15)`

### 9. Footer

40px top / 56px bottom padding, 64px horizontal. Flex row space-between, center-aligned. Top border dashed hairline. Color ink2, 13px.

- Left: small logo (size=small variant, 30px circle) + "© 2026 MyPinkAssistant."
- Right: 22px-gap link row — FAQ · Legal · Privacy · Terms · Support (all ink2, no underline, `href="#"` placeholders)

Mobile: stacks vertically (flex-direction column), centered, link row wraps.

---

## Interactions & Behavior

### Scroll reveal
Every major content block animates in on scroll:
- Initial: `opacity: 0; transform: translateY(16px)`
- Settled: `opacity: 1; transform: translateY(0)`
- Transition: `opacity 0.7s cubic-bezier(.2,.7,.2,1) ${delay}ms, transform 0.7s ${delay}ms`
- Triggered when 12% of element is visible (IntersectionObserver), with `rootMargin: '0px 0px -40px 0px'`
- Staggered delays for grid items: 0, 80, 100, 120ms

In production, use whatever scroll-reveal pattern the codebase already uses. Don't reach for a heavy animation library if there isn't one.

### Video autoplay
- Desktop hero video: autoplay muted loop playsinline preload=auto
- Mobile hero video: same attributes
- Both must play silently without user interaction (iOS Safari requires muted+playsinline)

### Buttons
- All `href` attributes are `#` placeholders. Wire to real routes:
  - "Start free trial" → trial signup flow
  - "Log in" + "I already have an account" → existing login page
  - Footer links → existing FAQ / Legal / Privacy / Terms / Support pages
- No hover states are defined in the prototype — add subtle ones matching the codebase's conventions (e.g., slight brightness drop or shadow lift). Don't change colors dramatically.

### Responsive
The prototype uses CSS **container queries** on a `.mpa-landing` wrapper because it renders the same page at both desktop (1180px) and mobile (~400px) widths inside a design canvas. **In production, switch to ordinary viewport media queries** at the equivalent breakpoint (≤700px collapses the layout).

At ≤700px:
- All multi-column grids → single column
- Hero phone bezel → hidden
- Mobile video block → visible
- Card tilts → reset to 0deg
- Type scales down (h1 36px, h2 28px, h3 22px)
- Trust strip wraps + center-justifies, dividers hide
- Footer stacks
- Section padding reduces (28/20px from 64/64px)

---

## State Management

None required beyond local UI state. The page is fully static / presentational; the only "state" is the scroll-reveal observer firing per-element.

---

## Assets

- **`demo.mp4`** — provided. iPhone screen recording of the MyPinkAssistant app in use. Plays inside the hero bezel on desktop, full-width below CTAs on mobile.
- **No icon library** — all icons (sync, sparkle, phone, stars, GreenCheck) are inline SVGs in the source. They're simple enough to keep inline, or you can swap for the codebase's icon component using equivalent symbols.
- **No image assets** for testimonial avatars — initials in pink-bg circles.

---

## Files in this bundle

| File | What it is |
|---|---|
| `landing-warm.jsx` | The full Warm Note page composition |
| `shared.jsx` | Shared bits — `Reveal` (scroll-fade), `IPhoneMock` (the bezel + video), `ChatSnippet`, `TESTIMONIALS` placeholder data, container-query CSS |
| `demo.mp4` | The phone demo video used in the hero |
| `MyPinkAssistant Landing.html` | The wrapper HTML that loads everything (only useful as a runnable preview) |
| `app.jsx` | Renders the page into a design canvas — **ignore** in production; you only need `landing-warm.jsx` + `shared.jsx` content |
| `tweaks-panel.jsx` / `design-canvas.jsx` / `ios-frame.jsx` | Prototype scaffolding — **not part of the design**, do not port |

To run the prototype locally:
1. Serve the folder over any static file server (the inline `<script type="text/babel">` setup needs HTTP, not `file://`)
2. Open `MyPinkAssistant Landing.html`

---

## Open items for the founder before launch

These were left as placeholders in the prototype and should be settled before shipping:

- **Testimonials** — three placeholder quotes are in `shared.jsx`. Replace with real ones.
- **Footer link destinations** — currently `#` placeholders.
- **Login route** — both "Log in" (top nav) and "I already have an account →" (hero) should point to the same existing login page.
- **Trial signup route** — both "Start free trial" buttons (top nav + hero + final CTA) point to the same destination.
