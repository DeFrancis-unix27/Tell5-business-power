const fs = require("fs");
const path = require("path");
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
    }
}

async function startBot() {
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
            writeState({ connected: true, qr: null, message: "WhatsApp is connected." });
        }

        if (connection === "close") {
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
        }
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("messages.upsert", async (msg) => {
        const m = msg.messages[0];
        if (!m.message || m.key.fromMe) return;

        const text = m.message.conversation
            || m.message.extendedTextMessage?.text
            || m.message.imageMessage?.caption
            || "";

        if (!text.trim()) return;

        const sender = m.key.remoteJid;
        const pushName = m.pushName || "";
        let profilePicUrl = null;
        try {
            profilePicUrl = await sock.profilePictureUrl(sender, "image");
        } catch {}

        console.log(`Incoming from ${pushName || sender}:`, text.slice(0, 80));

        await forwardToApi({
            from: sender,
            body: text,
            message_id: m.key.id,
            push_name: pushName,
            profile_pic_url: profilePicUrl,
        });
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

        if (req.method === "GET" && pathname === "/profile-pic") {
            const jid = url.searchParams.get("jid");
            if (!jid) return sendJson(400, { error: "Missing jid param" });
            let picUrl = null;
            try { picUrl = await sock.profilePictureUrl(jid, "image"); } catch {}
            return sendJson(200, { jid, profile_pic_url: picUrl });
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
