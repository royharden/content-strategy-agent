/**
 * Build needs no listener. Serve/preview require an explicitly assigned port.
 * Supplying a port is configuration, not proof of an agent-ports claim.
 * @param {string} command
 * @param {Record<string, string | undefined>} environment
 */
export function createFrontendConfig(command, environment = process.env) {
  const base = { root: "web", build: { outDir: "../dist", emptyOutDir: true } };
  if (command === "build") return base;
  const raw = environment.CSA_WEB_PORT;
  if (!raw || !/^\d{5}$/.test(raw) || Number(raw) < 20000 || Number(raw) > 29999) {
    throw new Error("CSA_WEB_PORT must be the 20000–29999 port from an actual agent-ports claim.");
  }
  const listener = { host: "127.0.0.1", port: Number(raw), strictPort: true };
  return { ...base, server: listener, preview: listener };
}
