# Predict UI

React application for Predict UI, designed to be consumed by the agent and available in [Pearl](https://github.com/valory-xyz/olas-operate-app).

## Multi-Agent Support

This app supports two different agents:
- **Omenstrat** (`omenstrat_trader`): Operates on Gnosis chain
- **Polystrat** (`polystrat_trader`): Operates on Polygon chain (default)

## 🔐 Deployment expectations

This app ships as a static-asset ZIP attached to a GitHub Release. The downstream operator (typically the Pearl agent container) is responsible for runtime security headers. Recommended minimum set when serving the unpacked bundle:

| Header | Recommended value | Why |
| --- | --- | --- |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' http://127.0.0.1:8716; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'` | `'unsafe-inline'` for `style-src` is required by styled-components 5.x. Google Fonts CSS + font files need explicit entries. Backend fetches go to `http://127.0.0.1:8716` via `LOCAL` / `API_V1` (see [`libs/util-constants-and-types`](../../libs/util-constants-and-types/src/lib/constants/local.ts)) — the subgraph and CoinGecko URLs referenced in [`src/constants/urls.ts`](src/constants/urls.ts) are server-side concerns of the backend, not browser fetches. `frame-ancestors 'none'` blocks clickjacking and **only works as a header** (meta-tag is ignored). |
| `Strict-Transport-Security` | `max-age=31536000` | If served over HTTPS. |
| `X-Content-Type-Options` | `nosniff` | Disable MIME-type sniffing. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limit referrer leakage. |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=()` | Disable browser features the app does not use. |

If the operator cannot set HTTP headers, an equivalent (weaker — no `frame-ancestors`) `<meta http-equiv="Content-Security-Policy">` can be injected into `index.html` post-build. See [`SUPPLY-CHAIN-SECURITY.md`](../../SUPPLY-CHAIN-SECURITY.md) for the threat model that drives these recommendations.
