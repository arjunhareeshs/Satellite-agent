/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 'standalone' is what backend/Dockerfile's runner stage depends on --
  // without it, `.next/standalone` is never produced and that COPY fails.
  output: 'standalone',
  async rewrites() {
    // BACKEND_INTERNAL_URL (not NEXT_PUBLIC_*, since this runs server-side in
    // Node, never in the browser) lets the proxy target differ from what the
    // browser calls. In docker-compose the backend is reachable at
    // `http://backend:8000` on the compose network, not `localhost` -- inside
    // the frontend container, `localhost` would mean the frontend container
    // itself.
    return [
      {
        source: '/api/v1/:path*',
        destination: `${process.env.BACKEND_INTERNAL_URL || 'http://localhost:8000'}/api/v1/:path*`,
      },
    ]
  },
}

module.exports = nextConfig
