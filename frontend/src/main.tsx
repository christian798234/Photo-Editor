import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { SecondScreen } from "./components/SecondScreen";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {new URLSearchParams(window.location.search).get("view") === "second" ? <SecondScreen /> : <App />}
  </React.StrictMode>,
);
