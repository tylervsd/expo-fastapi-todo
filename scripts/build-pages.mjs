import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";

export function validateApiOrigin(value) {
  try {
    if (!value || value.trim() !== value) throw new Error();
    const url = new URL(value);
    const host = url.hostname;
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash ||
      value.includes("?") ||
      value.includes("#") ||
      host === "localhost" ||
      host.endsWith(".localhost") ||
      host === "[::1]" ||
      host.startsWith("127.") ||
      host === "0.0.0.0" ||
      (value !== url.origin && value !== `${url.origin}/`)
    ) {
      throw new Error();
    }
  } catch {
    throw new Error("EXPO_PUBLIC_API_URL must be a non-loopback HTTPS origin");
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    validateApiOrigin(process.env.EXPO_PUBLIC_API_URL);
    const result = spawnSync("pnpm", ["build:web"], {
      stdio: "inherit",
      env: { ...process.env, EXPO_NO_DOTENV: "1" },
    });
    process.exitCode = result.status ?? 1;
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
