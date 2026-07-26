# Pocket Finance — a mobile deal-desk in your pocket

A fast, **installable, fully-offline** finance app for the calculations you
actually reach for during a meeting or a site visit — no login, no network, no
data leaving your phone. Built as a **Progressive Web App (PWA)**: add it to
your home screen and it launches full-screen like a native app.

Everything runs client-side in plain HTML/CSS/JavaScript — there is no build
step, no framework, and no server dependency once it's cached.

---

## What's inside

| Tab | What it does |
| --- | --- |
| **Returns** | Total return, absolute gain, **MOIC** multiple, and **CAGR** from initial value, final value, and holding period. |
| **IRR / NPV** | Enter a cash-flow series (add/remove periods). Solves **IRR** by bisection and computes **NPV** at any discount rate. |
| **Loan** | Fixed-rate equal-instalment **amortisation** — monthly payment, total interest, and a year-by-year schedule. |
| **VAT / Zakat** | KSA-oriented: add VAT to a net amount or extract it from a gross amount, plus **Zakat** on the base. Rates editable (defaults 15% / 2.5%). |
| **Margin** | Give any two of cost / price / margin and it derives the rest, plus markup and per-unit profit. |
| **FX** | Offline currency converter with rates **you control**, stored on-device. SAR, AED, USD, EUR, GBP, EGP, INR, JPY, CNY, KWD out of the box. |

Your last-used tab and your custom FX rates persist locally between sessions.

---

## Run / install it

It's static files, so any static host works. Locally:

```bash
cd mobile
python3 -m http.server 8137
```

Then open <http://127.0.0.1:8137/> — on a phone, browse to your machine's LAN
address (or host it anywhere with HTTPS) and use **"Add to Home Screen"**. An
**Install** button also appears in the header on supported browsers.

> A service worker (`sw.js`) caches everything on first load, so after that the
> app works with no connection at all. The install prompt and offline caching
> require serving over `http://localhost` or HTTPS (browser security rule);
> opening `index.html` directly via `file://` still runs every calculator, it
> just won't register the service worker.

### Regenerate the icons

The app icons are produced by a small pure-Python script (no Pillow needed):

```bash
python3 make_icons.py   # writes icons/icon-192.png, icon-512.png, icon-180.png
```

---

## Files

```
mobile/
├── index.html            # app shell + all six tool panels
├── styles.css            # mobile-first, dark/light aware, safe-area handling
├── app.js                # all calculator logic + tab nav + PWA wiring
├── sw.js                 # service worker (cache-first, full offline)
├── manifest.webmanifest  # PWA metadata (name, icons, standalone display)
├── make_icons.py         # generates the PNG icons from scratch
└── icons/                # generated app icons
```

## Notes on the numbers

- **IRR** requires at least one sign change in the cash flows; it's found by
  bisection over a wide bracket, robust for conventional (one-outflow-then-
  inflows) profiles. Unconventional flows with multiple sign changes can have
  multiple IRRs — treat the result as one root and lean on NPV.
- **Loan** rounding residue is cleared on the final payment so the balance lands
  exactly at zero.
- **FX** rates are stored as units per 1 USD and are whatever you set them to —
  the seeded values are illustrative, not a live feed.
