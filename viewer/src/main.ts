import { appTitle } from "./title";

const app = document.querySelector<HTMLElement>("#app");
if (app === null) {
  throw new Error("#app が見つからない");
}
app.textContent = appTitle();
