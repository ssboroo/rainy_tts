# RAINY Voice Studio

RAINY is the master brand. **Voice Studio** is the product descriptor; use this complete name in page titles, account emails and product introductions. In narrow navigation, display RAINY with VOICE STUDIO beneath it.

**Mongolian promise:** Таны санаа. Таны дуу хоолой.

**English promise:** Your ideas. Your voice.

## Identity

The mark combines a rain droplet with four audio bars. The droplet relates to RAINY; the bars communicate voice creation. Use the actual SVG assets, never an emoji or a replacement stock microphone.

| Asset | Location | Use |
| --- | --- | --- |
| Color mark | `app/static/brand-mark.svg` | Avatar, app header, profile image |
| Wordmark | `app/static/brand-wordmark.svg` | Light-background horizontal signature |
| Monochrome mark | `app/static/brand-mark-mono.svg` | Single-ink layouts; currentColor defaults to black |
| Favicon | `app/static/favicon.svg` | Browser tab |
| Social design | `app/static/brand-social.svg` | 1200 × 630 introduction artwork; rasterize before posting where SVG is unsupported |

Use a minimum 24 px mark. Leave at least one quarter of the mark's width as clear space. Keep proportions and do not add outlines or stretch the artwork. Use the color mark for both light and dark interfaces. Keep the wordmark on light backgrounds.

## Palette

| Role | Value |
| --- | --- |
| Primary indigo | `#6051E8` |
| Light canvas | `#F8F8FC` |
| Light surface | `#FFFFFF` |
| Light text | `#25243E` |
| Light secondary text | `#646379` |
| Light accent surface | `#EEEBFF` |
| Mint accent | `#1B7865` |
| Dark canvas | `#131322` |
| Dark surface | `#202034` |
| Dark text | `#F3F2FF` |
| Dark indigo accent | `#A79AFF` |

Use indigo for primary actions and selection. Use mint sparingly for supporting status and waveform accents. Status wording must communicate its meaning without relying on color alone.

## Typography and components

Use Inter when already installed, falling back to Segoe UI and system sans-serif with Mongolian Cyrillic support. No external font request is required. Keep inputs at 16 px to avoid mobile browser zoom. Titles use 750 weight, short line lengths and restrained negative tracking. Descriptions use regular weight and generous line height.

Surfaces use 20 px corners, a fine border and a subtle shadow. Primary actions use solid indigo with white text. Tool icons use one consistent 24 px line-icon family. Avoid platform-dependent emoji in navigation.

## Responsive behavior

- At 861 px and above, show the persistent sidebar.
- At 860 px and below, show the four-part dock: Бүтээх, Хоолой, Бүтээл, Бүх хэрэгсэл.
- The all-tools drawer supports Escape, focus containment, background dismissal and focus restoration. All tools remain available, including settings and account actions.
- At 700 px and below, stack editors, settings and result panels. At 480 px and below, remove the decorative hero illustration to prioritize content.
- Respect safe-area insets, reduced-motion preferences, keyboard focus and the chosen light/dark theme.

## Implementation

`brand.css` loads after `style.css` to centralize identity overrides. `brand.js` supplies the vector icon family and mobile drawer behavior. Generation, billing and account API contracts are unchanged. New assets are explicitly allowlisted by the existing static route.
