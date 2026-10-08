/** @type {import('next').NextConfig} */
// NEXT_DIST_DIR lets Noderze build an update next to the running version, then swap it in.
export default { reactStrictMode: true, distDir: process.env.NEXT_DIST_DIR || ".next" };
