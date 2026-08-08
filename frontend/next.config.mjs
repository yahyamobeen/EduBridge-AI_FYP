import createNextIntlPlugin from 'next-intl/plugin'

/**
 * Security headers per tdd.md §6.11.
 *
 * `script-src` CARRIES `'unsafe-inline'`, AND THAT IS DELIBERATE. Read this
 * before tightening it back, because the tighter value is what broke the app.
 *
 * The App Router streams its React payload through inline `<script>` elements.
 * Under a bare `script-src 'self'` every one of them is blocked, React never
 * hydrates, and the entire site ships as dead HTML — no form accepts input, no
 * button responds. It fails silently: every asset returns 200 and the console
 * stays empty, which is why it survived five phases unnoticed. Verified both
 * ways on a clean production build.
 *
 * The correct fix is a per-request nonce. It cannot be used here: a nonce must
 * differ per response, so the page must be rendered per request, and these
 * routes are prerendered per locale at build time. Forcing them dynamic would
 * trade the static prerendering that prd.md A11Y-2 depends on — the whole point
 * being a fast first paint on a mid-tier Android over Slow 3G — for a directive
 * that stops a subset of XSS payloads. Revisit if the auth routes ever become
 * dynamic for another reason.
 *
 * Everything else still holds, and these are the directives that matter most
 * for this application: `frame-ancestors` blocks clickjacking of the login and
 * 2FA screens, `form-action` stops a form being pointed at another origin,
 * `base-uri` stops a `<base>` tag rewriting every relative URL, `connect-src`
 * confines API calls, and `img-src` still allows only self and the `data:` URI
 * that renders the 2FA QR.
 */
const isDev = process.env.NODE_ENV !== 'production'

/**
 * The API's origin, when it is not our own.
 *
 * `connect-src 'self'` alone is wrong the moment the backend is a separate
 * origin, which it is in development: the app is served from :3000 and calls
 * :8000, so EVERY fetch is blocked by CSP before it leaves the browser. The
 * symptom is a login screen that appears to do nothing.
 *
 * Derived from the same variable the client reads, so the two cannot disagree.
 * Empty when the API is same-origin (a relative `/api`, or a reverse proxy in
 * production), in which case `'self'` already covers it and nothing is widened.
 */
const apiOrigin = (() => {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL
  if (!raw) return ''
  try {
    const { origin, protocol } = new URL(raw)
    // Only a real http(s) origin is a CSP source. Anything else parses to the
    // opaque origin "null", and emitting that would put a literal `null` into
    // the directive -- which allows nothing and reads like a bug.
    return protocol === 'http:' || protocol === 'https:' ? origin : ''
  } catch {
    return '' // relative path -- same origin, already covered by 'self'
  }
})()

const securityHeaders = [
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  {
    key: 'Content-Security-Policy',
    value: [
      "default-src 'self'",
      // `'unsafe-eval'` is DEVELOPMENT ONLY and must stay that way. React uses
      // eval() in dev to reconstruct call stacks across the server/client
      // boundary; without it the error overlay reports the CSP violation
      // instead of the actual bug. React never uses eval() in a production
      // build, so shipping the directive would weaken script-src for a feature
      // that is not there. `NODE_ENV` is set by `next build`, not by us.
      // Turnstile loads its challenge script from challenges.cloudflare.com and
      // renders inside a Cloudflare-served iframe — so script-src, the
      // otherwise-absent frame-src, AND connect-src must admit it, or the widget
      // is blocked by the very policy that protects these forms. All three
      // directives are in Cloudflare's own references (script-src + frame-src in
      // the CSP reference; connect-src because the widget's orchestration code
      // fetches from this origin, per the widget docs and production configs
      // such as Storefront). No other third-party origin is allowed.
      `script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com${isDev ? " 'unsafe-eval'" : ''}`,
      "style-src 'self' 'unsafe-inline'",
      // Self-hosted via next/font, plus the data: URI used to render the
      // server-supplied 2FA QR without injecting markup (tdd.md §6.11).
      "font-src 'self'",
      "img-src 'self' data:",
      // `ws:` in dev only, for Turbopack's hot-reload socket.
      `connect-src 'self' https://challenges.cloudflare.com${apiOrigin ? ` ${apiOrigin}` : ''}${isDev ? ' ws: wss:' : ''}`,
      // What we may FRAME (the Turnstile iframe), distinct from frame-ancestors
      // below, which says who may frame US. Both coexist.
      "frame-src https://challenges.cloudflare.com",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join('; '),
  },
]

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [{ source: '/:path*', headers: securityHeaders }]
  },
}

const withNextIntl = createNextIntlPlugin('./i18n/request.ts')

export default withNextIntl(nextConfig)
