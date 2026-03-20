/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    GATEWAY_URL: process.env.GATEWAY_URL || "http://localhost:8070",
  },
};

export default nextConfig;
