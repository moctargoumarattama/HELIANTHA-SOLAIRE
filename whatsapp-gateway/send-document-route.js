"use strict";

const DEFAULT_TIMEOUT_MS = 45000;

function normalizePhone(phone) {
  const digits = String(phone || "").replace(/\D/g, "");
  if (!digits) return "";
  if (digits.startsWith("00")) return digits.slice(2);
  if (digits.startsWith("0")) return `212${digits.slice(1)}`;
  return digits;
}

function jidForPhone(phone) {
  const normalized = normalizePhone(phone);
  return normalized ? `${normalized}@s.whatsapp.net` : "";
}

function safePdfFilename(filename) {
  const value = String(filename || "Devis_HeliAntha.pdf")
    .replace(/[\\/:*?"<>|]+/g, "_")
    .trim();
  if (!value) return "Devis_HeliAntha.pdf";
  return value.toLowerCase().endsWith(".pdf") ? value : `${value}.pdf`;
}

async function fetchPdfBuffer(pdfUrl, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(pdfUrl, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`PDF HTTP ${response.status}`);
    }
    const contentType = response.headers.get("content-type") || "";
    if (contentType && !contentType.toLowerCase().includes("pdf")) {
      throw new Error(`Unexpected PDF content-type: ${contentType}`);
    }
    return Buffer.from(await response.arrayBuffer());
  } finally {
    clearTimeout(timer);
  }
}

async function sendDocument(sock, payload) {
  if (!sock || typeof sock.sendMessage !== "function") {
    throw new Error("WhatsApp client is not ready");
  }

  const phone = String(payload.phone || "").trim();
  const pdfUrl = String(payload.pdf_url || "").trim();
  const caption = String(payload.caption || "").trim();
  const filename = safePdfFilename(payload.filename);
  const jid = jidForPhone(phone);

  if (!jid) {
    throw new Error("Missing phone");
  }
  if (!/^https?:\/\//i.test(pdfUrl)) {
    throw new Error("pdf_url must be an absolute http(s) URL");
  }

  const document = await fetchPdfBuffer(pdfUrl);
  await sock.sendMessage(jid, {
    document,
    mimetype: "application/pdf",
    fileName: filename,
    caption,
  });

  return { success: true, phone, filename };
}

function registerSendDocumentRoute(app, getSock) {
  app.post("/send-document", async (req, res) => {
    try {
      const sock = typeof getSock === "function" ? getSock() : getSock;
      const result = await sendDocument(sock, req.body || {});
      res.json(result);
    } catch (error) {
      res.status(400).json({
        success: false,
        error: error && error.message ? error.message : "Document send failed",
      });
    }
  });
}

module.exports = {
  jidForPhone,
  normalizePhone,
  registerSendDocumentRoute,
  safePdfFilename,
  sendDocument,
};
