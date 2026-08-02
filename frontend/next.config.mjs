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
const securityHeaders = [
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  {
    key: 'Content-Security-Policy',
    value: [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      // Self-hosted via next/font, plus the data: URI used to render the
      // server-supplied 2FA QR without injecting markup (tdd.md §6.11).
      "font-src 'self'",
      "img-src 'self' data:",
      "connect-src 'self'",
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
