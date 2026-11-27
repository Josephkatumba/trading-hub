import { defineConfig } from "vite";
import {fileURLToPath} from "node:url";

export default defineConfig({
  build:{rollupOptions:{input:{main:fileURLToPath(new URL("./index.html",import.meta.url)),classic:fileURLToPath(new URL("./classic.html",import.meta.url)),scalper:fileURLToPath(new URL("./scalper.html",import.meta.url)),research:fileURLToPath(new URL("./research.html",import.meta.url))}}},
  base: process.env.VITE_BASE_PATH || "/trading-hub/",
  resolve:{alias:process.env.VITE_AUTH_REQUIRED==="1"?{"./importedData.js":fileURLToPath(new URL("./src/emptyImportedData.mjs",import.meta.url))}: {}}
});
