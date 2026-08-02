/**
 * Security headers per tdd.md §6.11.
 *
 * The CSP below is intentionally conservative but NOT final: `unsafe-inline`
 * for styles is required while Tailwind injects its runtime style element in
 * dev, and the tutor's sandboxed visual renderer (tdd.md §3.10) will need its
 * own frame directives when it lands. Revisit in the phase that introduces it.
 */
const securityHeaders = [
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  {
    key: 'Content-Security-Policy',
    value: [
      "default-src 'self'",
      "script-src 'self'",
      "style-src 'self' 'unsafe-inline'",
      // Self-hosted via next/font, plus the base64 data: URI used to render the
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

export default nextConfig
