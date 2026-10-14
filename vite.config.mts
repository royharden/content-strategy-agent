import { defineConfig } from "vite";
import { createFrontendConfig } from "./scripts/frontend-config.mjs";

export default defineConfig(({ command }) => createFrontendConfig(command));
