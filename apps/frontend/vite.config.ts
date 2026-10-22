import { defineConfig, loadEnv } from 'vite'
import { devtools } from '@tanstack/devtools-vite'
import { tanstackStart } from '@tanstack/react-start/plugin/vite'
import viteReact from '@vitejs/plugin-react'
import viteTsConfigPaths from 'vite-tsconfig-paths'
import tailwindcss from '@tailwindcss/vite'
import { lingui } from '@lingui/vite-plugin'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  // Same-origin API in development: the browser calls /api/*, Vite forwards to the Litestar backend,
  // so the httpOnly session cookie and CSRF rules behave as in production.
  const proxyConfig = env.API_PROXY_TARGET
    ? { '/api': { target: env.API_PROXY_TARGET, changeOrigin: true } }
    : undefined

  return {
    plugins: [
      devtools(),
      // NOTE: nitro() conflicts with a root-level server.ts (Nitro tries to import it).
      // We keep the custom Bun production server, so Nitro is not used.
      viteTsConfigPaths({
        projects: ['./tsconfig.json'],
      }),
      tailwindcss(),
      tanstackStart({
        router: {
          routesDirectory: 'app',
          routeFileIgnorePattern: '\\.ts$',
        },
      }),
      viteReact({
        babel: {
          plugins: ['@lingui/babel-plugin-lingui-macro'],
        },
      }),
      lingui(),
    ],
    server: {
      proxy: proxyConfig,
    },
  }
})
