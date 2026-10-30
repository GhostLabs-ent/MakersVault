import React from "react";
import { createRoot } from "react-dom/client";
import "./index.css"; 
import App from "./ui/App";
import Toaster from "./ui/Toaster";

const el = document.getElementById("root");
if (!el) throw new Error("#root not found");
createRoot(el).render(
  <React.StrictMode>
    <>
      <App />
      <Toaster />
    </>
  </React.StrictMode>
);
