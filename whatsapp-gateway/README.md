# WhatsApp Gateway - PDF documents

This project does not contain the running Node gateway server. To add direct PDF sending to the existing gateway, copy `send-document-route.js` next to your `server.js`, then register the route after the Baileys socket is created.

Example:

```js
const express = require("express");
const { registerSendDocumentRoute } = require("./send-document-route");

const app = express();
app.use(express.json({ limit: "2mb" }));

let sock = null;

// After your Baileys connection is ready:
// sock = makeWASocket(...)

registerSendDocumentRoute(app, () => sock);
```

Endpoint:

```http
POST /send-document
Content-Type: application/json
```

Payload:

```json
{
  "phone": "0684056613",
  "pdf_url": "https://devis.heliantha.ma/devis/12/pdf",
  "filename": "Devis_HeliAntha_12.pdf",
  "caption": "Texte d'accompagnement sous le document"
}
```

Response:

```json
{ "success": true, "phone": "0684056613", "filename": "Devis_HeliAntha_12.pdf" }
```
