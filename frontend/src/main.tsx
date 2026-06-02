import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";
import App from "./App";
import "./styles.css";

const theme = createTheme({
    palette: {
        mode: "light",
        primary: { main: "#1748a0" },
        secondary: { main: "#f05d23" },
        background: { default: "#f5efe6", paper: "#fffdf9" },
    },
    typography: {
        fontFamily: '"Space Grotesk", "Segoe UI", sans-serif',
    },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
        <ThemeProvider theme={theme}>
            <CssBaseline />
            <BrowserRouter>
                <App />
            </BrowserRouter>
        </ThemeProvider>
    </React.StrictMode>
);
