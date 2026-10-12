import {defineConfig} from "@playwright/test";
export default defineConfig({testDir:"./tests/browser",workers:1,timeout:30000,
 use:{baseURL:"http://127.0.0.1:4173",headless:true,launchOptions:process.platform==="win32"?{executablePath:"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"}:{}},
 webServer:{command:"npm run preview -- --host 127.0.0.1 --port 4173",env:{VITE_BASE_PATH:"/"},url:"http://127.0.0.1:4173",reuseExistingServer:false,timeout:30000}});
