/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export so Tauri can bundle ../hud/out as frontendDist.
  output: "export",
  images: { unoptimized: true },
  // Backend is local-only FastAPI on :8000; no rewrites needed (CORS-free loopback fetch).
  env: {
    BUTLER_API: process.env.BUTLER_API || "http://127.0.0.1:8000",
  },
};

module.exports = nextConfig;
