import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import { AnalysisProvider } from "./lib/store";
import Shell from "./components/Shell";
import Landing from "./pages/Landing";
import Analyze from "./pages/Analyze";
import Overview from "./pages/Overview";
import Live from "./pages/Live";
import Health from "./pages/Health";
import FingerprintPage from "./pages/FingerprintPage";
import Router from "./pages/Router";
import Explain from "./pages/Explain";
import Diagnostics from "./pages/Diagnostics";
import Model from "./pages/Model";
import Ledger from "./pages/Ledger";
import Circular from "./pages/Circular";
import Minerals from "./pages/Minerals";
import Forensics from "./pages/Forensics";
import Explorer from "./pages/Explorer";
import Solar from "./pages/Solar";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AnalysisProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/app" element={<Shell />}>
            <Route index element={<Overview />} />
            <Route path="solar" element={<Solar />} />
            <Route path="analyze" element={<Analyze />} />
            <Route path="live" element={<Live />} />
            <Route path="health" element={<Health />} />
            <Route path="fingerprint" element={<FingerprintPage />} />
            <Route path="router" element={<Router />} />
            <Route path="explain" element={<Explain />} />
            <Route path="diagnostics" element={<Diagnostics />} />
            <Route path="model" element={<Model />} />
            <Route path="ledger" element={<Ledger />} />
            <Route path="circular" element={<Circular />} />
            <Route path="minerals" element={<Minerals />} />
            <Route path="forensics" element={<Forensics />} />
            <Route path="explorer" element={<Explorer />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AnalysisProvider>
  </React.StrictMode>,
);
