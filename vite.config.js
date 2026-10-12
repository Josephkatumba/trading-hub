import { defineConfig } from "vite";
import {fileURLToPath} from "node:url";

export default defineConfig({
  base: process.env.VITE_BASE_PATH || "/trading-hub/",
  resolve:{alias:process.env.VITE_AUTH_REQUIRED==="1"?{"./importedData.js":fileURLToPath(new URL("./src/emptyImportedData.mjs",import.meta.url))}: {}}
});
