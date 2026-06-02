const fs = require("fs");
const path = require("path");
<<<<<<< HEAD
const { default: makeWASocket, useMultiFileAuthState } = require("@whiskeysockets/baileys");
const qrcode = require("qrcode-terminal");

const statePath = path.join(__dirname, "qr-state.json");

function writeState(state) {
    try {
        fs.writeFileSync(statePath, JSON.stringify({ ...state, updated_at: new Date().toISOString() }, null, 2));
    } catch (err) {
        console.error("Failed to write WhatsApp QR state:", err);
=======
const http = require("http");
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason } = require("@whiskeysockets/baileys");

const STATE_FILE = path.join(__dirname, "qr-state.json");
const AUTH_DIR = path.join(__dirname, "auth");
const API_BASE = process.env.API_URL || "http://localhost:8000";
const BOT_PORT = parseInt(process.env.BOT_PORT || "3001", 10);

function writeState(state) {
    try {
        fs.writeFileSync(STATE_FILE, JSON.stringify({ ...state, updated_at: new Date().toISOString() }, null, 2));
    } catch (err) {
        console.error("writeState error:", err.message);
    }
}

let sock = null;
let currentQr = null;
let reconnectAttempts = 0;

async function forwardToApi(body) {
    const url = `${API_BASE}/api/baileys/webhook`;
    try {
        const resp = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!resp.ok) {
            const text = await resp.text().catch(() => "");
            console.error(`API returned ${resp.status}: ${text.slice(0, 200)}`);
        } else {
            const data = await resp.json();
            if (data.reply && data.to) {
                await sendMessage(data.to, data.reply);
            }
        }
    } catch (err) {
        console.error("forwardToApi error:", err.message);
    }
}

async function sendMessage(jid, text) {
    if (!sock) return false;
    try {
        await sock.sendMessage(jid, { text });
        return true;
    } catch (err) {
        console.error("sendMessage error:", err.message);
        return false;
>>>>>>> 4907714 (Refactor tests for API stats, CRUD notifications, and CSRF token expiry)
    }
}

async function startBot() {
<<<<<<< HEAD
    const { state, saveCreds } = await useMultiFileAuthState("auth");

    const sock = makeWASocket({
        auth: state,
        printQRInTerminal: false
    });

    writeState({ connected: false, qr: null, message: "Waiting for WhatsApp QR code..." });

    sock.ev.on("connection.update", (update) => {
        const { connection, qr } = update;

        if (qr) {
            qrcode.generate(qr, { small: true });
            writeState({ connected: false, qr, message: "Scan this code with WhatsApp to connect." });
        }

        if (connection === "open") {
            console.log("✅ WhatsApp connected!");
=======
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

    sock = makeWASocket({
        auth: state,
        printQRInTerminal: false,
        markOnlineOnConnect: true,
        connectTimeoutMs: 30000,
    });

    writeState({ connected: false, qr: null, message: "Connecting..." });

    sock.ev.on("connection.update", async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            currentQr = qr;
            reconnectAttempts = 0;
            writeState({ connected: false, qr, message: "Scan the QR code with WhatsApp to connect." });
        }

        if (connection === "open") {
            console.log("WhatsApp connected");
            currentQr = null;
>>>>>>> 4907714 (Refactor tests for API stats, CRUD notifications, and CSRF token expiry)
            writeState({ connected: true, qr: null, message: "WhatsApp is connected." });
        }

        if (connection === "close") {
<<<<<<< HEAD
            console.log("❌ Connection closed. Restarting...");
            writeState({ connected: false, qr: null, message: "Connection closed. Restart the service to reconnect." });
            startBot();
=======
            const reason = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = reason !== DisconnectReason.loggedOut;
            currentQr = null;

            if (reason === DisconnectReason.loggedOut) {
                console.log("Logged out. Delete auth folder to re-link.");
                writeState({ connected: false, qr: null, message: "Logged out. Delete auth folder and restart to re-link." });
                sock = null;
                return;
            }

            const delay = Math.min(5000 * Math.pow(2, reconnectAttempts), 60000);
            reconnectAttempts++;
            console.log(`Connection closed (reason: ${reason}). Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);
            writeState({ connected: false, qr: null, message: `Reconnecting in ${Math.round(delay / 1000)}s...` });

            setTimeout(startBot, delay);
>>>>>>> 4907714 (Refactor tests for API stats, CRUD notifications, and CSRF token expiry)
        }
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("messages.upsert", async (msg) => {
<<<<<<< HEAD
        const message = msg.messages[0];

        if (!message.message || message.key.fromMe) return;

        const text =
            message.message.conversation ||
            message.message.extendedTextMessage?.text;

        console.log("📩 Received:", text);

        // temporary reply
        await sock.sendMessage(message.key.remoteJid, {
            text: "Hello 👋 I received your message"
        });
    });
}

startBot();
=======
        const m = msg.messages[0];
        if (!m.message || m.key.fromMe) return;

        const text = m.message.conversation
            || m.message.extendedTextMessage?.text
            || m.message.imageMessage?.caption
            || "";

        if (!text.trim()) return;

        const sender = m.key.remoteJid;
        console.log("Incoming:", text.slice(0, 80));

        await forwardToApi({ from: sender, body: text, message_id: m.key.id });
    });
}

// ===== HTTP Server (for API to send messages) =====
const server = http.createServer(async (req, res) => {
    const sendJson = (code, data) => {
        res.writeHead(code, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
    };

    const body = await new Promise((resolve) => {
        let data = "";
        req.on("data", (chunk) => data += chunk);
        req.on("end", () => resolve(data));
    });

    try {
        const url = new URL(req.url, `http://localhost:${BOT_PORT}`);
        const pathname = url.pathname;

        if (req.method === "GET" && pathname === "/health") {
            return sendJson(200, { ok: true, connected: sock?.user ? true : false });
        }

        if (req.method === "GET" && pathname === "/qr") {
            let state = {};
            try { state = JSON.parse(fs.readFileSync(STATE_FILE, "utf-8")); } catch {}
            return sendJson(200, {
                connected: !!state.connected,
                qr: state.qr || null,
                message: state.message || "",
            });
        }

        if (req.method === "POST" && pathname === "/send") {
            const data = JSON.parse(body || "{}");
            const jid = data.to;
            const text = data.body;
            if (!jid || !text) return sendJson(400, { error: "Missing 'to' or 'body'" });
            const ok = await sendMessage(jid, text);
            return sendJson(ok ? 200 : 500, { sent: ok });
        }

        return sendJson(404, { error: "Not found" });
    } catch (err) {
        return sendJson(500, { error: err.message });
    }
});

server.listen(BOT_PORT, () => {
    console.log(`WhatsApp bot listening on port ${BOT_PORT}`);
    startBot();
});
>>>>>>> 4907714 (Refactor tests for API stats, CRUD notifications, and CSRF token expiry)
