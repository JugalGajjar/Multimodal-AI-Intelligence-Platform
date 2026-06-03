import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server.js bundle in .next/standalone; lets the production
  // image run without node_modules at runtime.
  output: "standalone",
};

export default nextConfig;
