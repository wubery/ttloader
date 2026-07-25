import React from "react";
import ReactDOM from "react-dom/client";
// Bootstrap и иконки идут в бандл (не с CDN) — панель работает без интернета,
// что важно на сервере за блокировками и при передаче архива.
import "bootstrap/dist/css/bootstrap.min.css";
import "bootstrap-icons/font/bootstrap-icons.css";
import "bootstrap/dist/js/bootstrap.bundle.min.js";
import { App } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
